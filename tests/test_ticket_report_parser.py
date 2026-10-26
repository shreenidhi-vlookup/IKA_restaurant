"""Tests for the ticket report CSV parser."""

import pytest

from app.parsers.ticket_report_parser import (
    parse_ticket_report,
    TicketReportParseError,
    validate_ticket_report,
    TicketRecord,
)


# ============================================================================
# Test fixtures - synthetic CSV examples
# ============================================================================

VALID_CSV_WITH_SUMMARY = """Ticket Count\t159\tTotal Amount\t9345.82\tCancelled Count\t10\tCancelled Total\t84.6

Ticket\tTerminal\tDepartment\tUser\tDate\tTime\tService\tTotal\tMethod\tGiven\tChange
261025-159\tTill-1\tRESTAURANT\tJIHAD\t10/26/2026\t6:38:23\tRESTAURANT\t116.3\tCredit Card\t116.3\t0
261025-158\tTill-1\tRESTAURANT\tANSH\t10/26/2026\t6:38:17\tRESTAURANT\t102.85\tCredit Card\t102.85\t0
"""

VALID_CSV_WITH_BLANK_LINES = """Ticket\tTerminal\tDepartment\tUser\tDate\tTime\tService\tTotal\tMethod\tGiven\tChange

261025-159\tTill-1\tRESTAURANT\tJIHAD\t10/26/2026\t6:38:23\tRESTAURANT\t116.3\tCredit Card\t116.3\t0

261025-158\tTill-1\tRESTAURANT\tANSH\t10/26/2026\t6:38:17\tRESTAURANT\t102.85\tCredit Card\t102.85\t0

"""

VALID_CSV_WITH_BOM = """﻿Ticket\tTerminal\tDepartment\tUser\tDate\tTime\tService\tTotal\tMethod\tGiven\tChange
261025-159\tTill-1\tRESTAURANT\tJIHAD\t10/26/2026\t6:38:23\tRESTAURANT\t116.3\tCredit Card\t116.3\t0
"""

VALID_CSV_DECIMAL_AND_ZERO = """Ticket\tTerminal\tDepartment\tUser\tDate\tTime\tService\tTotal\tMethod\tGiven\tChange
261025-159\tTill-1\tRESTAURANT\tJIHAD\t10/26/2026\t6:38:23\tRESTAURANT\t116.3\tCredit Card\t116.3\t0
261025-160\tTill-1\tRESTAURANT\tJIHAD\t10/26/2026\t5:31:07\tRESTAURANT\t11.87\tCash\t11.87\t0
261025-148\tTill-1\tTAKE AWAY\tADMIN\t10/26/2026\t2:55:31\tTAKE AWAY\t0\tUnpaid\t0\t0
261025-152\tTill-1\tRESTAURANT\tANSH\t10/26/2026\t4:43:12\tRESTAURANT\t255.85\tCredit Card\t243.06\t0
"""

VALID_CSV_EMPTY_OPTIONAL_FIELDS = """Ticket\tTerminal\tDepartment\tUser\tDate\tTime\tService\tTotal\tMethod\tGiven\tChange
261025-159\tTill-1\tRESTAURANT\tJIHAD\t10/26/2026\t6:38:23\tRESTAURANT\t116.3\tCredit Card\t116.3\t0
261025-160\t\t\t\t\t\t\t11.87\tCash\t11.87\t0
"""

CSV_MISSING_REQUIRED_COLUMNS = """Ticket\tTerminal\tDepartment\tUser\tDate\tTime\tService\tTotal\tMethod
261025-159\tTill-1\tRESTAURANT\tJIHAD\t10/26/2026\t6:38:23\tRESTAURANT\t116.3\tCredit Card
"""

CSV_NO_HEADER_ROW = """This is just some text
Without any header
Or ticket data
"""

CSV_HEADER_BUT_NO_DATA = """Ticket\tTerminal\tDepartment\tUser\tDate\tTime\tService\tTotal\tMethod\tGiven\tChange
"""

CSV_INVALID_NUMERIC = """Ticket\tTerminal\tDepartment\tUser\tDate\tTime\tService\tTotal\tMethod\tGiven\tChange
261025-159\tTill-1\tRESTAURANT\tJIHAD\t10/26/2026\t6:38:23\tRESTAURANT\tnot-a-number\tCredit Card\t116.3\t0
"""


# ============================================================================
# Tests
# ============================================================================

class TestParseTicketReport:
    """Tests for parse_ticket_report function."""

    def test_valid_csv_with_summary_section(self):
        """Test parsing a valid CSV with a summary section before the header."""
        records = parse_ticket_report(VALID_CSV_WITH_SUMMARY)

        assert len(records) == 2

        # First record
        assert records[0].ticket_id == "261025-159"
        assert records[0].terminal == "Till-1"
        assert records[0].department == "RESTAURANT"
        assert records[0].user == "JIHAD"
        assert records[0].date == "10/26/2026"
        assert records[0].time == "6:38:23"
        assert records[0].service == "RESTAURANT"
        assert records[0].total == 116.3
        assert records[0].method == "Credit Card"
        assert records[0].given == 116.3
        assert records[0].change == 0.0
        assert records[0].raw["Ticket"] == "261025-159"

        # Second record
        assert records[1].ticket_id == "261025-158"
        assert records[1].total == 102.85

    def test_valid_csv_with_blank_lines(self):
        """Test parsing a valid CSV containing blank lines before, between, and after data."""
        records = parse_ticket_report(VALID_CSV_WITH_BLANK_LINES)

        assert len(records) == 2
        assert records[0].ticket_id == "261025-159"
        assert records[1].ticket_id == "261025-158"

    def test_valid_csv_with_utf8_bom(self):
        """Test parsing a CSV with a UTF-8 BOM character at the start."""
        records = parse_ticket_report(VALID_CSV_WITH_BOM)

        assert len(records) == 1
        assert records[0].ticket_id == "261025-159"
        assert records[0].total == 116.3

    def test_ticket_identifiers_remain_strings(self):
        """Test that ticket identifiers are preserved as strings (not converted to numbers)."""
        # Ticket IDs with leading zeros or specific formats must remain strings
        csv_with_leading_zeros = """Ticket\tTerminal\tDepartment\tUser\tDate\tTime\tService\tTotal\tMethod\tGiven\tChange
000123\tTill-1\tRESTAURANT\tUSER\t10/26/2026\t12:00:00\tRESTAURANT\t100.0\tCash\t100.0\t0
000124\tTill-1\tRESTAURANT\tUSER\t10/26/2026\t12:00:00\tRESTAURANT\t200.0\tCash\t200.0\t0
"""

        records = parse_ticket_report(csv_with_leading_zeros)

        assert len(records) == 2
        assert records[0].ticket_id == "000123"  # Preserved as string
        assert records[1].ticket_id == "000124"  # Preserved as string
        assert isinstance(records[0].ticket_id, str)
        assert isinstance(records[1].ticket_id, str)

    def test_totals_decimal_values_and_zero(self):
        """Test parsing totals with decimal values and zero."""
        records = parse_ticket_report(VALID_CSV_DECIMAL_AND_ZERO)

        assert len(records) == 4

        # Check decimal values
        assert records[0].total == 116.3
        assert records[1].total == 11.87
        assert records[3].total == 255.85

        # Check zero total (unpaid ticket)
        assert records[2].total == 0.0
        assert records[2].method == "Unpaid"
        assert records[2].is_unpaid is True

        # Check other tickets are not marked as unpaid
        assert records[0].is_unpaid is False
        assert records[1].is_unpaid is False
        assert records[3].is_unpaid is False

    def test_empty_optional_fields(self):
        """Test that empty optional fields are handled gracefully (return None for numeric)."""
        records = parse_ticket_report(VALID_CSV_EMPTY_OPTIONAL_FIELDS)

        assert len(records) == 2

        # First record - all fields present
        assert records[0].total == 116.3
        assert records[0].given == 116.3
        assert records[0].change == 0.0

        # Second record - optional fields (Department, User, etc.) are empty
        assert records[1].terminal == ""
        assert records[1].department == ""
        assert records[1].user == ""
        assert records[1].date == ""
        assert records[1].time == ""
        assert records[1].service == ""
        assert records[1].total == 11.87
        assert records[1].method == "Cash"
        assert records[1].given == 11.87
        assert records[1].change == 0.0

    def test_missing_required_columns(self):
        """Test that missing required columns raise a clear error."""
        with pytest.raises(TicketReportParseError) as exc_info:
            parse_ticket_report(CSV_MISSING_REQUIRED_COLUMNS)

        assert "Missing required columns" in str(exc_info.value)
        assert "Given" in str(exc_info.value) or "Change" in str(exc_info.value)

    def test_no_identifiable_header_row(self):
        """Test that a CSV with no identifiable header row raises an error."""
        with pytest.raises(TicketReportParseError) as exc_info:
            parse_ticket_report(CSV_NO_HEADER_ROW)

        assert "Could not find header row" in str(exc_info.value)

    def test_header_but_no_ticket_records(self):
        """Test that a CSV with headers but no data rows raises an error."""
        with pytest.raises(TicketReportParseError) as exc_info:
            parse_ticket_report(CSV_HEADER_BUT_NO_DATA)

        assert "no ticket records" in str(exc_info.value).lower()

    def test_invalid_numeric_values(self):
        """Test that invalid numeric values raise an error (not silently converted to zero)."""
        with pytest.raises(TicketReportParseError) as exc_info:
            parse_ticket_report(CSV_INVALID_NUMERIC)

        assert "Invalid numeric value" in str(exc_info.value)
        assert "not-a-number" in str(exc_info.value)


class TestValidateTicketReport:
    """Tests for the lightweight validate_ticket_report function."""

    def test_valid_csv_returns_true(self):
        """Test that a valid CSV returns (True, None)."""
        is_valid, error = validate_ticket_report(VALID_CSV_WITH_SUMMARY)
        assert is_valid is True
        assert error is None

    def test_invalid_csv_returns_false_with_message(self):
        """Test that an invalid CSV returns (False, error_message)."""
        is_valid, error = validate_ticket_report(CSV_NO_HEADER_ROW)
        assert is_valid is False
        assert error is not None
        assert "header row" in error.lower()

    def test_missing_columns_returns_false(self):
        """Test that missing columns return False with descriptive error."""
        is_valid, error = validate_ticket_report(CSV_MISSING_REQUIRED_COLUMNS)
        assert is_valid is False
        assert "Missing required columns" in error


class TestTicketRecord:
    """Tests for the TicketRecord dataclass."""

    def test_is_unpaid_property(self):
        """Test the is_unpaid property correctly identifies unpaid tickets."""
        # Unpaid: Total=0 and Method=Unpaid
        unpaid = TicketRecord(
            ticket_id="123", terminal="", department="", user="",
            date="", time="", service="", total=0.0, method="Unpaid",
            given=0.0, change=0.0, raw={}
        )
        assert unpaid.is_unpaid is True

        # Not unpaid: Total > 0
        paid = TicketRecord(
            ticket_id="123", terminal="", department="", user="",
            date="", time="", service="", total=10.0, method="Cash",
            given=10.0, change=0.0, raw={}
        )
        assert paid.is_unpaid is False

        # Not unpaid: Method is not Unpaid
        zero_but_paid = TicketRecord(
            ticket_id="123", terminal="", department="", user="",
            date="", time="", service="", total=0.0, method="Credit Card",
            given=0.0, change=0.0, raw={}
        )
        assert zero_but_paid.is_unpaid is False

    def test_ticket_id_stripped(self):
        """Test that ticket_id is stripped of whitespace."""
        record = TicketRecord(
            ticket_id="  261025-159  ", terminal="", department="", user="",
            date="", time="", service="", total=10.0, method="Cash",
            given=10.0, change=0.0, raw={}
        )
        assert record.ticket_id == "261025-159"

    def test_raw_preserves_original_columns(self):
        """Test that the raw dict preserves all original column values."""
        csv = """Ticket\tTerminal\tDepartment\tUser\tDate\tTime\tService\tTotal\tMethod\tGiven\tChange
261025-159\tTill-1\tRESTAURANT\tJIHAD\t10/26/2026\t6:38:23\tRESTAURANT\t116.3\tCredit Card\t116.3\t0
"""
        records = parse_ticket_report(csv)
        raw = records[0].raw

        # All original columns should be in raw
        assert raw["Ticket"] == "261025-159"
        assert raw["Terminal"] == "Till-1"
        assert raw["Department"] == "RESTAURANT"
        assert raw["User"] == "JIHAD"
        assert raw["Date"] == "10/26/2026"
        assert raw["Time"] == "6:38:23"
        assert raw["Service"] == "RESTAURANT"
        assert raw["Total"] == "116.3"
        assert raw["Method"] == "Credit Card"
        assert raw["Given"] == "116.3"
        assert raw["Change"] == "0"