"""
Append-only audit trail.

Usage:
    from app.audit import emit
    emit("auth.login.success", actor_user_id=user.id, ip=client_ip)

Never read or mutate rows from app code — this table is for LGPD / SOC 2
investigation only. Writes must not fail the caller: if the DB is down,
we log and carry on rather than breaking user-visible flows.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.database.db import SessionLocal
from app.database.models import AuditEvent

logger = logging.getLogger(__name__)


def emit(
    event_type: str,
    *,
    actor_user_id: int | None = None,
    ip: str | None = None,
    **details: Any,
) -> None:
    """Record a security-relevant event. Never raises."""
    try:
        with SessionLocal() as db:
            db.add(
                AuditEvent(
                    event_type=event_type,
                    actor_user_id=actor_user_id,
                    ip_address=ip[:64] if ip else None,
                    details=json.dumps(details, default=str) if details else "",
                )
            )
            db.commit()
    except Exception as exc:
        logger.error("audit.emit failed (%s): %s", event_type, exc, exc_info=False)
