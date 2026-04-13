"""
FastAPI route definitions.
Exposes POST /chat for the agent swarm and GET /health for monitoring.
"""

import logging
from fastapi import APIRouter, HTTPException

from app.models.request_models import ChatRequest, ChatResponse, HealthResponse
from app.agents.router_agent import process_message
from app.rag.vector_store import get_document_count

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/chat", response_model=ChatResponse, summary="Send a message to the Agent Swarm")
def chat(request: ChatRequest) -> ChatResponse:
    """
    Processes a user message through the Agent Swarm and returns a response.

    The swarm will:
    1. Detect the message language.
    2. Run input safety guardrails.
    3. Classify the intent (product question, general question, support, escalation).
    4. Route to the appropriate specialized agent.
    5. Return a structured response.
    """
    try:
        state = process_message(
            message=request.message,
            user_id=request.user_id,
        )
        return ChatResponse(
            response=state["response"],
            agent_used=state["agent_used"],
            intent_detected=state["intent"],
            ticket_id=state.get("ticket_id"),
            escalated=state.get("escalated", False),
            language=state["language"],
        )
    except Exception as exc:
        logger.error("Unexpected error in /chat: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="An internal error occurred. Please try again later.",
        )


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
