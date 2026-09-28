"""Sales report (Work Period / Z-report) parsing.

Division 6 reference data: the till's aggregate totals per department
(Voids / Discounts / Promotions / Cancelled, each with count + amount).
Parsed from printed text (OCR or vision) and, when the till can export one,
from the long slip. Source 2 is the Excel "Daily Exception Report", a
row-level audit log with a different shape entirely, and lives in
`app/models/daily_exception.py`.

Conventions locked by the task:
- A "-" amount means zero/none, NOT missing data. It is parsed as 0.0.
- Stored against restaurant + report date (the same-day scope tickets and
  dockets are matched on).
- Unrecognized lines go to `extra_fields`, never a guessed field.
"""

import re
import typing as t
import zipfile
from datetime import datetime, timedelta
from xml.etree import ElementTree as ET

REPORT_SCHEMA = {
    "type": "sales_report",
    "restaurant": None,
    "report_date": None,
    "departments": [],
    "extra_fields": {},
}

_METRICS = (
    ("voids_count", "voids_amount"),
    ("discounts_count", "discounts_amount"),
    ("promotions_count", "promotions_amount"),
    ("cancelled_count", "cancelled_amount"),
)

_DASHES = {"-", "--", "\u2013", "\u2014", "_"}

_DATE_ANY = re.compile(r"\b([0-3]?\d[/-][01]?\d[/-](?:\d{2}|\d{4}))\b")
# ISO / big-endian forms a till export or printed report can also carry.
# Without these `2026-09-24` matched nothing and report_date came back null.
_DATE_ISO = re.compile(r"\b(\d{4}[-/]\d{1,2}[-/]\d{1,2})\b")
_DATE_LABELED = re.compile(
    r"(?i)\b(?:date|dated|report\s*for|work\s*period|period\s*(?:start|end)?|from)\s*:?\s*"
    r"(\d{4}[-/]\d{1,2}[-/]\d{1,2}|[0-3]?\d[/-][01]?\d[/-]\d{2,4})"
)
_TOTALS_RE = re.compile(
    r"(?i)\b(voids?|v0ids?|v01ds?|discounts?|promos?|promotions?|cancell?ed|can?cellations?)\s*"
    r"total\b\s*:?\s*(.*)$"
)


def _clean(value: t.Optional[str]) -> str:
    if value is None:
        return ""
    # NOTE: a trailing '-' is meaningful (dash means zero), so it must NOT be
    # stripped here — a dash-value totals line must keep its pair of dashes.
    return re.sub(r"\s+", " ", str(value)).strip(" \t:|")


def _normalize_department(name: t.Optional[str]) -> t.Optional[str]:
    if not name:
        return None
    cleaned = re.sub(
        r"\b(?:incomes?|department|dept|section|division)\b",
        " ",
        _clean(name),
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"\s+", " ", cleaned).strip().upper()
    return cleaned or None


def _to_count(token: t.Optional[str]) -> t.Optional[int]:
    """Parse a count cell; a dash means zero; empty means genuinely absent."""
    if token is None:
        return None
    cleaned = re.sub(r"[(),]", "", str(token)).strip()
    if cleaned in _DASHES:
        return 0
    if not cleaned:
        return None
    match = re.search(r"\d+", cleaned)
    return int(match.group()) if match else None


def _to_amount(token: t.Optional[str]) -> t.Optional[float]:
    """Parse an amount cell; a dash means zero; empty means genuinely absent."""
    if token is None:
        return None
    cleaned = str(token).replace("\u00a3", "").replace(",", "").strip()
    if not cleaned:
        return None
    cleaned = re.sub(r"[(),]", "", cleaned)
    if cleaned in _DASHES:
        return 0.0
    match = re.search(r"-?\d+(?:\.\d+)?", cleaned)
    return float(match.group()) if match else None


def _classify_totals_key(cleaned: str) -> t.Optional[str]:
    match = _TOTALS_RE.match(cleaned)
    if not match:
        return None
    key = re.sub(r"[^a-z]", "", match.group(1).casefold())
    if key.startswith("vo"):
        return "voids"
    if key.startswith("di"):
        return "discounts"
    if key.startswith("pro") or key.startswith("promo"):
        return "promotions"
    if key.startswith("ca") or key.startswith("can"):
        return "cancelled"
    return None


def _split_count_amount(tail: str) -> t.Tuple[t.Optional[int], t.Optional[float]]:
    """Resolve the figures after 'Voids Total:' into (count, amount).

    '1 15.98'  -> (1, 15.98)
    '3 20.00'  -> (3, 20.0)
    '- -'      -> (0, 0.0)
    '-'        -> (None, 0.0)   (a lone dash is a zero amount; the count is absent)
    '15.98'    -> (None, 15.98)
    '2'        -> (2, None)
    """
    tokens = re.findall(r"-?\d+(?:\.\d+)?|-", tail)
    values: t.List[t.Union[int, float, None]] = []
    for token in tokens:
        if token in _DASHES:
            values.append(0.0)
        elif "." in token:
            values.append(float(token))
        else:
            values.append(int(token))

    if not values:
        return None, None
    if len(values) == 1:
        single = values[0]
        if isinstance(single, float):
            return None, single
        return single, None
    # Count is the first figure, amount the last.
    count = values[0]
    amount = values[-1]
    count = int(count) if isinstance(count, (int, float)) and float(count).is_integer() else None
    amount = float(amount)
    return count, amount


def _new_department(name: str) -> t.Dict[str, t.Any]:
    department = {
        "name": name,
        "voids_count": None,
        "voids_amount": None,
        "discounts_count": None,
        "discounts_amount": None,
        "promotions_count": None,
        "promotions_amount": None,
        "cancelled_count": None,
        "cancelled_amount": None,
    }
    return department


def _is_department_header(line: str, after_header_block: bool = False) -> t.Optional[str]:
    """Normalized department name when `line` looks like a section heading.

    Section headings carrying an explicit marker (`TAKE AWAY Incomes`,
    `Department: X`) are always accepted. A bare alphabetic heading is only
    accepted once the report header block is passed (a date line or a marked
    section has been seen) — before that a line is far more likely to be the
    restaurant name than a department.
    """
    cleaned = _clean(line)
    if not cleaned or any(ch.isdigit() for ch in cleaned):
        return None
    lowered = cleaned.casefold()
    if re.search(r"\b(?:void|discount|promo|cancel|total|grand|tax|vat|payment|report|period)\b", lowered):
        return None
    if re.search(r"\b(?:incomes?|departments?|deps?|sections?|divisions?)\b", lowered):
        name = re.sub(
            r"\b(?:incomes?|departments?|deps?|sections?|divisions?)\b",
            "",
            cleaned,
            flags=re.IGNORECASE,
        )
        name = re.sub(r"^[:\-\s]+|[:\-\s]+$", "", name)
        return _normalize_department(name)
    if after_header_block and re.fullmatch(r"[A-Za-z][A-Za-z0-9 /&.'-]{0,32}", cleaned):
        words = cleaned.split()
        if 1 <= len(words) <= 4:
            return _normalize_department(cleaned)
    return None


def _parse_printed_lines(cleaned_lines: t.List[str]) -> t.Dict[str, t.Any]:
    result = {
        "restaurant": None,
        "report_date": None,
        "departments": [],
        "extra_fields": {"unparsed_lines": []},
    }
    dept_map: t.Dict[str, t.Dict[str, t.Any]] = {}
    current_dept: t.Optional[str] = None
    closed_departments: t.List[str] = []
    after_header_block = False

    for line in cleaned_lines:
        if not line:
            continue

        if not after_header_block:
            after_header_block = bool(_DATE_ANY.search(line) or result["departments"])

        dept = _is_department_header(line, after_header_block)
        if dept:
            if dept not in dept_map:
                dept_map[dept] = _new_department(dept)
            elif dept in closed_departments:
                # Same department section repeated (e.g. re-opened summary); keep
                # the earlier totals rather than silently overwriting.
                pass
            current_dept = dept
            after_header_block = True
            continue

        total_type = _classify_totals_key(line)
        if total_type:
            match = _TOTALS_RE.match(line)
            tail = match.group(2) if match else ""
            if current_dept is None:
                current_dept = "UNLABELLED"
                dept_map.setdefault(current_dept, _new_department(current_dept))
            count, amount = _split_count_amount(tail)
            department = dept_map[current_dept]
            if total_type == "voids":
                if count is not None and department["voids_count"] is None:
                    department["voids_count"] = count
                if amount is not None and department["voids_amount"] is None:
                    department["voids_amount"] = amount
            elif total_type == "discounts":
                if count is not None and department["discounts_count"] is None:
                    department["discounts_count"] = count
                if amount is not None and department["discounts_amount"] is None:
                    department["discounts_amount"] = amount
            elif total_type == "promotions":
                if count is not None and department["promotions_count"] is None:
                    department["promotions_count"] = count
                if amount is not None and department["promotions_amount"] is None:
                    department["promotions_amount"] = amount
            elif total_type == "cancelled":
                if count is not None and department["cancelled_count"] is None:
                    department["cancelled_count"] = count
                if amount is not None and department["cancelled_amount"] is None:
                    department["cancelled_amount"] = amount
            continue

        result["extra_fields"]["unparsed_lines"].append(line)

    result["departments"] = list(dept_map.values())
    if not result["departments"]:
        del result["extra_fields"]["unparsed_lines"]
    return result


_CORP_HINT = re.compile(
    r"(?i)\b(ltd|ltd\.|limited|company|co\.?\b|inc\b|inc\.|plc\b|group|&|and|restaurant|restaurants?|bakery|cafe|bar)\b"
)
_RESTAURANT_LABELED = re.compile(
    r"(?i)\b(?:restaurant|branch|store|outlet|company|site)\s*[:\u2013-]\s*(.{3,})"
)


def _parse_restaurant(lines: t.List[str]) -> t.Optional[str]:
    """Best-effort restaurant identification from report header/footer lines.

    Prefers an explicit label (`Restaurant: X`), then scans the header/footer
    lines for an alphabetic, jargon-free line, favouring ones carrying a
    business-name hint (Ltd, &, Restaurant, ...).
    """
    for line in lines:
        match = _RESTAURANT_LABELED.search(line)
        if not match:
            continue
        value = _clean(match.group(1))
        if len(re.findall(r"[A-Za-z]", value)) >= 3:
            return value

    candidates: t.List[t.Tuple[str, int]] = []
    seen: t.Set[str] = set()
    skip_rel = re.compile(
        r"(?i)\b(date|report|period|invoices?|receipt|sale|total|till|terminal|opening|closing|void|discount|promo|cancel|vat|tax|address|tel|no\.|number|operator|clerk|signature|time)\b|:"
    )
    for line in lines:
        cleaned = _clean(line)
        if not cleaned or any(ch.isdigit() for ch in cleaned):
            continue
        if len(re.findall(r"[A-Za-z]", cleaned)) < 3:
            continue
        if re.search(r"(?i)\bincomes?\b", cleaned):
            continue
        if skip_rel.search(cleaned):
            continue
        if cleaned in seen:
            continue
        seen.add(cleaned)
        score = 3 if _CORP_HINT.search(cleaned) else 1
        candidates.append((cleaned, score))

    if not candidates:
        return None
    return max(candidates, key=lambda item: (item[1], len(item[0])))[0]


def _match_date(token: t.Optional[str]) -> t.Optional[str]:
    """First labeled date, then a day-first date, then an ISO/big-endian date."""
    if not token:
        return None
    text = str(token)
    for pattern in (_DATE_LABELED, _DATE_ANY, _DATE_ISO):
        match = pattern.search(text)
        if match:
            return match.group(1)
    return None


def _parse_date(lines: t.List[str]) -> t.Optional[str]:
    for line in lines:
        match = _DATE_LABELED.search(line)
        if match:
            return match.group(1)
    joined = "\n".join(lines)
    match = _DATE_ANY.search(joined) or _DATE_ISO.search(joined)
    return match.group(1) if match else None


def parse_sales_report_text(text: str) -> t.Dict[str, t.Any]:
    """Parse printed report text (OCR output) into the sales report schema.

    This is Source 1 only: the long slip bill (printed Work Period Report).
    Source 2 is the Excel Daily Exception Report, a row-level audit log, and is
    parsed by `app/models/daily_exception.py` — the two are NOT the same shape
    and must never be parsed by the same function.
    """
    lines = [_clean(line) for line in (text or "").splitlines()]
    lines = [line for line in lines if line]

    result = _parse_printed_lines(lines)
    result["report_date"] = _parse_date(lines)
    result["restaurant"] = _parse_restaurant(lines)
    if result["extra_fields"].get("unparsed_lines") and not result["extra_fields"]["unparsed_lines"]:
        del result["extra_fields"]["unparsed_lines"]
    return result


def _xlsx_shared_strings(archive: zipfile.ZipFile) -> t.List[str]:
    try:
        root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    except (KeyError, ET.ParseError):
        return []
    ns = root.tag.rpartition("}")[0] + "}"
    strings: t.List[str] = []
    for item in root.iter(f"{ns}si"):
        strings.append("".join(element.text or "" for element in item.iter(f"{ns}t")))
    return strings


def _xlsx_col_from_ref(ref: t.Optional[str]) -> t.Optional[int]:
    letters = re.match(r"([A-Z]+)", ref or "")
    if not letters:
        return None
    column = 0
    for char in letters.group(1):
        column = column * 26 + (ord(char) - 64)
    return column - 1


def _xlsx_sheet_targets(archive: zipfile.ZipFile) -> t.List[str]:
    """Worksheet entry paths (e.g. xl/worksheets/sheet1.xml) in sheet order."""
    try:
        root = ET.fromstring(archive.read("xl/workbook.xml"))
    except (KeyError, ET.ParseError):
        return []
    ns = root.tag.rpartition("}")[0] + "}"
    rels: t.Dict[str, str] = {}
    try:
        rel_root = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        rel_ns = rel_root.tag.rpartition("}")[0] + "}"
        for relationship in rel_root.findall(f"{rel_ns}Relationship"):
            target = relationship.get("Target") or ""
            if not target.endswith(".xml"):
                continue
            rels[relationship.get("Id") or ""] = (
                target if target.startswith("/") else f"xl/{target.lstrip('/')}"
            )
    except (KeyError, ET.ParseError):
        pass

    targets: t.List[str] = []
    for index, sheet in enumerate(root.iter(f"{ns}sheet")):
        relationship_id = sheet.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
        if relationship_id and relationship_id in rels:
            target = rels[relationship_id]
            targets.append(target if target.startswith("/") else target)
        else:
            targets.append(f"xl/worksheets/sheet{index + 1}.xml")
    return targets


def _xlsx_sheet_rows(
    archive: zipfile.ZipFile, entry: str, shared: t.List[str]
) -> t.List[t.List[str]]:
    try:
        root = ET.fromstring(archive.read(entry))
    except (KeyError, ET.ParseError):
        return []
    ns = root.tag.rpartition("}")[0] + "}"
    rows: t.List[t.List[str]] = []
    for row_element in root.iter(f"{ns}row"):
        cells: t.Dict[int, str] = {}
        width = -1
        for cell in row_element.findall(f"{ns}c"):
            column = _xlsx_col_from_ref(cell.get("r"))
            cell_type = cell.get("t")
            value_element = cell.find(f"{ns}v")
            value = ""
            if cell_type == "s" and value_element is not None:
                try:
                    index = int(value_element.text or "0")
                    value = shared[index] if index < len(shared) else ""
                except ValueError:
                    pass
            elif cell_type == "inlineStr":
                inline = cell.find(f"{ns}is")
                if inline is not None:
                    value = "".join(element.text or "" for element in inline.iter(f"{ns}t"))
            elif value_element is not None:
                value = value_element.text or ""
            value = (value or "").strip()
            if value and column is not None:
                cells[column] = value
                width = max(width, column)
        if width >= 0:
            row_values = [cells.get(index, "") for index in range(width + 1)]
            if any(row_values):
                rows.append(row_values)
    return rows


def canonical_date_key(value: t.Optional[str]) -> str:
    """Canonical YYYYMMDD for any date shape this data actually uses.

    Separator forms come first because they are unambiguous: `22/09/2026`,
    `22-9-2026` and `2026-09-22` all collapse to `20260922`. A bare digit run
    is read as ISO when it starts with `20`, else day-first. A 6-digit run is
    read as YYMMDD, matching how the till builds its ticket IDs. An
    unrecognizable value returns its digits so it can never join by accident
    rather than being silently coerced into a wrong day.

    This is the single implementation: the slip, the Excel log, the tickets
    and the dockets must all resolve the same day the same way, or a day
    written two different ways never matches.
    """
    if not value:
        return ""
    text = str(value)
    separated = re.search(r"(\d{1,4})\s*[/\-.]\s*(\d{1,2})\s*[/\-.]\s*(\d{1,4})", text)
    if separated:
        first, second, third = separated.groups()
        if len(first) == 4:  # YYYY-MM-DD
            canonical = _compose_date(first, second, third)
        else:  # DD/MM/YYYY, or DD-MM-YY
            canonical = _compose_date(third if len(third) == 4 else f"20{third}", second, first)
        if canonical:
            return canonical
    digits = re.sub(r"\D", "", text)
    if len(digits) == 8:
        return digits if digits.startswith("20") else f"{digits[4:]}{digits[2:4]}{digits[:2]}"
    if len(digits) == 6:
        return f"20{digits}"
    return digits


def _compose_date(year: str, month: str, day: str) -> t.Optional[str]:
    """YYYYMMDD from parts, or None when they are not a real calendar date."""
    try:
        year_value, month_value, day_value = int(year), int(month), int(day)
    except (TypeError, ValueError):
        return None
    if not 1 <= month_value <= 12 or not 1 <= day_value <= 31:
        return None
    return f"{year_value:04d}{month_value:02d}{day_value:02d}"


def read_xlsx_sheets(path: str) -> t.List[t.Tuple[str, t.List[t.List[str]]]]:
    """Read every worksheet of an .xlsx workbook as (sheet_name, rows_of_cells).

    Stdlib-only (zipfile + XML) so no dependency is introduced; sparse cells
    stay aligned via their cell references. Workbook order is preserved.
    """
    try:
        archive = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError):
        return []
    with archive:
        shared = _xlsx_shared_strings(archive)
        sheets: t.List[t.Tuple[str, t.List[t.List[str]]]] = []
        for index, target in enumerate(_xlsx_sheet_targets(archive)):
            name = f"sheet{index + 1}"
            try:
                workbook = ET.fromstring(archive.read("xl/workbook.xml"))
                names = [
                    element.get("name") or ""
                    for element in workbook.iter(
                        "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}sheet"
                    )
                ]
                if index < len(names) and names[index]:
                    name = names[index]
            except (KeyError, ET.ParseError):
                pass
            sheets.append((name, _xlsx_sheet_rows(archive, target, shared)))
        return sheets


def read_sales_report_xlsx_rows(path: str) -> t.List[t.List[str]]:
    """Rows of the most data-rich worksheet of an .xlsx workbook."""
    richest: t.List[t.List[str]] = []
    richest_score = 0
    for _name, rows in read_xlsx_sheets(path):
        score = sum(len(row) for row in rows)
        if score > richest_score:
            richest = rows
            richest_score = score
    return richest


def maybe_excel_date(token: t.Optional[str]) -> t.Optional[str]:
    """dd/mm/yyyy for a real Excel date cell (serial number or text).

    The Daily Exception Report stores real Excel dates, so a bare serial like
    `46252` is the common case, not an edge case.
    """
    if token is None:
        return None
    text = str(token).strip()
    if not text:
        return None
    parsed = _match_date(text)
    if parsed:
        return parsed
    cleaned = re.sub(r"\s+", "", text)
    if not re.fullmatch(r"\d{4,6}(?:\.\d+)?", cleaned):
        return None
    try:
        serial = float(cleaned)
    except ValueError:
        return None
    if serial < 60 or serial > 2958465:  # 1900-03-01 .. 9999-12-31
        return None
    # Excel's 1900-02-29 does not exist; the 1899-12-30 basis repairs the offset.
    return (datetime(1899, 12, 30) + timedelta(days=int(serial))).strftime("%d/%m/%Y")


# --------------------------------------------------------------------------
# Slip vs Excel cross-verification (branch + day level)
# --------------------------------------------------------------------------
# The Excel Daily Exception Report has no department column, so the comparison
# is made at branch + day level: the slip's total voids (sum over all
# departments) against the Excel void rows for the same branch and day.
#
# AMOUNT is the primary check. COUNT is compared but NOT declared a pass or
# fail: it is not yet established whether the slip's void "count" counts voided
# items or voided bills, and one bill can own several void rows. Both counts
# are shown side by side and the finding is recorded in decisions.md.

_COUNT_MEANING_UNCONFIRMED = (
    "count is not scored: it is not yet confirmed whether the slip counts "
    "voided items or voided bills, and one bill can own several void rows"
)


def _slip_totals(departments: t.Optional[t.List[t.Dict[str, t.Any]]]) -> t.Dict[str, t.Any]:
    counts: t.List[int] = []
    amounts: t.List[float] = []
    for department in departments or []:
        if department.get("voids_count") is not None:
            counts.append(int(department["voids_count"]))
        if department.get("voids_amount") is not None:
            amounts.append(float(department["voids_amount"]))
    return {
        "voids_count": sum(counts) if counts else None,
        "voids_amount": round(sum(amounts), 2) if amounts else None,
        "department_count": sum(1 for d in (departments or []) if d.get("voids_count") is not None),
    }


def compare_slip_with_excel(
    slip_parsed: t.Optional[t.Dict[str, t.Any]],
    excel_parsed: t.Optional[t.Dict[str, t.Any]],
    amount_tolerance: float = 0.005,
) -> t.Dict[str, t.Any]:
    """Cross-verify Source 1 (long slip) against Source 2 (Excel exception log).

    Returns the two sides plus an explicit `mismatches` list. An empty list
    means the amounts agree. The count is reported as `count_comparison` with
    no pass/fail, because its meaning is not yet confirmed.
    """
    slip = _slip_totals((slip_parsed or {}).get("departments")) if slip_parsed is not None else {
        "voids_count": None, "voids_amount": None, "department_count": 0,
    }
    excel = {
        "voids_count": (excel_parsed or {}).get("void_rows"),
        "voids_amount": (excel_parsed or {}).get("voids_amount"),
        "unfilled_rows": (excel_parsed or {}).get("unfilled_rows", 0),
        "discount_rows": (excel_parsed or {}).get("discount_rows", 0),
        "promotion_rows": (excel_parsed or {}).get("promotion_rows", 0),
    }

    mismatches: t.List[t.Dict[str, t.Any]] = []
    if slip_parsed is not None and excel_parsed is not None:
        slip_amount = slip["voids_amount"]
        excel_amount = excel["voids_amount"]
        if (
            slip_amount is not None and excel_amount is not None
            and abs(slip_amount - excel_amount) > amount_tolerance
        ):
            mismatches.append({
                "metric": "voids amount",
                "slip": slip_amount,
                "excel": excel_amount,
                "difference": round(slip_amount - excel_amount, 2),
                "primary": True,
            })

    slip_count = slip["voids_count"]
    excel_count = excel["voids_count"]
    if slip_count is not None and excel_count is not None:
        count_difference: t.Optional[int] = slip_count - excel_count
        count_state = "match" if count_difference == 0 else "differs"
    else:
        count_difference, count_state = None, "unavailable"

    return {
        "scope": "branch + day (the Excel log has no department column)",
        "slip": slip,
        "excel": excel,
        "count_comparison": {
            "slip": slip_count,
            "excel": excel_count,
            "difference": count_difference,
            "state": count_state,
            "scored": False,
            "note": _COUNT_MEANING_UNCONFIRMED,
        },
        "mismatches": mismatches,
        "state": (
            "unavailable" if slip_parsed is None or excel_parsed is None
            else "mismatch" if mismatches
            else "match"
        ),
    }
