"""
CRM lookup service (DB-backed).

Historical name (`mock_users`) kept to avoid a sweeping rename — the contents
are no longer in-memory. All reads go through SQLAlchemy and return plain
dicts so the LangChain tools keep their JSON-friendly contract.

The agent sees authenticated users only: `user_id` here is the DB id as a
string. For backwards-compat with the 5 seeded fixtures, a legacy-id lookup
(e.g. "client789") also works.
"""

from __future__ import annotations

from typing import Optional

from app.database.db import SessionLocal
from app.database.models import User


def _resolve_user(db, user_id: str) -> Optional[User]:
    """Accepts a numeric DB id ('42') or an email ('carlos.andrade@infinitepay.test')."""
    if user_id.isdigit():
        return db.query(User).filter(User.id == int(user_id)).one_or_none()
    return db.query(User).filter(User.email == user_id.lower()).one_or_none()


def get_user(user_id: str) -> Optional[dict]:
    """Returns a flat dict mirroring the old in-memory shape, or None."""
    with SessionLocal() as db:
        user = _resolve_user(db, user_id)
        if user is None:
            return None
        return {
            "name": user.name,
            "email": user.email,
            "account_status": user.account_status,
            "kyc_verified": user.kyc_verified,
            "plan": user.plan,
            "since": user.member_since,
            "transfer_limit_daily": user.transfer_limit_daily,
            "transfer_limit_remaining": user.transfer_limit_remaining,
            "failed_login_attempts": user.failed_login_attempts,
            "transactions": [
                {
                    "id": t.id, "type": t.type, "amount": t.amount,
                    "date": t.date, "status": t.status, "description": t.description,
                }
                for t in user.transactions
            ],
        }


def get_account_status(user_id: str) -> dict:
    """Returns diagnostic-enriched account status for the Support Agent."""
    user = get_user(user_id)
    if not user:
        return {"found": False, "user_id": user_id}

    hints: list[str] = []
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
    if 0 < user["transfer_limit_remaining"] < user["transfer_limit_daily"] * 0.1:
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
