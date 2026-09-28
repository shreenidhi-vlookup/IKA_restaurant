"""Division 6 aggregate reconciliation: sales report vs per-pair void tally.

The sales report is the ground truth ("X voids happened today"). The existing
per-pair tally (Division 5c) says how many of those voids we have matched
ticket item -> docket for. The gap between the two is what remains unresolved.

This is an AGGREGATE layer on top of the per-pair one:
- reported: the sales report's department-level Voids Total (count)
- matched:  per-pair rows whose status is "matched", grouped by
            restaurant / date / department
- unresolved: reported - matched, shown when both numbers exist
- anomaly:   matched > reported => surfaced, never silently ignored

Discounts / promotions are read from the report but are NOT compared against
a pair tally: per mvp_spec the ticket/docket pair tally currently tracks
voids only. Those sections are surfaced as reported-but-untracked (a coverage
gap), never faked as matched counts.

`build_process_dashboard()` is what the UI's Process button renders. It owns
every number: the frontend draws the dashboard from this payload and never
counts, matches or subtracts anything itself.
"""

import json
import re
import typing as t
from collections import defaultdict
from datetime import datetime

from fastapi import APIRouter, Body
from pydantic import BaseModel

from app.storage.db import (
    get_daily_exception_rows,
    get_docket_records,
    get_sales_reports,
    get_ticket_records,
)
from app.models.daily_exception import normalize_branch
from app.models.sales_report import canonical_date_key, compare_slip_with_excel
from app.api.void_reconciliation import build_void_reconciliation


router = APIRouter()

_METRICS = (
    ("voids_count", "voids_amount"),
    ("discounts_count", "discounts_amount"),
    ("promotions_count", "promotions_amount"),
    ("cancelled_count", "cancelled_amount"),
)

_UNTRACKED_NOTE = "not yet reconciled - the ticket/docket tally tracks voids only"


def _norm_restaurant(value: t.Optional[str]) -> str:
    """Branch-aware restaurant key.

    The operator selects a branch (Ilford / Southall / Norbury) while the
    stored tickets carry the till's own names ("Haweli Ilford Ltd",
    "Haweli Restaurant Southall"). Both must collapse onto the same key or
    nothing would ever match.
    """
    branch = normalize_branch(value)
    if branch:
        return branch.casefold()
    return re.sub(r"\s+", " ", str(value or "")).strip().casefold()


def _norm_department(value: t.Optional[str]) -> t.Optional[str]:
    if not value:
        return None
    cleaned = re.sub(r"\b(?:incomes?|department|dept|section|division)\b", " ", str(value), flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip().upper()
    return cleaned or None


def _date_key(value: t.Optional[str]) -> str:
    return canonical_date_key(value)


def _ticket_date_key(ticket: t.Dict[str, t.Any]) -> str:
    """The ticket's working day: its Ticket ID's YYMMDD prefix wins.

    A ticket can print a different date from the day its docket is filed
    under, so the printed date is only a fallback. See
    app.api.void_reconciliation._ticket_date for the reasoning.
    """
    match = re.search(r"(?:#)?(\d{2})(\d{2})(\d{2})-\d+$", ticket.get("ticket_id_key", ""))
    if match:
        return "20{}{}{}".format(match.group(1), match.group(2), match.group(3))
    return _date_key(ticket.get("ticket_date"))


def build_sales_report_reconciliation() -> t.Dict[str, t.Any]:
    pair_tally = build_void_reconciliation()

    matched_by_key: t.Dict[t.Tuple[str, str, t.Optional[str]], int] = defaultdict(int)
    void_items_by_key: t.Dict[t.Tuple[str, str, t.Optional[str]], int] = defaultdict(int)

    for row in pair_tally["rows"]:
        ticket = row["ticket"]
        key = (
            _norm_restaurant(ticket.get("restaurant")),
            _ticket_date_key(ticket),
            _norm_department(ticket.get("department")),
        )
        void_items_by_key[key] += 1
        if row["status"] == "matched":
            matched_by_key[key] += 1

    reports_out: t.List[t.Dict[str, t.Any]] = []
    for report_row in get_sales_reports():
        departments = _json(report_row["departments"], [])
        department_rows: t.List[t.Dict[str, t.Any]] = []
        for department in departments:
            name = department.get("name")
            key = (
                _norm_restaurant(report_row["restaurant"]),
                _date_key(report_row["report_date"]),
                _norm_department(name),
            )

            reported_voids = department.get("voids_count")
            matched_voids = matched_by_key.get(key, 0)

            voids_row: t.Dict[str, t.Any] = {
                "reported": reported_voids,
                "matched": matched_voids,
            }
            if reported_voids is not None:
                voids_row["unresolved"] = max(reported_voids - matched_voids, 0)
                voids_row["anomaly"] = matched_voids > reported_voids
            else:
                voids_row["unresolved"] = None
                voids_row["anomaly"] = None

            def _gap(total_count, label: str) -> t.Dict[str, t.Any]:
                # The pair tally has no discount/promotion pair rows, so these
                # can never be subtracted — surface the gap instead.
                return {
                    "reported": total_count,
                    "tracked": False,
                    "note": label,
                }

            discounts_row = _gap(department.get("discounts_count"), "pair tally tracks voids only; discounts are not paired")
            promotions_row = _gap(department.get("promotions_count"), "pair tally tracks voids only; promotions are not paired")

            department_rows.append({
                "name": name,
                "voids": voids_row,
                "discounts": discounts_row,
                "promotions": promotions_row,
                "extra": {
                    "cancelled_count": department.get("cancelled_count"),
                    "cancelled_amount": department.get("cancelled_amount"),
                },
            })

        reports_out.append({
            "id": report_row["id"],
            "restaurant": report_row["restaurant"],
            "report_date": report_row["report_date"],
            "source": report_row["source"],
            "cross_verified": bool(report_row["cross_verified"]),
            "departments": department_rows,
        })

    return {
        "reports": reports_out,
        "pair_tally_summary": pair_tally["summary"],
        "coverage": {
            "voids": "tracked (per-pair matched counts subtracted from reported)",
            "discounts": "reported but NOT tracked by the pair tally — coverage gap",
            "promotions": "reported but NOT tracked by the pair tally — coverage gap",
        },
    }


def _json(raw, fallback):
    if not raw:
        return fallback
    try:
        return json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return fallback


@router.get("/sales-reports/reconcile")
async def reconcile_sales_reports():
    """Aggregate reported vs matched vs unresolved figures per department."""
    return build_sales_report_reconciliation()


# --------------------------------------------------------------------------
# Process dashboard
# --------------------------------------------------------------------------

class ProcessRequest(BaseModel):
    restaurant: str
    date: t.Optional[str] = None


def _metric_values(department: t.Optional[t.Dict[str, t.Any]]) -> t.Dict[str, t.Any]:
    """One department's four metrics as flat count/amount pairs."""
    department = department or {}
    return {name: department.get(name) for pair in _METRICS for name in pair}


def _departments_by_name(departments: t.Optional[t.List[t.Dict[str, t.Any]]]) -> t.Dict[str, t.Dict[str, t.Any]]:
    return {
        _norm_department(department.get("name")): department
        for department in (departments or [])
        if department
    }


def _sum_metrics(
    rows: t.Iterable[t.Dict[str, t.Any]],
) -> t.Dict[str, t.Any]:
    """Sum each count/amount field across departments; None only if all None."""
    totals: t.Dict[str, t.Any] = {}
    rows = list(rows)
    for count_field, amount_field in _METRICS:
        for field in (count_field, amount_field):
            values = [row.get(field) for row in rows if row.get(field) is not None]
            totals[field] = round(sum(values), 2) if values else None
    return totals


def _find_report(restaurant: str, date: t.Optional[str]) -> t.Optional[t.Any]:
    """The stored report for this restaurant, on `date` when one is given."""
    target = _date_key(date)
    candidates = [
        row for row in get_sales_reports()
        if _norm_restaurant(row["restaurant"]) == _norm_restaurant(restaurant)
    ]
    if target:
        candidates = [row for row in candidates if _date_key(row["report_date"]) == target]
    else:
        # No date given: the newest stored report for this restaurant defines
        # the working day, and the resolved date is returned to the UI.
        candidates.sort(key=lambda row: (row["report_date"] or "", row["updated_at"] or "", row["id"]), reverse=True)
    return candidates[0] if candidates else None


def _tickets_in_scope(restaurant: str, report_date: t.Optional[str]) -> t.List[t.Dict[str, t.Any]]:
    target = _date_key(report_date)
    out = []
    for row in get_ticket_records():
        if _norm_restaurant(row["restaurant"]) != _norm_restaurant(restaurant):
            continue
        if target and _ticket_date_key({
            "ticket_date": row["ticket_date"],
            "ticket_id_key": row["ticket_id"],
        }) != target:
            continue
        out.append(row)
    return out


def _dockets_in_scope(report_date: t.Optional[str]) -> t.List[t.Dict[str, t.Any]]:
    """Dockets carry no restaurant column, so they can only be date-scoped.

    The dashboard says so in `scope` rather than implying restaurant scope.
    """
    target = _date_key(report_date)
    if not target:
        return list(get_docket_records())
    return [row for row in get_docket_records() if _date_key(row["docket_date"]) == target]


def _empty_excel_view() -> t.Dict[str, t.Any]:
    """The Source 2 figures when no Excel log is stored for this branch + day.

    Every key the dashboard and the UI read must be present, so the frontend
    renders the named empty state instead of failing on a missing field.
    """
    return {
        "uploaded": False,
        "filename": None,
        "void_rows": 0,
        "voids_amount": None,
        "unfilled_rows": 0,
        "discount_rows": 0,
        "discounts_amount": None,
        "promotion_rows": 0,
        "promotions_amount": None,
        "skipped_rows": 0,
        "summary": {},
        "void_bills_found": [],
        "void_bills_not_found": [],
    }


def _excel_view(
    report: t.Any,
    date_key: str,
    restaurant: t.Optional[str] = None,
) -> t.Dict[str, t.Any]:
    """Source 2 figures for the stored report: void rows, amount, unfilled rows."""
    if report is None or not report["excel_filename"]:
        return _empty_excel_view()

    rows = [dict(row) for row in get_daily_exception_rows(report["id"])]
    void_rows = [row for row in rows if row["adjustment"] == "void"]
    unfilled = [row for row in rows if row["adjustment"] == "unfilled"]
    discounts = [row for row in rows if row["adjustment"] == "discount"]
    promotions = [row for row in rows if row["adjustment"] == "promotion"]

    def _amount(selection: t.List[t.Dict[str, t.Any]]) -> t.Optional[float]:
        values = [row["amount"] for row in selection if row["amount"] is not None]
        return round(sum(values), 2) if values else None

    # Excel void bills vs the uploaded tickets, matched on the normalized bill
    # number, which is the full ticket id. Only tickets in the same branch and
    # day are considered, so a bill that happens to share an id with another
    # branch's ticket is not reported as found.
    ticket_ids = {
        ticket["ticket_id"]
        for ticket in _tickets_in_scope(restaurant, date_key)
    }
    matched_bill_numbers = {row["bill_number"] for row in void_rows if row["bill_number"] in ticket_ids}

    def _bills(selection: t.List[t.Dict[str, t.Any]]) -> t.List[Dict[str, t.Any]]:
        return [{
            "bill_number": row["bill_number"],
            "item": row["item"],
            "amount": row["amount"],
            "adjustment_type": row["adjustment_type"],
            "found_in_tickets": row["bill_number"] in ticket_ids,
        } for row in selection]

    found = _bills([row for row in void_rows if row["bill_number"] in matched_bill_numbers])
    not_found = _bills([row for row in void_rows if row["bill_number"] not in ticket_ids])

    return {
        "uploaded": True,
        "filename": report["excel_filename"],
        "void_rows": len(void_rows),
        "voids_amount": _amount(void_rows),
        "unfilled_rows": len(unfilled),
        "discount_rows": len(discounts),
        "discounts_amount": _amount(discounts),
        "promotion_rows": len(promotions),
        "promotions_amount": _amount(promotions),
        "skipped_rows": report["excel_skipped_rows"] or 0,
        "summary": _json(report["excel_summary"], {}),
        "void_bills_found": found,
        "void_bills_not_found": not_found,
    }


def _department_view(
    name: str,
    reported_department: t.Optional[t.Dict[str, t.Any]],
    matched: int,
    void_items: int = 0,
) -> t.Dict[str, t.Any]:
    """One department of Source 1 (the long slip) plus its tally figures."""
    reported_metrics = _metric_values(reported_department)
    reported_voids = reported_metrics["voids_count"]

    unresolved = None
    anomaly = None
    if reported_voids is not None:
        unresolved = max(reported_voids - matched, 0)
        anomaly = matched > reported_voids

    return {
        "name": name,
        "bill": reported_metrics,
        "void_items_in_tickets": void_items,
        "matched": matched,
        "unresolved": unresolved,
        "anomaly": anomaly,
        "discounts": {
            "reported_count": reported_metrics["discounts_count"],
            "reported_amount": reported_metrics["discounts_amount"],
            "tracked": False,
            "note": _UNTRACKED_NOTE,
        },
        "promotions": {
            "reported_count": reported_metrics["promotions_count"],
            "reported_amount": reported_metrics["promotions_amount"],
            "tracked": False,
            "note": _UNTRACKED_NOTE,
        },
        "cancelled": {
            "count": reported_metrics["cancelled_count"],
            "amount": reported_metrics["cancelled_amount"],
        },
    }


def build_process_dashboard(restaurant: str, date: t.Optional[str] = None) -> t.Dict[str, t.Any]:
    """Every Process-dashboard figure for one branch + day, from stored data.

    Recomputed on each call so the dashboard always reflects the latest
    uploads. The frontend renders this payload verbatim.
    """
    report = _find_report(restaurant, date)
    report_date = report["report_date"] if report is not None else date

    tickets = _tickets_in_scope(restaurant, report_date)
    dockets = _dockets_in_scope(report_date)
    void_items = [
        item for row in tickets for item in _json(row["items"], []) if item.get("is_void") is True
    ]

    pair_tally = build_void_reconciliation()
    restaurant_key = _norm_restaurant(restaurant)
    date_key = _date_key(report_date)

    def _row_in_scope(row: t.Dict[str, t.Any]) -> bool:
        ticket = row["ticket"]
        return (
            _norm_restaurant(ticket.get("restaurant")) == restaurant_key
            and (not date_key or _ticket_date_key(ticket) == date_key)
        )

    scoped_rows = [row for row in pair_tally["rows"] if _row_in_scope(row)]

    matched_by_department: t.Dict[t.Optional[str], int] = defaultdict(int)
    void_items_by_department: t.Dict[t.Optional[str], int] = defaultdict(int)
    for row in scoped_rows:
        department = _norm_department(row["ticket"].get("department"))
        void_items_by_department[department] += 1
        if row["status"] == "matched":
            matched_by_department[department] += 1

    reported_departments = _departments_by_name(
        _json(report["departments"], None) if report is not None else None
    )
    department_names = sorted(
        {name for name in reported_departments if name} | set(void_items_by_department)
    )
    departments = [
        _department_view(
            name,
            reported_departments.get(name),
            matched_by_department.get(name, 0),
            void_items_by_department.get(name, 0),
        )
        for name in department_names
    ]

    total_matched = sum(matched_by_department.values())
    total_view = _department_view(
        "ALL DEPARTMENTS",
        _sum_metrics(reported_departments.values()),
        total_matched,
        len(void_items),
    )

    excel = _excel_view(report, date_key, restaurant)
    cross_check = compare_slip_with_excel(
        {"departments": _json(report["departments"], [])} if report is not None and report["image_filename"] else None,
        {"void_rows": excel["void_rows"], "voids_amount": excel["voids_amount"]} if excel["uploaded"] else None,
    )

    # The tally pairs a ticket void with a docket on the docket's trailing
    # order number, so a matched docket can carry a different printed date
    # from the ticket's working day. "Dockets filed on this day" and "dockets
    # used in a match" are therefore different numbers, and both are reported
    # rather than one standing in for the other.
    matched_docket_ids = {
        row["docket"].get("docket_id")
        for row in scoped_rows
        if row["status"] == "matched" and row.get("docket")
    }
    dockets_outside_day = [
        row for row in scoped_rows
        if row["status"] == "matched"
        and row.get("docket")
        and _date_key(row["docket"].get("docket_date")) != date_key
    ]

    # Unmatched ticket voids: void items with no docket to pair with.
    unmatched_ticket_voids = [
        {
            "ticket_id": row["ticket"].get("ticket_id"),
            "department": row["ticket"].get("department"),
            "item": row["ticket"]["item"].get("name"),
            "quantity": row["ticket"]["item"].get("quantity"),
            "unit_price": row["ticket"]["item"].get("unit_price"),
            "total": row["ticket"]["item"].get("total"),
            "reason": row["match_reason"],
        }
        for row in scoped_rows if row["status"] == "unmatched"
    ]

    # Unmatched dockets: any docket in scope that no void item was paired with.
    paired_docket_ids = {
        row["docket"]["id"] for row in scoped_rows if row["docket"] is not None
    }
    unmatched_dockets = [
        {
            "order_number": row["docket_order_no"],
            "date": row["docket_date"],
            "time": row["docket_time"],
            "item": row["item"],
            "discrepancy_type": row["discrepancy_type"],
            "image_filename": row["image_filename"],
            "review_required": bool(row["review_required"]),
        }
        for row in dockets
        if row["id"] not in paired_docket_ids
    ]

    missing = []
    if report is None or (not report["image_filename"] and not report["excel_filename"]):
        missing.append("long slip bill and Excel report")
    elif not report["image_filename"]:
        missing.append("long slip bill image")
    elif not report["excel_filename"]:
        missing.append("Excel report")
    if not tickets:
        missing.append("tickets")
    if not dockets:
        missing.append("dockets")

    return {
        "restaurant": restaurant,
        "report_date": report_date,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "ready": not missing,
        "missing": missing,
        "report": {
            "id": report["id"],
            "restaurant": report["restaurant"],
            "report_date": report["report_date"],
            "source": report["source"],
            "cross_verified": bool(report["cross_verified"]),
            "confirmed_source": report["confirmed_source"],
            "extraction_method": report["extraction_method"],
            "image_filename": report["image_filename"],
            "excel_filename": report["excel_filename"],
        } if report is not None else None,
        "bill": {
            "uploaded": bool(report is not None and report["image_filename"]),
            "filename": report["image_filename"] if report is not None else None,
            "extraction_method": report["extraction_method"] if report is not None else None,
        },
        "excel": excel,
        "bill_vs_excel": cross_check,
        "counts": {
            "tickets": len(tickets),
            "void_items_in_tickets": len(void_items),
            "dockets": len(dockets),
            "dockets_used_in_matches": len(matched_docket_ids),
            "matched_dockets_filed_on_another_day": len(dockets_outside_day),
            "matched": total_matched,
            "needs_review": sum(row["status"] == "needs_review" for row in scoped_rows),
            "unresolved_voids": total_view["unresolved"],
            "unmatched_ticket_voids": len(unmatched_ticket_voids),
            "unmatched_dockets": len(unmatched_dockets),
            "excel_void_bills_found": len(excel["void_bills_found"]),
            "excel_void_bills_not_found": len(excel["void_bills_not_found"]),
        },
        "docket_scope": "date_only",
        "departments": departments,
        "totals": total_view,
        "unmatched_ticket_voids": unmatched_ticket_voids,
        "unmatched_dockets": unmatched_dockets,
        "coverage": {
            "voids": "reconciled: slip voids minus matched ticket/docket pairs",
            "discounts": "not yet reconciled - reported by both sources, not paired by the tally",
            "promotions": "not yet reconciled - reported by both sources, not paired by the tally",
            "cancelled": "reported by the slip only",
            "dockets": (
                "dockets have no restaurant field, so docket figures are scoped by date only; "
                "a docket is paired on its trailing order number, so a matched docket may carry a "
                "printed date other than the ticket's working day"
            ),
            "void_count": cross_check["count_comparison"]["note"],
        },
    }


@router.post("/sales-reports/process")
async def process_sales_report(payload: ProcessRequest = Body(...)):
    """Run the reconciliation for one branch + day and return the dashboard.

    `date` is optional; when omitted the stored report's date defines the
    working day and the resolved date comes back in the payload.
    """
    restaurant = (payload.restaurant or "").strip()
    if not restaurant:
        return build_process_dashboard("", payload.date)
    return build_process_dashboard(restaurant, (payload.date or "").strip() or None)
