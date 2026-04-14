# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Local dev (requires Python 3.11+ and a populated venv)
pip install -r requirements.txt
python scripts/build_knowledge_base.py          # one-time: scrapes + indexes into data/chroma_db/
uvicorn app.main:app --reload                   # serves /, /chat, /docs, /health on :8000

# Containerized (first build ~3–5 min: model download + scrape + index)
docker-compose up --build

# Knowledge base maintenance
python scripts/build_knowledge_base.py --rebuild              # wipe + rebuild from cache
python scripts/build_knowledge_base.py --no-cache --rebuild   # re-scrape all 18 URLs

# Tests
pytest tests/ -v                                              # full suite
pytest tests/test_router.py -v                                # single file
pytest tests/test_router.py::test_classify_product_query -v   # single test
python scripts/test_agents.py                                 # manual end-to-end scenario run
```

**Required env:** `ANTHROPIC_API_KEY`, `JWT_SECRET` (≥ 32 random bytes in production).
**Optional env:** `TELEGRAM_BOT_TOKEN` (bot silently disabled if absent), `DATABASE_URL` (defaults to local SQLite at `data/app.db`; use `postgresql+psycopg2://…` in prod), `MOCK_USER_PASSWORD` (default `Test123!`), `SEED_MOCK_USERS` (default `true`), `ALLOWED_ORIGINS`, `CHROMA_DB_PATH`, `COLLECTION_NAME`.

**Telegram modes** (mutually exclusive — pick one per environment):
- **Webhook (Railway/prod):** set `TELEGRAM_WEBHOOK_URL=https://your-app.railway.app`. Bot registers `POST /telegram/webhook` with Telegram on startup and returns immediately — Railway healthcheck succeeds. Optionally set `TELEGRAM_WEBHOOK_SECRET` (any 256-char alphanumeric string) to authenticate incoming Telegram requests.
- **Long-polling (local dev):** leave `TELEGRAM_WEBHOOK_URL` empty; set `TELEGRAM_POLLING_ENABLED=true` (default). Only ONE poller per token — set `TELEGRAM_POLLING_ENABLED=false` locally when Railway is already polling.
- The lifespan is non-blocking in both modes: webhook startup is a fast HTTP call; polling is wrapped in `asyncio.create_task`.

## Architecture

The system is a FastAPI app that routes each message through a **LangGraph `StateGraph`** to one of four specialized agents. Understanding the graph is the key to understanding the codebase.

**Request flow:** `app/main.py` (FastAPI lifespan: `init_db()` → seed mock users → load RAG → start Telegram bot; installs slowapi limiter, security headers, request-timing middleware) → `app/auth/dependencies.get_current_user` (resolves JWT from `Authorization: Bearer …`) → `app/api/routes.py` (writes to `chat_history`, scopes `/history` and `/tickets` to the JWT user) → `app/agents/router_agent.py` (the graph).

**The graph** ([app/agents/router_agent.py](app/agents/router_agent.py)) owns the control flow. Nodes read/write a single `AgentState` TypedDict (`message`, `user_id`, `language`, `intent`, `response`, `agent_used`, `ticket_id`, `escalated`, `blocked`, `investigation_summary`). Edges:

```
START → guardrails_node → router_node → {knowledge | support | escalation | rejection} → END
support_node may also conditionally transition into escalation_node when escalated=True.
```

To add an agent, add a node function in `router_agent.py` and wire it into the `StateGraph` — do *not* call new agents from `routes.py`.

**Specialized agents** (all in `app/agents/`):
- `knowledge_agent.py` — LangChain ReAct agent with two tools: `rag_tool` (ChromaDB) and `search_tool` (DuckDuckGo).
- `support_agent.py` — LangChain ReAct agent with three custom tools in `app/tools/account_tools.py`, all backed by the mock CRM.
- `escalation_agent.py` — direct Claude call, creates a mock ticket.
- `guardrails.py` — **two-sided**: input blocking (regex + Claude classifier for prompt injection/abuse, both EN and PT variants) AND output PII sanitization (CPF, card numbers, phone, email). Changes to PII rules must update both sides.

**RAG pipeline** ([app/rag/](app/rag/)): `scraper.py` → `chunker.py` (RecursiveCharacterTextSplitter, 800/100) → `embedder.py` (`all-MiniLM-L6-v2`, local, multilingual) → `vector_store.py` (ChromaDB, persisted under `data/chroma_db/`). `pipeline.py` orchestrates building; `scripts/build_knowledge_base.py` is the CLI entry.

**Persistence (PostgreSQL via SQLAlchemy 2.0; SQLite fallback for local dev):**
- Schema lives in [app/database/models.py](app/database/models.py): `users` (auth identity + inline CRM profile + LGPD consent), `transactions`, `tickets`, `chat_messages`, `telegram_links`, `telegram_link_codes`. All FKs declared `ON DELETE CASCADE` so `DELETE /auth/me` truly erases everything (LGPD right-to-erasure).
- [app/database/chat_history.py](app/database/chat_history.py), [app/database/mock_tickets.py](app/database/mock_tickets.py), and [app/database/mock_users.py](app/database/mock_users.py) are now thin DB-backed services that accept either the DB id (`"42"`) or the legacy slug (`"client789"`) — `_resolve_user_id` handles both.
- The 5 demo fixtures used by every support scenario are seeded idempotently by [app/database/seed.py](app/database/seed.py) on every startup: `client789` (active), `user_002` (suspended), `user_003` (pending KYC), `user_004` (limit exhausted), `user_005` (risk signals). All share `MOCK_USER_PASSWORD` (default `Test123!`). Tests and `scripts/test_agents.py` depend on these legacy IDs.

**Authentication ([app/auth/](app/auth/)):**
- All routes except `GET /health` and `GET /` (frontend) require a valid bearer token.
- `POST /auth/register` requires explicit LGPD consent (`lgpd_consent`); `POST /auth/login` returns a generic 401 to prevent user enumeration; both rate-limited to `5/min` per IP.
- `POST /auth/telegram/code` mints a one-shot 6-char code (10-min TTL) consumed by the Telegram `/link <code>` handler. Unlinked Telegram accounts are rejected at message receipt.
- The frontend has no user switcher — the JWT subject is the only source of identity.

**Language handling:** `app/utils/language_detector.py` runs once per request in `router_agent.process_message`, stored on `AgentState["language"]`. The Knowledge and Support agents inject an explicit `[Respond strictly in <Language>]` directive into the user-message prefix — this is the source of truth, *not* the (vaguer) system-prompt rule. The Escalation prompt also uses the full language name (`Brazilian Portuguese` / `English`) for the same reason.

**Reliability patterns:**
- Agent `invoke()` calls are wrapped with `tenacity` (3 retries, exponential backoff 2–10s) for transient Anthropic errors.
- The Telegram bot ([app/integrations/telegram_bot.py](app/integrations/telegram_bot.py)) runs in long polling mode and processes messages through a **single-threaded executor** — intentionally serialized to avoid concurrent Anthropic calls. Do not parallelize it.
