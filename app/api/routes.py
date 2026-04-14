"""
FastAPI route definitions (authenticated).

Endpoints:
  POST /chat      — sends a message to the InfinitePay Assistant
  GET  /history   — returns the current user's chat history
  GET  /tickets   — returns the current user's support tickets
  GET  /health    — health check and knowledge base stats

All endpoints except /health require a valid Bearer token. The legacy
`/history/{user_id}` is gone — the user id is read from the JWT so users
cannot read anyone else's history.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.agents.router_agent import process_message
from app.database import chat_history, mock_tickets
from app.database.models import User
from app.models.request_models import ChatRequest, ChatResponse, HealthResponse
from app.rag.vector_store import get_document_count

logger = logging.getLogger(__name__)

router = APIRouter()

# Rate limiter instance — imported by main.py to attach to app state
limiter = Limiter(key_func=get_remote_address)


def _get_user_dep():
    """Lazy import to avoid circular imports (auth.routes imports `limiter` from here)."""
    from app.auth.dependencies import get_current_user
    return get_current_user


@router.post(
    "/chat",
    response_model=ChatResponse,
    summary="Send a message to the InfinitePay Assistant",
)
@limiter.limit("20/minute")
def chat(
    request: Request,
    body: ChatRequest,
    user: User = Depends(_get_user_dep()),
) -> ChatResponse:
    """Processes a user message through the InfinitePay Assistant."""
    try:
        # user_id fed into the agent graph is the DB id; legacy_id resolution
        # still works for the seeded demo accounts.
        agent_user_id = str(user.id)

        state = process_message(
            message=body.message,
            user_id=agent_user_id,
        )

        chat_history.append_turn(
            user_id=agent_user_id,
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


@router.get("/history", summary="Get the authenticated user's chat history")
def get_history(user: User = Depends(_get_user_dep())) -> dict:
    return {
        "user_id": user.id,
        "history": chat_history.get_history(str(user.id)),
    }


@router.get("/tickets", summary="List the authenticated user's support tickets")
def list_tickets(user: User = Depends(_get_user_dep())) -> dict:
    return {
        "user_id": user.id,
        "tickets": mock_tickets.list_user_tickets(str(user.id)),
    }


@router.get("/health", response_model=HealthResponse, summary="Health check")
def health() -> HealthResponse:
    """Public — intentionally unauthenticated so load balancers can probe it."""
    try:
        doc_count = get_document_count()
        return HealthResponse(
            status="ok",
            knowledge_base_loaded=doc_count > 0,
            documents_indexed=doc_count,
        )
    except Exception as exc:
        logger.error("Health check failed: %s", exc, exc_info=True)
        return HealthResponse(
            status="degraded",
            knowledge_base_loaded=False,
            documents_indexed=0,
        )
