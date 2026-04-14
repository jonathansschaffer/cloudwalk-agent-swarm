"""
Ticket service (DB-backed).

Creates and lists support tickets. Each ticket belongs to exactly one user —
the Support Agent passes the authenticated user's DB id (or legacy slug) so
tickets cannot be created for someone else.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from app.database.db import SessionLocal
from app.database.models import Ticket, User


_RESOLUTION_MAP = {
    "low": "3-5 business days",
    "medium": "24-48 hours",
    "high": "2-4 hours",
}


def _resolve_user_id(db, user_id_str: str) -> Optional[int]:
    if user_id_str.isdigit():
        exists = db.query(User.id).filter(User.id == int(user_id_str)).scalar()
        return int(exists) if exists is not None else None
    user = db.query(User).filter(User.legacy_id == user_id_str).one_or_none()
    return user.id if user else None


def create_ticket(user_id: str, issue: str, priority: str = "medium") -> dict:
    if priority not in _RESOLUTION_MAP:
        priority = "medium"

    with SessionLocal() as db:
        resolved_id = _resolve_user_id(db, user_id)
        if resolved_id is None:
            # Graceful fallback: still return a ticket shape but flag it.
            return {
                "ticket_id": None,
                "user_id": user_id,
                "issue": issue,
                "priority": priority,
                "status": "error",
                "error": "User not found.",
            }

        ticket_id = f"TKT-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{str(uuid.uuid4())[:6].upper()}"
        ticket = Ticket(
            id=ticket_id,
            user_id=resolved_id,
            issue=issue,
            priority=priority,
            status="open",
            estimated_resolution=_RESOLUTION_MAP[priority],
        )
        db.add(ticket)
        db.commit()
        db.refresh(ticket)
        return _ticket_to_dict(ticket)


def get_ticket(ticket_id: str) -> Optional[dict]:
    with SessionLocal() as db:
        ticket = db.query(Ticket).filter(Ticket.id == ticket_id).one_or_none()
        return _ticket_to_dict(ticket) if ticket else None


def list_user_tickets(user_id: str) -> list[dict]:
    with SessionLocal() as db:
        resolved_id = _resolve_user_id(db, user_id)
        if resolved_id is None:
            return []
        tickets = (
            db.query(Ticket)
            .filter(Ticket.user_id == resolved_id)
            .order_by(Ticket.created_at.desc())
            .all()
        )
        return [_ticket_to_dict(t) for t in tickets]


def _ticket_to_dict(ticket: Ticket) -> dict:
    return {
        "ticket_id": ticket.id,
        "user_id": ticket.user_id,
        "issue": ticket.issue,
        "priority": ticket.priority,
        "status": ticket.status,
        "created_at": ticket.created_at.isoformat() if ticket.created_at else None,
        "estimated_resolution": ticket.estimated_resolution,
    }
