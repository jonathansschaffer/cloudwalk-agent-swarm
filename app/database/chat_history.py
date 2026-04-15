"""
Chat history store (DB-backed).

Every successful /chat turn is persisted here. The frontend reloads the
authenticated user's history on every page load. Old in-memory semantics
are preserved on the write side — the caller passes a user_id (DB id as
string, or legacy slug) and we resolve it to the `users.id` FK.
"""

from __future__ import annotations

from typing import Optional

from app.database.db import SessionLocal
from app.database.models import ChatMessage, User

MAX_HISTORY_PER_USER = 100  # maximum turns returned per user


def _resolve_user_id(db, user_id_str: str) -> Optional[int]:
    # DB id form — fast path.
    if user_id_str.isdigit():
        exists = db.query(User.id).filter(User.id == int(user_id_str)).scalar()
        return int(exists) if exists is not None else None
    # Email form — kept so tests and scripts can address seeded users by email.
    user = db.query(User).filter(User.email == user_id_str.lower()).one_or_none()
    return user.id if user else None


def append_turn(
    user_id: str,
    user_message: str,
    bot_response: str,
    agent_used: str,
    intent: str = "",
    ticket_id: Optional[str] = None,
    escalated: bool = False,
    language: str = "en",
) -> None:
    with SessionLocal() as db:
        resolved_id = _resolve_user_id(db, user_id)
        if resolved_id is None:
            return  # Silently skip history for unknown users (e.g. Telegram unlinked).
        db.add(ChatMessage(
            user_id=resolved_id,
            user_message=user_message,
            bot_response=bot_response,
            agent_used=agent_used,
            intent=intent,
            ticket_id=ticket_id,
            escalated=escalated,
            language=language,
        ))
        db.commit()


def get_history(user_id: str) -> list[dict]:
    with SessionLocal() as db:
        resolved_id = _resolve_user_id(db, user_id)
        if resolved_id is None:
            return []
        rows = (
            db.query(ChatMessage)
            .filter(ChatMessage.user_id == resolved_id)
            .order_by(ChatMessage.created_at.asc())
            .limit(MAX_HISTORY_PER_USER)
            .all()
        )
        return [
            {
                "user": r.user_message,
                "bot": r.bot_response,
                "agent_used": r.agent_used,
                "intent": r.intent,
                "ticket_id": r.ticket_id,
                "escalated": r.escalated,
                "language": r.language,
                "timestamp": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]


def clear_history(user_id: str) -> None:
    with SessionLocal() as db:
        resolved_id = _resolve_user_id(db, user_id)
        if resolved_id is None:
            return
        db.query(ChatMessage).filter(ChatMessage.user_id == resolved_id).delete()
        db.commit()
