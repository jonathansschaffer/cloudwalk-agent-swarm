"""
Mock user database simulating a real CRM/user management system.

In production, these functions would be replaced by authenticated HTTP calls
to a CRM API (e.g., Salesforce, HubSpot) or direct database queries (PostgreSQL).

The 5 pre-configured users cover distinct support scenarios:

  client789 — Active account, KYC verified, full limits.  Standard user.
  user_002  — Suspended, KYC pending, 6 failed logins.    Tests suspension flow.
  user_003  — Pending KYC, new account, low limits.       Tests onboarding flow.
  user_004  — Enterprise plan, limit exhausted today.     Tests limit-exceeded flow.
  user_005  — Active, 2 failed logins, failed transaction.Tests partial issues.

All user data is read-only in this mock — no mutations are exposed,
which mirrors a typical read-only CRM integration for support agents.
"""

from typing import Optional
from copy import deepcopy

MOCK_USERS: dict = {
    "client789": {
        "name": "Carlos Andrade",
        "email": "carlos.andrade@email.com",
        "account_status": "active",
        "kyc_verified": True,
        "plan": "InfinitePay Pro",
        "since": "2023-06-10",
        "transfer_limit_daily": 10000.00,
        "transfer_limit_remaining": 10000.00,
        "failed_login_attempts": 0,
        "transactions": [
            {
                "id": "txn_001",
                "type": "pix_out",
                "amount": 250.00,
                "date": "2026-04-10",
                "status": "completed",
                "description": "Pagamento fornecedor",
            },
            {
                "id": "txn_002",
                "type": "card_payment_received",
                "amount": 1500.00,
                "date": "2026-04-11",
                "status": "completed",
                "description": "Venda débito",
            },
            {
                "id": "txn_003",
                "type": "pix_in",
                "amount": 300.00,
                "date": "2026-04-12",
                "status": "completed",
                "description": "Recebimento cliente",
            },
        ],
    },
    "user_002": {
        "name": "Maria Souza",
        "email": "maria.souza@email.com",
        "account_status": "suspended",
        "kyc_verified": False,
        "plan": "InfinitePay Basic",
        "since": "2022-08-20",
        "transfer_limit_daily": 1000.00,
        "transfer_limit_remaining": 0.00,
        "failed_login_attempts": 6,
        "transactions": [],
    },
    "user_003": {
        "name": "João Silva",
        "email": "joao.silva@email.com",
        "account_status": "pending_kyc",
        "kyc_verified": False,
        "plan": "InfinitePay Basic",
        "since": "2026-03-01",
        "transfer_limit_daily": 500.00,
        "transfer_limit_remaining": 500.00,
        "failed_login_attempts": 0,
        "transactions": [],
    },
    "user_004": {
        "name": "Ana Lima",
        "email": "ana.lima@empresa.com",
        "account_status": "active",
        "kyc_verified": True,
        "plan": "InfinitePay Enterprise",
        "since": "2021-11-05",
        "transfer_limit_daily": 50000.00,
        "transfer_limit_remaining": 0.00,
        "failed_login_attempts": 0,
        "transactions": [
            {
                "id": "txn_010",
                "type": "pix_out",
                "amount": 50000.00,
                "date": "2026-04-13",
                "status": "completed",
                "description": "Pagamento mensal fornecedores",
            },
        ],
    },
    "user_005": {
        "name": "Pedro Costa",
        "email": "pedro.costa@email.com",
        "account_status": "active",
        "kyc_verified": True,
        "plan": "InfinitePay Pro",
        "since": "2024-01-15",
        "transfer_limit_daily": 5000.00,
        "transfer_limit_remaining": 4800.00,
        "failed_login_attempts": 2,
        "transactions": [
            {
                "id": "txn_020",
                "type": "card_payment_received",
                "amount": 199.90,
                "date": "2026-04-12",
                "status": "failed",
                "description": "Tentativa de venda crédito - falhou",
            },
        ],
    },
}


def get_user(user_id: str) -> Optional[dict]:
    """Returns a copy of user data or None if not found."""
    user = MOCK_USERS.get(user_id)
    return deepcopy(user) if user else None


def get_account_status(user_id: str) -> dict:
    """
    Returns account status enriched with diagnostic hints for the support agent.

    The `diagnostic_hints` list contains human-readable strings that the
    Support Agent uses to explain the root cause of issues to the customer.
    Hints are generated based on account state (suspension, KYC status,
    failed login count, remaining transfer limit).

    Args:
        user_id: The customer's unique identifier.

    Returns:
        Dict with account fields and a `diagnostic_hints` list, or
        {"found": False, "user_id": user_id} if the user does not exist.
    """
    user = get_user(user_id)
    if not user:
        return {
            "found": False,
            "user_id": user_id,
        }

    hints = []
    status = user["account_status"]

    if status == "suspended":
        hints.append("Account is suspended — likely due to policy violation or failed KYC.")
    if status == "pending_kyc":
        hints.append("Account pending KYC verification — user must complete identity verification.")
    if not user["kyc_verified"]:
        hints.append("KYC not verified — transfers and some features may be restricted.")
    if user["failed_login_attempts"] >= 5:
        hints.append(
            f"High failed login attempts ({user['failed_login_attempts']}) — "
            "account may be temporarily locked."
        )
    if user["transfer_limit_remaining"] == 0:
        hints.append("Daily transfer limit exhausted — will reset at midnight.")
    if user["transfer_limit_remaining"] < user["transfer_limit_daily"] * 0.1:
        hints.append(
            f"Transfer limit nearly exhausted: R$ {user['transfer_limit_remaining']:.2f} remaining."
        )

    return {
        "found": True,
        "user_id": user_id,
        "name": user["name"],
        "account_status": status,
        "kyc_verified": user["kyc_verified"],
        "plan": user["plan"],
        "member_since": user["since"],
        "transfer_limit_daily": user["transfer_limit_daily"],
        "transfer_limit_remaining": user["transfer_limit_remaining"],
        "failed_login_attempts": user["failed_login_attempts"],
        "diagnostic_hints": hints,
    }


def get_recent_transactions(user_id: str, limit: int = 5) -> dict:
    """Returns the most recent transactions for a user."""
    user = get_user(user_id)
    if not user:
        return {"found": False, "user_id": user_id, "transactions": []}

    transactions = user.get("transactions", [])
    recent = transactions[-limit:] if len(transactions) > limit else transactions

    return {
        "found": True,
        "user_id": user_id,
        "name": user["name"],
        "transaction_count": len(recent),
        "transactions": recent,
    }
