"""Excel "Daily Exception Report" parsing — Source 2.

This is NOT an export of the long slip. It is a row-level audit log: one row
per voided / discounted / promoted item, with the evidence columns (food
status, payment status, cashier, approving manager, reason, whether it was
posted in the group chat, whether a docket photo is attached, proof, audit
status). The "Daily Exception Summary" sheet is a per-day/per-branch total
used only to sanity-check the void amount.

Rules confirmed against a real file — nothing beyond these is assumed:
- A VOID row is one whose Adjustment Type starts with "Void" (Void,
  "Void - Pre-Prep", "Void - Post-Pump", ...). "Discount", "Promotion" and
  friends are different adjustment types and are NEVER counted as voids.
- Many rows carry a BLANK Adjustment Type. Those are "unfilled", not voids.
  The count is surfaced so the operator can see the log is incomplete.
- Bill Number is the full ticket ID but inconsistently spaced
  ("260902 - 7" vs "260904-110"); it is normalized by removing all spaces so
  it equals the stored ticket_id ("260902-7").
- One bill can own several rows (two voids plus a discount, say), so rows are
  counted, never deduplicated by bill number.
- Branch is one of Ilford / Southall / Norbury.
- Dates are real Excel dates, and the file can cover several days and all
  branches: filter to the selected branch + date on load, store only what
  matches, and report how many rows were skipped.
"""

import re
import typing as t

from app.models.sales_report import canonical_date_key, maybe_excel_date, read_xlsx_sheets


# Ticket restaurant names map onto the three branches the operator selects.
BRANCHES = ("Ilford", "Southall", "Norbury")
_BRANCH_KEYWORDS = {
    "ilford": "Ilford",
    "southall": "Southall",
    "norbury": "Norbury",
}

_VOID_PREFIX = "void"

# Header aliases per logical field. Matched against the header cell with all
# non-alphanumerics removed, lowercased, so "Posted in Group Chat?" and
# "posted_in_group_chat" both resolve to the same column.
_COLUMN_ALIASES: t.Dict[str, t.Tuple[str, ...]] = {
    "date": ("date",),
    "branch": ("branch", "restaurant", "site", "outlet"),
    "bill_number": ("billnumber", "billno", "bill", "ticketnumber", "ordernumber", "orderno"),
    "item": ("itemdescription", "itemname", "item", "description", "product"),
    "quantity": ("quantity", "qty"),
    "amount": ("amount", "amt", "value", "total"),
    "adjustment_type": ("adjustmenttype", "adjustment", "type", "reason type", "exceptiontype"),
    "food_status": ("foodstatus", "kitchenstatus"),
    "payment_status": ("paymentstatus", "paidstatus"),
    "cashier": ("cashiername", "cashier", "operator", "user"),
    "manager": ("approvingmanager", "approver", "manager", "supervisor"),
    "reason": ("reasonspecified", "reason", "note", "notes", "comments"),
    "posted_in_group_chat": ("postedingroupchat", "groupchat", "postedgroupchat"),
    "docket_photo_attached": ("docketphotoattached", "docketphoto", "photoattached"),
    "proof": ("proof", "proofref"),
    "audit_status": ("auditstatus", "auditstate"),
}

VOID_LOG_SHEET_HINT = "void log"
SUMMARY_SHEET_HINT = "summary"


def normalize_branch(value: t.Optional[str]) -> t.Optional[str]:
    """Map a ticket restaurant name or a log Branch cell onto a branch."""
    if not value:
        return None
    lowered = re.sub(r"[^a-z]+", " ", str(value).casefold())
    for keyword, branch in _BRANCH_KEYWORDS.items():
        if keyword in lowered:
            return branch
    return None


def normalize_bill_number(value: t.Optional[str]) -> t.Optional[str]:
    """'260902 - 7' -> '260902-7'; this must equal the stored ticket_id."""
    if value is None:
        return None
    cleaned = re.sub(r"\s+", "", str(value)).strip()
    return cleaned or None


def bill_number_date_key(value: t.Optional[str]) -> str:
    """The day encoded in a bill number's YYMMDD prefix, as YYYYMMDD.

    A bill number is the till's own ticket id, e.g. `260921-48`, so its first
    six digits are the day that ticket belongs to. This is the authority for
    the day an Excel row belongs to: the Date column can disagree with it,
    exactly as a printed ticket date can disagree with its docket. Returns ""
    when the bill number carries no such prefix.
    """
    cleaned = re.sub(r"\s+", "", str(value or ""))
    match = re.match(r"#?(\d{2})(\d{2})(\d{2})(?:\D|$)", cleaned)
    return f"20{match.group(1)}{match.group(2)}{match.group(3)}" if match else ""


def classify_adjustment(adjustment_type: t.Optional[str]) -> str:
    """'void' | 'discount' | 'promotion' | 'cancelled' | 'unfilled' | 'other'.

    A blank Adjustment Type is `unfilled`, never a void.
    """
    cleaned = re.sub(r"\s+", " ", str(adjustment_type or "")).strip().casefold()
    if not cleaned:
        return "unfilled"
    if cleaned.startswith(_VOID_PREFIX):
        return "void"
    if cleaned.startswith("discount"):
        return "discount"
    if cleaned.startswith("promo"):
        return "promotion"
    if cleaned.startswith("cancel") or cleaned.startswith("can "):
        return "cancelled"
    return "other"


def _to_float(token: t.Optional[str]) -> t.Optional[float]:
    if token is None:
        return None
    cleaned = re.sub(r"[£$€,\s]", "", str(token)).strip()
    if not cleaned:
        return None
    if cleaned in {"-", "--"}:
        return 0.0
    match = re.search(r"-?\d+(?:\.\d+)?", cleaned)
    return float(match.group()) if match else None


def _header_key(cell: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(cell or "").casefold())


def _column_map(header: t.Sequence[str]) -> t.Dict[str, int]:
    """Resolve logical field -> column index using the alias lists."""
    keys = [_header_key(cell) for cell in header]
    resolved: t.Dict[str, int] = {}
    for field, aliases in _COLUMN_ALIASES.items():
        for alias in aliases:
            alias_key = re.sub(r"[^a-z0-9]", "", alias)
            for index, key in enumerate(keys):
                if key and (key == alias_key or alias_key in key):
                    resolved.setdefault(field, index)
                    break
            if field in resolved:
                break
    return resolved


def _find_header(rows: t.List[t.List[str]], limit: int = 10) -> t.Optional[t.Tuple[int, t.Dict[str, int]]]:
    """The first row that names both a bill number and an adjustment type."""
    for index, row in enumerate(rows[:limit]):
        columns = _column_map(row)
        if "bill_number" in columns and "adjustment_type" in columns:
            return index, columns
    return None


def _select_sheet(
    sheets: t.List[t.Tuple[str, t.List[t.List[str]]]],
) -> t.Optional[t.Tuple[str, t.List[t.List[str]], int, t.Dict[str, int]]]:
    """Prefer the sheet named like 'Daily Void Log', else the first log-shaped one."""
    for name, rows in sheets:
        if VOID_LOG_SHEET_HINT in re.sub(r"[^a-z]", "", name.casefold()):
            found = _find_header(rows)
            if found:
                return name, rows, found[0], found[1]
    for name, rows in sheets:
        found = _find_header(rows)
        if found:
            return name, rows, found[0], found[1]
    return None


def _read_summary(sheets: t.List[t.Tuple[str, t.List[t.List[str]]]]) -> t.Dict[str, t.Any]:
    """Totals from the 'Daily Exception Summary' sheet, for a sanity check only.

    Row-level figures always come from the void log; this only cross-checks
    that the void amount agrees with the operator's own daily total.
    """
    for name, rows in sheets:
        if SUMMARY_SHEET_HINT not in re.sub(r"[^a-z]", "", name.casefold()):
            continue
        for index, row in enumerate(rows[:10]):
            columns = _column_map(row)
            if "amount" not in columns:
                continue
            entry: t.Dict[str, t.Any] = {"sheet": name, "rows": []}
            for data_row in rows[index + 1:]:
                if "branch" in columns and "date" in columns:
                    branch = normalize_branch(data_row[columns["branch"]]) if columns["branch"] < len(data_row) else None
                    date_cell = data_row[columns["date"]] if columns["date"] < len(data_row) else None
                else:
                    branch, date_cell = None, None
                amount_cell = data_row[columns["amount"]] if columns["amount"] < len(data_row) else None
                amount = _to_float(amount_cell)
                if amount is None and not branch:
                    continue
                entry["rows"].append({
                    "branch": branch,
                    "date": maybe_excel_date(date_cell),
                    "voids_amount": amount,
                })
            return entry
    return {}


def parse_daily_exception_report(
    path: str,
    branch: t.Optional[str] = None,
    report_date: t.Optional[str] = None,
) -> t.Dict[str, t.Any]:
    """Parse the Daily Exception Report and keep only branch + date rows.

    Returns the filtered row log plus the skipped-row count, so the UI can say
    how much of the file was not part of the selected day.
    """
    sheets = read_xlsx_sheets(path)
    selected = _select_sheet(sheets)
    if selected is None:
        return {
            "sheet": None,
            "sheet_names": [name for name, _rows in sheets],
            "rows": [],
            "skipped_rows": 0,
            "unfilled_rows": 0,
            "void_rows": 0,
            "voids_amount": None,
            "summary": _read_summary(sheets),
            "error": "No 'Daily Void Log' sheet with a Bill Number and Adjustment Type column was found",
        }

    sheet_name, sheet_rows, header_index, columns = selected

    target_branch = normalize_branch(branch) if branch else None
    # Canonical keys, because the log stores real Excel dates (serial numbers,
    # read back as dd/mm/yyyy) while the operator picks a day as YYYY-MM-DD.
    target_date = canonical_date_key(report_date) if report_date else None

    kept: t.List[t.Dict[str, t.Any]] = []
    skipped = 0
    for row in sheet_rows[header_index + 1:]:
        if not row or not any(cell for cell in row):
            continue

        def cell(field: str) -> t.Optional[str]:
            index = columns.get(field)
            return row[index] if index is not None and index < len(row) else None

        row_branch = normalize_branch(cell("branch"))
        # The bill number's YYMMDD prefix is the till's own day, so it decides
        # which day a row belongs to; the Date column is only used when the bill
        # number carries no such prefix.
        row_date = (
            bill_number_date_key(normalize_bill_number(cell("bill_number")))
            or canonical_date_key(maybe_excel_date(cell("date")))
        )

        # The file covers every branch and day; keep only the selected scope.
        if target_branch and row_branch and row_branch != target_branch:
            skipped += 1
            continue
        if target_date and row_date and row_date != target_date:
            skipped += 1
            continue

        adjustment_type = (cell("adjustment_type") or "").strip()
        kept.append({
            "date": row_date,
            "branch": row_branch,
            "bill_number": normalize_bill_number(cell("bill_number")),
            "item": (cell("item") or "").strip() or None,
            "quantity": (cell("quantity") or "").strip() or None,
            "amount": _to_float(cell("amount")),
            "adjustment_type": adjustment_type or None,
            "adjustment": classify_adjustment(adjustment_type),
            "food_status": (cell("food_status") or "").strip() or None,
            "payment_status": (cell("payment_status") or "").strip() or None,
            "cashier_name": (cell("cashier") or "").strip() or None,
            "approving_manager": (cell("manager") or "").strip() or None,
            "reason": (cell("reason") or "").strip() or None,
            "posted_in_group_chat": (cell("posted_in_group_chat") or "").strip() or None,
            "docket_photo_attached": (cell("docket_photo_attached") or "").strip() or None,
            "proof": (cell("proof") or "").strip() or None,
            "audit_status": (cell("audit_status") or "").strip() or None,
        })

    void_rows = [row for row in kept if row["adjustment"] == "void"]
    amounts = [row["amount"] for row in void_rows if row["amount"] is not None]
    discounts = [row for row in kept if row["adjustment"] == "discount"]
    promotions = [row for row in kept if row["adjustment"] == "promotion"]

    return {
        "sheet": sheet_name,
        "sheet_names": [name for name, _rows in sheets],
        "rows": kept,
        "skipped_rows": skipped,
        "unfilled_rows": sum(row["adjustment"] == "unfilled" for row in kept),
        "void_rows": len(void_rows),
        "voids_amount": round(sum(amounts), 2) if amounts else 0.0,
        "discount_rows": len(discounts),
        "discounts_amount": round(sum(r["amount"] for r in discounts if r["amount"] is not None), 2),
        "promotion_rows": len(promotions),
        "promotions_amount": round(sum(r["amount"] for r in promotions if r["amount"] is not None), 2),
        "summary": _read_summary(sheets),
    }
