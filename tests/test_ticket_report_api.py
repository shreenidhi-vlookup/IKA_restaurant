"""Tests for the ticket report CSV upload endpoint."""

from conftest import BRANCH, DATE


def post_ticket_report(client, body, filename="ticket_report.csv", branch=BRANCH, selected_date=DATE, **extra):
    return client.post(
        "/api/ticket-report",
        files={"file": (filename, body.encode(), "text/csv")},
        data={"branch": branch, "selected_date": selected_date, **extra},
    )


# Valid comma-separated ticket report (subset for testing)
VALID_CSV_COMMA = """Ticket Count,159,Total Amount,9345.82,Cancelled Count,10,Cancelled Total,84.60

Ticket,Terminal,Department,User,Date,Time,Service,Total,Method,Given,Change
261025-159,Till-1,RESTAURANT,JIHAD,2026-10-26,06:38:23,RESTAURANT,116.30,Credit Card,116.30,0.00
261025-158,Till-1,RESTAURANT,ANSH,2026-10-26,06:38:17,RESTAURANT,102.85,Credit Card,102.85,0.00
261025-141,Till-1,RESTAURANT,AKASH,2026-10-26,02:12:22,RESTAURANT,34.22,Unpaid,0.00,0.00
261025-148,Till-1,TAKE AWAY,ADMIN,2026-10-26,02:55:31,TAKE AWAY,0.00,Unpaid,0.00,0.00
"""

# Valid tab-separated ticket report (backward compatibility)
VALID_CSV_TAB = """Ticket Count\t159\tTotal Amount\t9345.82\tCancelled Count\t10\tCancelled Total\t84.60

Ticket\tTerminal\tDepartment\tUser\tDate\tTime\tService\tTotal\tMethod\tGiven\tChange
261025-159\tTill-1\tRESTAURANT\tJIHAD\t2026-10-26\t06:38:23\tRESTAURANT\t116.30\tCredit Card\t116.30\t0.00
261025-158\tTill-1\tRESTAURANT\tANSH\t2026-10-26\t06:38:17\tRESTAURANT\t102.85\tCredit Card\t102.85\t0.00
261025-141\tTill-1\tRESTAURANT\tAKASH\t2026-10-26\t02:12:22\tRESTAURANT\t34.22\tUnpaid\t0.00\t0.00
261025-148\tTill-1\tTAKE AWAY\tADMIN\t2026-10-26\t02:55:31\tTAKE AWAY\t0.00\tUnpaid\t0.00\t0.00
"""

# CSV with various Unpaid formats (case/whitespace variations)
UNPAID_VARIATIONS_CSV = """Ticket,Terminal,Department,User,Date,Time,Service,Total,Method,Given,Change
261025-001,Till-1,RESTAURANT,USER,2026-10-26,12:00:00,RESTAURANT,100.00,Unpaid,0.00,0.00
261025-002,Till-1,RESTAURANT,USER,2026-10-26,12:00:00,RESTAURANT,0.00,UNPAID,0.00,0.00
261025-003,Till-1,RESTAURANT,USER,2026-10-26,12:00:00,RESTAURANT,50.00,unpaid,0.00,0.00
261025-004,Till-1,RESTAURANT,USER,2026-10-26,12:00:00,RESTAURANT,75.00, Unpaid ,0.00,0.00
"""

# CSV with no unpaid tickets
NO_UNPAID_CSV = """Ticket,Terminal,Department,User,Date,Time,Service,Total,Method,Given,Change
261025-159,Till-1,RESTAURANT,JIHAD,2026-10-26,06:38:23,RESTAURANT,116.30,Credit Card,116.30,0.00
261025-158,Till-1,RESTAURANT,ANSH,2026-10-26,06:38:17,RESTAURANT,102.85,Cash,102.85,0.00
"""

# CSV missing required columns
MISSING_COLUMNS_CSV = """Ticket,Terminal,Department,User,Date,Time,Service,Total,Method
261025-159,Till-1,RESTAURANT,JIHAD,2026-10-26,06:38:23,RESTAURANT,116.30,Credit Card
"""

# CSV with no identifiable header
NO_HEADER_CSV = """This is just some text
Without any header
Or ticket data
"""

# CSV with invalid numeric value
INVALID_NUMERIC_CSV = """Ticket,Terminal,Department,User,Date,Time,Service,Total,Method,Given,Change
261025-159,Till-1,RESTAURANT,JIHAD,2026-10-26,06:38:23,RESTAURANT,not-a-number,Credit Card,116.30,0.00
"""

# Empty CSV (header only)
EMPTY_CSV = """Ticket,Terminal,Department,User,Date,Time,Service,Total,Method,Given,Change
"""

# CSV with UTF-8 BOM
BOM_CSV = """﻿Ticket,Terminal,Department,User,Date,Time,Service,Total,Method,Given,Change
261025-159,Till-1,RESTAURANT,JIHAD,2026-10-26,06:38:23,RESTAURANT,116.30,Credit Card,116.30,0.00
261025-148,Till-1,TAKE AWAY,ADMIN,2026-10-26,02:55:31,TAKE AWAY,0.00,Unpaid,0.00,0.00
"""


class TestTicketReportAPI:
    """Tests for POST /api/ticket-report endpoint."""

    def test_valid_comma_separated_report(self, client):
        """Valid comma-separated ticket report returns correct counts and unpaid details."""
        response = post_ticket_report(client, VALID_CSV_COMMA)
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["total_tickets"] == 4
        assert data["unpaid_count"] == 2
        assert data["branch"] == BRANCH
        assert data["date"] == DATE
        unpaid = data["unpaid_tickets"]
        assert len(unpaid) == 2
        # Check first unpaid ticket (positive total)
        assert unpaid[0]["ticket_id"] == "261025-141"
        assert unpaid[0]["total"] == 34.22
        assert unpaid[0]["method"] == "Unpaid"
        # Check second unpaid ticket (zero total)
        assert unpaid[1]["ticket_id"] == "261025-148"
        assert unpaid[1]["total"] == 0.0
        assert unpaid[1]["method"] == "Unpaid"

    def test_valid_tab_separated_report(self, client):
        """Valid tab-separated ticket report works (backward compatibility)."""
        response = post_ticket_report(client, VALID_CSV_TAB)
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["total_tickets"] == 4
        assert data["unpaid_count"] == 2

    def test_unpaid_tickets_with_positive_and_zero_totals(self, client):
        """Unpaid tickets with both positive and zero totals are identified."""
        response = post_ticket_report(client, VALID_CSV_COMMA)
        assert response.status_code == 200
        data = response.json()
        unpaid = data["unpaid_tickets"]
        totals = [t["total"] for t in unpaid]
        assert 34.22 in totals  # positive total
        assert 0.0 in totals    # zero total

    def test_case_insensitive_and_whitespace_unpaid_method(self, client):
        """Unpaid detection is case-insensitive and ignores surrounding whitespace."""
        response = post_ticket_report(client, UNPAID_VARIATIONS_CSV)
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["total_tickets"] == 4
        assert data["unpaid_count"] == 4
        assert len(data["unpaid_tickets"]) == 4

    def test_report_with_no_unpaid_tickets(self, client):
        """Report containing no unpaid tickets returns zero count and empty list."""
        response = post_ticket_report(client, NO_UNPAID_CSV)
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["total_tickets"] == 2
        assert data["unpaid_count"] == 0
        assert data["unpaid_tickets"] == []

    def test_missing_required_columns(self, client):
        """Missing required columns returns 400 with descriptive error."""
        response = post_ticket_report(client, MISSING_COLUMNS_CSV)
        assert response.status_code == 400
        assert "Missing required columns" in response.json()["detail"]

    def test_missing_or_invalid_header(self, client):
        """CSV with no identifiable header returns 400."""
        response = post_ticket_report(client, NO_HEADER_CSV)
        assert response.status_code == 400
        assert "Could not find header row" in response.json()["detail"]

    def test_invalid_numeric_values(self, client):
        """Invalid numeric values return 400 (not silently converted to zero)."""
        response = post_ticket_report(client, INVALID_NUMERIC_CSV)
        assert response.status_code == 400
        assert "Invalid numeric value" in response.json()["detail"]

    def test_empty_file(self, client):
        """CSV with header but no data rows returns 400."""
        response = post_ticket_report(client, EMPTY_CSV)
        assert response.status_code == 400
        assert "no ticket records" in response.json()["detail"].lower()

    def test_utf8_bom_handling(self, client):
        """UTF-8 BOM prefix is handled correctly."""
        response = post_ticket_report(client, BOM_CSV)
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["total_tickets"] == 2
        assert data["unpaid_count"] == 1

    def test_invalid_file_extension(self, client):
        """Non-CSV file extension is rejected."""
        response = post_ticket_report(client, VALID_CSV_COMMA, filename="report.xlsx")
        assert response.status_code == 400
        assert response.json()["detail"] == "Upload one CSV file"

    def test_blank_branch_rejected(self, client):
        """Blank branch name is rejected."""
        response = post_ticket_report(client, VALID_CSV_COMMA, branch="   ")
        assert response.status_code == 400
        assert "Select a branch" in response.json()["detail"]

    def test_invalid_date_format_rejected(self, client):
        """Invalid date format is rejected."""
        response = post_ticket_report(client, VALID_CSV_COMMA, selected_date="30/09/2026")
        assert response.status_code == 400
        assert "Date must be YYYY-MM-DD" in response.json()["detail"]


class TestExistingCsvEndpointPreserved:
    """Ensure the existing /api/csv endpoint behavior is unchanged."""

    def test_existing_csv_endpoint_still_works(self, client):
        """Existing TIL CSV upload endpoint still functions as before."""
        from tests.test_csv_verification import HEADER, VOID_ROW, PLAIN_ROW
        body = f"TIL export for Leeds\n\n{HEADER}\n{VOID_ROW}\n{PLAIN_ROW}\n"
        response = client.post(
            "/api/csv",
            files={"file": ("til.csv", body.encode(), "text/csv")},
            data={"branch": BRANCH, "selected_date": DATE},
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["saved_rows"] == 2
        assert data["branch"] == BRANCH
        assert data["date"] == DATE
        assert "csv_dates" in data
        assert "promotions_in_file" in data


def test_non_utf8_upload_returns_400(client):
    body = VALID_CSV_COMMA.replace("RESTAURANT,JIHAD", "RESTAURANT,JIHADé").encode("latin-1")
    response = client.post(
        "/api/ticket-report",
        files={"file": ("ticket_report.csv", body, "text/csv")},
        data={"branch": BRANCH, "selected_date": DATE},
    )
    assert response.status_code == 400
    assert "UTF-8" in response.json()["detail"]