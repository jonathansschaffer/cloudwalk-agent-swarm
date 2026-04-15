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
| 📖 **Swagger UI** | `http://localhost:8000/docs` | Interactive API docs (dev only — disabled in prod via `ENABLE_DOCS=false`) |
| 💬 **Telegram Bot** | http://t.me/CloudWalk_Challenge_Bot | Chat via the Telegram app |

---

## Challenge deliverables checklist

Mapping the CloudWalk Agent Swarm spec to what's actually shipped:

| Spec requirement | Status | Evidence |
|---|---|---|
| **≥ 3 distinct agent types** | ✅ 4 agents | [Router](app/agents/router_agent.py), [Knowledge](app/agents/knowledge_agent.py), [Support](app/agents/support_agent.py), [Escalation](app/agents/escalation_agent.py) |
| Router Agent — primary entry, classifies intent, manages flow | ✅ | `process_message` in [router_agent.py](app/agents/router_agent.py) owns the `StateGraph`. Claude classifier picks one of 5 intents, conditional edges dispatch to the right node. |
| Knowledge Agent — RAG over infinitepay.io | ✅ | [scraper.py](app/rag/scraper.py) ingests all 18 URLs listed in the brief (`maquininha`, `tap-to-pay`, `pdv`, `pix`, `conta-digital`, `emprestimo`, `cartao`, `rendimento`, etc.). Indexed via `all-MiniLM-L6-v2` into ChromaDB. |
| Knowledge Agent — web search tool | ✅ | [search_tool.py](app/tools/search_tool.py) (DuckDuckGo) used when the RAG hit is weak. |
| Customer Support Agent — ≥ 2 tools | ✅ 3 tools | [account_tools.py](app/tools/account_tools.py): `lookup_account_status`, `get_transaction_history`, `create_support_ticket`. |
| Explicit inter-agent communication mechanism | ✅ | LangGraph `StateGraph` with typed `AgentState`; nodes mutate a single state dict and edges are declarative. See architecture diagram below. |
| **FastAPI `POST /chat` with JSON body** | ✅ with documented deviation | See [API Reference](#post-chat) — body is `{"message": "..."}`; `user_id` is derived from the JWT (not from the body) to eliminate IDOR. The deviation is intentional, documented, and regression-tested. |
| Meaningful JSON response | ✅ | `ChatResponse` model: `response`, `agent_used`, `intent_detected`, `ticket_id`, `escalated`, `language`, `tools_used`. |
| **Dockerfile + docker-compose.yml** | ✅ | Both present at repo root — `docker-compose up --build` runs end-to-end. |
| **Testing strategy documented** | ✅ | [Testing section](#testing) + 144 tests across `tests/{agents,api,rag,security,unit}/`. |

All deliverables are met. The only intentional deviation is the `/chat` body shape (no `user_id`), motivated and regression-tested as described above.

---

## Architecture

The system is composed of **4 specialized agents** orchestrated by a LangGraph `StateGraph`:

```
┌─────────────────────────────────────────────────────────────────────┐
│                     POST /chat  or  Telegram Bot                    │
│   {"message": "..."}  + JWT (user_id is the JWT subject, not body)  │
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

**Authentication:** requires `Authorization: Bearer <JWT>` obtained from `POST /auth/login`.

**Request:**

```json
{
  "message": "What are the rates for the Maquininha Smart?"
}
```

> **Deviation from the challenge spec (documented on purpose).** The challenge brief proposes `{"message": "...", "user_id": "..."}`. We intentionally do **not** accept `user_id` in the request body — it is derived from the JWT subject server-side. Trusting a client-supplied `user_id` would let any authenticated user impersonate another (read/write someone else's history and tickets), which is a classic **IDOR** vulnerability and was verified-negative during the 2026-04-15 pentest (`GET /history/2` as user 1 returns 404). The JWT-subject approach removes that entire class of bug; the only cost is that clients must log in first, which also unlocks rate-limit-per-user, LGPD right-to-erasure, and audit trails.

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

### GET `/history`

Returns the authenticated user's conversation history. `user_id` is **not** a path parameter — same security rationale as `/chat` above.

```bash
curl -H "Authorization: Bearer $JWT" http://localhost:8000/history
```

```json
{
  "user_id": 42,
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

# By domain (tests grouped into subfolders)
pytest tests/agents/ -v                   # router + knowledge + support agents
pytest tests/api/ -v                      # HTTP scenarios + tickets
pytest tests/rag/ -v                      # RAG pipeline, cross-language, eval
pytest tests/security/ -v                 # regressions from the pentest
pytest tests/unit/ -v                     # cache + language detection
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
| `tests/agents/test_support_agent.py` | Unit | Mock DB, ticket system, tool output format |
| `tests/agents/test_knowledge_agent.py` | Unit | Language detection, chunker, vector store API |
| `tests/agents/test_router.py` | Unit | Intent classification with mocked Claude, guardrail regex |
| `tests/api/test_api.py` | Integration | All 8 challenge scenarios, edge cases, schema validation |
| `tests/api/test_tickets.py` | Integration | Ticket dedup + lifecycle through `/tickets` |
| `tests/rag/test_rag_eval.py` | Eval | Recall@K + MRR against a golden Q&A set |
| `tests/rag/test_rag_cross_language.py` | Eval | EN↔PT retrieval parity |
| `tests/rag/test_incremental_rag.py` | Integration | Content-hash diffing on re-ingest |
| `tests/security/test_security.py` | Regression | 16 pentest findings (XSS, lockout, docs off, HTML→guardrail) |
| `tests/unit/test_cache.py` | Unit | TTL cache behavior, negative-cache, language-keyed isolation |
| `tests/unit/test_language_detection.py` | Unit | PT/EN heuristic + 23 cases for "other"-misclassification regressions |

### Testing strategy

- **Unit tests** stub the Anthropic client and exercise pure logic (classifier regex, chunker, cache, language detection). Fast — full unit subset runs in under 5 s.
- **Integration tests** hit `TestClient(app)` end-to-end and make real Anthropic calls. They're the ones that catch prompt regressions when the router or agents are tuned.
- **RAG evals** (`tests/rag/test_rag_eval.py`) measure retrieval quality per build using Recall@K and MRR against a hand-curated Q&A set. Treat this as a quality gate when the scraper or chunker changes.
- **Security regression tests** (`tests/security/`) lock in every pentest fix so future refactors can't silently undo them.

**How I would scale integration testing.** (1) Record-and-replay fixtures (VCR-style) to freeze Claude outputs for deterministic CI. (2) A small synthetic chat-log corpus feeding a nightly job that asserts `agent_used` + `intent_detected` distributions stay within a tolerance. (3) `promptfoo` / `garak` jailbreak corpus in CI for guardrail coverage. (4) `k6` load test (`scripts/load_test.k6.js`) already exists — wire it into a pre-release pipeline.

---

## Project Structure

```
cloudwalk-agent-swarm/
├── app/
│   ├── main.py                      # FastAPI entrypoint + lifespan (bot + RAG + middleware)
│   ├── config.py                    # Configuration and environment variables
│   │
│   ├── api/
│   │   └── routes.py                # POST /chat, GET /health, GET /history, GET /tickets
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
│   ├── agents/                      # Router, knowledge, support agent tests
│   ├── api/                         # HTTP integration tests + tickets
│   ├── rag/                         # RAG eval, cross-language, incremental ingest
│   ├── security/                    # Pentest regression tests (16 cases)
│   └── unit/                        # Cache + language detection unit tests
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

**Why a mock CRM (not a real CRM API)?**
The challenge focuses on agent architecture, not CRM integration. The five seeded demo users (`carlos.andrade`, `maria.souza`, etc.) cover every support scenario the agent needs to exercise. In production, `lookup_account_status` and `get_transaction_history` would call the real InfinitePay CRM — the tool interface is unchanged.

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

## How it was built

The project went through several distinct iterations beyond the initial agent swarm:

- **Storage** started in-memory and was migrated to SQLAlchemy 2.0 + PostgreSQL (SQLite fallback for local dev). `ON DELETE CASCADE` ensures the LGPD right-to-erasure `DELETE /auth/me` truly removes all user data.
- **Authentication** was added as a full layer: bcrypt, JWT, rate limiting, account lockout, CAPTCHA, email verification flow, and an append-only audit log.
- **RAG hardening** — multilingual `all-MiniLM-L6-v2`, persistent ChromaDB, scrape cache, incremental re-indexing (content-hash diff), and a RAG evaluation harness (Recall@K + MRR).
- **Telegram** — webhook mode for production, long-polling for local dev, account linking via one-shot 6-char codes, serialized Anthropic calls to avoid rate-limit bursts.
- **Language reliability** — the `[Respond strictly in <Language>]` directive injected per-turn replaced a vague system-prompt instruction that caused Portuguese queries on Brazilian product topics to bleed into English replies.
- **Observability** — Prometheus metrics, LangSmith opt-in tracing, request timing middleware, structured log lines per agent turn, k6 load test.
- **Security** — black-box pentest with two real findings fixed (XFF rate-limit bypass, public `/metrics`); 16 regression tests locked in the remediation.

## Security

Security was treated as a first-class concern from the start. The application was subject to a black-box pentest (2026-04-15) that produced a self-assessed weighted score of **9.0 / 10** — full findings and attack-class results in [security-assessment-report.md](security-assessment-report.md). The sections below describe every control layer currently in place.

### Authentication & session management

- **bcrypt password hashing** via `passlib[bcrypt]`; passwords are never logged.
- **JWT (HS256)** signed with a `JWT_SECRET` that must be ≥ 32 random bytes in production; tokens carry `iat`/`exp` claims. Startup guard fires a `CRITICAL` log and an audit event if the app boots in production mode with the default secret.
- **Account lockout** — after `LOGIN_LOCKOUT_THRESHOLD` (default 10) consecutive failures the account is locked; a one-time unlock link (30-min TTL) is emailed to the owner.
- **Cloudflare Turnstile CAPTCHA** — appears on the login form after `CAPTCHA_AFTER_FAILED_LOGINS` failures (default 3) and on every registration. Flag-gated via `TURNSTILE_SECRET_KEY`.
- **Email verification flow** — `email_tokens` table with `verify_email` / `unlock_account` purposes; pluggable provider (`EMAIL_PROVIDER=resend|postmark|ses`). Disabled by default to keep the demo frictionless; activating requires only three env vars plus a verified sender domain.

### Authorization & isolation

- Every authenticated endpoint derives `user_id` from the **JWT subject** — no path parameter is trusted. This closes IDOR by design: `/history` and `/tickets` always return the calling user's own data, regardless of any value passed in the request.
- **`POST /auth/register`** always returns `202` with the same generic message whether the email was free or already taken — no account-existence signal leaks.
- **`POST /auth/login`** returns the same generic `401` for wrong password and unknown email.
- Admin-only routes (e.g. `GET /admin/health`) check `user.is_admin`; all other endpoints require only a valid token.
- `DELETE /auth/me` cascades via `ON DELETE CASCADE` through tickets, chat history, Telegram link, and transactions — full LGPD right-to-erasure.

### Input validation & guardrails

- **Pydantic** validates every field on every endpoint; raw bodies that fail to parse return `422`.
- **`name` field whitelist** — NFC-normalized, rejects `<`, `>`, `&`, `"`, `\`, `;`, `{}`, `[]`, `|`, backticks, `on*` event-handler keywords. Unicode letters (including `á`, `ç`, `ã`) are accepted.
- **Two-sided AI guardrail** ([app/agents/guardrails.py](app/agents/guardrails.py)):
  - *Input*: regex blocks HTML tags, `javascript:` URIs, inline event handlers, and HTML entities; Claude classifier flags prompt injection and abusive content in both English and Portuguese.
  - *Output*: `sanitize_output` strips CPF, card numbers, phone numbers, and email addresses from every agent reply before it leaves the server.
- **SQL injection** — SQLAlchemy ORM parameterizes all queries; no raw SQL anywhere in the application code.

### Rate limiting & anti-abuse

- `slowapi` limiter uses `X-Forwarded-For` correctly: Railway's edge appends the real client IP to the end of the chain; the limiter reads the rightmost-minus-`TRUSTED_PROXY_HOPS` value so clients cannot rotate spoofed IPs to bypass per-IP limits.
- `/chat` — **`20/min` per IP** stacked with **`30/min` per JWT** (keyed by SHA-256 of the bearer token), protecting against both anonymous hammering and a single authenticated user abusing a shared NAT.
- `/auth/login` — `5/min` per IP.
- `/auth/register` — `5/min;20/hour` per IP.
- `/auth/telegram/code` — `10/min` per IP + at most one code every 30 s per user, regardless of IP.
- Escalation abuse — 24-h open-ticket dedup reuses the existing ticket instead of creating a new one.
- Telegram bot — calls are serialized through a single-threaded executor so a single user cannot spawn concurrent Anthropic API calls.

### HTTP security headers

`SecurityHeadersMiddleware` (applied to every response):

```
Content-Security-Policy:  default-src 'self'; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://challenges.cloudflare.com; …
Strict-Transport-Security: max-age=31536000; includeSubDomains; preload  (HTTPS only)
X-Frame-Options:           DENY
X-Content-Type-Options:    nosniff
Referrer-Policy:           strict-origin-when-cross-origin
Permissions-Policy:        camera=(), microphone=(), geolocation=()
```

- `Authorization: Bearer …` only — no cookies, so there is no CSRF surface.
- CORS origin list locked to `ALLOWED_ORIGINS` env var.
- `/docs`, `/redoc`, `/openapi.json` disabled by default (`ENABLE_DOCS=false`); enabled only in dev/staging.
- Public `/health` returns `{"status":"ok","show_agent_badge":bool}` only; KB size and internal flags live at authenticated `/admin/health`.

### LGPD compliance

- Explicit `lgpd_consent` checkbox required on registration; timestamp persisted on `users.lgpd_consent_at`.
- Registration rejected without consent regardless of other fields.
- Full cascade deletion on `DELETE /auth/me` — no orphan data remains after a user deletes their account.
- PII never logged in plaintext; structured log lines use user IDs, not names or emails.

### Observability & audit trail

- **`audit_events` table** (append-only) — records `auth.login.success`, `auth.login.failure`, `auth.login.lockout_triggered`, `auth.register.captcha_failed`, `auth.email.verified`, `auth.account.deleted`, `telegram.linked`, `telegram.unlinked`.
- **`/metrics`** (Prometheus exposition) — gated behind an optional `METRICS_TOKEN` Bearer header to prevent reconnaissance of per-path hit counts and error distributions.
- **LangSmith tracing** — opt-in per-node latency, tool calls, and token usage for every graph execution (`LANGSMITH_API_KEY` + `LANGSMITH_PROJECT`).
- **Request timing middleware** — every response carries `X-Process-Time` and a structured `agent_response` log line with end-to-end latency.

### Concurrency

- Each request opens its own `SessionLocal()` — no shared mutable database state between concurrent requests.
- `chat_history` inserts are independent rows; ticket IDs include a UUID4 suffix (no collision risk); `telegram/code` invalidates prior unused codes in a single transaction.
- Transient Anthropic API errors are handled by `tenacity` (3 retries, exponential backoff 2–10 s).

## What could be better (next evolution)

Curated shortlist: items that are load-bearing for a real production deployment, obvious next steps a reviewer will ask about, or disruptive enough to move the product bar.

**Channels & input**

- **WhatsApp Business channel.** Brazilian customers live on WhatsApp — Telegram+Web leaves the dominant channel unserved. Meta Cloud API webhook → `POST /whatsapp/webhook` → same router graph → same persistence; pairing reuses the one-shot code flow keyed on `users.phone`. Gated on Meta Business verification and the per-conversation fee.
- **Speech-to-text input.** Web via the browser-native Web Speech API (zero backend cost); Telegram and WhatsApp voice notes transcribed server-side with `faster-whisper`.

**Search & knowledge**

- **Replace DuckDuckGo with a paid search API (Tavily / Brave / SerpAPI).** `ddgs` rate-limits unpredictably under load and returns thin snippets that force extra tool loops. Tavily has an official LangChain tool, clean JSON with dates, and a 1k/mo free tier — drop-in swap at [app/tools/search_tool.py](app/tools/search_tool.py), kills the #1 source of flakiness in load tests.
- **Per-user vector recall over `chat_messages`.** The 3-turn × 500-char window is a cheap stopgap. Embedding each user's own history into a second Chroma collection gives constant-cost multi-session memory and displaces the rolling-window hack entirely.

**Auth & anti-abuse**

- **Turn email verification back on.** The full flow (token table, `/auth/verify`, unlock, pluggable provider) is built and tested — `REQUIRE_EMAIL_VERIFICATION=false` only keeps the demo frictionless. Activation = three env vars plus a verified sender domain on Resend/Postmark/SES. Without this, a real-user deployment has no protection against signups with throwaway emails.
- **OWASP ZAP baseline scan in CI.** Nightly `zaproxy/action-baseline` against the Railway preview, fails the build on new HIGHs. Unit tests don't catch missing headers or XSS on new fields; a baseline scan does, and 15 minutes of GitHub Actions YAML is cheap insurance.
- **Prompt-injection canaries in CI.** Rotating corpus of jailbreak payloads (from `garak` / `promptfoo`) in the test suite — catches guardrail-prompt regressions.

**Observability & compliance**

- **Extended audit events.** `audit_events` covers auth. Wire ticket lifecycle, escalation triggers, and moderation decisions for a complete SOC 2 / LGPD trail.
- **PII audit on RAG embeddings.** Today the KB is public marketing content. The moment it ingests support docs or transcripts, every chunk must pass through `guardrails.sanitize_output` *before* embedding — otherwise CPFs/emails leak via nearest-neighbor retrieval regardless of the response-side sanitizer.

**Ops & surface**

- **Redis-backed response cache.** The in-memory TTL cache is fine for one worker; sharding across Railway replicas needs a shared backend. Change is isolated to [app/cache.py](app/cache.py).
- **Web UI migration to `/chat/stream`.** Backend SSE is live; the frontend still consumes `/chat`. Migrating = `EventSource` + incremental DOM updates, ~80 lines, no backend churn.
- **Agent A/B + prompt versioning.** System prompts live in source today. Moving to a `prompts` table with `version_id` + `is_active` enables instant rollback and sticky-bucketed A/B testing of router prompts — non-negotiable once anyone wants to tune prompts in production.
- **Feature-flag service.** `ENABLE_DOCS`, `SHOW_AGENT_BADGE`, `LANGSMITH_TRACING` require a redeploy to toggle. A runtime flag table (or LaunchDarkly/Unleash) unlocks instant kill-switches for the guardrail and escalation path.
- **Admin console.** Read-only UI on top of `/admin/health`, `audit_events`, and tickets — currently SQL-only.
- **Multi-region read replicas.** São Paulo primary + US edge for LATAM reach; writes stay single-region. Meaningful only once traffic justifies it.
