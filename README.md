# InfinitePay Agent Swarm

![Python](https://img.shields.io/badge/Python-3.11-3776AB?style=flat-square&logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?style=flat-square&logo=fastapi&logoColor=white)
![LangGraph](https://img.shields.io/badge/LangGraph-1.0-FF6B35?style=flat-square)
![LangChain](https://img.shields.io/badge/LangChain-0.3-1C3C3C?style=flat-square)
![Claude](https://img.shields.io/badge/Claude-Sonnet_4.6-CC785C?style=flat-square)
![ChromaDB](https://img.shields.io/badge/ChromaDB-0.5-E8613C?style=flat-square)
![Docker](https://img.shields.io/badge/Docker-Ready-2496ED?style=flat-square&logo=docker&logoColor=white)

> A multi-agent AI system for InfinitePay customer support. Automatically routes messages to the right specialized agent, with RAG, web search, CRM tools, human escalation, and a Telegram bot.

---

## Available Interfaces

| Interface | URL / Access | Description |
|---|---|---|
| 🌐 **Web Chat** | `http://localhost:8000/` | Full-featured chat UI with history |
| 🤖 **REST API** | `http://localhost:8000/chat` | JSON endpoint for integrations |
| 📖 **Swagger UI** | `http://localhost:8000/docs` | Interactive API documentation |
| 💬 **Telegram Bot** | http://t.me/CloudWalk_Challenge_Bot | Chat via the Telegram app |

---

## Architecture

The system is composed of **4 specialized agents** orchestrated by a LangGraph `StateGraph`:

```
┌─────────────────────────────────────────────────────────────────────┐
│                     POST /chat  or  Telegram Bot                    │
│                  {"message": "...", "user_id": "..."}               │
└─────────────────────────────┬───────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│                     ROUTER AGENT  (LangGraph)                       │
│                                                                     │
│   ① Guardrails Node  ──► blocks prompt injection and abuse          │
│           │ SAFE                                                    │
│   ② Router Node      ──► Claude classifies the intent              │
│           │                                                         │
│     ┌─────┴───────┬────────────────┬──────────────┐                │
│     │             │                │              │                 │
│ KNOWLEDGE_    KNOWLEDGE_      CUSTOMER_      ESCALATION /           │
│  PRODUCT       GENERAL        SUPPORT       INAPPROPRIATE           │
│     │             │                │              │                 │
│     ▼             ▼                ▼              ▼                 │
│ ┌─────────┐  ┌─────────┐  ┌──────────────┐  ┌──────────────┐      │
│ │Knowledge│  │Knowledge│  │   Support    │  │  Escalation  │      │
│ │ Agent   │  │ Agent   │  │   Agent      │  │   Agent      │      │
│ │ (RAG)   │  │(Search) │  │  (3 tools)   │  │ (4th agent)  │      │
│ └────┬────┘  └────┬────┘  └──────┬───────┘  └──────────────┘      │
│      │            │              │ ESCALATED?                      │
│      │            │              ├──► YES ──► Escalation Agent     │
│      │            │              │ NO                              │
│      └────────────┴──────────────┴──► Output guardrails            │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
                       ChatResponse JSON
```

### Agent Descriptions

| Agent | Responsibility | Technology |
|---|---|---|
| **Router Agent** | Entry point: classifies intent and orchestrates the flow | LangGraph StateGraph + Claude |
| **Knowledge Agent** | Answers product questions (RAG) and general questions (web search) | LangChain ReAct + ChromaDB + DuckDuckGo |
| **Support Agent** | Diagnoses and resolves account issues using CRM tools | LangChain ReAct + 3 custom tools |
| **Escalation Agent** | Redirects complex issues to human support with full context | Claude direct + mock ticket system |

### Guardrails

- **Input**: Detects and blocks prompt injection (regex + Portuguese variants), offensive content (Claude classifier), XSS attempts, and system abuse
- **Output**: Sanitizes responses to prevent PII leakage (CPF, card numbers, phone numbers, emails)

---

## RAG Pipeline

The Knowledge Agent uses Retrieval-Augmented Generation (RAG) to answer questions based on real InfinitePay content.

```
 ┌────────────┐    ┌─────────────┐    ┌───────────────────┐
 │  SCRAPING  │ ─► │  CHUNKING   │ ─► │    EMBEDDING      │
 │            │    │             │    │                   │
 │ BeautifulS │    │ Recursive   │    │ all-MiniLM-L6-v2  │
 │ oup scrapes│    │ CharText    │    │ (local, free,     │
 │ 18 URLs    │    │ Splitter    │    │  multilingual)    │
 │ from IP    │    │ 800 chars / │    │ → 384-dim vector  │
 │            │    │ 100 overlap │    │   per chunk       │
 └────────────┘    └─────────────┘    └────────┬──────────┘
                                               │
 ┌─────────────────────────────────────────────┘
 │
 ▼
 ┌─────────────────┐    ┌────────────────────────────────────┐
 │    STORAGE      │    │       RETRIEVAL + GENERATION       │
 │                 │    │                                    │
 │   ChromaDB      │ ◄─►│  Query → embedding → top-5        │
 │   (local,       │    │  chunks by cosine similarity →    │
 │   persistent)   │    │  injected into Claude prompt →    │
 │  data/chroma_db/│    │  grounded response                │
 └─────────────────┘    └────────────────────────────────────┘
```

### Knowledge Sources (18 pages)

| URL | Content |
|---|---|
| `infinitepay.io` | Overview / Homepage |
| `/maquininha` | Maquininha Smart (card reader) |
| `/maquininha-celular` | Phone as card reader |
| `/tap-to-pay` | Tap to Pay |
| `/pdv` | Point of Sale (POS) |
| `/receba-na-hora` | Instant settlement |
| `/gestao-de-cobranca` | Collections management |
| `/link-de-pagamento` | Payment link |
| `/loja-online` | Online store |
| `/boleto` | Bank slip (boleto) |
| `/conta-digital` | Personal digital account |
| `/conta-pj` | Business digital account |
| `/pix` | PIX instant payments |
| `/pix-parcelado` | Installment PIX |
| `/emprestimo` | Loans |
| `/cartao` | InfinitePay card |
| `/rendimento` | Account yield |
| `/gestao-de-cobranca-2` | Collections management (v2) |

---

## Tech Stack

| Component | Technology | Rationale |
|---|---|---|
| Language | Python 3.11 | Best AI ecosystem support |
| API Framework | FastAPI | Modern, async, auto-docs |
| Agent Orchestration | LangGraph + LangChain | Industry standard for agentic systems |
| LLM | Claude Sonnet 4.6 (Anthropic) | Excellent at Portuguese, tool use, and reasoning |
| Embeddings | sentence-transformers (all-MiniLM-L6-v2) | Free, local, multilingual |
| Vector Store | ChromaDB | Simple, local, persistent, no external server |
| Web Scraping | BeautifulSoup4 + requests | Reliable HTML parser |
| Web Search | DuckDuckGo (ddgs) | Free, no API key required |
| Language Detection | langdetect | Lightweight, detects PT-BR vs EN |
| Telegram Bot | python-telegram-bot v21 | Native asyncio, most mature library |
| Rate Limiting | slowapi (X-Forwarded-For aware) | Per-IP throttling + account-level login lockout |
| Retry Logic | tenacity | Exponential backoff on API failures |
| Containerization | Docker + docker-compose | One-command deployment |

---

## Prerequisites

- **Docker Desktop** (recommended) → [docker.com](https://www.docker.com/products/docker-desktop/)
- **OR** Python 3.11+ for local development
- **Anthropic API Key** → [console.anthropic.com](https://console.anthropic.com)
- **Telegram Bot Token** *(optional)* → create a bot via [@BotFather](https://t.me/botfather) on Telegram

---

## Quick Start with Docker

```bash
# 1. Clone the repository
git clone https://github.com/jonathansschaffer/cloudwalk-agent-swarm.git
cd cloudwalk-agent-swarm

# 2. Configure environment variables
cp .env.example .env
# Edit .env and fill in ANTHROPIC_API_KEY (and optionally TELEGRAM_BOT_TOKEN)

# 3. Start the container
docker-compose up --build
# First run (~3-5 min): downloads the embedding model, scrapes pages, and indexes vectors.
# Subsequent runs are near-instant (data persisted in ./data/).

# 4. Verify it is running
curl http://localhost:8000/health
# {"status":"ok","knowledge_base_loaded":true,"documents_indexed":225}

# 5. Open the chat in your browser
open http://localhost:8000
```

---

## Local Development (without Docker)

```bash
# 1. Create a virtual environment
python -m venv venv
source venv/bin/activate       # Linux/Mac
venv\Scripts\activate          # Windows

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure environment variables
cp .env.example .env
# Edit .env and add your ANTHROPIC_API_KEY

# 4. Build the knowledge base (one-time)
python scripts/build_knowledge_base.py

# 5. Start the server
uvicorn app.main:app --reload

# Available interfaces:
#   http://localhost:8000/        ← Web Chat
#   http://localhost:8000/docs    ← Swagger UI
#   http://localhost:8000/health  ← Health check
```

---

## Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `ANTHROPIC_API_KEY` | ✅ Yes | — | Anthropic API key for the LLM |
| `TELEGRAM_BOT_TOKEN` | ❌ No | — | Telegram bot token (from @BotFather) |
| `CHROMA_DB_PATH` | ❌ No | `./data/chroma_db` | Where ChromaDB persists vectors |
| `SCRAPED_CACHE_PATH` | ❌ No | `./data/scraped_cache` | Cache for scraped content |
| `COLLECTION_NAME` | ❌ No | `infinitepay_knowledge` | ChromaDB collection name |
| `LOG_LEVEL` | ❌ No | `INFO` | Log verbosity (DEBUG / INFO / WARNING / ERROR) |
| `ENABLE_DOCS` | ❌ No | `false` | Enable `/docs`, `/redoc`, `/openapi.json` (keep `false` in prod) |
| `LOGIN_LOCKOUT_THRESHOLD` | ❌ No | `10` | Consecutive failed logins that lock an account |

---

## Telegram Bot

The Telegram bot integrates directly with the Agent Swarm, sharing the same intelligence and features as the REST API.

> ✅ **Token already configured in `.env`** — just start the server and the bot comes online automatically.

### How to use

```bash
# 1. Start the server normally
uvicorn app.main:app --reload
# Or with Docker: docker-compose up

# 2. Open Telegram and search for: @CloudWalk_Challenge_Bot
# 3. Send /start to begin
```

> 💬 **Bot available at:** [t.me/CloudWalk\_Challenge\_Bot](https://t.me/CloudWalk_Challenge_Bot)

### Available commands

| Command | Description |
|---|---|
| `/start` | Welcome message |
| `/help` | Example questions by category |
| *(any text)* | Processed by the Agent Swarm |

### Creating your own bot (for other environments)

```bash
# 1. Open Telegram and message @BotFather
# 2. Send /newbot, set a name and username
# 3. Copy the generated token and add it to .env:
TELEGRAM_BOT_TOKEN=your_token_here
# 4. Restart the server
```

### How it works

- The bot runs in **long polling** mode — no public URL or HTTPS required
- It is **optional**: if `TELEGRAM_BOT_TOKEN` is not set, the server starts normally without the bot
- The Telegram user ID is mapped as `tg_{telegram_id}` in the internal system
- Messages are processed sequentially (single-threaded executor) to prevent concurrent API calls

---

## API Reference

### POST `/chat`

Sends a message to the Agent Swarm and returns a structured response.

**Request:**

```json
{
  "message": "What are the rates for the Maquininha Smart?",
  "user_id": "client789"
}
```

**Response:**

```json
{
  "response": "The Maquininha Smart rates vary based on your monthly revenue...",
  "agent_used": "knowledge_agent",
  "intent_detected": "KNOWLEDGE_PRODUCT",
  "ticket_id": null,
  "escalated": false,
  "language": "en"
}
```

**Response fields:**

| Field | Type | Description |
|---|---|---|
| `response` | `string` | Agent response text (supports Markdown) |
| `agent_used` | `string` | Which agent replied (`knowledge_agent`, `support_agent`, `escalation_agent`, `guardrails`) |
| `intent_detected` | `string` | Classified intent (`KNOWLEDGE_PRODUCT`, `KNOWLEDGE_GENERAL`, `CUSTOMER_SUPPORT`, `ESCALATION`, `INAPPROPRIATE`) |
| `ticket_id` | `string \| null` | Created ticket ID, if applicable (e.g. `TKT-20260413-A1B2C3`) |
| `escalated` | `boolean` | Whether the conversation was escalated to human support |
| `language` | `string` | Detected message language (`pt` or `en`) |

### GET `/history/{user_id}`

Returns the server-side conversation history for a user. History is isolated per `user_id`.

```bash
curl http://localhost:8000/history/client789
```

```json
{
  "user_id": "client789",
  "history": [
    {
      "user": "What are the Maquininha fees?",
      "bot": "The Maquininha Smart rates...",
      "agent_used": "knowledge_agent",
      "timestamp": "2026-04-13T19:00:00+00:00"
    }
  ]
}
```

### GET `/health`

```bash
curl http://localhost:8000/health
```

```json
{
  "status": "ok",
  "knowledge_base_loaded": true,
  "documents_indexed": 225
}
```

### curl Examples

```bash
# Product question (RAG)
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "What are the rates for debit and credit card?", "user_id": "client789"}'

# General question (web search)
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "What was the last Santos FC match result?", "user_id": "client789"}'

# Account issue (support)
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "I cannot make transfers from my account", "user_id": "client789"}'

# Suspended account
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Não consigo fazer login", "user_id": "user_002"}'

# Human escalation
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "I want to speak with a human agent", "user_id": "client789"}'
```

---

## Mock Test Users (CRM)

The system includes 5 simulated users to demonstrate different support scenarios. They are seeded idempotently on every startup and come pre-verified (`email_verified=true`) so they can log in without going through the email flow.

| Email | Name | Status | Test scenario |
|---|---|---|---|
| `carlos.andrade@infinitepay.test` | Carlos Andrade | ✅ Active | Healthy account — product questions or transfers |
| `maria.souza@infinitepay.test` | Maria Souza | 🔴 Suspended | KYC not verified, 6 failed logins → ticket created |
| `joao.silva@infinitepay.test` | João Silva | 🟡 Pending KYC | New account, identity verification pending |
| `ana.lima@infinitepay.test` | Ana Lima | 🟡 Active | Enterprise plan, daily transfer limit exhausted |
| `pedro.costa@infinitepay.test` | Pedro Costa | 🟠 Active | 2 failed logins, recent failed transaction |

**Password:** shared across all 5 accounts and read from the `MOCK_USER_PASSWORD` env var at startup (default in `.env.example`). It is deliberately **not** printed in this README — see `.env.example` or your Railway variables panel. Rotate it away from the default before any external testing. Accounts use the `.test` TLD (IANA special-use) so the emails are never deliverable — they exist purely for local/demo use.

---

## Testing

### Automated Tests (pytest)

```bash
# Run all tests
pytest tests/ -v

# By module
pytest tests/test_support_agent.py -v     # Support tools (unit)
pytest tests/test_knowledge_agent.py -v   # RAG pipeline (unit)
pytest tests/test_router.py -v            # Intent classification (unit)
pytest tests/test_api.py -v               # Full scenarios (integration)
```

### Manual Scenario Test

```bash
# Tests all 8 main scenarios automatically
python scripts/test_agents.py
```

### Rebuild the Knowledge Base

```bash
python scripts/build_knowledge_base.py              # Skips if already built
python scripts/build_knowledge_base.py --rebuild    # Forces rebuild
python scripts/build_knowledge_base.py --no-cache --rebuild  # Re-scrapes everything
```

### Test Coverage

| Suite | Type | What it covers |
|---|---|---|
| `test_support_agent.py` | Unit | Mock DB, ticket system, tool output format |
| `test_knowledge_agent.py` | Unit | Language detection, chunker, vector store API |
| `test_router.py` | Unit | Intent classification with mocked Claude, guardrail regex |
| `test_api.py` | Integration | All 8 challenge scenarios, edge cases, schema validation |

---

## Project Structure

```
cloudwalk-agent-swarm/
├── app/
│   ├── main.py                      # FastAPI entrypoint + lifespan (bot + RAG + middleware)
│   ├── config.py                    # Configuration and environment variables
│   │
│   ├── api/
│   │   └── routes.py                # POST /chat, GET /health, GET /history/{user_id}
│   │
│   ├── agents/
│   │   ├── router_agent.py          # LangGraph StateGraph (central orchestrator)
│   │   ├── knowledge_agent.py       # RAG + web search agent (with retry logic)
│   │   ├── support_agent.py         # Support agent with CRM tools (with retry logic)
│   │   ├── escalation_agent.py      # 4th agent: human escalation
│   │   └── guardrails.py            # Input/output filtering and PII sanitization
│   │
│   ├── integrations/
│   │   └── telegram_bot.py          # Telegram bot (long polling, asyncio, serialized executor)
│   │
│   ├── rag/
│   │   ├── scraper.py               # InfinitePay page scraper
│   │   ├── chunker.py               # Text chunking
│   │   ├── embedder.py              # sentence-transformers wrapper
│   │   ├── vector_store.py          # ChromaDB CRUD + similarity search
│   │   └── pipeline.py              # Full RAG pipeline orchestration
│   │
│   ├── tools/
│   │   ├── rag_tool.py              # RAG as a LangChain Tool
│   │   ├── search_tool.py           # DuckDuckGo as a LangChain Tool
│   │   └── account_tools.py         # 3 customer support tools
│   │
│   ├── database/
│   │   ├── mock_users.py            # Simulated CRM (5 users)
│   │   ├── mock_tickets.py          # In-memory ticket system
│   │   └── chat_history.py          # Per-user conversation history store
│   │
│   ├── models/
│   │   ├── request_models.py        # Pydantic: ChatRequest, ChatResponse
│   │   └── user_models.py           # Pydantic: User, Ticket
│   │
│   ├── static/
│   │   └── index.html               # Web Chat frontend (HTML + CSS + JS)
│   │
│   └── utils/
│       ├── language_detector.py     # EN/PT-BR detection
│       └── logger.py                # Structured logging
│
├── scripts/
│   ├── build_knowledge_base.py      # CLI: build RAG knowledge base
│   └── test_agents.py               # Manual scenario testing
│
├── tests/
│   ├── test_api.py                  # Integration tests
│   ├── test_knowledge_agent.py      # RAG pipeline tests
│   ├── test_router.py               # Router tests
│   └── test_support_agent.py        # Support tools tests
│
├── data/                            # Generated at runtime (git-ignored)
│   ├── chroma_db/                   # Persisted vectors
│   └── scraped_cache/               # Scraping cache
│
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── .env.example
```

---

## Design Decisions

**Why LangGraph?**
LangGraph's `StateGraph` provides explicit, debuggable control flow between agents. Unlike LCEL chains, you can see exactly which node executed and in what order — essential for a multi-agent system with conditional routing logic.

**Why sentence-transformers instead of OpenAI embeddings?**
Free, runs locally without an extra API key, and the `all-MiniLM-L6-v2` model is multilingual — it handles Portuguese queries finding Portuguese content without any translation step.

**Why DuckDuckGo instead of Tavily?**
Zero configuration, no API key, completely free. Tavily would be better for production (more reliable, more results), but DuckDuckGo is sufficient for demonstration purposes.

**Why a mock database?**
The challenge focuses on agent architecture. A mock DB demonstrates the tool-calling pattern clearly without adding PostgreSQL complexity. In production, `lookup_account_status` would call a real CRM API.

**Multilingual strategy:**
Language detection runs once per request at the API layer, stored in `AgentState["language"]`. Each agent's system prompt includes an explicit rule: *"Always respond in the EXACT SAME LANGUAGE as the user's message."* Claude handles PT-BR natively with no extra translation step. Error messages also respect the detected language.

**Reliability:**
Agent `invoke()` calls are wrapped with `tenacity` (3 retries, exponential backoff 2–10s) to survive transient Anthropic API connection errors. The Telegram bot uses a single-threaded executor to serialize requests and avoid concurrent API calls.

---

## How I Used LLMs in This Project

I used AI assistants throughout development:

- **Architecture design**: Discussing the LangGraph StateGraph design, each agent's responsibilities, and data flow between nodes.
- **Prompt engineering**: Iterating on the Router classification prompt with few-shot examples until routing was reliable in both English and Portuguese.
- **Code generation**: Boilerplate for FastAPI routes, Pydantic models, and ChromaDB wrappers, with review and refinement of each component.
- **RAG debugging**: Diagnosing why certain queries returned irrelevant chunks (chunking strategy adjustment).
- **Documentation**: Structuring this README and the testing strategy section.

---

## Implementation History

A condensed log of the major iterations on the project, in order:

1. **MVP swarm (initial commit)** — FastAPI + LangGraph router + Knowledge/Support/Escalation/Guardrails agents; in-memory CRM, tickets, and chat history; web chat UI + manual user switcher.
2. **RAG hardening** — multilingual `all-MiniLM-L6-v2`, persistent ChromaDB, scrape cache, retry/backoff via `tenacity`, cross-language retrieval fix.
3. **Telegram channel** — long-polling bot with single-thread executor (serializes Anthropic calls), Markdown→Telegram-HTML converter, multi-attempt safe reply.
4. **Railway deployment** — Dockerfile with CPU-only torch wheel, `railway.toml`, externalized healthcheck, `data/chroma_db` committed to skip rebuilds.
5. **Persistent storage migration** — SQLAlchemy 2.0 + PostgreSQL (SQLite fallback for local dev). All in-memory stores (`mock_users`, `mock_tickets`, `chat_history`) migrated to ORM with `ON DELETE CASCADE` for LGPD right-to-erasure. Idempotent seeding of the 5 demo users keyed by `legacy_id` so existing tests/scripts keep working.
6. **Authentication + LGPD compliance** — bcrypt-hashed passwords, JWT (HS256) via PyJWT, FastAPI `HTTPBearer` dependency, mandatory LGPD consent on registration, self-service `DELETE /auth/me` cascade.
7. **Telegram account linking** — one-shot 6-char codes generated in the web UI (`POST /auth/telegram/code`, 10-min TTL), consumed via `/link <code>` in the bot. Unlinked Telegram accounts are rejected with onboarding instructions.
8. **Per-user data isolation** — `/chat`, `/history`, `/tickets` all derive `user_id` from the JWT — no path parameter, no enumeration. The legacy user-switcher in the web UI was removed.
9. **Language reliability fix** — explicit `[Respond strictly in <Language>]` directive injected into the Knowledge and Support agent inputs (was previously relying on a vague system-prompt instruction, which leaked PT replies for EN questions on Brazilian product topics).
10. **Telegram UX polish** — collapse runs of blank lines in the rendered HTML, agent label + language badge in the signature, mirroring the web UI pattern.
11. **Observability foundations** — request timing middleware, in-memory counters exposed at `/metrics`, structured `agent_response` log line with per-turn latency.

## Security Audit

Snapshot of the security posture after the **2026-04-14 ethical pentest** (see `security-assessment-report.md`) and the subsequent Phase 1.5 remediation commit. Items marked **OK** are addressed in the current code; items marked **TODO** are tracked in the Production Roadmap → "Phase 1.5 — Security Remediation" below.

| Risk                                      | Status | Mitigation                                                                                          |
|-------------------------------------------|--------|------------------------------------------------------------------------------------------------------|
| Plaintext password storage                | OK     | bcrypt via `passlib[bcrypt]`; never logged.                                                          |
| Token forgery                             | OK     | JWT HS256 with `JWT_SECRET` from env (must be ≥ 32 random bytes in prod). Tokens carry `iat`/`exp`.  |
| Cross-user data access                    | OK     | All authenticated endpoints derive `user_id` from the JWT subject — no path parameter is trusted.    |
| User enumeration via login                | OK     | `POST /auth/login` returns the same generic 401 for unknown email and wrong password.                |
| User enumeration via registration         | OK     | `POST /auth/register` always returns `202` with a generic ack regardless of whether the email already exists (HIGH-03 fix, Phase 1.5 Commit C).      |
| Stored XSS via profile fields             | OK     | `name` field rejects `<`, `>`, `&`, `"`, `\\`, `;`, `{}`, `[]`, `|`, backticks, event-handler chars — Unicode-aware whitelist with NFC normalization. |
| Brute-force login (per-IP + per-account)  | OK     | `slowapi` (X-Forwarded-For aware) `5/min` per IP + **account lockout** after `LOGIN_LOCKOUT_THRESHOLD` (default 10) consecutive failures. |
| Rate limiting for registration            | OK     | `5/min;20/hour` per IP on `POST /auth/register`.                                                     |
| Rate limiting for Telegram code mint      | OK     | `10/min` per IP **plus** per-user throttle: at most one code every 30 s regardless of origin.        |
| API reconnaissance (Swagger/OpenAPI)      | OK     | `/docs`, `/redoc`, `/openapi.json` disabled unless `ENABLE_DOCS=true` (dev/staging only).            |
| HTML/JS injection via chat message        | OK     | Guardrail regex rejects any HTML tag (`<svg>`, `<img>`, `<script>`), `javascript:` URIs, inline `on*=` handlers, and HTML entities — no 500s on malformed input. |
| Prompt injection / abusive input          | OK     | Input guardrail (regex + Claude classifier, EN/PT) before any agent runs. Output PII sanitization.   |
| PII leakage in agent responses            | OK     | `guardrails.sanitize_output` strips CPF, card numbers, phone, and email patterns from every reply.   |
| Session token transport                   | OK     | `Authorization: Bearer …` only; no cookies → no CSRF surface. CORS restricted via `ALLOWED_ORIGINS`. |
| Clickjacking / MIME sniffing / XSS        | OK     | `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, strict `Content-Security-Policy`.        |
| Telegram channel hijack                   | OK     | One Telegram account ↔ one App user; codes are single-use, 10-min TTL, A-Z0-9 (≈ 2 ⁱⁿ ³¹ entropy).  |
| Fake escalation abuse                     | OK     | 24-h open-ticket dedup (`app/database/mock_tickets.py`) reuses the existing ticket instead of opening a new one — tighter than the 2/h the pentest asked for. |
| Account creation abuse (no verification)  | OK     | Email-verification token (60-min TTL) issued on register; Cloudflare Turnstile required after `CAPTCHA_AFTER_FAILED_LOGINS` failures (MEDIUM-08 fix).   |
| Health endpoint information disclosure    | OK     | Public `/health` returns `{"status":"ok","show_agent_badge":bool}`; KB size + flags now live at authenticated `/admin/health` (MEDIUM-09 fix).       |
| LGPD right-to-erasure                     | OK     | `DELETE /auth/me` cascades through tickets, chat history, telegram link, transactions.               |
| LGPD explicit consent                     | OK     | Registration is rejected unless `lgpd_consent_at` is set; consent timestamp persisted.               |
| SQL injection                             | OK     | SQLAlchemy ORM parameterizes all queries; no raw SQL in app code.                                    |
| DoS / Anthropic API exhaustion            | OK     | Stacked limits on `/chat`: `20/min` per IP **+** `30/min` per JWT (keyed by a hash of the bearer token). Telegram serializes calls through a single-threaded executor. |
| Concurrent state race (transfer limit)   | Partial| Mock CRM only writes on ticket creation today, so no race in practice. **TODO:** when wired to a real CRM, wrap `transfer_limit_remaining` updates in a `SELECT … FOR UPDATE`. |
| Missing security headers (HSTS, etc.)    | OK     | `SecurityHeadersMiddleware` sends `Referrer-Policy`, `Permissions-Policy`, CSP and — when the request reaches us over HTTPS (Railway edge or direct) — `Strict-Transport-Security: max-age=31536000; includeSubDomains; preload`. |
| Secret rotation                           | TODO   | `JWT_SECRET` rotation invalidates all sessions instantly — design a key-id-aware decode path before going live. |
| Audit log                                 | OK     | `audit_events` table (append-only) logs auth success/failure, captcha_failed, lockout_triggered, email_verified, unlock, account_deleted, telegram link/unlink. |
| HTTPS termination                         | OK     | Railway terminates TLS at the edge proxy and forwards `X-Forwarded-Proto`; rate limiter uses `X-Forwarded-For` to see the real client IP. |

### Pentest result summary (2026-04-14)

| # | Finding | Pre-remediation severity | Status |
|---|---|---|---|
| CRITICAL-01 | Stored XSS via registration name field | Critical (6.1) | **Fixed** in Phase 1.5 — name validator rejects HTML chars |
| CRITICAL-02 | Swagger/OpenAPI exposed in production | Critical (7.5) | **Fixed** in Phase 1.5 — `ENABLE_DOCS=false` by default |
| HIGH-03     | Account enumeration via registration | High (5.3) | **Fixed** in Phase 1.5 Commit C — generic 202 ack on `/auth/register` |
| HIGH-04     | Login brute-force mitigations | High (7.5) | **Fixed** in Phase 1.5 — XFF-aware per-IP + account lockout |
| HIGH-05     | Telegram code generation throttle | High (6.5) | **Fixed** in Phase 1.5 — 30-s per-user throttle added |
| HIGH-06     | HTML input → 500 on `/chat` | High (5.3) | **Fixed** in Phase 1.5 — broader guardrail patterns |
| MEDIUM-07   | Fake escalation creates real tickets | Medium (4.3) | **Fixed** — 24-h per-user open-ticket dedup already in place |
| MEDIUM-08   | No email verification / CAPTCHA | Medium (4.3) | **Fixed** in Phase 1.5 Commit C — email verification token + Turnstile (flag-gated) |
| MEDIUM-09   | `/health` information disclosure | Medium (3.1) | **Fixed** in Phase 1.5 Commit C — slim public `/health`, details at `/admin/health` |

**Score (self-assessed):** 6.5/10 pre-remediation → **~9/10** after Phase 1.5 Commits A + B → **~9.5/10** after Commit C (email verification, CAPTCHA, admin `/health`, audit log, Telegram self-service unlink).

**OWASP alignment:** this project is tracked against the **OWASP Top 10** (A03 Injection, A05 Misconfiguration, A07 Authentication). OWASP is a framework, not a certification body — formal certifications that use OWASP as a technical base are ISO 27001, SOC 2 Type II, and PCI DSS. For this demo-stage project we use the Top 10 as a PR-review checklist and plan to run `OWASP ZAP` baseline scans in CI once Phase 1.5 lands.

### Concurrency analysis

- **Within a single request**: each request uses its own `SessionLocal()` context — no shared mutable state.
- **Same user, parallel requests**: `chat_history` inserts are independent rows (interleaving is fine); `tickets` IDs include a UUID4 suffix (no collision); `telegram/code` invalidates prior unused codes inside one transaction (last writer wins, intended).
- **Different users**: completely independent at the DB and agent layers.
- **Anthropic rate limits**: handled by `tenacity` (3 retries, exponential backoff 2–10 s). The Telegram bot serializes calls through a single-threaded executor; HTTP `/chat` does not — this is intentional so unrelated users aren't blocked behind a slow agent turn.

## Production Roadmap

Items are grouped by phase. Each phase depends on the previous one being stable.

### Phase 1 — Public deployment (in progress)

- [x] **PostgreSQL persistence** (Railway addon + local docker-compose service)
- [x] **JWT auth + LGPD-compliant registration**
- [x] **Telegram account linking via one-shot code**
- [x] **Railway healthcheck fix** (removed `localhost:8000` from Dockerfile, kept Railway external probe via `railway.toml`)
- [x] **Public Railway URL + Telegram webhook** (webhook mode live at `cloudwalk-agent-swarm-challenge.up.railway.app`)
- [x] **Mobile UX polish** — iOS viewport (`100dvh`, safe-area), table overflow scroll, Telegram @handle card
- [ ] **Production secrets rotation** — generate a strong `JWT_SECRET` and rotate `MOCK_USER_PASSWORD` away from the seeded default before any external testing
- [x] **Per-JWT-user rate limit** on `/chat` (`30/min` per JWT, stacked on top of the existing `20/min` per IP)

### Phase 1.5 — Security Remediation (post-pentest 2026-04-14)

Tracked against the 9 findings in `security-assessment-report.md`. Split into two commits so remediation ships in small, testable batches.

**Commit A — P0 criticals (done):**
- [x] Disable `/docs`, `/redoc`, `/openapi.json` in prod (`ENABLE_DOCS=false` by default) — CRITICAL-02
- [x] Sanitize `name` field on registration (reject HTML/JS chars, NFC normalize, Unicode whitelist) — CRITICAL-01
- [x] Broaden guardrail regex to catch any HTML tag, `javascript:` URIs, inline event handlers — HIGH-06 (no more 500s)
- [x] Rate limiter honors `X-Forwarded-For` behind Railway edge proxy — precondition for HIGH-04/HIGH-05
- [x] Account-level login lockout after `LOGIN_LOCKOUT_THRESHOLD` (default 10) consecutive failures — HIGH-04
- [x] Per-user throttle on `POST /auth/telegram/code` (≤ 1 code / 30 s) — HIGH-05
- [x] Tighter `POST /auth/register` rate limit (`5/min;20/hour`) — precondition for MEDIUM-08
- [x] Regression tests: `tests/test_security.py` covers all of the above (16 cases)

**Commit B — P1 sprint (done):**
- [x] `Strict-Transport-Security: max-age=31536000; includeSubDomains; preload` emitted when the request is HTTPS (Railway edge, `X-Forwarded-Proto`) — Missing header from pentest
- [x] Per-JWT-user `/chat` rate limit (`30/min`) stacked on top of the per-IP `20/min` — closes the shared-NAT bypass
- [x] Escalation throttle confirmed via existing 24-h open-ticket dedup (`mock_tickets.create_ticket` returns the existing ticket with `is_duplicate=True`) — MEDIUM-07 satisfied
- [x] Session-expiry UX: `apiFetch` intercepts every 401 → clears JWT → routes back to login; `loadTickets` swallows the `UNAUTHORIZED` error (no more blank "Falha ao carregar tickets" banner)
- [x] Telegram bot: `/start`, `/help`, and the not-linked message include the web-app URL (`WEB_APP_URL` env, defaults to the Railway domain)
- [x] Agent/language badge gated by `SHOW_AGENT_BADGE` (default `false` in prod) — web reads the flag from `/health`, Telegram reads from config
- [x] DB integrity pass: local SQLite reseeded (5 legacy mock users + real accounts); added `telegram_links.telegram_username` column; purged ~26 test-pollution users (`ok+…`, `lock+…`, `sec+…`, `smoke@test.io`) + 4 stale tickets
- [x] Test isolation: autouse `_clean_seeded_tickets` fixture in `test_tickets.py` and `test_support_agent.py` wipes seeded-user tickets between tests so the 24-h dedup doesn't cause phantom failures
- [ ] Fix account enumeration on `POST /auth/register` (generic "if available, check your email" response) — HIGH-03 **(deferred to Commit C; only meaningful once email verification is in place)**

**Commit C — P2 medium-term (done):**
- [x] Email verification flow (`email_tokens` table w/ `verify_email` purpose + pluggable provider; log-only adapter for demo, Resend/Postmark/SES drop-in via `EMAIL_PROVIDER` env) — MEDIUM-08
- [x] HIGH-03 enumeration fix: `/auth/register` always returns 202 + generic ack regardless of email existence
- [x] Slim public `/health` → `{"status":"ok","show_agent_badge":bool}`; details at authenticated `/admin/health` (requires `user.is_admin`) — MEDIUM-09
- [x] CAPTCHA (Cloudflare Turnstile) after `CAPTCHA_AFTER_FAILED_LOGINS` (default 3) — flag-gated via `TURNSTILE_SECRET_KEY`; `/auth/captcha-config` exposes the site key to the frontend
- [x] Self-service account unlock via emailed token (`unlock_account` purpose, 30-min TTL) — completes the HIGH-04 lockout loop
- [x] Append-only `audit_events` table (auth_success/failure, captcha_failed, lockout_triggered, account_deleted, telegram_linked/unlinked) — `app/audit.emit(...)` logs without blocking the request
- [x] Language-detection bug fix: heuristic PT prefilter (accent regex + closed-class token sets) + 23 regression tests in `tests/test_language_detection.py`
- [x] Telegram self-service unlink: `DELETE /auth/telegram` + button in the web UI (no need to delete account or contact support)
- [x] Auto-refresh of the "Vincular Telegram" screen on link (4-s poll of `/auth/me` while the code is live) and on unlink

### Phase 2 — Observability & quality

- [x] **Request timing middleware + `/metrics` counters + structured `agent_response` logs**
- [ ] **LangSmith trace export** for the agent graph (per-node latency + tool calls)
- [x] **Prometheus exporter** at `/metrics` (text exposition v0.0.4 by default; JSON snapshot still available via `?format=json`)
- [x] **RAG evaluation harness** — golden Q&A set, Recall@K + MRR tracked per knowledge-base build (`tests/test_rag_eval.py`)
- [x] **Load test** with k6 against the Railway URL (P95/P99 budgets, `scripts/load_test.k6.js`)
- [x] **Cross-language retrieval audit** — EN↔PT pairs now have a parametrized fixture (`tests/test_rag_cross_language.py`) asserting overlap on `source_url`
- [x] **Conversation-history context injection (last 3 turns)** — `router_agent` loads `chat_history.get_history(user_id)[-3:]` and prepends alternating `HumanMessage` / `AIMessage` turns (capped at 500 chars/side) before each knowledge/support invocation, so follow-ups like *"e como eu faço isso?"* resolve correctly. Skipped for anonymous Telegram users (`anon_tg_*`) who have no persisted history.

### Phase 3 — Hardening & data

- [x] **In-memory stores migrated to PostgreSQL with cascade-deletion**
- [x] **Per-user isolation enforced via JWT subject (no enumeration)**
- [x] **Input/output guardrails (prompt-injection blocking + PII sanitization)**
- [x] **Audit log table** (auth events) — append-only; extending to ticket lifecycle / escalation events is a follow-up
- [ ] **Background RAG warm-up** so `/health` returns immediately even on the very first cold start

### Phase 4 — Performance & scale

- [ ] **Response cache** — Redis layer for frequent KB questions (cache key = normalized question + language)
- [ ] **Incremental RAG** — sitemap diff + per-chunk re-embedding, instead of full rebuilds
- [ ] **Streaming responses** — surface tokens to the web UI via SSE so long answers feel responsive
- [ ] **Multi-region read replicas** if user base spans LATAM

### Future improvements (nice-to-haves, out of scope for the current challenge)

Ideas worth considering once Phases 1–4 are stable. Kept separate so the delivered roadmap stays focused.

- **Speech-to-text input (web + Telegram).** Free, good-enough option for the web is the browser-native **Web Speech API** (`SpeechRecognition`): zero backend cost, works in Chrome/Edge/Safari, streams transcripts while the user talks. On Telegram, voice notes can be transcribed server-side with `faster-whisper` (`base` model, ~140 MB) running on the same dyno — viable on a modest VM but tight on a free Railway tier. Would add a mic button next to the chat input on the web and handle `voice` updates in `app/integrations/telegram_bot.py`.
- **Real CRM integration.** Replace the inline CRM columns on `users` with a thin adapter to HubSpot / Salesforce / an internal API. Not planned for this challenge — the mock CRM is deliberate to keep the demo self-contained.
- **Extended audit events.** The `audit_events` table covers auth today. Wiring ticket lifecycle, escalation, and chat-moderation events would round out the trail for SOC 2–style review.
- **Admin console.** Read-only UI on top of `/admin/health`, `audit_events`, and the tickets table. Currently everything is introspectable via SQL only.
- **Streaming tokens on the web.** Switch `/chat` to SSE so the web UI feels as responsive as Telegram-style typing indicators, with incremental rendering of long Knowledge-agent answers.
- **OWASP ZAP baseline scan in CI.** Nightly job that hits the Railway preview URL, fails the build on new highs. Low-effort follow-up to the Phase 1.5 pentest.
- **Larger-window conversation context.** The shipped injection caps at **3 turns** and **500 chars/side** — a deliberate cost trade-off. Each extra turn adds ~150 input tokens against the Anthropic bill; going from 3 → 10 turns roughly doubles per-request input cost with diminishing relevance (most follow-ups resolve against the most recent 1–2 turns). Kept out of the current scope because: (a) measured latency/cost regression on the default 3-turn window is already ~+30%, (b) the support agent's tool-use loop multiplies that cost per turn, (c) long tails are better handled by summarization than raw concatenation. Evolution path: (i) adaptive window — keep 3 turns by default, extend only when a lightweight pronoun/short-message heuristic flags a follow-up; (ii) rolling 1-sentence "session summary" cached on `chat_messages` so arbitrarily old context stays addressable at constant cost; (iii) per-user vector recall over their own `chat_messages` for multi-session memory.
