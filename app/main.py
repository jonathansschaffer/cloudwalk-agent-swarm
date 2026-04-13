"""
FastAPI application entrypoint.

Wires together startup/shutdown events, middleware, API routes,
static file serving (frontend chat UI), and the optional Telegram bot.

Startup sequence:
  1. Validate required environment variables (API keys)
  2. Build RAG knowledge base if not already populated
  3. Start Telegram bot (if TELEGRAM_BOT_TOKEN is set)
  4. Serve until shutdown signal received
  5. Gracefully stop Telegram bot on shutdown
"""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.utils.logger import setup_logging
from app.config import validate_config, TELEGRAM_BOT_TOKEN
from app.api.routes import router
from app.rag.pipeline import build_knowledge_base

# Configure logging before anything else
setup_logging()
logger = logging.getLogger(__name__)

# Path to the static frontend directory
_STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manages startup and shutdown of all long-lived resources."""

    # ------------------------------------------------------------------ #
    # Startup                                                              #
    # ------------------------------------------------------------------ #
    logger.info("=== InfinitePay Agent Swarm Starting Up ===")

    # Validate required configuration (raises on missing ANTHROPIC_API_KEY)
    validate_config()

    # Build vector knowledge base if not already populated
    logger.info("Checking knowledge base...")
    doc_count = build_knowledge_base(force_rebuild=False)
    if doc_count > 0:
        logger.info("Knowledge base ready with %d documents.", doc_count)
    else:
        logger.warning("Knowledge base is empty — RAG responses may be limited.")

    # Start Telegram bot (optional — only if token is configured)
    tg_app = None
    if TELEGRAM_BOT_TOKEN:
        try:
            from app.integrations.telegram_bot import build_application
            tg_app = build_application(TELEGRAM_BOT_TOKEN)
            await tg_app.initialize()
            await tg_app.start()
            await tg_app.updater.start_polling()
            logger.info("Telegram bot started (long polling).")
        except Exception as exc:
            logger.error("Failed to start Telegram bot: %s", exc)
            tg_app = None
    else:
        logger.info("TELEGRAM_BOT_TOKEN not set — Telegram bot disabled.")

    logger.info("=== Agent Swarm Ready ===")

    yield  # Application serves requests here

    # ------------------------------------------------------------------ #
    # Shutdown                                                             #
    # ------------------------------------------------------------------ #
    logger.info("=== Agent Swarm Shutting Down ===")

    if tg_app is not None:
        try:
            await tg_app.updater.stop()
            await tg_app.stop()
            await tg_app.shutdown()
            logger.info("Telegram bot stopped.")
        except Exception as exc:
            logger.error("Error stopping Telegram bot: %s", exc)


# ------------------------------------------------------------------ #
# FastAPI application                                                  #
# ------------------------------------------------------------------ #

app = FastAPI(
    title="InfinitePay Agent Swarm",
    description=(
        "A multi-agent AI system for InfinitePay customer support. "
        "Routes user messages to specialized agents: Knowledge (RAG + Web Search), "
        "Customer Support, and Escalation (Human Redirect). "
        "Also exposes a web chat UI at / and an optional Telegram bot."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

# CORS — allow all origins (suitable for development and demo)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ------------------------------------------------------------------ #
# Frontend — serve the chat UI                                         #
# ------------------------------------------------------------------ #

@app.get("/", include_in_schema=False)
def serve_frontend() -> FileResponse:
    """Serves the web chat interface."""
    return FileResponse(_STATIC_DIR / "index.html")

# Mount remaining static assets (if any future CSS/JS files are added)
if _STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")

# ------------------------------------------------------------------ #
# API routes                                                           #
# ------------------------------------------------------------------ #

app.include_router(router, tags=["Agent Swarm"])
