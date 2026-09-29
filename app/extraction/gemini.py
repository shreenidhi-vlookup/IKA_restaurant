"""Vision-only structured extraction for POS screenshots and docket photos."""
import io
import json
import os
import re
import time
from typing import Any

from google import genai
from google.genai import types
from PIL import Image, ImageEnhance, ImageOps
from pydantic import BaseModel, ConfigDict, Field
from app.extraction.rate_limit import request_pacer


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class VoidSignals(StrictModel):
    row_tint: bool = False
    strikethrough_line: bool = False
    void_label_text: bool = False


class ExtraField(StrictModel):
    label: str
    value: str


class TicketItem(StrictModel):
    name: str | None = None
    category: str | None = None
    price: str | None = None
    qty: str | None = None
    total: str | None = None
    modifier: str | None = None
    is_void: bool = False
    void_confidence: str | None = None
    review_flags: list[str] = Field(default_factory=list)
    signals: VoidSignals = Field(default_factory=VoidSignals)
    modifiers: list[str] = Field(default_factory=list)


class TicketExtraction(StrictModel):
    ticket_id: str | None = None
    branch: str | None = None
    date: str | None = None
    terminal: str | None = None
    table: str | None = None
    department: str | None = None
    user: str | None = None
    payment_status: str | None = None
    credit_card: str | None = None
    items: list[TicketItem] = Field(default_factory=list)
    ticket_total: str | None = None
    grand_total: str | None = None
    charged: str | None = None
    extra_fields: list[ExtraField] = Field(default_factory=list)


class DocketItem(StrictModel):
    quantity: str | None = None
    name: str | None = None
    modifier: str | None = None
    is_void: bool = False
    marker_type: str | None = None


class DocketView(StrictModel):
    order_number: str | None = None
    date: str | None = None
    time: str | None = None
    department: str | None = None
    table: str | None = None
    covers: str | None = None
    staff_name: str | None = None
    items: list[DocketItem] = Field(default_factory=list)
    description: str | None = None
    description_confidence: float | None = None
    partial_fields: list[str] = Field(default_factory=list)
    extra_fields: list[ExtraField] = Field(default_factory=list)


class DocketExtraction(StrictModel):
    dockets: list[DocketView] = Field(default_factory=list)
    multiple_dockets: bool = False


class VisionExtractionError(RuntimeError):
    def __init__(self, message: str, raw_json: str = ""):
        super().__init__(message)
        self.raw_json = raw_json


def _gemini_schema(model: type[BaseModel]) -> dict[str, Any]:
    """Pydantic remains strict locally; omit unsupported AP keywords in API schema."""
    schema = model.model_json_schema()

    def remove_additional_properties(value):
        if isinstance(value, dict):
            value.pop("additionalProperties", None)
            value.pop("default", None)
            for nested in value.values():
                remove_additional_properties(nested)
        elif isinstance(value, list):
            for nested in value:
                remove_additional_properties(nested)

    remove_additional_properties(schema)
    return schema


def _transient_retry_delay(error: Exception, transient_attempt: int) -> float | None:
    message = str(error)
    if not any(code in message for code in ("429", "RESOURCE_EXHAUSTED", "503", "UNAVAILABLE", "500", "INTERNAL")):
        return None
    retry_hint = re.search(r"retry in\s+([\d.]+)s", message, flags=re.IGNORECASE)
    if retry_hint:
        return min(60.0, max(1.0, float(retry_hint.group(1))))
    return min(30.0, 2.0 ** transient_attempt)


def _prepared_image(path: str) -> tuple[bytes, str]:
    with Image.open(path) as opened:
        image = ImageOps.exif_transpose(opened).convert("RGB")
        image.thumbnail((2400, 2400), Image.Resampling.LANCZOS)
        gray = ImageOps.grayscale(image)
        if sum(gray.resize((1, 1)).getpixel((0, 0)) for _ in [0]) < 90:
            image = ImageEnhance.Brightness(image).enhance(1.18)
        image = ImageEnhance.Contrast(image).enhance(1.12)
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=92, optimize=True)
        return buffer.getvalue(), "image/jpeg"


def extract_image(path: str, kind: str) -> tuple[dict[str, Any], str]:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise VisionExtractionError("GEMINI_API_KEY is not set")
    model = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
    image_bytes, mime = _prepared_image(path)
    schema = TicketExtraction if kind == "ticket" else DocketExtraction
    prompt = (
        "Read this restaurant POS screenshot directly from the image. Return only schema-conforming JSON. "
        "Ticket ID is the top-left #YYMMDD-N, preserve the hyphen. Null unknowns and put unrecognized labeled text in extra_fields. "
        "Return visible item lines in screenshot order. Wrapped names stay one item; modifier sub-lines belong to the item above. "
        "Set is_void from visual strike-through of the letters, not merely the label; report strikethrough, (Void) label, and pink/red tint separately. "
        "Info cards can be absent on scrolled screenshots. Capture repeated footer totals when visible."
        if kind == "ticket" else
        "Inspect all docket copies/views in this photo and return each as a separate dockets entry; complementary crops of the same docket are separate views for later merging. "
        "Return only schema-conforming JSON. Order number is trailing digits only, so No:1 and ORDER NO:No:1 mean 1. "
        "Extract date, time, department/order type, table, covers, staff name, and every printed item line in order. "
        "Only lines adjacent to VOID/discount/promotion markers have is_void or marker_type; ordinary unmarked lines are normal items. "
        "A modifier belongs to its item, never return it as a separate item. Mark cropped/partly legible fields in partial_fields and do not guess. "
        "Description is handwritten text only, verbatim, use [illegible] for unreadable words, null if absent, with confidence 0..1. "
        "Null missing values; unrecognized labeled text goes to extra_fields."
    )
    client = genai.Client(api_key=api_key)
    last_raw = ""
    last_error: Exception | None = None
    transient_retries = 0
    schema_retried = False
    while True:
        request_pacer.acquire()
        try:
            response = client.models.generate_content(
                model=model,
                contents=[prompt, types.Part.from_bytes(data=image_bytes, mime_type=mime)],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_json_schema=_gemini_schema(schema),
                    temperature=0,
                    automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
                ),
            )
        except Exception as exc:
            last_error = exc
            delay = _transient_retry_delay(exc, transient_retries)
            if delay is not None and transient_retries < 3:
                transient_retries += 1
                time.sleep(delay)
                continue
            break
        last_raw = response.text or ""
        try:
            parsed = schema.model_validate_json(last_raw)
            return parsed.model_dump(mode="json"), last_raw
        except Exception as exc:
            last_error = exc
            if not schema_retried:
                schema_retried = True
                continue
            break
    raise VisionExtractionError(f"Gemini extraction failed after transient retries/schema retry: {last_error}", last_raw)
