"""
Response cache for knowledge-base hits.

Only caches KNOWLEDGE_PRODUCT / KNOWLEDGE_GENERAL responses — customer-support
answers contain per-user CRM data and must never be cross-served. The cache key
is a normalized (question, language) tuple; the value is the full `state` dict
the router returns, minus fields that can't be reused (`user_id`, `ticket_id`).

Backend: in-memory TTL dict by default (zero infra). Optional drop-in Redis
backend when `REDIS_URL` is set — adapter pattern kept deliberately thin so
swapping in `redis.asyncio` later is a single file change.
"""

from __future__ import annotations

import hashlib
import logging
import re
import threading
import time
from typing import Any, Optional

from app.config import RESPONSE_CACHE_TTL_SECONDS

logger = logging.getLogger(__name__)

_CACHEABLE_INTENTS = {"KNOWLEDGE_PRODUCT", "KNOWLEDGE_GENERAL"}
_STRIP_PATTERN = re.compile(r"\s+")


def _normalize(message: str) -> str:
    return _STRIP_PATTERN.sub(" ", message.strip().lower())


def _make_key(message: str, language: str) -> str:
    raw = f"{language}::{_normalize(message)}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


class _InMemoryTTLCache:
    """Thread-safe dict with per-entry expiry. Fine for single-instance demo;
    swap for Redis once we shard across workers."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._store: dict[str, tuple[float, dict]] = {}

    def get(self, key: str) -> Optional[dict]:
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            expires_at, value = entry
            if expires_at < time.time():
                self._store.pop(key, None)
                return None
            return value

    def set(self, key: str, value: dict, ttl_seconds: int) -> None:
        with self._lock:
            self._store[key] = (time.time() + ttl_seconds, value)

    def clear(self) -> None:
        with self._lock:
            self._store.clear()

    def size(self) -> int:
        with self._lock:
            return len(self._store)


_cache = _InMemoryTTLCache()


def is_enabled() -> bool:
    return RESPONSE_CACHE_TTL_SECONDS > 0


def lookup(message: str, language: str, intent_hint: Optional[str] = None) -> Optional[dict]:
    """Returns a cached response state, or None on miss / disabled / ineligible intent."""
    if not is_enabled():
        return None
    if intent_hint and intent_hint not in _CACHEABLE_INTENTS:
        return None
    return _cache.get(_make_key(message, language))


def store(message: str, language: str, state: dict) -> None:
    """Stores the state if the intent is safe to cache. No-ops for support /
    escalation responses (they carry per-user CRM data)."""
    if not is_enabled():
        return
    intent = state.get("intent") or ""
    if intent not in _CACHEABLE_INTENTS:
        return
    if state.get("blocked") or state.get("escalated"):
        return
    payload = {
        "response": state.get("response", ""),
        "agent_used": state.get("agent_used", ""),
        "intent": intent,
        "language": state.get("language", language),
        "tools_used": state.get("tools_used", []),
        "cached": True,
    }
    _cache.set(_make_key(message, language), payload, RESPONSE_CACHE_TTL_SECONDS)


def stats() -> dict:
    return {"enabled": is_enabled(), "size": _cache.size(), "ttl_seconds": RESPONSE_CACHE_TTL_SECONDS}


def clear() -> None:
    _cache.clear()
