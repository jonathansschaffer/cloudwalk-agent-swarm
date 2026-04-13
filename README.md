# InfinitePay Agent Swarm

![Python](https://img.shields.io/badge/Python-3.11-3776AB?style=flat-square&logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?style=flat-square&logo=fastapi&logoColor=white)
![LangGraph](https://img.shields.io/badge/LangGraph-1.0-FF6B35?style=flat-square)
![LangChain](https://img.shields.io/badge/LangChain-0.3-1C3C3C?style=flat-square)
![Claude](https://img.shields.io/badge/Claude-Sonnet_4.6-CC785C?style=flat-square)
![ChromaDB](https://img.shields.io/badge/ChromaDB-0.5-E8613C?style=flat-square)
![Docker](https://img.shields.io/badge/Docker-Ready-2496ED?style=flat-square&logo=docker&logoColor=white)

> Sistema multi-agente de IA para suporte ao cliente da InfinitePay. Roteia mensagens automaticamente para o agente especializado correto, com suporte a RAG, busca web, ferramentas de CRM e escalação humana.

---

## Interfaces Disponíveis

| Interface | URL / Acesso | Descrição |
|---|---|---|
| 🌐 **Web Chat** | `http://localhost:8000/` | Tela de chat com UI completa |
| 🤖 **API REST** | `http://localhost:8000/chat` | Endpoint JSON para integrações |
| 📖 **Swagger UI** | `http://localhost:8000/docs` | Documentação interativa da API |
| 💬 **Telegram Bot** | Configure `TELEGRAM_BOT_TOKEN` no `.env` | Chat pelo app do Telegram |

---

## Arquitetura

O sistema é composto por **4 agentes distintos** orquestrados por um `StateGraph` do LangGraph:

```
┌─────────────────────────────────────────────────────────────────────┐
│                         POST /chat  ou  Telegram Bot                │
│                    {"message": "...", "user_id": "..."}             │
└─────────────────────────────┬───────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      ROUTER AGENT  (LangGraph)                      │
│                                                                     │
│   ① Guardrails Node  ──► bloqueia injeção de prompt e ofensas       │
│           │ SEGURO                                                  │
│   ② Router Node      ──► Claude classifica a intenção              │
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
│ │ (RAG)   │  │(Search) │  │ (3 tools)    │  │  (4° agente) │      │
│ └────┬────┘  └────┬────┘  └──────┬───────┘  └──────────────┘      │
│      │            │              │ ESCALADO?                       │
│      │            │              ├──► SIM ──► Escalation Agent     │
│      │            │              │ NÃO                             │
│      └────────────┴──────────────┴──► Guardrails de saída          │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
                       ChatResponse JSON
```

### Descrição dos Agentes

| Agente | Responsabilidade | Tecnologia |
|---|---|---|
| **Router Agent** | Ponto de entrada: classifica a intenção e orquestra o fluxo | LangGraph StateGraph + Claude |
| **Knowledge Agent** | Responde perguntas sobre produtos (RAG) e perguntas gerais (busca web) | LangChain ReAct + ChromaDB + DuckDuckGo |
| **Support Agent** | Diagnostica e resolve problemas de conta usando ferramentas de CRM | LangChain ReAct + 3 ferramentas customizadas |
| **Escalation Agent** | Redireciona issues complexos para o suporte humano com contexto completo | Claude direct + mock ticket system |

### Guardrails

- **Entrada**: Detecta e bloqueia injeções de prompt (regex), conteúdo ofensivo (Claude) e abuso do sistema
- **Saída**: Sanitiza respostas para prevenir vazamento de PII (CPF, número de cartão)

---

## Pipeline RAG

O Knowledge Agent usa Retrieval-Augmented Generation (RAG) para responder perguntas baseado em conteúdo real da InfinitePay.

```
 ┌────────────┐    ┌─────────────┐    ┌───────────────────┐
 │  SCRAPING  │ ─► │  CHUNKING   │ ─► │    EMBEDDING      │
 │            │    │             │    │                   │
 │ BeautifulS │    │ Recursive   │    │ all-MiniLM-L6-v2  │
 │ oup scrapes│    │ CharText    │    │ (local, gratuito, │
 │ 18 URLs da │    │ Splitter    │    │  multilingual)    │
 │ InfinitePay│    │ 800 chars / │    │ → vetor 384-dim   │
 │ (~20 docs) │    │ 100 overlap │    │ por chunk         │
 └────────────┘    └─────────────┘    └────────┬──────────┘
                                               │
 ┌─────────────────────────────────────────────┘
 │
 ▼
 ┌─────────────────┐    ┌────────────────────────────────────┐
 │    STORAGE      │    │          RETRIEVAL + GENERATION    │
 │                 │    │                                    │
 │   ChromaDB      │ ◄─►│  Pergunta → embedding → top-5     │
 │   (local,       │    │  chunks por cosine similarity →   │
 │   persistente)  │    │  injetados no prompt do Claude →  │
 │  data/chroma_db/│    │  resposta fundamentada nos dados  │
 └─────────────────┘    └────────────────────────────────────┘
```

### Fontes de Conhecimento (18 páginas)

| URL | Conteúdo |
|---|---|
| `infinitepay.io` | Visão geral / Homepage |
| `/maquininha` | Maquininha Smart |
| `/maquininha-celular` | Celular como maquininha |
| `/tap-to-pay` | Tap to Pay |
| `/pdv` | Ponto de Venda (PDV) |
| `/receba-na-hora` | Recebimento instantâneo |
| `/gestao-de-cobranca` | Gestão de cobranças |
| `/link-de-pagamento` | Link de pagamento |
| `/loja-online` | Loja online |
| `/boleto` | Boleto bancário |
| `/conta-digital` | Conta digital PF |
| `/conta-pj` | Conta digital PJ |
| `/pix` | PIX |
| `/pix-parcelado` | PIX Parcelado |
| `/emprestimo` | Empréstimo |
| `/cartao` | Cartão InfinitePay |
| `/rendimento` | Rendimento da conta |
| `/gestao-de-cobranca-2` | Gestão de cobranças (v2) |

---

## Stack Tecnológica

| Componente | Tecnologia | Motivo da escolha |
|---|---|---|
| Linguagem | Python 3.11 | Melhor suporte ao ecossistema de IA |
| API Framework | FastAPI | Moderna, async, documentação automática |
| Orquestração de Agentes | LangGraph + LangChain | Padrão da indústria para sistemas agênticos |
| LLM | Claude Sonnet 4.6 (Anthropic) | Excelente em português, tool use e raciocínio |
| Embeddings | sentence-transformers (all-MiniLM-L6-v2) | Gratuito, local, multilingual |
| Banco Vetorial | ChromaDB | Simples, local, persistente, sem servidor externo |
| Web Scraping | BeautifulSoup4 + requests | Parser HTML confiável |
| Busca Web | DuckDuckGo (ddgs) | Gratuito, sem API key |
| Detecção de Idioma | langdetect | Leve, detecta PT-BR vs EN |
| Bot Telegram | python-telegram-bot v21 | Asyncio nativo, biblioteca mais madura |
| Containerização | Docker + docker-compose | Deploy com um comando |

---

## Pré-requisitos

- **Docker Desktop** (recomendado) → [docker.com](https://www.docker.com/products/docker-desktop/)
- **OU** Python 3.11+ para desenvolvimento local
- **Anthropic API Key** → [console.anthropic.com](https://console.anthropic.com)
- **Telegram Bot Token** *(opcional)* → crie um bot via [@BotFather](https://t.me/botfather) no Telegram

---

## Quick Start com Docker

```bash
# 1. Clone o repositório
git clone https://github.com/jonathansschaffer/cloudwalk-agent-swarm.git
cd cloudwalk-agent-swarm

# 2. Configure as variáveis de ambiente
cp .env.example .env
# Edite .env e preencha ANTHROPIC_API_KEY (e opcionalmente TELEGRAM_BOT_TOKEN)

# 3. Suba o container
docker-compose up --build
# Na primeira execução (~3-5 min): baixa o modelo de embedding, scrapa as páginas e indexa os vetores.
# Execuções seguintes são quase instantâneas (dados persistidos em ./data/).

# 4. Verifique que está funcionando
curl http://localhost:8000/health
# {"status":"ok","knowledge_base_loaded":true,"documents_indexed":225}

# 5. Acesse o chat pelo browser
open http://localhost:8000
```

---

## Desenvolvimento Local (sem Docker)

```bash
# 1. Crie o ambiente virtual
python -m venv venv
source venv/bin/activate       # Linux/Mac
venv\Scripts\activate          # Windows

# 2. Instale as dependências
pip install -r requirements.txt

# 3. Configure as variáveis de ambiente
cp .env.example .env
# Edite .env com sua ANTHROPIC_API_KEY

# 4. Construa a base de conhecimento (uma única vez)
python scripts/build_knowledge_base.py

# 5. Inicie o servidor
uvicorn app.main:app --reload

# Interfaces disponíveis:
#   http://localhost:8000/        ← Chat Web
#   http://localhost:8000/docs    ← Swagger UI
#   http://localhost:8000/health  ← Health check
```

---

## Variáveis de Ambiente

| Variável | Obrigatória | Padrão | Descrição |
|---|---|---|---|
| `ANTHROPIC_API_KEY` | ✅ Sim | — | API key da Anthropic para o LLM |
| `TELEGRAM_BOT_TOKEN` | ❌ Não | — | Token do bot Telegram (do @BotFather) |
| `CHROMA_DB_PATH` | ❌ Não | `./data/chroma_db` | Onde o ChromaDB persiste os vetores |
| `SCRAPED_CACHE_PATH` | ❌ Não | `./data/scraped_cache` | Cache do conteúdo raspado |
| `COLLECTION_NAME` | ❌ Não | `infinitepay_knowledge` | Nome da coleção no ChromaDB |
| `LOG_LEVEL` | ❌ Não | `INFO` | Verbosidade dos logs (DEBUG/INFO/WARNING) |

---

## Bot Telegram

O bot Telegram se integra diretamente ao Agent Swarm, com a mesma inteligência e funcionalidades da API REST.

> ✅ **Token já configurado no `.env`** — basta iniciar o servidor e o bot estará online automaticamente.

### Como usar

```bash
# 1. Inicie o servidor normalmente
uvicorn app.main:app --reload
# Ou com Docker: docker-compose up

# 2. Abra o Telegram e acesse: @CloudWalk_Challenge_Bot
# 3. Envie /start para começar
```

> 💬 **Bot disponível em:** [t.me/CloudWalk\_Challenge\_Bot](https://t.me/CloudWalk_Challenge_Bot)

### Comandos disponíveis no bot

| Comando | Descrição |
|---|---|
| `/start` | Mensagem de boas-vindas e instruções |
| `/help` | Exemplos de perguntas por categoria |
| *(qualquer texto)* | Processado pelo Agent Swarm |

### Como criar um bot próprio (para outros ambientes)

```bash
# 1. Abra o Telegram e fale com @BotFather
# 2. Envie /newbot, defina um nome e username
# 3. Copie o token gerado e adicione ao .env:
TELEGRAM_BOT_TOKEN=seu_token_aqui
# 4. Reinicie o servidor
```

### Funcionamento técnico

- O bot roda em modo **long polling** — não requer URL pública ou HTTPS
- É **opcional**: se `TELEGRAM_BOT_TOKEN` não estiver no `.env`, o servidor sobe normalmente sem o bot
- O `user_id` do Telegram é mapeado como `tg_{telegram_id}` no sistema interno

---

## Uso da API

### POST `/chat`

Envia uma mensagem ao Agent Swarm e recebe a resposta estruturada.

**Request:**

```json
{
  "message": "Quais as taxas da Maquininha Smart?",
  "user_id": "client789"
}
```

**Response:**

```json
{
  "response": "As taxas da Maquininha Smart variam conforme seu faturamento mensal...",
  "agent_used": "knowledge_agent",
  "intent_detected": "KNOWLEDGE_PRODUCT",
  "ticket_id": null,
  "escalated": false,
  "language": "pt"
}
```

**Campos da resposta:**

| Campo | Tipo | Descrição |
|---|---|---|
| `response` | `string` | Texto de resposta do agente (suporta Markdown) |
| `agent_used` | `string` | Qual agente respondeu (`knowledge_agent`, `support_agent`, `escalation_agent`, `guardrails`) |
| `intent_detected` | `string` | Intenção classificada (`KNOWLEDGE_PRODUCT`, `KNOWLEDGE_GENERAL`, `CUSTOMER_SUPPORT`, `ESCALATION`, `INAPPROPRIATE`) |
| `ticket_id` | `string \| null` | ID do ticket criado, se aplicável (ex: `TKT-20260413-A1B2C3`) |
| `escalated` | `boolean` | Se a conversa foi escalada para atendimento humano |
| `language` | `string` | Idioma detectado na mensagem (`pt` ou `en`) |

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

### Exemplos com curl

```bash
# Pergunta sobre produto (RAG)
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "What are the rates for debit and credit card?", "user_id": "client789"}'

# Pergunta geral (busca web)
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Quando foi o último jogo do Palmeiras?", "user_id": "client789"}'

# Problema de conta (suporte)
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "I cannot make transfers from my account", "user_id": "client789"}'

# Login bloqueado (conta suspensa)
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Não consigo fazer login", "user_id": "user_002"}'

# Escalação para humano
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Quero falar com um atendente humano", "user_id": "client789"}'
```

---

## Usuários de Teste (Mock CRM)

O sistema inclui 5 usuários simulados para demonstrar diferentes cenários de suporte:

| User ID | Nome | Status | Cenário de teste |
|---|---|---|---|
| `client789` | Carlos Oliveira | ✅ Ativo | Conta saudável — perguntas sobre produto ou transferência |
| `user_002` | Maria Souza | 🔴 Suspensa | KYC não verificado, 5 tentativas de login falhas → gera ticket |
| `user_003` | Pedro Santos | 🟡 Ativo | Limite de transferência esgotado → explicação sobre limites |
| `user_004` | Ana Lima | 🟡 Ativo | Conta nova (pendente KYC), sem histórico de transações |
| `user_005` | Roberto Costa | 🔴 Bloqueado | Conta bloqueada por múltiplas tentativas de login → escalação |

---

## Testes

### Testes Automatizados (pytest)

```bash
# Rodar todos os testes
pytest tests/ -v

# Por módulo
pytest tests/test_support_agent.py -v     # Ferramentas de suporte (unit)
pytest tests/test_knowledge_agent.py -v   # Componentes RAG (unit)
pytest tests/test_router.py -v            # Classificação de intenção (unit)
pytest tests/test_api.py -v               # Cenários completos (integração)
```

### Teste Manual dos Cenários

```bash
# Testa os 8 cenários principais automaticamente
python scripts/test_agents.py
```

### Reconstruir a Base de Conhecimento

```bash
python scripts/build_knowledge_base.py          # Pula se já existir
python scripts/build_knowledge_base.py --rebuild    # Força reconstrução
python scripts/build_knowledge_base.py --no-cache --rebuild  # Re-scrapa tudo
```

### Cobertura de Testes

| Suite | Tipo | O que cobre |
|---|---|---|
| `test_support_agent.py` | Unit | Mock DB, sistema de tickets, formato dos tools |
| `test_knowledge_agent.py` | Unit | Detecção de idioma, chunker, API do vector store |
| `test_router.py` | Unit | Classificação de intenção com Claude mockado, regex de guardrails |
| `test_api.py` | Integração | Todos os 8 cenários do desafio, edge cases, validação de schema |

---

## Estrutura do Projeto

```
cloudwalk-agent-swarm/
├── app/
│   ├── main.py                      # Entrypoint FastAPI + lifespan (bot + RAG)
│   ├── config.py                    # Configurações e variáveis de ambiente
│   │
│   ├── api/
│   │   └── routes.py                # POST /chat e GET /health
│   │
│   ├── agents/
│   │   ├── router_agent.py          # LangGraph StateGraph (orquestrador central)
│   │   ├── knowledge_agent.py       # Agente RAG + busca web
│   │   ├── support_agent.py         # Agente de suporte com ferramentas de CRM
│   │   ├── escalation_agent.py      # 4° agente: escalação para humano
│   │   └── guardrails.py            # Filtragem de input/output
│   │
│   ├── integrations/
│   │   └── telegram_bot.py          # Bot Telegram (long polling, asyncio)
│   │
│   ├── rag/
│   │   ├── scraper.py               # Scraper das páginas da InfinitePay
│   │   ├── chunker.py               # Divisor de texto em chunks
│   │   ├── embedder.py              # Wrapper do sentence-transformers
│   │   ├── vector_store.py          # CRUD do ChromaDB + busca por similaridade
│   │   └── pipeline.py              # Orquestra o pipeline RAG completo
│   │
│   ├── tools/
│   │   ├── rag_tool.py              # RAG como LangChain Tool
│   │   ├── search_tool.py           # DuckDuckGo como LangChain Tool
│   │   └── account_tools.py         # 3 ferramentas de suporte ao cliente
│   │
│   ├── database/
│   │   ├── mock_users.py            # CRM simulado (5 usuários)
│   │   └── mock_tickets.py          # Sistema de tickets in-memory
│   │
│   ├── models/
│   │   ├── request_models.py        # Pydantic: ChatRequest, ChatResponse
│   │   └── user_models.py           # Pydantic: User, Ticket
│   │
│   ├── static/
│   │   └── index.html               # Frontend Web Chat (HTML + CSS + JS)
│   │
│   └── utils/
│       ├── language_detector.py     # Detecção EN/PT-BR
│       └── logger.py                # Logging estruturado
│
├── scripts/
│   ├── build_knowledge_base.py      # CLI: construir base RAG
│   └── test_agents.py               # Teste manual dos cenários
│
├── tests/
│   ├── test_api.py                  # Testes de integração
│   ├── test_knowledge_agent.py      # Testes do pipeline RAG
│   ├── test_router.py               # Testes do roteador
│   └── test_support_agent.py        # Testes das ferramentas de suporte
│
├── data/                            # Gerado em runtime (git-ignored)
│   ├── chroma_db/                   # Vetores persistidos
│   └── scraped_cache/               # Cache do scraping
│
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── .env.example
```

---

## Decisões de Design

**Por que LangGraph?**
O `StateGraph` do LangGraph fornece controle de fluxo explícito e debugável entre agentes. Ao contrário de chains LCEL, é possível ver exatamente qual nó executou e em que ordem — essencial para um sistema multi-agente com lógica de roteamento condicional.

**Por que sentence-transformers ao invés de embeddings da OpenAI?**
Gratuito, roda localmente sem API key adicional, e o modelo `all-MiniLM-L6-v2` é multilingual — lida com consultas em português encontrando conteúdo em português sem precisar de tradução.

**Por que DuckDuckGo ao invés de Tavily?**
Zero configuração, sem API key, gratuito. Tavily seria melhor para produção (mais confiável, mais resultados), mas DuckDuckGo é suficiente para demonstração.

**Por que banco de dados mock?**
O desafio foca em arquitetura de agentes. Um mock DB demonstra o padrão de tool-calling claramente sem adicionar complexidade de PostgreSQL. Em produção, `lookup_account_status` chamaria uma API real de CRM.

**Estratégia multilíngue:**
Detecção de idioma roda uma vez por requisição na camada de API, armazenada em `AgentState["language"]`. O system prompt de cada agente inclui a regra explícita: *"Responda no MESMO IDIOMA da mensagem do usuário."* Claude lida com PT-BR nativamente sem passo adicional de tradução.

---

## Como Usei LLMs neste Projeto

Utilizei assistentes de IA ao longo de todo o desenvolvimento:

- **Design de arquitetura**: Discussão sobre o design do StateGraph do LangGraph, responsabilidades de cada agente e fluxo de dados entre nós.
- **Engenharia de prompts**: Iteração no prompt de classificação do Router com exemplos few-shot até o roteamento ser confiável em inglês e português.
- **Geração de código**: Boilerplate para rotas FastAPI, modelos Pydantic e wrappers do ChromaDB, com revisão e refinamento de cada componente.
- **Debugging de RAG**: Diagnóstico de por que certas consultas retornavam chunks irrelevantes (ajuste da estratégia de chunking).
- **Documentação**: Estruturação deste README e da seção de estratégia de testes.

---

## Melhorias para Produção (Roadmap)

- [ ] **Autenticação**: JWT na API para ambientes multi-tenant
- [ ] **CRM real**: Substituir mock por integração com API de CRM (HubSpot, Salesforce)
- [ ] **Observabilidade**: LangSmith para rastreamento de traces de agentes; Prometheus/Grafana para métricas
- [ ] **Avaliação RAG**: Golden set de Q&A para regressão automática; métricas MRR e Recall@K
- [ ] **Rate limiting**: Throttling por `user_id` para prevenir abuso
- [ ] **Webhook Telegram**: Para produção, substituir long polling por webhook HTTPS
- [ ] **Cache de respostas**: Redis para responder perguntas frequentes sem chamar o LLM
- [ ] **Testes de carga**: k6 ou Locust para medir P95/P99 com usuários concorrentes
- [ ] **RAG incremental**: Atualização automática da base quando páginas da InfinitePay mudam
