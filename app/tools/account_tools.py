"""
Customer support tools for the Support Agent.
Each tool wraps a mock database operation and is exposed as a LangChain Tool.
"""

import json
import logging
from langchain_core.tools import tool
from app.database import mock_users, mock_tickets

logger = logging.getLogger(__name__)


@tool
def lookup_account_status(user_id: str) -> str:
    """
    Look up the account status and key details for a customer.

    ALWAYS call this tool FIRST when handling any customer support request.
    It returns account status, KYC verification status, transfer limits,
    and diagnostic hints about potential issues.

    Args:
        user_id: The customer's unique identifier.

    Returns:
        JSON string with account status details and diagnostic hints.
    """
    logger.info("Looking up account status for user_id: %s", user_id)
    result = mock_users.get_account_status(user_id)
    return json.dumps(result, ensure_ascii=False, indent=2)


@tool
def get_transaction_history(user_id: str, limit: int = 5) -> str:
    """
    Retrieve the most recent transactions for a customer.

    Use this when the customer reports issues with payments, transfers,
    unexpected charges, or missing transactions.

    Args:
        user_id: The customer's unique identifier.
        limit:   Number of recent transactions to return (default 5, max 10).

    Returns:
        JSON string with a list of recent transactions.
    """
    limit = min(limit, 10)
    logger.info("Fetching %d transactions for user_id: %s", limit, user_id)
    result = mock_users.get_recent_transactions(user_id, limit)
    return json.dumps(result, ensure_ascii=False, indent=2)


@tool
def create_support_ticket(user_id: str, issue: str, priority: str = "medium") -> str:
    """
    Create a support ticket for issues that cannot be resolved automatically.

    Use this when:
    - The account issue requires manual review by the support team.
    - The customer's problem is complex or requires human intervention.
    - You have diagnosed the issue but cannot fix it programmatically.

    Args:
        user_id:  The customer's unique identifier.
        issue:    Clear description of the problem being reported.
        priority: Urgency level — 'low', 'medium', or 'high'.

    Returns:
        JSON string with the created ticket ID and estimated resolution time.
    """
    logger.info("Creating support ticket for user_id: %s | Priority: %s", user_id, priority)
    ticket = mock_tickets.create_ticket(user_id, issue, priority)
    return json.dumps(ticket, ensure_ascii=False, indent=2)
