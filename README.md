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
| 💬 **Telegram Bot** | Set `TELEGRAM_BOT_TOKEN` in `.env` | Chat via the Telegram app |

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
| Rate Limiting | slowapi | Per-IP request throttling (20 req/min) |
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

The system includes 5 simulated users to demonstrate different support scenarios:

| User ID | Name | Status | Test scenario |
|---|---|---|---|
| `client789` | Carlos Andrade | ✅ Active | Healthy account — product questions or transfers |
| `user_002` | Maria Souza | 🔴 Suspended | KYC not verified, 6 failed logins → ticket created |
| `user_003` | João Silva | 🟡 Pending KYC | New account, identity verification pending |
| `user_004` | Ana Lima | 🟡 Active | Enterprise plan, daily transfer limit exhausted |
| `user_005` | Pedro Costa | 🟠 Active | 2 failed logins, recent failed transaction |

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

## Production Roadmap

- [ ] **Authentication**: JWT on the API for multi-tenant environments
- [ ] **Real CRM**: Replace mock with a real CRM API integration (HubSpot, Salesforce)
- [ ] **Observability**: LangSmith for agent trace monitoring; Prometheus/Grafana for metrics
- [ ] **RAG evaluation**: Golden Q&A set for automated regression; MRR and Recall@K metrics
- [ ] **Telegram webhook**: Replace long polling with HTTPS webhook for production
- [ ] **Response cache**: Redis to answer frequent questions without calling the LLM
- [ ] **Load testing**: k6 or Locust to measure P95/P99 with concurrent users
- [ ] **Incremental RAG**: Auto-update the knowledge base when InfinitePay pages change
- [ ] **Persistent history**: Replace in-memory history store with Redis or PostgreSQL
