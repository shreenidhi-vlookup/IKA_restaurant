import csv
import io
import json
from typing import Any, Dict, List

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.models.daily_exception import BRANCHES, normalize_branch
from app.storage.db import get_docket_records, get_sales_reports, get_ticket_items, get_ticket_records


router = APIRouter()


def _json(raw: str, fallback: Any) -> Any:
    if not raw:
        return fallback
    try:
        return json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return fallback


def _ticket_record(row) -> Dict[str, Any]:
    items = [dict(item) for item in get_ticket_items(row["ticket_id"])]
    for item in items:
        item["is_void"] = bool(item["is_void"])
    return {
        "ticket_id": row["ticket_id"],
        "uploaded_at": row["updated_at"],
        "restaurant": row["restaurant"],
        "phone": row["phone"],
        "date": row["ticket_date"],
        "terminal": row["terminal"],
        "table": row["table_name"],
        "department": row["department"],
        "user": row["user_name"],
        "payment_status": row["payment_status"],
        "credit_card_amount": row["credit_card_amount"],
        "ticket_total": row["ticket_total"],
        "grand_total": row["grand_total"],
        "charged": row["charged"],
        "extra_fields": _json(row["extra_fields"], {}),
        "items": items,
        "screenshot_filenames": _json(row["screenshot_filenames"], []),
        "extraction_method": row["extraction_method"],
    }


def _docket_record(row) -> Dict[str, Any]:
    return {
        "id": row["id"],
        "order_number": row["docket_order_no"],
        "date": row["docket_date"],
        "time": row["docket_time"],
        "item": row["item"],
        "discrepancy_type": row["discrepancy_type"],
        "description": row["handwritten_reason"],
        "extra_fields": _json(row["extra_fields"], {}),
        "image_filename": row["image_filename"],
        "review_required": bool(row["review_required"]),
        "review_reason": row["review_reason"],
        "extraction_method": row["extraction_method"],
    }


def _sales_report_payload(row) -> Dict[str, Any]:
    return {
        "id": row["id"],
        "restaurant": row["restaurant"],
        "report_date": row["report_date"],
        "departments": _json(row["departments"], []),
        "source": row["source"],
        "cross_verified": bool(row["cross_verified"]),
        "confirmed_source": row["confirmed_source"],
        "extraction_method": row["extraction_method"],
        "image_filename": row["image_filename"],
        "excel_filename": row["excel_filename"],
        "excel": {
            "void_rows": row["excel_void_rows"],
            "unfilled_rows": row["excel_unfilled_rows"],
            "skipped_rows": row["excel_skipped_rows"],
        },
        "extra_fields": _json(row["extra_fields"], {}),
    }


@router.get("/tickets")
async def get_ticket_records_endpoint() -> List[Dict[str, Any]]:
    """Return parsed ticket records with their complete item arrays."""
    return [_ticket_record(row) for row in get_ticket_records()]


@router.get("/dockets")
async def get_docket_records_endpoint() -> List[Dict[str, Any]]:
    """Return parsed docket records, including separate handwriting fields."""
    return [_docket_record(row) for row in get_docket_records()]


@router.get("/restaurants")
async def get_restaurants() -> List[Dict[str, Any]]:
    """The branch names the operator selects, with the ticket names behind each.

    The frontend renders this list; it must never hardcode branches or map
    restaurant names itself. All three branches are always returned, even
    before any ticket has been uploaded for them, so the operator can pick the
    branch they are working on rather than only the ones that already have data.
    """
    seen: Dict[str, List[str]] = {branch: [] for branch in BRANCHES}
    for row in get_ticket_records():
        branch = normalize_branch(row["restaurant"])
        if branch and row["restaurant"] not in seen[branch]:
            seen[branch].append(row["restaurant"])
    return [{"branch": branch, "restaurant_names": seen[branch]} for branch in BRANCHES]


@router.get("/sales-reports")
async def get_sales_reports_endpoint() -> List[Dict[str, Any]]:
    """Return stored sales report (work period) records."""
    return [_sales_report_payload(row) for row in get_sales_reports()]


@router.get("/tickets/export")
async def export_ticket_records():
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "ticket_id", "uploaded_at", "restaurant", "terminal", "department", "user", "date",
        "item", "category", "price", "quantity", "total", "is_void",
        "payment_status", "credit_card_amount", "ticket_total", "grand_total",
        "charged", "extra_fields", "screenshots", "extraction_method",
    ])
    for ticket in await get_ticket_records_endpoint():
        for item in ticket["items"] or [{}]:
            writer.writerow([
                ticket["ticket_id"], ticket["uploaded_at"], ticket["restaurant"], ticket["terminal"],
                ticket["department"], ticket["user"], ticket["date"],
                item.get("name"), item.get("category"), item.get("unit_price"),
                item.get("quantity"), item.get("total"), item.get("is_void", False),
                ticket["payment_status"], ticket["credit_card_amount"],
                ticket["ticket_total"], ticket["grand_total"], ticket["charged"],
                json.dumps(ticket["extra_fields"]), json.dumps(ticket["screenshot_filenames"]),
                ticket["extraction_method"],
            ])
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=tickets.csv"},
    )


@router.get("/dockets/export")
async def export_docket_records():
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "order_number", "date", "time", "item",
        "discrepancy_type", "description", "review_required",
        "review_reason", "image_filename", "extra_fields", "extraction_method",
    ])
    for docket in await get_docket_records_endpoint():
        writer.writerow([
            docket["order_number"], docket["date"], docket["time"],
            docket["item"], docket["discrepancy_type"], docket["description"],
            docket["review_required"], docket["review_reason"], docket["image_filename"],
            json.dumps(docket["extra_fields"]), docket["extraction_method"],
        ])
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=dockets.csv"},
    )


@router.get("/sales-reports/export")
async def export_sales_reports():
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "report_id", "branch", "report_date", "source", "cross_verified",
        "department", "voids_count", "voids_amount", "discounts_count",
        "discounts_amount", "promotions_count", "promotions_amount",
        "cancelled_count", "cancelled_amount", "image_filename", "excel_filename",
        "excel_void_rows", "excel_unfilled_rows", "excel_skipped_rows", "extra_fields",
    ])
    for report in await get_sales_reports_endpoint():
        departments = report["departments"] or [{}]
        for department in departments:
            writer.writerow([
                report["id"], report["restaurant"], report["report_date"],
                report["source"], report["cross_verified"],
                department.get("name"), department.get("voids_count"),
                department.get("voids_amount"), department.get("discounts_count"),
                department.get("discounts_amount"), department.get("promotions_count"),
                department.get("promotions_amount"), department.get("cancelled_count"),
                department.get("cancelled_amount"), report["image_filename"],
                report["excel_filename"],
                report["excel"]["void_rows"], report["excel"]["unfilled_rows"],
                report["excel"]["skipped_rows"], json.dumps(report["extra_fields"]),
            ])
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=sales-reports.csv"},
    )