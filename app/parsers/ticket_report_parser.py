"""Parser for ticket report CSV exports from the restaurant management system.

This module parses ticket report exports (comma or tab separated) that contain:
- A summary line (e.g., "Ticket Count,159,Total Amount,9345.82...")
- Blank lines
- A header row with column names
- Data rows with ticket information

The parser is designed to be reusable and separate from business logic.
"""

import csv
import io
from dataclasses import dataclass

# Required columns that must be present in the header
REQUIRED_COLUMNS = {
    "Ticket",
    "Terminal",
    "Department",
    "User",
    "Date",
    "Time",
    "Service",
    "Total",
    "Method",
    "Given",
    "Change",
}


@dataclass
class TicketRecord:
    """Structured representation of a ticket record from the report."""
    ticket_id: str
    terminal: str
    department: str
    user: str
    date: str
    time: str
    service: str
    total: float | None
    method: str
    given: float | None
    change: float | None
    raw: dict[str, str]

    def __post_init__(self):
        # Ensure ticket_id is always a string (preserve leading zeros if any)
        self.ticket_id = str(self.ticket_id).strip()

    @property
    def is_unpaid(self) -> bool:
        return self.method.strip().casefold() == "unpaid"


class TicketReportParseError(Exception):
    """Raised when the ticket report CSV cannot be parsed."""

    def __init__(self, message: str, details: str | None = None):
        super().__init__(message)
        self.message = message
        self.details = details


def _parse_numeric(value: str | None) -> float | None:
    """Parse a numeric value, returning None for empty/invalid values.

    Does NOT default to zero - invalid values raise an error to avoid
    silently converting bad data to zero.
    """
    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        return None
    try:
        return float(stripped)
    except ValueError:
        raise TicketReportParseError(
            f"Invalid numeric value: {value!r}",
            details=f"Could not convert {value!r} to float"
        )


def _detect_delimiter(line: str) -> str:
    """Detect the delimiter used in a CSV line.

    Tries common delimiters and returns the one that produces the most columns.
    Falls back to comma if detection fails.
    """
    # Try to use csv.Sniffer first
    try:
        dialect = csv.Sniffer().sniff(line, delimiters=",\t;|")
        return dialect.delimiter
    except csv.Error:
        pass

    # Fallback: try common delimiters and pick the one that gives most fields
    # (assuming header has many columns)
    best_delimiter = ","
    max_fields = 0
    for delimiter in [",", "\t", ";", "|"]:
        try:
            parts = next(csv.reader([line], delimiter=delimiter))
            if len(parts) > max_fields:
                max_fields = len(parts)
                best_delimiter = delimiter
        except csv.Error:
            continue
    return best_delimiter


def _find_header_row(lines: list[str]) -> tuple[int, str]:
    """Find the index of the header row and its delimiter.

    Identifies the header by checking for required column names.
    Skips summary lines and blank lines.

    Returns:
        Tuple of (header_index, delimiter). Returns (-1, ",") if not found.
    """
    for i, line in enumerate(lines):
        if not line.strip():
            continue

        # Detect delimiter for this line
        delimiter = _detect_delimiter(line)

        # Parse the line using the detected delimiter
        try:
            parts = next(csv.reader([line], delimiter=delimiter))
        except csv.Error:
            continue

        parts = [part.strip() for part in parts]

        if "Ticket" in parts and "Terminal" in parts and "Total" in parts:
            return i, delimiter

    return -1, ","

def parse_ticket_report(content: str) -> list[TicketRecord]:
    """Parse ticket report CSV content into a list of TicketRecord objects.

    Args:
        content: The raw CSV content as a string (UTF-8, may contain BOM)

    Returns:
        List of TicketRecord objects, one per data row

    Raises:
        TicketReportParseError: If the CSV is malformed, missing required columns,
                                has no header row, or has no data rows
    """
    # Handle UTF-8 BOM
    if content.startswith("﻿"):
        content = content[1:]

    # Split into lines
    lines = content.splitlines()

    if not lines:
        raise TicketReportParseError("CSV content is empty")

    # Find the header row and its delimiter
    header_index, delimiter = _find_header_row(lines)

    if header_index == -1:
        raise TicketReportParseError(
            "Could not find header row with required columns (Ticket, Terminal, Total)",
            details="Expected a row containing 'Ticket', 'Terminal', and 'Total' columns"
        )

    # Extract header and data lines
    header_line = lines[header_index]
    data_lines = lines[header_index + 1:]

    # Parse header using detected delimiter
    reader = csv.DictReader(
        io.StringIO(header_line + "\n" + "\n".join(data_lines)),
        delimiter=delimiter,
        skipinitialspace=True,
    )

    # Normalize field names (strip whitespace)
    if reader.fieldnames:
        reader.fieldnames = [name.strip() for name in reader.fieldnames]

    # Validate required columns
    if not reader.fieldnames:
        raise TicketReportParseError("Header row is empty")

    missing_columns = REQUIRED_COLUMNS - set(reader.fieldnames)
    if missing_columns:
        raise TicketReportParseError(
            f"Missing required columns: {', '.join(sorted(missing_columns))}",
            details=f"Found columns: {', '.join(reader.fieldnames)}"
        )

    # Parse data rows
    records: list[TicketRecord] = []
    for row_num, row in enumerate(reader, start=header_index + 2):  # +2 for 1-indexed and header
        # Skip completely blank rows
        if not any(v.strip() for v in row.values()):
            continue

        # Normalize row keys
        normalized_row = {k.strip(): (v or "").strip() for k, v in row.items()}

        # Parse numeric fields
        try:
            total = _parse_numeric(normalized_row.get("Total"))
            given = _parse_numeric(normalized_row.get("Given"))
            change = _parse_numeric(normalized_row.get("Change"))
        except TicketReportParseError as e:
            # Preserve the original error message and add row context
            raise TicketReportParseError(
                f"{e.message} (row {row_num})",
                details=e.details
            ) from e

        # Create record - preserve all original columns in raw
        record = TicketRecord(
            ticket_id=normalized_row.get("Ticket", ""),
            terminal=normalized_row.get("Terminal", ""),
            department=normalized_row.get("Department", ""),
            user=normalized_row.get("User", ""),
            date=normalized_row.get("Date", ""),
            time=normalized_row.get("Time", ""),
            service=normalized_row.get("Service", ""),
            total=total,
            method=normalized_row.get("Method", ""),
            given=given,
            change=change,
            raw=normalized_row,
        )

        records.append(record)

    if not records:
        raise TicketReportParseError(
            "CSV contains no ticket records after header",
            details=f"Header found at line {header_index + 1}, but no valid data rows"
        )

    return records


def validate_ticket_report(content: str) -> tuple[bool, str | None]:
    """Validate that the content appears to be a valid ticket report.

    This is a lightweight check that doesn't fully parse - useful for
    quick validation before processing.

    Returns:
        Tuple of (is_valid, error_message). error_message is None if valid.
    """
    try:
        parse_ticket_report(content)
        return True, None
    except TicketReportParseError as e:
        return False, e.message