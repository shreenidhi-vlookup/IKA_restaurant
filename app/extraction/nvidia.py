"""NVIDIA NIM vision extraction for docket photos."""
import base64
import json
import os
import re
import time
import urllib.error
import urllib.request
from typing import Any

from pydantic import BaseModel

from app.extraction.gemini import DocketExtraction, VisionExtractionError, _gemini_schema, _prepared_image
from app.extraction.rate_limit import request_pacer


_TEXT_NUMBER_FIELDS = {
    "ticket_id", "branch", "date", "terminal", "table", "department", "user",
    "payment_status", "credit_card", "name", "category", "price", "qty", "total",
    "order_number", "time", "covers", "staff_name", "quantity", "modifier",
    "description", "marker_type", "label", "value",
}


def _normalize_text_numbers(value: Any):
    if isinstance(value, list):
        return [_normalize_text_numbers(item) for item in value]
    if isinstance(value, dict):
        normalized = {}
        for key, item in value.items():
            if key in _TEXT_NUMBER_FIELDS and isinstance(item, (int, float)) and not isinstance(item, bool):
                normalized[key] = str(item)
            else:
                normalized[key] = _normalize_text_numbers(item)
        return normalized
    return value


def _parse_json_object(raw: str, model: type[BaseModel]):
    decoder = json.JSONDecoder()
    last_validation_error: Exception | None = None
    for match in re.finditer(r"\{", raw):
        try:
            payload, _end = decoder.raw_decode(raw[match.start():])
            payload = _normalize_text_numbers(payload)
            return model.model_validate(payload).model_dump(mode="json")
        except (json.JSONDecodeError, ValueError) as exc:
            last_validation_error = exc
            continue
    detail = f": {last_validation_error}" if last_validation_error else ""
    raise ValueError(f"NVIDIA response did not contain a schema-valid JSON object{detail}")


def extract_image(path: str, kind: str) -> tuple[dict[str, Any], str]:
    if kind != "docket":
        raise VisionExtractionError("NVIDIA vision is configured for docket photos only; tickets use local OCR")
    api_key = os.getenv("NVIDIA_API_KEY", "").strip()
    if not api_key:
        raise VisionExtractionError("NVIDIA_API_KEY is not set; add it to the project .env to enable fallback")

    model: type[BaseModel] = DocketExtraction
    model_name = os.getenv("NVIDIA_MODEL", "meta/llama-3.2-11b-vision-instruct")
    image_bytes, mime = _prepared_image(path)
    schema = _gemini_schema(model)
    prompt = (
        "Extract every docket view in this photo into JSON matching this schema exactly, including order number, date, time, department, table, covers, staff, and all item lines. "
        "Only VOID/discount/promotion-marked lines are discrepancy items; do not turn modifiers into items. "
        "Handwritten description only; transcribe verbatim, null if absent, [illegible] for unreadable text. "
        "Do not add markdown or explanatory prose. Return only one JSON object with the exact schema keys.\n" + json.dumps(schema)
    )
    data_uri = f"data:{mime};base64,{base64.b64encode(image_bytes).decode('ascii')}"
    last_raw = ""
    last_error: Exception | None = None
    for attempt in range(2):
        request_pacer.acquire()
        attempt_prompt = prompt if attempt == 0 else prompt + "\nCorrection: The previous response was not valid JSON for the supplied schema. Return only the complete JSON object, with no explanation or markdown."
        body = json.dumps({
            "model": model_name,
            "messages": [{"role": "user", "content": [
                {"type": "text", "text": attempt_prompt},
                {"type": "image_url", "image_url": {"url": data_uri}},
            ]}],
            "temperature": 0,
            "max_tokens": 8192,
            "stream": False,
            "response_format": {"type": "json_schema", "json_schema": {"name": model.__name__, "schema": schema}},
        }).encode("utf-8")
        req = urllib.request.Request(
            "https://integrate.api.nvidia.com/v1/chat/completions",
            data=body,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as response:
                payload = json.loads(response.read().decode("utf-8"))
            last_raw = payload["choices"][0]["message"]["content"] or ""
            return _parse_json_object(last_raw, model), last_raw
        except urllib.error.HTTPError as exc:
            body_text = exc.read().decode("utf-8", errors="replace")
            last_error = RuntimeError(f"NVIDIA HTTP {exc.code}: {body_text[:1200]}")
            if exc.code not in (429, 500, 502, 503, 504) or attempt:
                break
            retry = re.search(r"retry[- ]after[^0-9]*([0-9.]+)", body_text, flags=re.IGNORECASE)
            time.sleep(min(60.0, max(1.0, float(retry.group(1)))) if retry else 2.0)
        except Exception as exc:
            last_error = exc
            if attempt:
                break
    raise VisionExtractionError(f"NVIDIA fallback extraction failed: {last_error}", last_raw)
