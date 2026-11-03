"""Service for identifying unpaid tickets from parsed ticket records.

This module provides business logic for classifying tickets as unpaid
based on their payment method. It operates on parsed TicketRecord objects
and does not perform any I/O, database operations, or CSV parsing.
"""

from app.parsers.ticket_report_parser import TicketRecord


def get_unpaid_tickets(tickets: list[TicketRecord]) -> list[TicketRecord]:
    """Filter and return only the tickets classified as unpaid.

    A ticket is considered unpaid if its Method field equals "Unpaid",
    ignoring capitalization and leading/trailing whitespace.

    The ticket's Total value does NOT affect this classification.
    Both tickets with positive totals and zero totals can be unpaid
    if their Method is "Unpaid".

    Args:
        tickets: List of parsed TicketRecord objects.

    Returns:
        List of TicketRecord objects that are classified as unpaid.
        The returned records are the same objects from the input list
        (not copies), preserving all original data including ticket IDs,
        totals, and raw column values.

    Examples:
        >>> tickets = [ticket_with_method_unpaid, ticket_with_method_cash]
        >>> unpaid = get_unpaid_tickets(tickets)
        >>> len(unpaid)
        1
    """
    return [ticket for ticket in tickets if ticket.is_unpaid]


def count_unpaid_tickets(tickets: list[TicketRecord]) -> int:
    """Return the count of unpaid tickets in the list.

    Args:
        tickets: List of parsed TicketRecord objects.

    Returns:
        Number of tickets classified as unpaid.
    """
    return len(get_unpaid_tickets(tickets))