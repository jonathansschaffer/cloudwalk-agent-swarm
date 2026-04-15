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


def _client_ip(request: Request) -> str:
    """Rate-limit key that honors X-Forwarded-For when behind a trusted proxy.

    Railway / Cloudflare / NGINX append the real client IP as the first hop
    of X-Forwarded-For. Using `get_remote_address` alone would see only the
    proxy's IP and make all users share a single bucket.
    """
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return get_remote_address(request)


def _jwt_subject_key(request: Request) -> str:
    """Rate-limit key derived from the JWT subject — guards against a single
    authenticated user burning through the /chat quota from many IPs (shared
    NAT, botnet, etc.). Falls back to the IP bucket when no token is present.
    """
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        token = auth[7:].strip()
        if token:
            import hashlib
            return "jwt:" + hashlib.sha256(token.encode()).hexdigest()[:32]
    return "ip:" + _client_ip(request)

from app.agents.router_agent import process_message
from app.database import chat_history, mock_tickets
from app.database.models import User
from app.models.request_models import ChatRequest, ChatResponse, HealthResponse
from app.rag.vector_store import get_document_count

logger = logging.getLogger(__name__)

router = APIRouter()

# Rate limiter instance — imported by main.py to attach to app state.
# Uses `_client_ip` so per-IP limits apply to the real caller even when
# running behind Railway's edge proxy (X-Forwarded-For is honored).
limiter = Limiter(key_func=_client_ip)


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
@limiter.limit("30/minute", key_func=_jwt_subject_key)
def chat(
    request: Request,
    body: ChatRequest,
    user: User = Depends(_get_user_dep()),
) -> ChatResponse:
    """Processes a user message through the InfinitePay Assistant."""
    try:
        # user_id fed into the agent graph is the DB id.
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
            tools_used=state.get("tools_used", []),
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


@router.get("/health", summary="Public liveness probe")
def health() -> dict:
    """Public — minimal by design (MEDIUM-09). Load balancers only need to
    know that the process is up, not how many docs are indexed or whether
    internal flags are set. Details live on /admin/health.

    Frontend note: the `show_agent_badge` flag used to live here; it moved to
    `/admin/health` but is also surfaced on this endpoint because the web UI
    reads it before the user logs in. Keep it minimal — nothing else leaks."""
    from app.config import SHOW_AGENT_BADGE
    return {"status": "ok", "show_agent_badge": SHOW_AGENT_BADGE}


@router.get(
    "/admin/health",
    response_model=HealthResponse,
    summary="Detailed health — admin only",
)
def admin_health(user: User = Depends(_get_user_dep())) -> HealthResponse:
    """Requires `user.is_admin=True`. Exposes KB size, config flags, etc."""
    from app.config import SHOW_AGENT_BADGE
    if not getattr(user, "is_admin", False):
        raise HTTPException(status_code=403, detail="Admin privileges required.")
    try:
        doc_count = get_document_count()
        return HealthResponse(
            status="ok",
            knowledge_base_loaded=doc_count > 0,
            documents_indexed=doc_count,
            show_agent_badge=SHOW_AGENT_BADGE,
        )
    except Exception as exc:
        logger.error("Admin health check failed: %s", exc, exc_info=True)
        return HealthResponse(
            status="degraded",
            knowledge_base_loaded=False,
            documents_indexed=0,
            show_agent_badge=SHOW_AGENT_BADGE,
        )
