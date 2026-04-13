"""
In-memory chat history store.

Stores conversation turns per user_id so the frontend can reload previous
messages on page refresh or when switching users. Each user's history is
isolated — no user can access another's conversation data.

Limitations (acceptable for demo):
  - History is lost when the server restarts (no persistence layer).
  - Memory bounded by MAX_HISTORY_PER_USER per user (oldest turns dropped).

In production this would be backed by Redis or a database with proper
authentication ensuring users can only read their own history.
"""

import threading
from collections import defaultdict
from datetime import datetime, timezone
from typing import Optional

MAX_HISTORY_PER_USER = 100  # maximum turns stored per user

_store: dict[str, list[dict]] = defaultdict(list)
_lock = threading.Lock()


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
    """
    Appends a completed conversation turn to the user's history.

    Args:
        user_id:      The user's unique identifier.
        user_message: The message the user sent.
        bot_response: The agent's reply.
        agent_used:   Which agent produced the response.
        intent:       Classified intent (e.g. KNOWLEDGE_PRODUCT).
        ticket_id:    Support ticket ID if one was created.
        escalated:    Whether the conversation was escalated to a human.
        language:     Detected language ("pt" or "en").
    """
    turn = {
        "user": user_message,
        "bot": bot_response,
        "agent_used": agent_used,
        "intent": intent,
        "ticket_id": ticket_id,
        "escalated": escalated,
        "language": language,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    with _lock:
        history = _store[user_id]
        history.append(turn)
        if len(history) > MAX_HISTORY_PER_USER:
            history.pop(0)  # drop the oldest turn


def get_history(user_id: str) -> list[dict]:
    """
    Returns a copy of the conversation history for a user.

    Args:
        user_id: The user's unique identifier.

    Returns:
        List of turn dicts, oldest first. Empty list if no history.
    """
    with _lock:
        return list(_store.get(user_id, []))


def clear_history(user_id: str) -> None:
    """Clears all history for a user (useful for testing)."""
    with _lock:
        _store.pop(user_id, None)
