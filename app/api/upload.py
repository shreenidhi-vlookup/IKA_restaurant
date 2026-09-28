import os
import uuid
import json
import logging
import re
import typing as t
from typing import Any, Dict, List, Tuple
from fastapi import APIRouter, File, UploadFile, HTTPException, Form
from app.extraction.ocr import extract_text_from_image
from app.extraction.vision import (
    VisionExtractionError,
    vision_available,
    vision_extract_docket,
    vision_extract_sales_report,
    vision_extract_ticket,
)
from app.models.ticket import parse_ticket_screenshot
from app.models.docket import ORDER_NO_RE, parse_docket_text
from app.models.daily_exception import normalize_branch, parse_daily_exception_report
from app.models.sales_report import canonical_date_key, compare_slip_with_excel, parse_sales_report_text
from app.storage.db import (
    create_docket_record,
    get_docket_record,
    get_ticket_record,
    get_sales_report_by_id,
    upsert_sales_report,
    upsert_ticket_record,
    init_db,
)


logger = logging.getLogger(__name__)

router = APIRouter()
init_db()

# Configure upload directory
UPLOAD_DIR = "data/uploads"
TICKET_SCREENSHOT_DIR = os.path.join(UPLOAD_DIR, "ticket_screenshots")
DOCKET_IMAGE_DIR = os.path.join(UPLOAD_DIR, "dockets")
SALES_REPORT_DIR = os.path.join(UPLOAD_DIR, "sales_reports")
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(TICKET_SCREENSHOT_DIR, exist_ok=True)
os.makedirs(DOCKET_IMAGE_DIR, exist_ok=True)
os.makedirs(SALES_REPORT_DIR, exist_ok=True)
MAX_BULK_UPLOADS = 30


def _looks_like_ticket_screenshot(extracted_text: str) -> bool:
    """Detect ticket screenshot using the master prompt's pattern: Ticket #YYMMDD-N"""
    return bool(re.search(r"(?:ticket\s*)?#?\s*\d{6}\s*[-–]\s*\d+", extracted_text, re.IGNORECASE))


def _extract_ticket_parsed(file_path: str, ocr_text: str = "") -> Tuple[Dict[str, Any], str, str]:
    """Parse a ticket screenshot, vision-first with OCR fallback.

    Returns (parsed, raw_ocr_text, extraction_method) where method is
    "vision" when the image was read visually or "ocr_fallback" otherwise.
    """
    method = "ocr_fallback"
    parsed = None

    if vision_available():
        try:
            parsed = vision_extract_ticket(file_path)
            method = "vision"
        except VisionExtractionError as error:
            logger.warning(
                "Vision ticket extraction failed for %s, falling back to OCR: %s",
                file_path,
                error,
            )

        if parsed is not None and not parsed.get("ticket_number"):
            logger.warning(
                "Vision could not read a Ticket ID from %s, falling back to OCR",
                file_path,
            )
            parsed = None
            method = "ocr_fallback"

    if parsed is None:
        if not ocr_text:
            ocr_text = extract_text_from_image(file_path)
        return parse_ticket_screenshot(ocr_text), ocr_text, "ocr_fallback"

    # Vision path: keep OCR text for audit only; never let it replace the parse.
    if not ocr_text:
        try:
            ocr_text = extract_text_from_image(file_path)
        except Exception as error:  # noqa: BLE001 - OCR is best-effort on the vision path
            logger.warning("OCR audit text unavailable for %s: %s", file_path, error)
            ocr_text = ""
    return parsed, ocr_text, "vision"


def _extract_docket_parsed(file_path: str) -> Tuple[Dict[str, Any], str, str, List[str]]:
    """Parse a docket image, vision-first with OCR fallback.

    Returns (parsed, raw_ocr_text, extraction_method, vision_review_flags).
    """
    method = "ocr_fallback"
    parsed = None
    vision_flags: List[str] = []

    if vision_available():
        try:
            parsed, vision_flags = vision_extract_docket(file_path)
            method = "vision"
        except VisionExtractionError as error:
            logger.warning(
                "Vision docket extraction failed for %s, falling back to OCR: %s",
                file_path,
                error,
            )

    if parsed is None:
        ocr_text = extract_text_from_image(file_path)
        return parse_docket_text(ocr_text), ocr_text, "ocr_fallback", []

    try:
        ocr_text = extract_text_from_image(file_path)
    except Exception as error:  # noqa: BLE001 - OCR is audit-only on the vision path
        logger.warning("OCR audit text unavailable for %s: %s", file_path, error)
        ocr_text = ""
    return parsed, ocr_text, "vision", vision_flags


def _extract_sales_report_image(file_path: str) -> Tuple[Dict[str, Any], str, str]:
    """Parse a till work period report image, vision-first with OCR fallback.

    Returns (parsed, raw_ocr_text, extraction_method).
    """
    parsed = None
    method = "ocr_fallback"

    if vision_available():
        try:
            parsed = vision_extract_sales_report(file_path)
            method = "vision"
        except VisionExtractionError as error:
            logger.warning(
                "Vision sales report extraction failed for %s, falling back to OCR: %s",
                file_path,
                error,
            )

    if parsed is None:
        ocr_text = extract_text_from_image(file_path)
        return parse_sales_report_text(ocr_text), ocr_text, "ocr_fallback"

    try:
        ocr_text = extract_text_from_image(file_path)
    except Exception as error:  # noqa: BLE001 - OCR is audit-only on the vision path
        logger.warning("OCR audit text unavailable for %s: %s", file_path, error)
        ocr_text = ""
    return parsed, ocr_text, "vision"


def _map_sales_report_to_storage(
    parsed: Dict[str, Any],
    raw_text: str,
    source: str,
    extraction_method: str,
    cross_verified: bool,
    confirmed_source: str = None,
    image_filename: str = None,
    csv_filename: str = None,
    image_departments: List[Dict[str, Any]] = None,
    csv_departments: List[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    return {
        "restaurant": parsed.get("restaurant"),
        "report_date": parsed.get("report_date"),
        "departments": parsed.get("departments", []),
        "source": source,
        "cross_verified": cross_verified,
        "confirmed_source": confirmed_source,
        "image_filename": image_filename,
        "csv_filename": csv_filename,
        "extracted_text": raw_text,
        "extraction_method": extraction_method,
        "extra_fields": parsed.get("extra_fields", {}),
        # Each source's own parse is kept so the Process dashboard can show
        # "Voids in bill" next to "Voids in Excel" rather than only the winner.
        "image_departments": image_departments,
        "csv_departments": csv_departments,
    }


def _map_ticket_to_storage(parsed: Dict[str, Any]) -> Dict[str, Any]:
    """Map the master prompt's ticket structure to the storage format expected by upsert_ticket_record."""
    # Extract ticket number (without #) for ticket_id
    ticket_number = parsed.get("ticket_number")
    ticket_id = ticket_number  # This is already in the format YYMMDD-N
    ticket_id_display = f"#{ticket_number}" if ticket_number else None

    # Map fields
    mapped = {
        "ticket_id": ticket_id,
        "ticket_id_display": ticket_id_display,
        "restaurant": parsed.get("restaurant"),
        "phone": None,  # Not in master prompt; we leave as None
        "ticket_date": parsed.get("date"),
        "terminal": parsed.get("terminal"),
        "table_name": parsed.get("table"),
        "department": parsed.get("department"),
        "user_name": parsed.get("user"),
        "payment_status": parsed.get("payment_status"),
        "credit_card_amount": parsed.get("credit_card_amount"),
        "ticket_total": parsed.get("ticket_total"),
        "grand_total": parsed.get("grand_total"),
        "charged": parsed.get("charged"),
        "extra_fields": parsed.get("extra_fields", {}),
        "items": parsed.get("items", []),
        # screenshot_filenames and raw_texts will be added by the caller
    }
    # Remove None values? We'll keep them as None; the storage function handles None.
    return mapped


def _map_docket_to_storage(
    parsed: Dict[str, Any],
    extracted_text: str,
    image_filename: str,
    extraction_method: str = "ocr_fallback",
    vision_review_flags: List[str] = None,
) -> Dict[str, Any]:
    """Map the master prompt's docket structure to the storage format expected by create_docket_record."""
    # Extract date and time
    date = parsed.get("date")
    time = parsed.get("time")

    # Determine review_required and review_reason
    docket_order_no = parsed.get("docket_order_no")
    discrepancy_type = parsed.get("discrepancy_type")
    vision_review_flags = vision_review_flags or []

    review_parts: List[str] = []
    if extraction_method == "vision":
        # The vision parse already reasoned about the image as a whole;
        # review flows from what the model could or could not commit to.
        if not docket_order_no:
            review_parts.append("Could not isolate one docket order number")
        if not discrepancy_type:
            review_parts.append("Could not isolate discrepancy marker")
        if "multiple_order_numbers" in vision_review_flags:
            review_parts.append("Multiple docket order numbers detected in one image")
    else:
        # OCR text is the only evidence on the fallback path.
        unique_order_numbers = list(dict.fromkeys(ORDER_NO_RE.findall(extracted_text)))
        ambiguous = len(unique_order_numbers) > 1
        if ambiguous:
            review_parts.append("Multiple docket order numbers detected in one image")
        elif not unique_order_numbers:
            review_parts.append("Could not isolate one docket order number")
        elif not discrepancy_type:
            review_parts.append("Could not isolate discrepancy marker")

    # Map fields
    mapped = {
        "docket_order_no": docket_order_no,
        "docket_date": date,
        "docket_time": time,
        "item": parsed.get("item"),
        "discrepancy_type": discrepancy_type,
        "handwritten_reason": parsed.get("handwritten_reason"),
        "printed_text": parsed.get("printed_text") or "",
        "raw_text": extracted_text,
        "extra_fields": parsed.get("extra_fields", {}),
        "image_filename": image_filename,
        "review_required": bool(review_parts),
        "review_reason": "; ".join(review_parts),
        "extraction_method": extraction_method,
    }
    return mapped


async def _process_uploaded_file(
    file: UploadFile = File(...),
    restaurant: str = Form(None, description="Restaurant name (optional - overrides OCR extraction)")
):
    # Validate file type
    if not file.content_type or not file.content_type.startswith("image/"):
        raise ValueError("File must be an image")

    # Generate unique filename to avoid conflicts
    original_filename = file.filename or "unnamed"
    file_extension = os.path.splitext(original_filename)[1]
    unique_filename = f"{uuid.uuid4()}{file_extension}"
    file_path = os.path.join(UPLOAD_DIR, unique_filename)

    try:
        # Save uploaded file
        contents = await file.read()
        with open(file_path, "wb") as f:
            f.write(contents)

        # Extract text from image using OCR
        extracted_text = extract_text_from_image(file_path)

        if _looks_like_ticket_screenshot(extracted_text):
            # Treat as ticket
            parsed_ticket, parsed_text, extraction_method = _extract_ticket_parsed(
                file_path, ocr_text=extracted_text
            )
            if not parsed_ticket.get("ticket_number"):
                raise ValueError("Ticket screenshot detected, but the full Ticket ID could not be parsed")

            # Map to storage format
            ticket_for_storage = _map_ticket_to_storage(parsed_ticket)
            ticket_for_storage["extraction_method"] = extraction_method

            # Save the ticket screenshot
            ticket_filename = f"ticket-{uuid.uuid4()}{file_extension or '.png'}"
            ticket_path = os.path.join(TICKET_SCREENSHOT_DIR, ticket_filename)
            with open(ticket_path, "wb") as ticket_handle:
                ticket_handle.write(contents)
            os.remove(file_path)
            file_path = ticket_path

            # Add screenshot_filenames and raw_texts
            ticket_for_storage["screenshot_filenames"] = [ticket_filename]
            ticket_for_storage["raw_texts"] = [extracted_text]

            record = upsert_ticket_record(ticket_for_storage)
            if get_ticket_record(ticket_for_storage["ticket_id"]) is None:
                raise RuntimeError("Ticket was saved but could not be retrieved")
            return {
                "record_type": "ticket",
                "filename": ticket_filename,
                "original_filename": original_filename,
                "extracted_text": extracted_text,
                "ticket_number": record["ticket_id"],
                "ticket_id": record["ticket_id"],
                "item_count": len(json.loads(record["items"])),
                "screenshot_count": len(json.loads(record["screenshot_filenames"])),
            }

        else:
            raise ValueError(
                "Unrecognized image type; use /api/upload/tickets for ticket screenshots "
                "or /api/upload/dockets for docket images"
            )

    except Exception as e:
        # Clean up file if processing failed
        if os.path.exists(file_path):
            os.remove(file_path)
        raise RuntimeError(f"Failed to process image: {str(e)}") from e


@router.post("/upload")
async def upload_bill_image(
    file: UploadFile = File(...),
    restaurant: str = Form(None, description="Restaurant name (optional - overrides OCR extraction)")
):
    """Upload and process one bill image."""
    try:
        return await _process_uploaded_file(file, restaurant)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=str(e)
        ) from e


@router.post("/upload/bulk")
async def upload_bill_images_bulk(
    files: List[UploadFile] = File(...),
    restaurant: str = Form(None, description="Restaurant name (optional - overrides OCR extraction)")
):
    """Process up to 30 bill images and report each result independently."""
    if len(files) > MAX_BULK_UPLOADS:
        raise HTTPException(
            status_code=400,
            detail=f"Bulk upload accepts at most {MAX_BULK_UPLOADS} images"
        )

    succeeded = []
    failed = []
    for file in files:
        original_filename = file.filename or "unnamed"
        try:
            succeeded.append(await _process_uploaded_file(file, restaurant))
        except Exception as e:
            failed.append({
                "filename": original_filename,
                "reason": str(e),
            })

    return {
        "total": len(files),
        "succeeded": succeeded,
        "failed": failed,
    }


@router.post("/upload/tickets")
async def upload_ticket_screenshots(files: List[UploadFile] = File(...)):
    """OCR and merge a batch of ticket screenshots by their Ticket ID."""
    if len(files) > MAX_BULK_UPLOADS:
        raise HTTPException(
            status_code=400,
            detail=f"Bulk ticket screenshot upload accepts at most {MAX_BULK_UPLOADS} files"
        )

    succeeded = []
    failed = []
    for file in files:
        original_filename = file.filename or "unnamed"
        file_path = None
        try:
            if not file.content_type or not file.content_type.startswith("image/"):
                raise ValueError("Ticket upload must be an image")

            extension = os.path.splitext(original_filename)[1] or ".png"
            stored_filename = f"ticket-{uuid.uuid4()}{extension}"
            file_path = os.path.join(TICKET_SCREENSHOT_DIR, stored_filename)
            contents = await file.read()
            with open(file_path, "wb") as handle:
                handle.write(contents)

            parsed, parsed_text, extraction_method = _extract_ticket_parsed(
                file_path, ocr_text=""
            )
            if not parsed.get("ticket_number"):
                raise ValueError("Could not extract Ticket ID in #YYMMDD-N format")

            # Map to storage format
            ticket_for_storage = _map_ticket_to_storage(parsed)
            ticket_for_storage["extraction_method"] = extraction_method
            ticket_for_storage["screenshot_filenames"] = [stored_filename]
            ticket_for_storage["raw_texts"] = [parsed_text]

            record = upsert_ticket_record(ticket_for_storage)
            succeeded.append({
                "filename": stored_filename,
                "original_filename": original_filename,
                "ticket_number": record["ticket_id"],
                "ticket_id": record["ticket_id"],
                "item_count": len(json.loads(record["items"])),
                "screenshot_count": len(json.loads(record["screenshot_filenames"])),
            })
        except Exception as error:
            if file_path and os.path.exists(file_path):
                os.remove(file_path)
            logger.exception("Ticket screenshot parsing failed for %s", original_filename)
            failed.append({
                "filename": original_filename,
                "reason": str(error),
            })

    return {
        "total": len(files),
        "succeeded": succeeded,
        "failed": failed,
    }


@router.post("/upload/dockets")
async def upload_docket_images(files: List[UploadFile] = File(...)):
    """OCR and store a batch of discrepancy dockets with partial failures."""
    if len(files) > MAX_BULK_UPLOADS:
        raise HTTPException(
            status_code=400,
            detail=f"Bulk docket upload accepts at most {MAX_BULK_UPLOADS} files"
        )

    succeeded = []
    failed = []
    for file in files:
        original_filename = file.filename or "unnamed"
        file_path = None
        try:
            if not file.content_type or not file.content_type.startswith("image/"):
                raise ValueError("Docket upload must be an image")

            extension = os.path.splitext(original_filename)[1] or ".png"
            stored_filename = f"docket-{uuid.uuid4()}{extension}"
            file_path = os.path.join(DOCKET_IMAGE_DIR, stored_filename)
            contents = await file.read()
            with open(file_path, "wb") as handle:
                handle.write(contents)

            parsed, raw_text, extraction_method, vision_review_flags = _extract_docket_parsed(
                file_path
            )
            # Map to storage format
            docket_for_storage = _map_docket_to_storage(
                parsed,
                raw_text,
                stored_filename,
                extraction_method=extraction_method,
                vision_review_flags=vision_review_flags,
            )
            if extraction_method == "ocr_fallback":
                # Never hide that a docket was read without vision.
                docket_for_storage["review_required"] = True
                fallback_reason = "Vision extraction unavailable or failed; OCR fallback used"
                existing_reason = docket_for_storage.get("review_reason") or ""
                docket_for_storage["review_reason"] = "; ".join(
                    part for part in (fallback_reason, existing_reason) if part
                )

            docket_id = create_docket_record(docket_for_storage)
            stored_docket = get_docket_record(docket_id)
            if stored_docket is None:
                raise RuntimeError("Docket was saved but could not be retrieved")
            succeeded.append({
                "id": stored_docket["id"],
                "filename": stored_filename,
                "original_filename": original_filename,
                "order_number": stored_docket["docket_order_no"],
                "date": stored_docket["docket_date"],
                "time": stored_docket["docket_time"],
                "item": stored_docket["item"],
                "discrepancy_type": stored_docket["discrepancy_type"],
                "description": stored_docket["handwritten_reason"],
                "review_required": bool(stored_docket["review_required"]),
                "review_reason": stored_docket["review_reason"],
            })
        except Exception as error:
            if file_path and os.path.exists(file_path):
                os.remove(file_path)
            failed.append({
                "filename": original_filename,
                "reason": str(error),
            })

    return {
        "total": len(files),
        "succeeded": succeeded,
        "failed": failed,
    }


@router.post("/upload/sales-reports")
async def upload_sales_reports(
    file: UploadFile = File(None, description="Photo of the long slip bill / printed Work Period Report (optional)"),
    excel_file: UploadFile = File(None, description="Excel Daily Exception Report .xlsx (optional)"),
    restaurant: str = Form(None, description="Operator-selected branch: Ilford / Southall / Norbury"),
    report_date: str = Form(None, description="Working day as YYYY-MM-DD; scopes the Excel log"),
    confirm: str = Form(None, description="On a slip/Excel mismatch: 'slip' or 'excel' confirms which source wins"),
):
    """Upload the two reference sources for one branch + day.

    Source 1 `file`        the long slip bill (printed Work Period Report):
                           per-department Voids/Discounts/Promotions/Cancelled.
    Source 2 `excel_file`  the Excel "Daily Exception Report" row-level log.

    Either may be uploaded alone. When both are supplied they are cross-verified
    at branch + day level before storage; a mismatch without `confirm` returns a
    structured 409 and stores NOTHING.
    """
    if file is None and excel_file is None:
        raise HTTPException(
            status_code=400,
            detail="Provide at least one of `file` (long slip image) or `excel_file`",
        )

    confirm = (confirm or "").strip().lower()
    if confirm not in ("", "slip", "excel"):
        raise HTTPException(status_code=400, detail="confirm must be empty, 'slip', or 'excel'")

    # The operator's selected day is the only scope. The slip's own printed date
    # is never used to define the day, because a till can print a date that
    # differs from the day the report is filed under.
    if not report_date:
        raise HTTPException(
            status_code=400,
            detail="A working day is required so the report is stored against the right day",
        )
    if not canonical_date_key(report_date):
        raise HTTPException(
            status_code=400,
            detail=f"Could not read '{report_date}' as a working day",
        )

    saved_paths: List[str] = []

    def _cleanup():
        for path in saved_paths:
            if path and os.path.exists(path):
                os.remove(path)

    try:
        image_path = None
        excel_path = None
        slip_parsed: t.Optional[Dict[str, Any]] = None
        excel_parsed: t.Optional[Dict[str, Any]] = None
        image_raw = ""
        method_image = None

        if file is not None:
            if not file.content_type or not file.content_type.startswith("image/"):
                raise ValueError("The long slip bill `file` must be an image")
            extension = os.path.splitext(file.filename or "")[1] or ".png"
            stored_image_name = f"sales-report-{uuid.uuid4()}{extension}"
            image_path = os.path.join(SALES_REPORT_DIR, stored_image_name)
            with open(image_path, "wb") as handle:
                handle.write(await file.read())
            saved_paths.append(image_path)
            slip_parsed, image_raw, method_image = _extract_sales_report_image(image_path)

        if excel_file is not None:
            if not (excel_file.filename or "").lower().endswith((".xlsx", ".xlsm")):
                raise ValueError("`excel_file` must be the Excel Daily Exception Report (.xlsx)")
            stored_excel_name = f"daily-exception-{uuid.uuid4()}.xlsx"
            excel_path = os.path.join(SALES_REPORT_DIR, stored_excel_name)
            with open(excel_path, "wb") as handle:
                handle.write(await excel_file.read())
            saved_paths.append(excel_path)
            excel_parsed = parse_daily_exception_report(
                excel_path,
                branch=restaurant,
                report_date=report_date,
            )
            if excel_parsed.get("error"):
                raise ValueError(excel_parsed["error"])
            if not excel_parsed.get("rows"):
                raise ValueError(
                    "The Daily Exception Report has no rows for this branch and date. "
                    f"Rows skipped as out of scope: {excel_parsed.get('skipped_rows', 0)}"
                )

        # The operator's branch always wins over a name read off the slip.
        branch = normalize_branch(restaurant) if restaurant else None
        if branch and slip_parsed is not None:
            slip_parsed["restaurant"] = branch

        cross_check = compare_slip_with_excel(slip_parsed, excel_parsed)
        if cross_check["mismatches"] and not confirm:
            _cleanup()
            raise HTTPException(
                status_code=409,
                detail={
                    "status": "mismatch",
                    "message": "Long slip and Excel report disagree; confirm which source to store before anything is saved",
                    "mismatches": cross_check["mismatches"],
                    "slip": cross_check["slip"],
                    "excel": cross_check["excel"],
                },
            )

        if slip_parsed is not None and excel_parsed is not None:
            if confirm == "excel" or (not confirm and not cross_check["mismatches"]):
                source = "excel (confirmed)" if confirm == "excel" else "slip+excel"
            else:
                source = "slip (confirmed)"
            if confirm and cross_check["mismatches"]:
                cross_verified = False
                confirmed_source = confirm
            else:
                cross_verified = not cross_check["mismatches"]
                confirmed_source = None
        else:
            source = "slip" if slip_parsed is not None else "excel"
            cross_verified = False
            confirmed_source = None

        final_branch = (slip_parsed or {}).get("restaurant") or (excel_parsed["rows"][0]["branch"] if excel_parsed and excel_parsed["rows"] else None)
        if not final_branch:
            raise HTTPException(
                status_code=400,
                detail="Could not determine the branch; the operator must select one",
            )

        stored = {
            "restaurant": final_branch,
            # The day scope comes from the operator, so the slip's own printed
            # date can never silently move the working day.
            "report_date": report_date,
            "departments": (slip_parsed or {}).get("departments", []),
            "source": source,
            "cross_verified": cross_verified,
            "confirmed_source": confirmed_source,
            "image_filename": os.path.basename(image_path) if image_path else None,
            "excel_filename": os.path.basename(excel_path) if excel_path else None,
            "extracted_text": image_raw,
            "extraction_method": method_image if slip_parsed is not None else "xlsx",
            "extra_fields": (slip_parsed or {}).get("extra_fields", {}),
            "excel_rows": (excel_parsed or {}).get("rows", []),
            "excel_summary": (excel_parsed or {}).get("summary", {}),
            "excel_skipped_rows": (excel_parsed or {}).get("skipped_rows", 0),
            "excel_void_rows": (excel_parsed or {}).get("void_rows", 0),
            "excel_unfilled_rows": (excel_parsed or {}).get("unfilled_rows", 0),
        }
        record = upsert_sales_report(stored)
        if get_sales_report_by_id(record["id"]) is None:
            raise RuntimeError("Sales report was saved but could not be retrieved")

        return {
            "id": record["id"],
            "restaurant": record["restaurant"],
            "report_date": record["report_date"],
            "departments": json.loads(record["departments"]),
            "source": record["source"],
            "cross_verified": bool(record["cross_verified"]),
            "confirmed_source": record["confirmed_source"],
            "extraction_method": record["extraction_method"],
            "image_filename": record["image_filename"],
            "excel_filename": record["excel_filename"],
            "excel": {
                "void_rows": record["excel_void_rows"],
                "unfilled_rows": record["excel_unfilled_rows"],
                "skipped_rows": record["excel_skipped_rows"],
                "discount_rows": (excel_parsed or {}).get("discount_rows", 0),
                "promotion_rows": (excel_parsed or {}).get("promotion_rows", 0),
            } if excel_parsed is not None else None,
            "cross_check": cross_check,
        }
    except HTTPException:
        raise
    except Exception as error:
        _cleanup()
        logger.exception("Sales report upload failed: %s", error)
        raise HTTPException(status_code=400, detail=str(error)) from error
