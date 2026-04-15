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
import time
from contextlib import asynccontextmanager
from pathlib import Path
from threading import Lock

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from app.utils.logger import setup_logging
from app.config import (
    validate_config,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_POLLING_ENABLED,
    TELEGRAM_WEBHOOK_URL,
    TELEGRAM_WEBHOOK_SECRET,
    ALLOWED_ORIGINS,
    ENABLE_DOCS,
)
from app.api.routes import router, limiter
from app.auth.routes import router as auth_router
from app.database.db import SessionLocal, init_db
from app.database.seed import seed_mock_users
from app.rag.pipeline import build_knowledge_base

# Configure logging before anything else
setup_logging()
logger = logging.getLogger(__name__)

# Path to the static frontend directory
_STATIC_DIR = Path(__file__).parent / "static"


# ------------------------------------------------------------------ #
# Security Headers Middleware                                          #
# ------------------------------------------------------------------ #

class MetricsMiddleware(BaseHTTPMiddleware):
    """Times every HTTP request, emits a structured log line, and feeds counters."""

    async def dispatch(self, request: Request, call_next):
        start = time.monotonic()
        try:
            response = await call_next(request)
            status = response.status_code
        except Exception:
            METRICS.record(request.method, request.url.path, 500, time.monotonic() - start)
            raise
        latency_ms = (time.monotonic() - start) * 1000.0
        METRICS.record(request.method, request.url.path, status, latency_ms / 1000.0)
        if not request.url.path.startswith(("/static", "/docs", "/openapi", "/favicon")):
            logger.info(
                "http %s %s status=%d latency_ms=%.1f",
                request.method, request.url.path, status, latency_ms,
            )
        return response


class _Metrics:
    """Thread-safe in-memory counters and latency aggregates per (method, path, status)."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._counters: dict[tuple[str, str, int], int] = {}
        self._latency_sum: dict[tuple[str, str, int], float] = {}

    def record(self, method: str, path: str, status: int, latency_seconds: float) -> None:
        key = (method, path, status)
        with self._lock:
            self._counters[key] = self._counters.get(key, 0) + 1
            self._latency_sum[key] = self._latency_sum.get(key, 0.0) + latency_seconds

    def snapshot(self) -> list[dict]:
        with self._lock:
            return [
                {
                    "method": k[0],
                    "path": k[1],
                    "status": k[2],
                    "count": v,
                    "avg_latency_ms": (self._latency_sum[k] / v) * 1000.0,
                }
                for k, v in self._counters.items()
            ]

    def prometheus(self) -> str:
        """Render counters in Prometheus text exposition format (v0.0.4)."""
        def esc(v: str) -> str:
            return v.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")

        lines: list[str] = [
            "# HELP http_requests_total Total HTTP requests received.",
            "# TYPE http_requests_total counter",
        ]
        with self._lock:
            counters = dict(self._counters)
            latency_sum = dict(self._latency_sum)
        for (method, path, status), count in counters.items():
            labels = f'method="{esc(method)}",path="{esc(path)}",status="{status}"'
            lines.append(f"http_requests_total{{{labels}}} {count}")
        lines += [
            "# HELP http_request_duration_seconds_sum Sum of request latencies in seconds.",
            "# TYPE http_request_duration_seconds_sum counter",
        ]
        for key, total in latency_sum.items():
            method, path, status = key
            labels = f'method="{esc(method)}",path="{esc(path)}",status="{status}"'
            lines.append(f"http_request_duration_seconds_sum{{{labels}}} {total}")
        lines += [
            "# HELP http_request_duration_seconds_count Observation count matching _sum.",
            "# TYPE http_request_duration_seconds_count counter",
        ]
        for key, count in counters.items():
            method, path, status = key
            labels = f'method="{esc(method)}",path="{esc(path)}",status="{status}"'
            lines.append(f"http_request_duration_seconds_count{{{labels}}} {count}")
        return "\n".join(lines) + "\n"


METRICS = _Metrics()


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Adds security headers to every HTTP response."""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
        # HSTS: only meaningful over HTTPS. Railway / production terminates TLS
        # at the edge, so forwards X-Forwarded-Proto=https. Skip the header in
        # local dev (plain HTTP) to avoid poisoning the browser cache with a
        # preload pin for 127.0.0.1.
        if request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https":
            response.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains; preload"
            )
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

    # Initialize database schema + seed mock users on first run
    init_db()
    with SessionLocal() as db:
        seed_mock_users(db)

    # Build vector knowledge base if not already populated
    logger.info("Checking knowledge base...")
    doc_count = build_knowledge_base(force_rebuild=False)
    if doc_count > 0:
        logger.info("Knowledge base ready with %d documents.", doc_count)
    else:
        logger.warning("Knowledge base is empty — RAG responses may be limited.")

    # ------------------------------------------------------------------ #
    # Telegram bot — webhook mode (prod) or long-polling (local dev)     #
    # ------------------------------------------------------------------ #
    # Webhook mode: set TELEGRAM_WEBHOOK_URL=https://your-app.railway.app
    #   → bot registers POST /telegram/webhook with Telegram and returns
    #     immediately; no blocking, healthcheck always succeeds.
    # Polling mode: leave TELEGRAM_WEBHOOK_URL empty and ensure only ONE
    #   instance is polling (set TELEGRAM_POLLING_ENABLED=false on others).
    tg_app = None
    _tg_webhook_mode = False

    if not TELEGRAM_BOT_TOKEN:
        logger.info("TELEGRAM_BOT_TOKEN not set — Telegram bot disabled.")
    elif TELEGRAM_WEBHOOK_URL:
        # ── Webhook mode ────────────────────────────────────────────────
        try:
            from app.integrations.telegram_bot import build_application
            tg_app = build_application(TELEGRAM_BOT_TOKEN)
            await tg_app.initialize()
            webhook_endpoint = f"{TELEGRAM_WEBHOOK_URL}/telegram/webhook"
            secret = TELEGRAM_WEBHOOK_SECRET or None
            await tg_app.bot.set_webhook(
                url=webhook_endpoint,
                secret_token=secret,
                allowed_updates=["message", "callback_query"],
            )
            _tg_webhook_mode = True
            logger.info("Telegram bot registered webhook: %s", webhook_endpoint)
        except Exception as exc:
            logger.error("Failed to register Telegram webhook: %s", exc)
            tg_app = None
    elif TELEGRAM_POLLING_ENABLED:
        # ── Long-polling mode (background task — non-blocking) ──────────
        try:
            import asyncio as _asyncio
            from app.integrations.telegram_bot import build_application
            tg_app = build_application(TELEGRAM_BOT_TOKEN)

            async def _run_polling():
                try:
                    await tg_app.initialize()
                    await tg_app.start()
                    await tg_app.updater.start_polling()
                    logger.info("Telegram bot started (long polling).")
                except Exception as _exc:
                    logger.error("Telegram polling error: %s", _exc)

            _asyncio.create_task(_run_polling())
        except Exception as exc:
            logger.error("Failed to schedule Telegram polling task: %s", exc)
            tg_app = None
    else:
        logger.info(
            "TELEGRAM_BOT_TOKEN is set but TELEGRAM_POLLING_ENABLED=false "
            "and TELEGRAM_WEBHOOK_URL is empty — bot disabled."
        )

    # Store reference on app.state so the webhook route can reach it.
    app.state.tg_app = tg_app
    app.state.tg_webhook_mode = _tg_webhook_mode

    logger.info("=== Agent Swarm Ready ===")

    yield  # Application serves requests here

    logger.info("=== Agent Swarm Shutting Down ===")

    if tg_app is not None:
        try:
            if _tg_webhook_mode:
                await tg_app.bot.delete_webhook()
                await tg_app.shutdown()
            else:
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
    title="InfinitePay Assistant",
    description=(
        "AI-powered customer support assistant for InfinitePay. "
        "Routes user messages to specialized agents: Knowledge (RAG + Web Search), "
        "Customer Support, and Human Escalation. "
        "Also exposes a web chat UI at / and an optional Telegram bot."
    ),
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs" if ENABLE_DOCS else None,
    redoc_url="/redoc" if ENABLE_DOCS else None,
    openapi_url="/openapi.json" if ENABLE_DOCS else None,
)

# Attach limiter to app state (required by slowapi)
app.state.limiter = limiter

# Rate limit exceeded handler — returns 429 with a clear message
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Rate limiting middleware
app.add_middleware(SlowAPIMiddleware)

# Security headers on every response
app.add_middleware(SecurityHeadersMiddleware)

# Request timing + counters (outermost so it sees the full latency)
app.add_middleware(MetricsMiddleware)

# CORS — configured via ALLOWED_ORIGINS env variable (defaults to localhost only)
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Content-Type", "Authorization"],
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

app.include_router(router, tags=["InfinitePay Assistant"])
app.include_router(auth_router)


# ------------------------------------------------------------------ #
# Telegram webhook endpoint                                            #
# ------------------------------------------------------------------ #

@app.post("/telegram/webhook", include_in_schema=False)
async def telegram_webhook(request: Request) -> JSONResponse:
    """
    Receives Telegram updates when running in webhook mode.

    Telegram sends a POST request with the update JSON payload to this URL.
    If TELEGRAM_WEBHOOK_SECRET is configured, the request is authenticated
    via the X-Telegram-Bot-Api-Secret-Token header.
    """
    tg = getattr(app.state, "tg_app", None)
    if tg is None:
        return JSONResponse({"ok": False, "error": "Bot not initialised"}, status_code=503)

    # Validate optional secret token
    if TELEGRAM_WEBHOOK_SECRET:
        incoming_secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if incoming_secret != TELEGRAM_WEBHOOK_SECRET:
            logger.warning("Telegram webhook: invalid secret token from %s", request.client)
            return JSONResponse({"ok": False, "error": "Unauthorized"}, status_code=401)

    try:
        data = await request.json()
        from telegram import Update
        update = Update.de_json(data, tg.bot)
        await tg.process_update(update)
    except Exception as exc:
        logger.error("Telegram webhook processing error: %s", exc, exc_info=True)
        # Still return 200 so Telegram does not retry endlessly
        return JSONResponse({"ok": False, "error": str(exc)})

    return JSONResponse({"ok": True})


# ------------------------------------------------------------------ #
# Metrics endpoint                                                     #
# ------------------------------------------------------------------ #

@app.get("/metrics", include_in_schema=False)
def metrics(request: Request):
    """Prometheus exposition (default) or JSON snapshot with ?format=json."""
    if request.query_params.get("format") == "json":
        return JSONResponse({"requests": METRICS.snapshot()})
    from fastapi.responses import PlainTextResponse
    return PlainTextResponse(
        METRICS.prometheus(),
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )
