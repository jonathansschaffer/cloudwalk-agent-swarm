"""
FastAPI route definitions.

Endpoints:
  POST /chat          — sends a message through the Agent Swarm
  GET  /health        — health check and knowledge base stats
  GET  /history/{id}  — retrieves chat history for a user (server-side, isolated)
"""

import logging
import re

from fastapi import APIRouter, HTTPException, Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.models.request_models import ChatRequest, ChatResponse, HealthResponse
from app.agents.router_agent import process_message
from app.rag.vector_store import get_document_count
from app.database import chat_history

logger = logging.getLogger(__name__)

router = APIRouter()

# Rate limiter instance — imported by main.py to attach to app state
limiter = Limiter(key_func=get_remote_address)

# Only allow alphanumeric, underscore, hyphen — prevents path traversal and injection
_USER_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_\-]{1,64}$")


@router.post("/chat", response_model=ChatResponse, summary="Send a message to the Agent Swarm")
@limiter.limit("20/minute")
def chat(request: Request, body: ChatRequest) -> ChatResponse:
    """
    Processes a user message through the Agent Swarm and returns a response.

    The swarm will:
    1. Validate user_id format.
    2. Detect the message language.
    3. Run input safety guardrails.
    4. Classify the intent (product question, general question, support, escalation).
    5. Route to the appropriate specialized agent.
    6. Append the turn to the server-side history store.
    7. Return a structured response.
    """
    if not _USER_ID_PATTERN.match(body.user_id):
        raise HTTPException(
            status_code=400,
            detail="Invalid user_id. Use only letters, digits, underscores, or hyphens (max 64 chars).",
        )

    try:
        state = process_message(
            message=body.message,
            user_id=body.user_id,
        )

        # Persist turn to in-memory history store
        chat_history.append_turn(
            user_id=body.user_id,
            user_message=body.message,
            bot_response=state["response"],
            agent_used=state["agent_used"],
            intent=state.get("intent", ""),
            ticket_id=state.get("ticket_id"),
            escalated=state.get("escalated", False),
            language=state.get("language", "en"),
        )

        return ChatResponse(
            response=state["response"],
            agent_used=state["agent_used"],
            intent_detected=state["intent"],
            ticket_id=state.get("ticket_id"),
            escalated=state.get("escalated", False),
            language=state["language"],
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Unexpected error in /chat: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="An internal error occurred. Please try again later.",
        )


@router.get("/history/{user_id}", summary="Get chat history for a user")
def get_history(user_id: str) -> dict:
    """
    Returns the server-side conversation history for a given user.

    History is isolated per user_id — each key returns only that user's turns.
    Returns an empty list if no history exists yet.
    """
    if not _USER_ID_PATTERN.match(user_id):
        raise HTTPException(
            status_code=400,
            detail="Invalid user_id format.",
        )
    return {
        "user_id": user_id,
        "history": chat_history.get_history(user_id),
    }


@router.get("/health", response_model=HealthResponse, summary="Health check")
def health() -> HealthResponse:
    """Returns the health status and knowledge base statistics."""
    try:
        doc_count = get_document_count()
        return HealthResponse(
            status="ok",
            knowledge_base_loaded=doc_count > 0,
            documents_indexed=doc_count,
        )
    except Exception:
        return HealthResponse(
            status="degraded",
            knowledge_base_loaded=False,
            documents_indexed=0,
        )
