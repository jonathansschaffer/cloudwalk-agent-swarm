"""
Mock support ticket system.
Simulates a real ticketing platform (e.g., Zendesk, Freshdesk).
"""

import uuid
from datetime import datetime
from typing import Optional

# In-memory ticket store (resets on app restart — acceptable for a demo)
_TICKETS: dict[str, dict] = {}


def create_ticket(user_id: str, issue: str, priority: str = "medium") -> dict:
    """
    Creates a new support ticket and returns its details.

    Args:
        user_id:  The customer identifier.
        issue:    Brief description of the problem.
        priority: 'low', 'medium', or 'high'.

    Returns:
        Ticket info dict with ticket_id and estimated resolution.
    """
    valid_priorities = {"low", "medium", "high"}
    if priority not in valid_priorities:
        priority = "medium"

    ticket_id = f"TKT-{datetime.now().strftime('%Y%m%d')}-{str(uuid.uuid4())[:6].upper()}"
    resolution_map = {"low": "3-5 business days", "medium": "24-48 hours", "high": "2-4 hours"}

    ticket = {
        "ticket_id": ticket_id,
        "user_id": user_id,
        "issue": issue,
        "priority": priority,
        "status": "open",
        "created_at": datetime.now().isoformat(),
        "estimated_resolution": resolution_map[priority],
    }
    _TICKETS[ticket_id] = ticket
    return ticket


def get_ticket(ticket_id: str) -> Optional[dict]:
    """Returns ticket data or None if not found."""
    return _TICKETS.get(ticket_id)


def list_user_tickets(user_id: str) -> list[dict]:
    """Returns all tickets for a given user."""
    return [t for t in _TICKETS.values() if t["user_id"] == user_id]
