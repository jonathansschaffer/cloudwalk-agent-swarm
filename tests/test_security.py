"""
Security regression tests for the remediations from security-assessment-report.md.

Covers:
  - CRITICAL-01: name field rejects HTML/JS characters
  - CRITICAL-02: /docs, /redoc, /openapi.json disabled when ENABLE_DOCS=false
  - HIGH-04:     account lockout after N consecutive failed logins
  - HIGH-06:     HTML input to /chat is classified as INAPPROPRIATE (no 500)
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.agents import guardrails
from app.main import app


def _unique_email(prefix: str = "sec") -> str:
    return f"{prefix}+{uuid.uuid4().hex[:10]}@example.com"


# ---------------------------------------------------------------------------
# CRITICAL-01 — name sanitization
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "bad_name",
    [
        "<img src=x onerror=alert(1)>",
        "<script>alert(1)</script>",
        "Bob\"; DROP TABLE users;--",
        "Ana & Bia",
        "user@@@",
        "back\\slash",
    ],
)
def test_register_rejects_html_in_name(client, bad_name):
    resp = client.post(
        "/auth/register",
        json={
            "email": _unique_email("xss"),
            "password": "Test123!A",
            "name": bad_name,
            "lgpd_consent": True,
        },
    )
    assert resp.status_code == 422, resp.text


@pytest.mark.parametrize(
    "good_name",
    ["Maria Silva", "João d'Água", "Ana-Lúcia", "José Ramalho Jr."],
)
def test_register_accepts_legitimate_names(client, good_name):
    resp = client.post(
        "/auth/register",
        json={
            "email": _unique_email("ok"),
            "password": "Test123!A",
            "name": good_name,
            "lgpd_consent": True,
        },
    )
    # HIGH-03: register is enumeration-safe and always returns 202 with a
    # generic ack, regardless of whether the email already exists. Anything
    # other than 422 proves the name validator did NOT reject the input.
    assert resp.status_code == 202, resp.text


# ---------------------------------------------------------------------------
# CRITICAL-02 — docs disabled by default
# ---------------------------------------------------------------------------

def test_docs_endpoints_disabled_by_default(client):
    # Default config: ENABLE_DOCS unset → docs off.
    for path in ("/docs", "/redoc", "/openapi.json"):
        resp = client.get(path)
        assert resp.status_code == 404, f"{path} should be disabled (got {resp.status_code})"


# ---------------------------------------------------------------------------
# HIGH-04 — account lockout after N failed logins
# ---------------------------------------------------------------------------

def test_login_locks_account_after_threshold(client):
    # Spread requests across different IPs (X-Forwarded-For) so the
    # per-IP rate limiter doesn't mask the account-level lockout.
    email = _unique_email("lock")
    reg = client.post(
        "/auth/register",
        json={
            "email": email,
            "password": "CorrectHorse42!",
            "name": "Locked User",
            "lgpd_consent": True,
        },
        headers={"X-Forwarded-For": "10.0.0.100"},
    )
    assert reg.status_code == 202, reg.text

    from app.config import LOGIN_LOCKOUT_THRESHOLD

    for i in range(LOGIN_LOCKOUT_THRESHOLD):
        r = client.post(
            "/auth/login",
            json={"email": email, "password": "wrongpass"},
            headers={"X-Forwarded-For": f"10.0.{i // 4}.{100 + (i % 4)}"},
        )
        assert r.status_code == 401, r.text

    r = client.post(
        "/auth/login",
        json={"email": email, "password": "CorrectHorse42!"},
        headers={"X-Forwarded-For": "10.0.9.99"},
    )
    assert r.status_code == 401, "Locked account should reject even correct password"


# ---------------------------------------------------------------------------
# HIGH-06 — guardrail blocks HTML/JS payloads
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "payload",
    [
        "<script>alert(1)</script>",
        "<img src=x onerror=alert(1)>",
        "<svg onload=alert(document.cookie)>",
        "[Click](javascript:alert(1))",
    ],
)
def test_guardrail_blocks_html_payloads(payload):
    """Unit-level check: the regex pre-filter must reject HTML/JS injections
    before the message reaches the LLM classifier or the Anthropic API."""
    result = guardrails.check_input(payload, language="en")
    assert result["safe"] is False, f"Payload should be blocked: {payload!r}"
    assert result["rejection_message"]
