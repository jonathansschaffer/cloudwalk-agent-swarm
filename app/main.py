"""
FastAPI application entrypoint.
Wires together startup events, middleware, and routes.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.utils.logger import setup_logging
from app.config import validate_config
from app.api.routes import router
from app.rag.pipeline import build_knowledge_base

# Configure logging before anything else
setup_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Runs startup and shutdown logic."""
    # --- Startup ---
    logger.info("=== InfinitePay Agent Swarm Starting Up ===")

    # Validate required configuration (API keys, etc.)
    validate_config()

    # Build knowledge base if not already populated
    logger.info("Checking knowledge base...")
    doc_count = build_knowledge_base(force_rebuild=False)
    if doc_count > 0:
        logger.info("Knowledge base ready with %d documents.", doc_count)
    else:
        logger.warning("Knowledge base is empty! RAG responses may be limited.")

    logger.info("=== Agent Swarm Ready ===")

    yield  # Application runs here

    # --- Shutdown ---
    logger.info("=== Agent Swarm Shutting Down ===")


app = FastAPI(
    title="InfinitePay Agent Swarm",
    description=(
        "A multi-agent AI system for InfinitePay customer support. "
        "Routes user messages to specialized agents: Knowledge (RAG + Web Search), "
        "Customer Support, and Escalation (Human Redirect)."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

# CORS middleware — allows any origin (suitable for development/demo)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register API routes
app.include_router(router, tags=["Agent Swarm"])
