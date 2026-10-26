import csv
from difflib import SequenceMatcher
import io
import json
import re
from datetime import date, datetime
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.parsers.ticket_report_parser import parse_ticket_report, TicketReportParseError
from app.services.unpaid_ticket_service import get_unpaid_tickets, count_unpaid_tickets
from app.storage.db import get_db_connection

router = APIRouter()


def _norm(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").casefold())


def _product_key(value: Any, learned_suffixes: set[str]) -> str:
    text = str(value or "").casefold().strip()
    text = re.sub(r"^\s*\d+(?:\.\d+)?\s*(?:x\s*)?", "", text)
    text = re.sub(r"\s*\(void\)\s*$", "", text, flags=re.I)
    text = re.sub(r"\([^)]*(?:£|Â£)\s*\d+(?:\.\d+)?[^)]*\)", "", text)
    if "." in text:
        base, suffix = text.rsplit(".", 1)
        if suffix.strip() in learned_suffixes:
            text = base
    return re.sub(r"[^a-z0-9]+", "", text)


def _text_match(left: Any, right: Any, threshold: float = 0.88) -> bool:
    """Match OCR text conservatively after punctuation/case normalization."""
    a, b = _norm(left), _norm(right)
    if not a or not b:
        return False
    if a == b or set(a.split()) == set(b.split()):
        return True
    if min(len(a), len(b)) < 5:
        return False
    return SequenceMatcher(None, a, b).ratio() >= threshold


def _product_match(left: Any, right: Any, learned_suffixes: set[str]) -> bool:
    return _text_match(_product_key(left, learned_suffixes), _product_key(right, learned_suffixes), 0.86)


def _day(value: Any) -> str:
    text = str(value or "").strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            pass
    return text


def _ticket_day(ticket_id: str) -> str:
    if re.fullmatch(r"\d{6}-\d+", ticket_id or ""):
        return f"20{ticket_id[:2]}-{ticket_id[2:4]}-{ticket_id[4:6]}"
    return ""


def _docket_items(docket: dict[str, Any]) -> list[dict[str, Any]]:
    try:
        items = json.loads(docket.get("item_lines") or "[]")
    except (TypeError, json.JSONDecodeError):
        items = []
    if not items and docket.get("item"):
        items = [{"name": docket["item"], "is_void": (docket.get("discrepancy_type") or "").casefold() == "void", "marker_type": docket.get("discrepancy_type")}]
    return items


def _match_num(value: Any) -> float | None:
    try:
        return round(float(re.sub(r"[^0-9.-]", "", str(value or ""))), 2)
    except (ValueError, TypeError):
        return None

def _num(value: Any) -> float | None:
    try:
        return round(float(str(value).replace("£", "").replace(",", "").strip()), 2)
    except (ValueError, TypeError):
        return None


@router.post("/csv")
async def upload_csv(branch: str = Form(...), selected_date: str = Form(...), file: UploadFile = File(...), confirm_date_mismatch: bool = Form(False)):
    if not branch.strip():
        raise HTTPException(400, "Select a branch")
    try:
        date.fromisoformat(selected_date)
    except ValueError as exc:
        raise HTTPException(400, "Date must be YYYY-MM-DD") from exc
    if not (file.filename or "").lower().endswith(".csv"):
        raise HTTPException(400, "Upload one CSV file")
    content = (await file.read()).decode("utf-8-sig")
    lines = [line for line in content.splitlines() if line.strip()]
    header_index = next((i for i, line in enumerate(lines) if "Product Name" in line), None)
    if header_index is None:
        raise HTTPException(400, "Could not find the Product Name header row")
    parsed = list(csv.DictReader(io.StringIO("\n".join(lines[header_index:]))))
    parsed = [{(k or "").strip(): (v or "").strip() for k, v in row.items()} for row in parsed]
    dates = sorted({r.get("Date") for r in parsed if r.get("Date") and r.get("Date") != selected_date})
    if dates and not confirm_date_mismatch:
        return {"confirmation_required": True, "selected_date": selected_date, "csv_dates": dates, "message": "CSV dates differ from the selected date. Confirm to continue."}
    if not parsed:
        raise HTTPException(400, "CSV contains no item rows")
    headers = set(parsed[0])
    promo_column = next((h for h in headers if h.casefold() in {"promotion", "promotions", "discount", "discounts"}), None)
    with get_db_connection() as conn:
        conn.execute("DELETE FROM csv_rows WHERE branch=? AND selected_date=?", (branch, selected_date))
        for row in parsed:
            flags = {"void": _num(row.get("Void")) or 0, "cancel": _num(row.get("Cancel")) or 0, "promotion": _num(row.get(promo_column)) or 0 if promo_column else 0}
            conn.execute("INSERT INTO csv_rows(branch,selected_date,row_date,product,quantity,user_name,department,till,category,group_name,sales_value,void_count,cancel_count,promotion_count,raw_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
                branch, selected_date, row.get("Date"), row.get("Product Name"), _num(row.get("Quantity")) or 0, row.get("User"), row.get("Department"), row.get("Till"), row.get("Category"), row.get("Group"), _num(row.get("Sales Value")) or 0, flags["void"], flags["cancel"], flags["promotion"], json.dumps(row, ensure_ascii=False)))
        conn.execute("""INSERT INTO csv_imports(branch,selected_date,filename,promotions_in_file) VALUES(?,?,?,?)
            ON CONFLICT(branch,selected_date) DO UPDATE SET filename=excluded.filename,promotions_in_file=excluded.promotions_in_file""",
                     (branch, selected_date, file.filename, int(bool(promo_column))))
        conn.commit()
    return {"saved_rows": len(parsed), "branch": branch, "date": selected_date, "csv_dates": sorted({r.get("Date") for r in parsed if r.get("Date")}), "promotions_in_file": bool(promo_column)}


@router.post("/ticket-report")
async def upload_ticket_report(branch: str = Form(...), selected_date: str = Form(...), file: UploadFile = File(...)):
    if not branch.strip():
        raise HTTPException(400, "Select a branch")
    try:
        date.fromisoformat(selected_date)
    except ValueError as exc:
        raise HTTPException(400, "Date must be YYYY-MM-DD") from exc
    if not (file.filename or "").lower().endswith(".csv"):
        raise HTTPException(400, "Upload one CSV file")
    content = (await file.read()).decode("utf-8-sig")
    try:
        records = parse_ticket_report(content)
    except TicketReportParseError as exc:
        raise HTTPException(400, exc.message) from exc
    unpaid = get_unpaid_tickets(records)
    unpaid_count = count_unpaid_tickets(records)
    unpaid_details = [
        {
            "ticket_id": ticket.ticket_id,
            "terminal": ticket.terminal,
            "department": ticket.department,
            "user": ticket.user,
            "date": ticket.date,
            "time": ticket.time,
            "service": ticket.service,
            "total": ticket.total,
            "method": ticket.method,
            "given": ticket.given,
            "change": ticket.change,
        }
        for ticket in unpaid
    ]
    return {
        "total_tickets": len(records),
        "unpaid_count": unpaid_count,
        "unpaid_tickets": unpaid_details,
        "branch": branch,
        "date": selected_date,
    }


def _ticket_candidates(row, tickets, branch, learned_suffixes):
    result = []
    for t in tickets:
        if _norm(t.get("selected_branch")) != _norm(branch):
            continue
        ticket_id = t["ticket_id"]
        if not re.fullmatch(r"\d{6}-\d+", ticket_id) or _ticket_day(ticket_id) != _day(row["row_date"]):
            continue
        try:
            items = json.loads(t["items"] or "[]")
        except ValueError:
            items = []
        for item in items:
            term = (item.get("terminal") or t["terminal"] or "")
            value_match = _match_num(item.get("total")) == _match_num(row["sales_value"])
            if item.get("total") is None and (_match_num(item.get("quantity")) or 0) == 1:
                value_match = _match_num(item.get("unit_price")) == _match_num(row["sales_value"])
            product_match = _product_match(item.get("name"), row["product"], learned_suffixes)
            quantity_match = (_num(item.get("quantity") or item.get("qty")) or 0) == (_num(row["quantity"]) or 0)
            context_matches = all(_text_match(left, right) for left, right in ((t.get("user_name"), row.get("user_name")), (t.get("department"), row.get("department")), (term, row.get("till"))))
            # Item, quantity, and price identify the transaction strongly enough to
            # retain it for review even when a receipt field was misread by OCR.
            if product_match and quantity_match and value_match:
                result.append((t, item, not context_matches or _product_key(item.get("name"), learned_suffixes) != _product_key(row["product"], learned_suffixes)))
    return result


def build_verification(branch: str, selected_date: str):
    with get_db_connection() as conn:
        rows = [dict(r) for r in conn.execute("SELECT * FROM csv_rows WHERE branch=? AND selected_date=? ORDER BY id", (branch, selected_date))]
        import_record = conn.execute("SELECT promotions_in_file FROM csv_imports WHERE branch=? AND selected_date=?", (branch, selected_date)).fetchone()
        tickets = [dict(r) for r in conn.execute("SELECT * FROM ticket_records")]
        dockets = [dict(r) for r in conn.execute("SELECT * FROM docket_records WHERE selected_branch=?", (branch,))]
    names = [r.get("product") for r in rows]
    for ticket in tickets:
        try:
            names.extend(i.get("name") for i in json.loads(ticket.get("items") or "[]"))
        except (TypeError, json.JSONDecodeError):
            pass
    for docket in dockets:
        names.extend(i.get("name") for i in _docket_items(docket))
    learned_suffixes = {str(name).rsplit(".", 1)[1].strip().casefold() for name in names if name and "." in str(name)}
    for row in rows:
        row["matches"] = {}
        row["candidates"] = []
        for kind, count in (("void", row["void_count"]), ("cancel", row["cancel_count"]), ("promotion", row["promotion_count"])):
            if count <= 0:
                row["matches"][kind] = {"status": "not_flagged", "verified": 0, "total": 0}
                continue
            candidates = []
            review = False
            ticket_only = 0
            docket_only = 0
            all_candidates = _ticket_candidates(row, tickets, branch, learned_suffixes)
            for ticket, item, ticket_needs_review in all_candidates:
                if ticket_needs_review:
                    review = True
                if kind == "void" and not item.get("is_void"):
                    review = True
                    row["candidates"].append({"ticket": ticket, "ticket_item": item, "docket": None, "docket_item": None, "needs_review": True})
                    continue
                tail = ticket["ticket_id"].rsplit("-", 1)[-1]
                related = [d for d in dockets if str(d.get("docket_order_no") or "") == tail and _day(d.get("docket_date")) == _day(row.get("row_date"))]
                allowed_types = {"void"} if kind == "void" else {"cancel", "cancelled"} if kind == "cancel" else {"promotion", "promotions", "discount"}
                docket_matches = []
                for docket in related:
                    for docket_item in _docket_items(docket):
                        marker = (docket_item.get("marker_type") or docket.get("discrepancy_type") or "").casefold()
                        if not (docket_item.get("is_void") or marker):
                            continue
                        if marker and marker not in allowed_types:
                            continue
                        if kind == "void" and not (docket_item.get("is_void") or marker == "void"):
                            continue
                        if not _product_match(docket_item.get("name"), row["product"], learned_suffixes):
                            continue
                        # Keep item/order/date-supported readings visible if another
                        # extracted field conflicts; the conflict is handled below.
                        docket_matches.append((docket, docket_item))
                if len(docket_matches) > 1 or (related and not docket_matches) or any(d.get("review_required") or not _text_match(d.get("staff_name"), ticket.get("user_name")) or not _text_match(d.get("department"), ticket.get("department")) for d, _ in docket_matches):
                    review = True
                if not related:
                    ticket_only += 1
                    row["candidates"].append({"ticket": ticket, "ticket_item": item, "docket": None, "docket_item": None})
                if related and not docket_matches:
                    row["candidates"].extend({"ticket": ticket, "ticket_item": item, "docket": docket, "needs_review": True} for docket in related)
                for docket, docket_item in docket_matches:
                    ticket_qty = _match_num(item.get("quantity") or item.get("qty")) or 1
                    docket_qty = _match_num(docket_item.get("quantity") or docket_item.get("qty"))
                    uncertain = ticket_needs_review or docket.get("review_required") or not _text_match(docket.get("staff_name"), ticket.get("user_name")) or not _text_match(docket.get("department"), ticket.get("department")) or _product_key(docket_item.get("name"), learned_suffixes) != _product_key(row["product"], learned_suffixes)
                    if uncertain:
                        row["candidates"].append({"ticket": ticket, "ticket_item": item, "docket": docket, "docket_item": docket_item, "needs_review": True})
                    else:
                        candidates.append({"ticket": ticket, "ticket_item": item, "docket": docket, "docket_item": docket_item, "pair_count": max(1, int(min(ticket_qty, docket_qty if docket_qty is not None else ticket_qty)))})
            docket_only_matches = []
            docket_review_matches = []
            for docket in dockets:
                if _day(docket.get("docket_date")) != _day(row.get("row_date")):
                    continue
                for docket_item in _docket_items(docket):
                    if not (docket_item.get("is_void") or docket_item.get("marker_type")):
                        continue
                    marker = (docket_item.get("marker_type") or docket.get("discrepancy_type") or "").casefold()
                    allowed_types = {"void"} if kind == "void" else {"cancel", "cancelled"} if kind == "cancel" else {"promotion", "promotions", "discount"}
                    if marker and marker not in allowed_types:
                        continue
                    if _product_match(docket_item.get("name"), row["product"], learned_suffixes):
                        candidate = {"ticket": None, "ticket_item": None, "docket": docket, "docket_item": docket_item}
                        context_matches = _text_match(docket.get("staff_name"), row.get("user_name")) and _text_match(docket.get("department"), row.get("department"))
                        if context_matches and not docket.get("review_required"):
                            docket_only_matches.append(candidate)
                        else:
                            docket_review_matches.append({**candidate, "needs_review": True})
            if not all_candidates and docket_only_matches:
                docket_only = len(docket_only_matches)
                row["candidates"].extend(docket_only_matches)
            if docket_review_matches:
                review = True
                row["candidates"].extend(docket_review_matches)
            if all_candidates and docket_only_matches and not candidates:
                review = True
                row["candidates"].extend({**candidate, "needs_review": True} for candidate in docket_only_matches)
            if kind == "void" and all_candidates and not any(item.get("is_void") for _, item, _ in all_candidates):
                review = True
            need = max(int(count + 0.999999), int((row["quantity"] or 0) + 0.999999) if count > 0 else 0)
            pair_count = sum(candidate.get("pair_count", 1) for candidate in candidates)
            verified = min(pair_count, need)
            status = "needs_review" if review or pair_count > need else ("verified" if verified >= need else "partial" if verified or ticket_only or docket_only else "pending")
            row["matches"][kind] = {"status": status, "verified": verified, "total": need}
            row["candidates"].extend(candidates)
        active_matches = [m for m in row["matches"].values() if m["total"] > 0]
        row["row_status"] = "needs_review" if any(m["status"] == "needs_review" for m in active_matches) else "verified" if active_matches and all(m["status"] == "verified" for m in active_matches) else "partial" if any(m["verified"] > 0 for m in active_matches) else "pending"
    flagged_rows = [r for r in rows if any((r[k+"_count"] or 0) > 0 for k in ("void", "cancel", "promotion"))]
    verified_total = sum(1 for r in flagged_rows if r["row_status"] == "verified")
    return {"has_import": import_record is not None, "rows": rows, "summary": {"item_rows": len(rows), "quantity": sum(r["quantity"] or 0 for r in rows), "void": _box(rows, "void"), "cancel": _box(rows, "cancel"), "promotions": _box(rows, "promotion"), "promotions_in_file": bool(import_record["promotions_in_file"]) if import_record else False, "status": {"verified": verified_total, "total": len(flagged_rows), "label": "Verified" if flagged_rows and verified_total == len(flagged_rows) else f"{verified_total} of {len(flagged_rows)} verified"}}, "promotions_in_file": bool(import_record["promotions_in_file"]) if import_record else False}


def _box(rows, key):
    active = [r for r in rows if r[key+"_count"] > 0]
    verified = sum(1 for r in active if r["matches"][key]["status"] == "verified")
    return {"flagged_rows": len(active), "amount": round(sum((r["sales_value"] or 0) for r in active), 2), "verified": verified, "total": len(active)}


@router.get("/verification")
def get_verification(branch: str, selected_date: str):
    return build_verification(branch, selected_date)


@router.get("/verification/dates")
def get_verification_dates(branch: str):
    with get_db_connection() as conn:
        dates = conn.execute("""
            SELECT i.selected_date AS date, i.filename, COUNT(r.id) AS item_rows,
            SUM(CASE WHEN COALESCE(r.void_count,0)>0 OR COALESCE(r.cancel_count,0)>0 OR COALESCE(r.promotion_count,0)>0 THEN 1 ELSE 0 END) AS flagged_rows
            FROM csv_imports i LEFT JOIN csv_rows r ON r.branch=i.branch AND r.selected_date=i.selected_date
            WHERE i.branch=? GROUP BY i.branch, i.selected_date, i.filename
            ORDER BY i.selected_date DESC
        """, (branch,)).fetchall()
    return {"branch": branch, "dates": [{**dict(row), "flagged_rows": row["flagged_rows"] or 0} for row in dates]}
