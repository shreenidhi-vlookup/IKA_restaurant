"""Tests for the unpaid ticket service."""

import pytest

from app.parsers.ticket_report_parser import TicketRecord
from app.services.unpaid_ticket_service import get_unpaid_tickets, count_unpaid_tickets


def make_ticket(
    ticket_id: str,
    total: float | None,
    method: str,
    **kwargs
) -> TicketRecord:
    """Helper to create a TicketRecord with minimal required fields."""
    defaults = {
        "terminal": "Till-1",
        "department": "RESTAURANT",
        "user": "TEST",
        "date": "2026-10-26",
        "time": "12:00:00",
        "service": "RESTAURANT",
        "given": total,
        "change": 0.0,
        "raw": {},
    }
    defaults.update(kwargs)
    return TicketRecord(
        ticket_id=ticket_id,
        total=total,
        method=method,
        **defaults
    )


class TestGetUnpaidTickets:
    """Tests for get_unpaid_tickets function."""

    def test_ticket_with_total_34_22_and_method_unpaid_is_identified(self):
        """Ticket with Total 34.22 and Method 'Unpaid' should be identified."""
        ticket = make_ticket("261025-141", 34.22, "Unpaid")
        unpaid = get_unpaid_tickets([ticket])
        assert len(unpaid) == 1
        assert unpaid[0].ticket_id == "261025-141"
        assert unpaid[0].total == 34.22

    def test_ticket_with_total_0_00_and_method_unpaid_is_identified(self):
        """Ticket with Total 0.00 and Method 'Unpaid' should be identified."""
        ticket = make_ticket("261025-148", 0.00, "Unpaid")
        unpaid = get_unpaid_tickets([ticket])
        assert len(unpaid) == 1
        assert unpaid[0].ticket_id == "261025-148"
        assert unpaid[0].total == 0.0

    def test_ticket_with_method_cash_is_not_identified(self):
        """Ticket with Method 'Cash' should not be identified as unpaid."""
        ticket = make_ticket("261025-159", 116.30, "Cash")
        unpaid = get_unpaid_tickets([ticket])
        assert len(unpaid) == 0

    def test_ticket_with_method_credit_card_is_not_identified(self):
        """Ticket with Method 'Credit Card' should not be identified as unpaid."""
        ticket = make_ticket("261025-158", 102.85, "Credit Card")
        unpaid = get_unpaid_tickets([ticket])
        assert len(unpaid) == 0

    def test_matching_is_case_insensitive(self):
        """Method matching should be case-insensitive."""
        tickets = [
            make_ticket("1", 10.0, "Unpaid"),
            make_ticket("2", 10.0, "UNPAID"),
            make_ticket("3", 10.0, "unpaid"),
            make_ticket("4", 10.0, "UnPaId"),
        ]
        unpaid = get_unpaid_tickets(tickets)
        assert len(unpaid) == 4
        assert {u.ticket_id for u in unpaid} == {"1", "2", "3", "4"}

    def test_leading_and_trailing_whitespace_is_ignored(self):
        """Leading and trailing whitespace in Method should be ignored."""
        tickets = [
            make_ticket("1", 10.0, " Unpaid "),
            make_ticket("2", 10.0, "\tUnpaid\n"),
            make_ticket("3", 10.0, "  UNPAID  "),
        ]
        unpaid = get_unpaid_tickets(tickets)
        assert len(unpaid) == 3
        assert {u.ticket_id for u in unpaid} == {"1", "2", "3"}

    def test_empty_input_list_returns_empty_result(self):
        """Empty input list should return empty list."""
        unpaid = get_unpaid_tickets([])
        assert unpaid == []

    def test_multiple_tickets_classified_correctly(self):
        """Multiple tickets with mixed methods should be classified correctly."""
        tickets = [
            make_ticket("1", 100.0, "Unpaid"),
            make_ticket("2", 50.0, "Cash"),
            make_ticket("3", 0.0, "Unpaid"),
            make_ticket("4", 75.0, "Credit Card"),
            make_ticket("5", 25.0, "UNPAID"),
        ]
        unpaid = get_unpaid_tickets(tickets)
        assert len(unpaid) == 3
        assert {u.ticket_id for u in unpaid} == {"1", "3", "5"}

    def test_returned_records_preserve_original_ticket_ids_and_values(self):
        """Returned records should preserve original ticket IDs and all values."""
        ticket = make_ticket(
            "261025-141",
            34.22,
            "Unpaid",
            terminal="Till-1",
            department="RESTAURANT",
            user="AKASH",
            given=0.0,
            change=0.0,
            raw={"Ticket": "261025-141", "Method": "Unpaid", "Total": "34.22"}
        )
        unpaid = get_unpaid_tickets([ticket])
        assert len(unpaid) == 1
        assert unpaid[0].ticket_id == "261025-141"
        assert unpaid[0].total == 34.22
        assert unpaid[0].method == "Unpaid"
        assert unpaid[0].terminal == "Till-1"
        assert unpaid[0].raw["Method"] == "Unpaid"

    def test_original_input_list_not_modified(self):
        """Original input list should not be modified."""
        tickets = [
            make_ticket("1", 10.0, "Unpaid"),
            make_ticket("2", 10.0, "Cash"),
        ]
        original_length = len(tickets)
        get_unpaid_tickets(tickets)
        assert len(tickets) == original_length

    def test_original_records_not_modified(self):
        """Original TicketRecord objects should not be modified."""
        ticket = make_ticket("1", 10.0, "Unpaid")
        original_method = ticket.method
        original_total = ticket.total
        get_unpaid_tickets([ticket])
        assert ticket.method == original_method
        assert ticket.total == original_total


class TestCountUnpaidTickets:
    """Tests for count_unpaid_tickets function."""

    def test_count_matches_get_unpaid_tickets(self):
        """Count should match the length of get_unpaid_tickets result."""
        tickets = [
            make_ticket("1", 100.0, "Unpaid"),
            make_ticket("2", 50.0, "Cash"),
            make_ticket("3", 0.0, "Unpaid"),
        ]
        count = count_unpaid_tickets(tickets)
        unpaid = get_unpaid_tickets(tickets)
        assert count == len(unpaid)
        assert count == 2

    def test_empty_list_returns_zero(self):
        """Empty list should return zero."""
        assert count_unpaid_tickets([]) == 0

    def test_all_unpaid_returns_correct_count(self):
        """All unpaid tickets should return correct count."""
        tickets = [
            make_ticket("1", 10.0, "Unpaid"),
            make_ticket("2", 20.0, "UNPAID"),
        ]
        assert count_unpaid_tickets(tickets) == 2