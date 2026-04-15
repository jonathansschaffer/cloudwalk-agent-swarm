"""
Cloudflare Turnstile verification (free CAPTCHA, no interaction when the risk
score is low). Disabled when `TURNSTILE_SECRET_KEY` is empty — that's the
default in tests and local dev.

The frontend renders the widget with `TURNSTILE_SITE_KEY` (exposed via
/auth/captcha-config) once it sees a login response flagged with
`captcha_required=true`. The resulting token is POSTed back to /auth/login.
"""

from __future__ import annotations

import logging

import httpx

from app.config import TURNSTILE_SECRET_KEY

logger = logging.getLogger(__name__)

_TURNSTILE_VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"


def is_enabled() -> bool:
    return bool(TURNSTILE_SECRET_KEY)


def verify(token: str, remote_ip: str | None = None) -> bool:
    """Returns True iff Cloudflare confirms the token is valid.

    Network failures fall *closed* (return False) because a pass-on-failure
    policy defeats the purpose of the challenge. The caller decides whether
    to raise 401 or 503 based on the return value.
    """
    if not is_enabled():
        return True
    if not token:
        return False

    data = {"secret": TURNSTILE_SECRET_KEY, "response": token}
    if remote_ip:
        data["remoteip"] = remote_ip

    try:
        with httpx.Client(timeout=5.0) as client:
            resp = client.post(_TURNSTILE_VERIFY_URL, data=data)
            resp.raise_for_status()
            body = resp.json()
    except Exception as exc:
        logger.error("Turnstile verification failed: %s", exc)
        return False

    return bool(body.get("success"))
