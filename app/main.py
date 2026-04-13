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

Security middleware stack (outermost → innermost):
  SecurityHeadersMiddleware → CORSMiddleware → SlowAPI rate limiting → routes
"""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from app.utils.logger import setup_logging
from app.config import validate_config, TELEGRAM_BOT_TOKEN
from app.api.routes import router, limiter
from app.rag.pipeline import build_knowledge_base

# Configure logging before anything else
setup_logging()
logger = logging.getLogger(__name__)

# Path to the static frontend directory
_STATIC_DIR = Path(__file__).parent / "static"


# ------------------------------------------------------------------ #
# Security Headers Middleware                                          #
# ------------------------------------------------------------------ #

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Adds security headers to every HTTP response."""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
        # Allow scripts from self + cdn.jsdelivr.net (marked.js CDN used by frontend)
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; "
            "connect-src 'self'; "
            "font-src 'self'; "
            "frame-ancestors 'none';"
        )
        return response


# ------------------------------------------------------------------ #
# Lifespan                                                            #
# ------------------------------------------------------------------ #

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manages startup and shutdown of all long-lived resources."""

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

# Attach limiter to app state (required by slowapi)
app.state.limiter = limiter

# Rate limit exceeded handler — returns 429 with a clear message
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Rate limiting middleware
app.add_middleware(SlowAPIMiddleware)

# Security headers on every response
app.add_middleware(SecurityHeadersMiddleware)

# CORS — restrict to same origin for demo; widen for production deployments
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8000", "http://127.0.0.1:8000"],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


# ------------------------------------------------------------------ #
# Frontend — serve the chat UI                                        #
# ------------------------------------------------------------------ #

@app.get("/", include_in_schema=False)
def serve_frontend() -> FileResponse:
    """Serves the web chat interface."""
    return FileResponse(_STATIC_DIR / "index.html")

# Mount remaining static assets (if any future CSS/JS files are added)
if _STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")


# ------------------------------------------------------------------ #
# API routes                                                          #
# ------------------------------------------------------------------ #

app.include_router(router, tags=["Agent Swarm"])
