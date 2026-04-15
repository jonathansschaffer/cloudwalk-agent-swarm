"""
Pluggable email provider.

Today the only implementation is ``LogOnlyEmailProvider`` — it logs the message
body (including verification/unlock links) at INFO level instead of sending a
real email. That is deliberately safe for a demo: no external credentials
needed, tokens are still issued and remain valid, and a developer can copy
the link from the log line.

Swapping to Resend / Postmark / SES is a one-file change plus env vars
(`EMAIL_PROVIDER=resend`, `EMAIL_API_KEY=...`). The protocol is small on
purpose so any HTTP-based transactional mail service fits.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Protocol

logger = logging.getLogger(__name__)


@dataclass
class OutgoingEmail:
    to: str
    subject: str
    body_text: str
    body_html: str | None = None


class EmailProvider(Protocol):
    def send(self, email: OutgoingEmail) -> bool: ...


class LogOnlyEmailProvider:
    """Writes the email to the logs instead of sending it.

    Every line is prefixed with ``MAIL >>`` so they are easy to grep in dev.
    """

    def send(self, email: OutgoingEmail) -> bool:
        logger.info("MAIL >> to=%s subject=%r", email.to, email.subject)
        for line in email.body_text.splitlines():
            logger.info("MAIL >>   %s", line)
        return True


_PROVIDER: EmailProvider | None = None


def get_provider() -> EmailProvider:
    global _PROVIDER
    if _PROVIDER is not None:
        return _PROVIDER

    name = os.getenv("EMAIL_PROVIDER", "log").lower()
    if name == "log":
        _PROVIDER = LogOnlyEmailProvider()
    else:
        # Guardrail: if an env value is set but we don't recognize it, fall back
        # to log instead of silently dropping mail. Loud beats silent.
        logger.warning(
            "Unknown EMAIL_PROVIDER=%r — falling back to log-only provider.", name
        )
        _PROVIDER = LogOnlyEmailProvider()
    return _PROVIDER


def send_email(to: str, subject: str, body_text: str) -> bool:
    return get_provider().send(OutgoingEmail(to=to, subject=subject, body_text=body_text))
