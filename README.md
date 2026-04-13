# InfinitePay Agent Swarm

A multi-agent AI system that routes customer messages to specialized agents for intelligent, context-aware responses — built for InfinitePay.

---

## Architecture Overview

The system consists of **four distinct agents** orchestrated by a LangGraph StateGraph:

```
POST /chat {"message": "...", "user_id": "..."}
            │
            ▼
    ┌─────────────────────────────────────────────────────────────┐
    │                   ROUTER AGENT (LangGraph)                   │
    │                                                             │
    │  [1] Guardrails Node   ← blocks offensive/injected input    │
    │         │ SAFE                                              │
    │  [2] Router Node       ← Claude classifies intent           │
    │         │                                                   │
    │    ┌────┴──────────┬──────────────┐                         │
    │    │               │              │                         │
    │ KNOWLEDGE       SUPPORT      ESCALATION/                    │
    │ PRODUCT/GENERAL               INAPPROPRIATE                 │
    │    │               │              │                         │
    │    ▼               ▼              ▼                         │
    │ ┌──────────┐  ┌──────────┐  ┌──────────────┐               │
    │ │Knowledge │  │Support   │  │ Escalation   │               │
    │ │Agent     │  │Agent     │  │ Agent        │               │
    │ │(RAG +    │  │(3 tools) │  │ (4th Agent)  │               │
    │ │ Search)  │  └────┬─────┘  └──────────────┘               │
    │ └──────────┘       │ ESCALATE?                             │
    │                    ├─YES────► Escalation Agent             │
    │                    │ NO                                    │
    │                    ▼                                       │
    │              Output Guardrails                             │
    └─────────────────────────────────────────────────────────────┘
                         │
                         ▼
                  ChatResponse JSON
```

### Agent Descriptions

| Agent | Role | Technology |
|---|---|---|
| **Router Agent** | Entry point; classifies intent and orchestrates the workflow | LangGraph StateGraph + Claude |
| **Knowledge Agent** | Answers product/service questions (RAG) and general questions (web search) | LangChain ReAct + ChromaDB + DuckDuckGo |
| **Support Agent** | Diagnoses and resolves account issues using CRM tools | LangChain ReAct + 3 custom tools |
| **Escalation Agent** | Redirects complex issues to human support with full context | Claude direct call |

### Guardrails

- **Input**: Blocks prompt injection attempts (regex), offensive content, and system abuse (Claude classifier)
- **Output**: Sanitizes responses to prevent PII leakage (CPF, card numbers)

---

## RAG Pipeline

The Knowledge Agent uses Retrieval Augmented Generation (RAG) to answer questions grounded in real InfinitePay content.

### How It Works

```
1. SCRAPING     → BeautifulSoup scrapes 18 InfinitePay URLs
                  Result: ~15-20 text documents

2. CHUNKING     → RecursiveCharacterTextSplitter
                  chunk_size=800, chunk_overlap=100
                  Result: ~300-600 text chunks with URL metadata

3. EMBEDDING    → sentence-transformers (all-MiniLM-L6-v2, FREE & local)
                  Each chunk → 384-dimensional vector

4. STORAGE      → ChromaDB (local, persistent, cosine similarity)
                  Persisted in data/chroma_db/

5. RETRIEVAL    → At query time: embed question → top-5 similar chunks
                  → Injected as context into Claude's prompt

6. GENERATION   → Claude generates an answer grounded in retrieved context
```

### Knowledge Base Sources

| URL | Topic |
|---|---|
| infinitepay.io | Homepage / Overview |
| /maquininha | Card machine (Maquininha) |
| /maquininha-celular | Phone as card machine |
| /tap-to-pay | Tap to Pay |
| /pdv | Point of Sale (PDV) |
| /receba-na-hora | Instant payment receipt |
| /gestao-de-cobranca | Billing management |
| /link-de-pagamento | Payment links |
| /loja-online | Online store |
| /boleto | Bank slip (boleto) |
| /conta-digital | Digital account |
| /conta-pj | Business account |
| /pix | PIX transfers |
| /pix-parcelado | Installment PIX |
| /emprestimo | Loans |
| /cartao | Card |
| /rendimento | Yield/returns |
| /gestao-de-cobranca-2 | Billing management (v2) |

---

## Tech Stack

| Component | Technology | Why |
|---|---|---|
| Language | Python 3.11 | Best AI/ML ecosystem |
| API Framework | FastAPI | Modern, async, auto-docs |
| Agent Orchestration | LangGraph + LangChain | Industry standard for agentic systems |
| LLM | Claude (Anthropic) | Excellent Portuguese support, tool use, reasoning |
| Embeddings | sentence-transformers (all-MiniLM-L6-v2) | Free, local, multilingual |
| Vector Store | ChromaDB | Simple, persistent, no external service |
| Web Scraping | BeautifulSoup4 + requests | Reliable HTML parsing |
| Web Search | DuckDuckGo Search | Free, no API key required |
| Language Detection | langdetect | Lightweight EN/PT-BR detection |
| Containerization | Docker + docker-compose | Single-command deployment |

---

## Prerequisites

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) (recommended)
- OR Python 3.11+ for local development
- An **Anthropic API key** — get one at [console.anthropic.com](https://console.anthropic.com)

---

## Quick Start (Docker — Recommended)

```bash
# 1. Clone the repository
git clone <your-repo-url>
cd cloudwalk-agent-swarm

# 2. Set up your API key
cp .env.example .env
# Edit .env and set your ANTHROPIC_API_KEY

# 3. Build and start the application
docker-compose up --build

# First startup takes ~3-5 minutes while it:
#   - Downloads the embedding model (~90MB)
#   - Scrapes InfinitePay pages
#   - Builds the vector database
# Subsequent starts are nearly instant (data is persisted in ./data/)

# 4. Verify it's running
curl http://localhost:8000/health
# Expected: {"status":"ok","knowledge_base_loaded":true,"documents_indexed":400}
```

---

## Local Development (Without Docker)

```bash
# 1. Create a virtual environment
python -m venv venv
source venv/bin/activate          # Linux/Mac
venv\Scripts\activate             # Windows

# 2. Install dependencies
pip install -r requirements.txt

# 3. Set up environment variables
cp .env.example .env
# Edit .env with your ANTHROPIC_API_KEY

# 4. Build the knowledge base (one-time)
python scripts/build_knowledge_base.py

# 5. Start the server
uvicorn app.main:app --reload

# API available at http://localhost:8000
# Interactive docs at http://localhost:8000/docs
```

---

## API Usage

### POST /chat

Send a message to the Agent Swarm:

```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "What are the fees of the Maquininha Smart?", "user_id": "client789"}'
```

**Response:**
```json
{
  "response": "The Maquininha Smart has the following transaction fees: ...",
  "agent_used": "knowledge_agent",
  "intent_detected": "KNOWLEDGE_PRODUCT",
  "ticket_id": null,
  "escalated": false,
  "language": "en"
}
```

### Example Scenarios

```bash
# Product question (RAG)
curl -X POST http://localhost:8000/chat \
  -d '{"message": "What are the rates for debit and credit card transactions?", "user_id": "client789"}'

# General question (web search)
curl -X POST http://localhost:8000/chat \
  -d '{"message": "Quando foi o último jogo do Palmeiras?", "user_id": "client789"}'

# Support issue (account lookup + ticket)
curl -X POST http://localhost:8000/chat \
  -d '{"message": "Why I am not able to make transfers?", "user_id": "client789"}'

# Login issue (PT-BR)
curl -X POST http://localhost:8000/chat \
  -d '{"message": "Não consigo fazer login na minha conta.", "user_id": "user_002"}'

# Human escalation
curl -X POST http://localhost:8000/chat \
  -d '{"message": "I want to speak with a human agent", "user_id": "client789"}'
```

### GET /health

```bash
curl http://localhost:8000/health
# {"status":"ok","knowledge_base_loaded":true,"documents_indexed":412}
```

### Interactive API Docs

Visit `http://localhost:8000/docs` for the full Swagger UI.

---

## Running Tests

### Automated Tests (pytest)

```bash
# Install test dependencies (already in requirements.txt)
pip install -r requirements.txt

# Run all tests
pytest tests/ -v

# Run specific test files
pytest tests/test_support_agent.py -v     # Unit tests (no API calls)
pytest tests/test_knowledge_agent.py -v   # RAG component tests
pytest tests/test_router.py -v            # Router classification tests
pytest tests/test_api.py -v               # Full integration tests (requires running server + API key)
```

### Manual Integration Test

```bash
# Tests all 8 scenarios from the challenge README
python scripts/test_agents.py
```

### Rebuilding the Knowledge Base

```bash
# Standard build (skips if already populated)
python scripts/build_knowledge_base.py

# Force full rebuild
python scripts/build_knowledge_base.py --rebuild

# Clear scraping cache and re-scrape
python scripts/build_knowledge_base.py --no-cache --rebuild
```

---

## Testing Strategy

### Current Test Coverage

| Test Suite | Type | What it covers |
|---|---|---|
| `test_support_agent.py` | Unit | Mock DB CRUD, ticket system, tool output format |
| `test_knowledge_agent.py` | Unit | Language detection, text chunker, vector store API |
| `test_router.py` | Unit | Intent classification with mocked Claude, guardrail regex |
| `test_api.py` | Integration | All 8 README scenarios, edge cases, validation |

### How to Approach Comprehensive Integration Testing

For production-grade testing of the agent swarm, I would add:

1. **Golden Set Evaluation**: Maintain a curated set of 50+ question/answer pairs, run weekly to detect quality regressions as the RAG content or LLM changes.

2. **RAG Retrieval Quality**: Track Mean Reciprocal Rank (MRR) and Recall@K for known questions. Ensure the correct InfinitePay page is in the top-3 retrieved chunks.

3. **Intent Classification Accuracy**: Label 100+ messages, compute precision/recall per intent category. Target >95% accuracy before deployment.

4. **Latency Benchmarks**: P50/P95/P99 response times under realistic load (10-100 concurrent users). LLM calls are typically 2-8 seconds.

5. **Guardrails Red-Teaming**: Adversarial inputs — prompt injections, jailbreak attempts, PII submissions. Verify they are blocked 100% of the time.

6. **Multi-language Tests**: Ensure Portuguese responses when queried in Portuguese, English when queried in English. No language mixing.

7. **Contract Tests**: Validate the `/chat` response schema never changes unexpectedly, preventing downstream breakage.

---

## How I Used LLMs to Complete This Challenge

I leveraged AI assistants (LLM-based tools) throughout this project:

- **Architecture design**: Used LLMs to think through the LangGraph StateGraph design, agent responsibilities, and data flow between nodes.
- **Prompt engineering**: Iterated on the Router's classification prompt with few-shot examples until intent routing was reliable across English and Portuguese.
- **Code generation**: Generated boilerplate for FastAPI routes, Pydantic models, and ChromaDB wrappers, then reviewed and refined each component.
- **RAG debugging**: Used LLMs to help diagnose why certain queries returned irrelevant chunks (chunking strategy tuning).
- **Documentation**: Structured this README and the testing strategy section with AI assistance.

---

## Project Structure

```
cloudwalk-agent-swarm/
├── app/
│   ├── main.py                  # FastAPI entrypoint + startup events
│   ├── config.py                # All settings and environment variables
│   ├── api/routes.py            # POST /chat and GET /health
│   ├── agents/
│   │   ├── router_agent.py      # LangGraph orchestrator (CORE)
│   │   ├── knowledge_agent.py   # RAG + web search agent
│   │   ├── support_agent.py     # CRM tools agent
│   │   ├── escalation_agent.py  # Human redirect agent (4th agent)
│   │   └── guardrails.py        # Input/output safety
│   ├── rag/
│   │   ├── scraper.py           # InfinitePay page scraper
│   │   ├── chunker.py           # Text splitter
│   │   ├── embedder.py          # sentence-transformers wrapper
│   │   ├── vector_store.py      # ChromaDB wrapper
│   │   └── pipeline.py          # End-to-end RAG build
│   ├── tools/
│   │   ├── rag_tool.py          # RAG as LangChain Tool
│   │   ├── search_tool.py       # DuckDuckGo as LangChain Tool
│   │   └── account_tools.py     # 3 customer support tools
│   ├── database/
│   │   ├── mock_users.py        # Simulated CRM (5 users)
│   │   └── mock_tickets.py      # Simulated ticket system
│   └── utils/
│       ├── language_detector.py # EN/PT-BR detection
│       └── logger.py            # Structured logging
├── scripts/
│   ├── build_knowledge_base.py  # CLI: build RAG knowledge base
│   └── test_agents.py           # Manual test: 8 README scenarios
├── tests/                       # pytest test suite
├── data/                        # ChromaDB + scraping cache (git-ignored)
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── .env.example
```

---

## Design Decisions

**Why LangGraph?** LangGraph's StateGraph provides explicit, debuggable control flow between agents. Unlike LCEL chains, you can see exactly which node executed and in what order — essential for a multi-agent system.

**Why sentence-transformers over OpenAI embeddings?** Free, runs locally, no extra API key, and the `all-MiniLM-L6-v2` model is multilingual — handles Portuguese queries finding Portuguese content without translation.

**Why DuckDuckGo over Tavily?** Zero configuration, no API key, free tier. Tavily is better for production (more reliable, more results), but DuckDuckGo is sufficient for the demo.

**Why mock database instead of a real DB?** The challenge focuses on agent architecture. A mock DB demonstrates the tool-calling pattern clearly without adding PostgreSQL complexity. In production, `lookup_account_status` would call a real CRM API.

**Multi-language strategy**: Language detection runs once per request at the API layer, stored in `AgentState["language"]`. Every agent's system prompt includes an explicit rule: *"Respond in the EXACT SAME LANGUAGE as the user's message."* Claude handles PT-BR naturally without any additional translation step.
