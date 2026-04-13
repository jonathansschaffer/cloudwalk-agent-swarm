"""
Unit tests for the Customer Support Agent and its tools.

Run with:
    pytest tests/test_support_agent.py -v
"""

import pytest
import json
from app.database.mock_users import get_account_status, get_recent_transactions, get_user
from app.database.mock_tickets import create_ticket, get_ticket


class TestMockUserDatabase:
    """Tests for the mock user database functions."""

    def test_known_user_found(self):
        result = get_account_status("client789")
        assert result["found"] is True
        assert result["name"] == "Carlos Andrade"
        assert result["account_status"] == "active"

    def test_unknown_user_not_found(self):
        result = get_account_status("does_not_exist")
        assert result["found"] is False

    def test_suspended_user_has_hints(self):
        result = get_account_status("user_002")
        assert result["account_status"] == "suspended"
        assert len(result["diagnostic_hints"]) > 0

    def test_high_failed_logins_flagged(self):
        result = get_account_status("user_002")
        hints = result["diagnostic_hints"]
        assert any("login" in h.lower() or "locked" in h.lower() for h in hints)

    def test_zero_transfer_limit_flagged(self):
        result = get_account_status("user_002")
        hints = result["diagnostic_hints"]
        assert any("limit" in h.lower() for h in hints)

    def test_transactions_returned_correctly(self):
        result = get_recent_transactions("client789", limit=5)
        assert result["found"] is True
        assert isinstance(result["transactions"], list)

    def test_limit_respected(self):
        result = get_recent_transactions("client789", limit=2)
        assert len(result["transactions"]) <= 2


class TestTicketSystem:
    """Tests for the mock ticketing system."""

    def test_ticket_created_with_valid_id(self):
        ticket = create_ticket("client789", "Cannot make transfers", "high")
        assert ticket["ticket_id"].startswith("TKT-")
        assert ticket["user_id"] == "client789"
        assert ticket["priority"] == "high"
        assert ticket["status"] == "open"
        assert "estimated_resolution" in ticket

    def test_ticket_retrievable(self):
        ticket = create_ticket("client789", "Test issue", "medium")
        retrieved = get_ticket(ticket["ticket_id"])
        assert retrieved is not None
        assert retrieved["ticket_id"] == ticket["ticket_id"]

    def test_invalid_priority_defaults_to_medium(self):
        ticket = create_ticket("client789", "Test", "urgent")  # invalid
        assert ticket["priority"] == "medium"

    def test_all_priority_levels(self):
        for priority in ["low", "medium", "high"]:
            ticket = create_ticket("client789", "Test", priority)
            assert ticket["priority"] == priority
            assert "estimated_resolution" in ticket


class TestAccountTools:
    """Tests that account tools return properly formatted JSON strings."""

    def test_lookup_account_status_tool(self):
        from app.tools.account_tools import lookup_account_status
        result = lookup_account_status.invoke("client789")
        data = json.loads(result)
        assert data["found"] is True

    def test_get_transaction_history_tool(self):
        from app.tools.account_tools import get_transaction_history
        result = get_transaction_history.invoke({"user_id": "client789", "limit": 3})
        data = json.loads(result)
        assert "transactions" in data

    def test_create_support_ticket_tool(self):
        from app.tools.account_tools import create_support_ticket
        result = create_support_ticket.invoke({
            "user_id": "client789",
            "issue": "Cannot access account",
            "priority": "high"
        })
        data = json.loads(result)
        assert "ticket_id" in data
        assert data["ticket_id"].startswith("TKT-")
