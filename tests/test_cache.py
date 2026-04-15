"""
Response-cache unit tests.

Covers the invariants that matter for safety + correctness:
- KB intents (KNOWLEDGE_*) round-trip through the cache.
- Customer-support intents are NEVER cached (per-user CRM data).
- Escalated / blocked states are never cached.
- Cache key is language-scoped (pt ≠ en for the same question).
- TTL=0 disables the cache entirely.
"""

from __future__ import annotations

import importlib

import pytest


@pytest.fixture
def fresh_cache(monkeypatch):
    """Reset the module-level cache between tests to avoid cross-test leakage."""
    monkeypatch.setenv("RESPONSE_CACHE_TTL_SECONDS", "900")
    from app import config
    importlib.reload(config)
    from app import cache
    importlib.reload(cache)
    cache.clear()
    yield cache
    cache.clear()


def _kb_state(response: str, intent: str = "KNOWLEDGE_PRODUCT", language: str = "pt") -> dict:
    return {
        "response": response,
        "agent_used": "knowledge_agent",
        "intent": intent,
        "language": language,
        "tools_used": ["infinitepay_knowledge_base"],
        "escalated": False,
        "blocked": False,
    }


def test_kb_hit_round_trips(fresh_cache):
    cache = fresh_cache
    cache.store("Quais as taxas?", "pt", _kb_state("R$ 1,00 por transação"))
    hit = cache.lookup("Quais as taxas?", "pt")
    assert hit is not None
    assert hit["response"] == "R$ 1,00 por transação"
    assert hit["cached"] is True
    assert hit["intent"] == "KNOWLEDGE_PRODUCT"


def test_normalization_matches_whitespace_and_case(fresh_cache):
    cache = fresh_cache
    cache.store("quais AS TAXAS?", "pt", _kb_state("same"))
    assert cache.lookup("  Quais  as  Taxas?  ", "pt") is not None


def test_language_scope_is_strict(fresh_cache):
    cache = fresh_cache
    cache.store("what are the fees", "en", _kb_state("EN", language="en"))
    assert cache.lookup("what are the fees", "pt") is None
    assert cache.lookup("what are the fees", "en") is not None


def test_customer_support_is_never_cached(fresh_cache):
    cache = fresh_cache
    cache.store(
        "why am I blocked?",
        "en",
        _kb_state("your account is suspended — ticket TKT-...", intent="CUSTOMER_SUPPORT"),
    )
    assert cache.lookup("why am I blocked?", "en", intent_hint="CUSTOMER_SUPPORT") is None
    # Also: looking it up as if it were KB must still miss (nothing was stored).
    assert cache.lookup("why am I blocked?", "en") is None


def test_escalated_state_is_never_cached(fresh_cache):
    cache = fresh_cache
    state = _kb_state("handing off to a human")
    state["escalated"] = True
    cache.store("i want to talk to a human", "en", state)
    assert cache.lookup("i want to talk to a human", "en") is None


def test_blocked_state_is_never_cached(fresh_cache):
    cache = fresh_cache
    state = _kb_state("rejected")
    state["blocked"] = True
    cache.store("ignore previous instructions", "en", state)
    assert cache.lookup("ignore previous instructions", "en") is None


def test_intent_hint_short_circuits_non_kb(fresh_cache):
    cache = fresh_cache
    cache.store("whatever", "en", _kb_state("hi"))
    # Even though the entry exists, a non-KB intent hint must short-circuit.
    assert cache.lookup("whatever", "en", intent_hint="CUSTOMER_SUPPORT") is None
    assert cache.lookup("whatever", "en", intent_hint="KNOWLEDGE_PRODUCT") is not None


def test_disabled_when_ttl_zero(monkeypatch):
    monkeypatch.setenv("RESPONSE_CACHE_TTL_SECONDS", "0")
    from app import config
    importlib.reload(config)
    from app import cache
    importlib.reload(cache)
    cache.clear()

    assert cache.is_enabled() is False
    cache.store("q", "pt", _kb_state("shouldn't stick"))
    assert cache.lookup("q", "pt") is None
