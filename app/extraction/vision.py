"""Vision-based extraction via Google Gemini.

Division 1 extraction now has a vision-first path beside plain Tesseract OCR.
Plain OCR cannot (a) see whether a ticket line item is struck through and
(b) read handwriting on dockets.  This module sends the actual image bytes to
Gemini with a structured JSON prompt and returns the same master parsing
schema the regex parsers produce, so every downstream caller stays the same.

Configuration (all optional, all read from the environment):
    GEMINI_API_KEY | GOOGLE_API_KEY   required to call the API
    GEMINI_MODEL                      model id, default "gemini-3.8-flash"

Uses only the standard library so no new dependency is required.
"""

import base64
import json
import logging
import os
import re
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

_API_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
_DEFAULT_MODEL = "gemini-3.5-flash"
_TIMEOUT_SECONDS = 120

TICKET_SCHEMA = {
    "type": "ticket",
    "ticket_number": None,
    "restaurant": None,
    "date": None,
    "terminal": None,
    "table": None,
    "department": None,
    "user": None,
    "payment_status": None,
    "credit_card_amount": None,
    "items": [],
    "ticket_total": None,
    "grand_total": None,
    "charged": None,
    "extra_fields": {},
}

DOCKET_SCHEMA = {
    "type": "docket",
    "docket_order_no": None,
    "date": None,
    "time": None,
    "item": None,
    "discrepancy_type": None,
    "handwritten_reason": None,
    "printed_text": None,
    "extra_fields": {},
    "_review_flags": [],
}


class VisionExtractionError(Exception):
    """Raised when the vision model cannot be called or returns unusable JSON."""


def api_key() -> Optional[str]:
    """Return the configured Google/Gemini API key, or None when unset."""
    return os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or None


def vision_available() -> bool:
    """True when this environment can attempt a vision extraction."""
    return bool(api_key())


def _mime_type(path: str) -> str:
    ext = os.path.splitext(path)[1].casefold()
    return {
        ".jpeg": "image/jpeg",
        ".jpg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
        ".bmp": "image/bmp",
        ".gif": "image/gif",
    }.get(ext, "image/png")


def _extract_json(text: str) -> dict:
    """Parse model output that should be a single JSON object."""
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```[a-zA-Z]*\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start != -1 and end > start:
            return json.loads(stripped[start : end + 1])
        raise


def _call_gemini(image_path: str, prompt: str) -> dict:
    """Send one image to Gemini and return the parsed JSON response."""
    key = api_key()
    if not key:
        raise VisionExtractionError("No GEMINI_API_KEY / GOOGLE_API_KEY configured")

    model = os.environ.get("GEMINI_MODEL", _DEFAULT_MODEL)
    with open(image_path, "rb") as handle:
        image_b64 = base64.b64encode(handle.read()).decode("ascii")

    body = {
        "contents": [
            {
                "parts": [
                    {"inline_data": {"mime_type": _mime_type(image_path), "data": image_b64}},
                    {"text": prompt},
                ]
            }
        ],
        "generationConfig": {
            "responseMimeType": "application/json",
            "temperature": 0.1,
        },
    }
    request = urllib.request.Request(
        _API_ENDPOINT.format(model=model),
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": key,
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")[:500]
        raise VisionExtractionError(
            f"Gemini HTTP {error.code}: {detail}"
        ) from error
    except urllib.error.URLError as error:
        raise VisionExtractionError(f"Gemini network error: {error.reason}") from error
    except Exception as error:  # noqa: BLE001 - wrap any transport issue
        raise VisionExtractionError(f"Gemini request failed: {error}") from error

    try:
        candidates = payload.get("candidates") or []
        if not candidates:
            block = payload.get("promptFeedback", {}).get("blockReason", "no candidates")
            raise VisionExtractionError(f"Gemini returned no candidates ({block})")
        parts = candidates[0].get("content", {}).get("parts") or []
        text = "".join(part.get("text", "") for part in parts)
        if not text.strip():
            raise VisionExtractionError("Gemini returned an empty response")
        return _extract_json(text)
    except (KeyError, TypeError, json.JSONDecodeError) as error:
        raise VisionExtractionError(
            f"Gemini returned unusable JSON: {error}"
        ) from error


def _as_bool(value: Any) -> bool:
    """Coerce a model-provided is_void value to a real boolean."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().casefold() in {"true", "yes", "y", "1", "void", "voided", "struck", "strikethrough"}
    return False


def _as_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _normalize_department_text(value: Any) -> str:
    import re
    text = str(value or "").strip()
    text = re.sub(r"\b(?:incomes?|department|dept|section|division)\b", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text).strip().upper()
    return text or "UNKNOWN"


def _as_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    try:
        number = float(str(value).replace(",", "").strip())
        if number.is_integer():
            return int(number)
        return int(number)
    except (TypeError, ValueError):
        return None


def _as_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        text = str(value).replace("\u00a3", "").replace(",", "").strip()
        if text in {"-", "--", ""}:
            return 0.0
        return float(text)
    except (TypeError, ValueError):
        return None


def _as_mapping(value: Any) -> Dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def vision_extract_ticket(image_path: str) -> Dict[str, Any]:
    """Extract a ticket screenshot with vision; returns the master ticket schema.

    Per-item is_void is decided from VISUAL styling (strikethrough, strike-out,
    crossed text) in addition to any printed "(Void)" label. Plain OCR cannot
    see strikethrough, so this path is what catches all-voided tickets.

    Raises:
        VisionExtractionError: when the model cannot be called or parsed.
    """
    prompt = """
You are an expert receipt/ticket reader. Look at this POS ticket screenshot
and reason about the image visually. Return ONLY a JSON object with exactly
these keys:

{
  "type": "ticket",
  "ticket_number": string or null,       // full value like "260921-48", no "#"
  "restaurant": string or null,
  "date": string or null,
  "terminal": string or null,
  "table": string or null,
  "department": string or null,
  "user": string or null,
  "payment_status": string or null,
  "credit_card_amount": string or null,
  "ticket_total": string or null,
  "grand_total": string or null,
  "charged": string or null,
  "items": [
    {
      "name": string,                    // item name only, no prices
      "category": string or null,
      "price": string or null,           // unit price e.g. "12.50"
      "qty": string or null,
      "total": string or null,
      "is_void": boolean                 // REQUIRED for every item
    }
  ],
  "extra_fields": {}                     // unknown labeled fields key->value
}

VOID RULES — the most important part:
1. For EVERY item row you must decide is_void by looking at the row's visual
   styling, not only its text.
2. Set is_void true when the item row/name is struck through, crossed out, or
   underlined by a strike line, EVEN IF there is no "(Void)" text label. A
   struck-through row with no label is still void.
3. Set is_void true when the row shows a printed "Void"/"(Void)"/"voided"
   label next to the item.
4. Otherwise is_void must be false. Do not mark an item void just because it
   appears in a summary or if the row has no void styling.
5. Only list real item rows. Never add sub-total, VAT, tax, payment, or grand
   total lines as items.
6. If one of the items is followed by "N/A" as its price (Nas/A, n/a), keep
   item with its void state and leave price null.
"""
    parsed = _call_gemini(image_path, prompt)

    result = dict(TICKET_SCHEMA)
    for key in (
        "type", "ticket_number", "restaurant", "date", "terminal", "table",
        "department", "user", "payment_status", "credit_card_amount",
        "ticket_total", "grand_total", "charged",
    ):
        if key == "type":
            result[key] = "ticket"
        else:
            result[key] = _as_text(parsed.get(key))

    ticket_number = result["ticket_number"]
    if ticket_number:
        result["ticket_number"] = ticket_number.strip().lstrip("#").strip()

    items = []
    for item in parsed.get("items") or []:
        if not isinstance(item, dict):
            continue
        name = _as_text(item.get("name"))
        if not name:
            continue
        items.append({
            "name": name,
            "category": _as_text(item.get("category")),
            "price": _as_text(item.get("price")),
            "qty": _as_text(item.get("qty")),
            "total": _as_text(item.get("total")),
            "is_void": _as_bool(item.get("is_void", False)),
        })
    result["items"] = items
    result["extra_fields"] = _as_mapping(parsed.get("extra_fields"))
    return result


def vision_extract_docket(image_path: str) -> Tuple[Dict[str, Any], List[str]]:
    """Extract a docket image with vision; returns (master docket schema, review flags).

    Handwriting is separated from printed receipt text: only handwritten text
    goes into `handwritten_reason` (published as `description` by the API).
    A docket with no handwriting leaves `handwritten_reason` null — the model
    must NOT fabricate a reason from printed text.

    Raises:
        VisionExtractionError: when the model cannot be called or parsed.
    """
    prompt = """
You are an expert restaurant docket reader. This image is a printed kitchen/
discrepancy docket that may also contain HANDWRITTEN annotations in pen/pencil.
Look at the image visually and return ONLY a JSON object with exactly these
keys:

{
  "type": "docket",
  "docket_order_no": string or null,     // trailing order number only, e.g. "49"
  "date": string or null,
  "time": string or null,
  "item": string or null,                // printed item the discrepancy refers to
  "discrepancy_type": "void" | "discount" | "promotion" | null,
  "description": string or null,         // HANDWRITING ONLY — see rules
  "printed_text": string,                // the full printed receipt text
  "extra_fields": {},                    // unknown labeled printed fields
  "review_flags": []                     // list of strings, e.g.
                                         //   "multiple_order_numbers"
}

HANDWRITING RULES — the most important part:
1. Separate PRINTED receipt text (thermal/print font, uniform) from HANDWRITTEN
   annotations (pen/pencil, irregular, slanted). They are two different things.
2. Put ALL and ONLY the handwritten text into "description", transcribed
   exactly as written (keep the author's spelling and abbreviations).
3. If the image has NO handwriting, set "description" to null. Never move
   printed receipt text into description — never fabricate a reason.
4. The discrepancy_type must come from the PRINTED marker only
   (VOID/VOIDED/DISCOUNT/PROMO). A handwritten note alone is not a marker.
5. docket_order_no is only the trailing integer, never a full "YYMMDD-N".
6. If the image shows more than one distinct order number, set
   docket_order_no to null and add "multiple_order_numbers" to review_flags.
7. "printed_text" holds everything that is printed, including labels,
   item rows and the printed marker.
"""
    parsed = _call_gemini(image_path, prompt)

    result = dict(DOCKET_SCHEMA)
    result["type"] = "docket"
    for key in ("docket_order_no", "date", "time", "item", "discrepancy_type"):
        result[key] = _as_text(parsed.get(key))
    result["handwritten_reason"] = _as_text(parsed.get("description"))

    discrepancy_type = result["discrepancy_type"]
    if discrepancy_type:
        result["discrepancy_type"] = discrepancy_type.casefold()
        if result["discrepancy_type"] not in {"void", "discount", "promotion"}:
            result["discrepancy_type"] = None

    printed = parsed.get("printed_text")
    result["printed_text"] = _as_text(printed) if printed is not None else None
    result["extra_fields"] = _as_mapping(parsed.get("extra_fields"))

    flags = parsed.get("review_flags") or []
    flags = [str(flag) for flag in flags if isinstance(flag, (str,)) and str(flag).strip()]
    result["_review_flags"] = flags
    return result, flags


def vision_extract_sales_report(image_path: str) -> Dict[str, Any]:
    """Extract a till Work Period report image with vision.

    Returns the master sales report schema (department-level Voids /
    Discounts / Promotions / Cancelled totals with count + amount).

    Raises:
        VisionExtractionError: when the model cannot be called or parsed.
    """
    prompt = """
You are an expert till Z/X report reader. This image is a restaurant till Work
Period report (a Z report) showing system-of-record totals per department.
Read it visually and return ONLY a JSON object with exactly these keys:

{
  "type": "sales_report",
  "restaurant": string or null,
  "report_date": string or null,          // printed report date e.g. "22/09/2026"
  "departments": [
    {
      "name": string,                     // department name, e.g. "TAKE AWAY" or "RESTAURANT"
      "voids_count": integer or null,
      "voids_amount": number or null,
      "discounts_count": integer or null,
      "discounts_amount": number or null,
      "promotions_count": integer or null,
      "promotions_amount": number or null,
      "cancelled_count": integer or null,
      "cancelled_amount": number or null
    }
  ],
  "extra_fields": {}                       // unrecognized labeled text, key -> value
}

RULES:
1. Group the totals under THEIR department section (e.g. "TAKE AWAY Incomes",
   "RESTAURANT Incomes"). Capture every department that appears — never
   hardcode only Take Away and Restaurant. A department with no total rows
   still gets a null-filled entry.
2. Each total has a count then an amount. A "-" amount means zero/none: store
   it as 0, never as null, and never as missing.
3. If a count or amount is truly absent from the paper, leave it null — do not
   invent numbers.
4. Unrecognized labeled lines go into extra_fields. Do not merge or invent
   fields.
5. Never fabricate a restaurant, date, or department name that is not printed
   on the report.
"""
    parsed = _call_gemini(image_path, prompt)

    result = {
        "type": "sales_report",
        "restaurant": _as_text(parsed.get("restaurant")),
        "report_date": _as_text(parsed.get("report_date")),
        "departments": [],
        "extra_fields": _as_mapping(parsed.get("extra_fields")),
    }
    for department in parsed.get("departments") or []:
        if not isinstance(department, dict):
            continue
        name = _as_text(department.get("name"))
        if not name:
            continue
        row = {
            "name": _normalize_department_text(name),
            "voids_count": _as_int(department.get("voids_count")),
            "voids_amount": _as_float(department.get("voids_amount")),
            "discounts_count": _as_int(department.get("discounts_count")),
            "discounts_amount": _as_float(department.get("discounts_amount")),
            "promotions_count": _as_int(department.get("promotions_count")),
            "promotions_amount": _as_float(department.get("promotions_amount")),
            "cancelled_count": _as_int(department.get("cancelled_count")),
            "cancelled_amount": _as_float(department.get("cancelled_amount")),
        }
        result["departments"].append(row)
    return result