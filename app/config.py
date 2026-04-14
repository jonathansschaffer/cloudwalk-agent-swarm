"""
Centralized configuration for the InfinitePay Agent Swarm.

All settings are loaded from environment variables (via .env file).
Call `validate_config()` on startup to ensure required values are present.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# API Keys
# ---------------------------------------------------------------------------

# Anthropic API key — required. Obtain at https://console.anthropic.com
ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")

# Telegram Bot token — optional. Create a bot via @BotFather on Telegram.
# If not set, the Telegram integration is disabled automatically.
TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")

# Telegram polling switch. Telegram allows only ONE long-polling instance per
# bot — if Railway (prod) is already polling, set TELEGRAM_POLLING_ENABLED=false
# locally to avoid noisy NetworkError/Conflict logs while still keeping the
# token configured for code-reuse in tests.
TELEGRAM_POLLING_ENABLED: bool = os.getenv(
    "TELEGRAM_POLLING_ENABLED", "true"
).lower() in {"1", "true", "yes"}

# Telegram webhook URL — when set, the bot uses webhook mode instead of long
# polling. Set this to your Railway app URL (e.g. "https://my-app.railway.app").
# The bot will register the webhook at <TELEGRAM_WEBHOOK_URL>/telegram/webhook.
# Leave empty for local dev (falls back to long polling).
TELEGRAM_WEBHOOK_URL: str = os.getenv("TELEGRAM_WEBHOOK_URL", "").rstrip("/")

# Optional secret token to authenticate incoming webhook requests from Telegram.
# Set any random 256-char alphanumeric string; Telegram will include it as the
# X-Telegram-Bot-Api-Secret-Token header. Leave empty to skip validation.
TELEGRAM_WEBHOOK_SECRET: str = os.getenv("TELEGRAM_WEBHOOK_SECRET", "")

# ---------------------------------------------------------------------------
# Storage Paths
# ---------------------------------------------------------------------------

# Directory where ChromaDB persists the vector store between restarts
CHROMA_DB_PATH: str = os.getenv("CHROMA_DB_PATH", "./data/chroma_db")

# Directory where scraped HTML content is cached (avoids re-scraping)
SCRAPED_CACHE_PATH: str = os.getenv("SCRAPED_CACHE_PATH", "./data/scraped_cache")

# ---------------------------------------------------------------------------
# ChromaDB
# ---------------------------------------------------------------------------

# Name of the ChromaDB collection that stores InfinitePay knowledge chunks
COLLECTION_NAME: str = os.getenv("COLLECTION_NAME", "infinitepay_knowledge")

# ---------------------------------------------------------------------------
# RAG Pipeline Parameters
# ---------------------------------------------------------------------------

# Maximum number of characters per text chunk
CHUNK_SIZE: int = 800

# Number of characters overlapping between consecutive chunks (preserves context)
CHUNK_OVERLAP: int = 100

# Number of top-matching chunks to retrieve per query
TOP_K_RETRIEVAL: int = 7

# Sentence-transformers model used for embedding (multilingual, runs locally)
EMBEDDING_MODEL: str = "all-MiniLM-L6-v2"

# ---------------------------------------------------------------------------
# LLM Settings
# ---------------------------------------------------------------------------

# Claude model used for all agent reasoning and classification
LLM_MODEL: str = "claude-sonnet-4-6"

# Maximum number of tokens the LLM can generate per response
LLM_MAX_TOKENS: int = 2048

# Temperature = 0 for deterministic, factual responses
LLM_TEMPERATURE: float = 0.0

# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------

# Space-separated list of allowed origins for the API.
# In production, set this to your Railway/deployment URL.
# Example: "https://your-app.railway.app"
ALLOWED_ORIGINS: list[str] = os.getenv(
    "ALLOWED_ORIGINS",
    "http://localhost:8000 http://127.0.0.1:8000",
).split()

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

# Postgres on Railway (injected automatically as DATABASE_URL) or SQLite for
# local dev. SQLAlchemy normalization (postgres:// → postgresql+psycopg2://)
# happens in app/database/db.py.
DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./data/app.db")

# ---------------------------------------------------------------------------
# Authentication / JWT
# ---------------------------------------------------------------------------

# IMPORTANT: set JWT_SECRET in production via env var. In dev we fall back to
# a warning-loud default so tokens rotate only when config is set explicitly.
JWT_SECRET: str = os.getenv("JWT_SECRET", "dev-only-change-me-32chars-minimum-ok")
JWT_ALGORITHM: str = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))

# Shared password used to seed the 5 legacy mock users. Document-only secret —
# these accounts are demo fixtures, not real customers. Prod deployments can
# disable seeding by setting SEED_MOCK_USERS=false.
MOCK_USER_PASSWORD: str = os.getenv("MOCK_USER_PASSWORD", "Test123!")
SEED_MOCK_USERS: bool = os.getenv("SEED_MOCK_USERS", "true").lower() in {"1", "true", "yes"}

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

# Log verbosity: DEBUG | INFO | WARNING | ERROR
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

# ---------------------------------------------------------------------------
# InfinitePay URLs for RAG Scraping
# ---------------------------------------------------------------------------

# These pages are scraped once and stored in ChromaDB for retrieval-augmented generation
INFINITEPAY_URLS: list[str] = [
    "https://www.infinitepay.io",
    "https://www.infinitepay.io/maquininha",
    "https://www.infinitepay.io/maquininha-celular",
    "https://www.infinitepay.io/tap-to-pay",
    "https://www.infinitepay.io/pdv",
    "https://www.infinitepay.io/receba-na-hora",
    "https://www.infinitepay.io/gestao-de-cobranca",
    "https://www.infinitepay.io/gestao-de-cobranca-2",
    "https://www.infinitepay.io/link-de-pagamento",
    "https://www.infinitepay.io/loja-online",
    "https://www.infinitepay.io/boleto",
    "https://www.infinitepay.io/conta-digital",
    "https://www.infinitepay.io/conta-pj",
    "https://www.infinitepay.io/pix",
    "https://www.infinitepay.io/pix-parcelado",
    "https://www.infinitepay.io/emprestimo",
    "https://www.infinitepay.io/cartao",
    "https://www.infinitepay.io/rendimento",
    # Additional pages added to cover JIM (AI assistant) and other products
    "https://www.infinitepay.io/jim",
    "https://www.infinitepay.io/seguro",
    "https://www.infinitepay.io/antecipacao",
    "https://www.infinitepay.io/sobre",
]


def validate_config() -> None:
    """Raise a ValueError on startup if required config values are missing."""
    if not ANTHROPIC_API_KEY:
        raise ValueError(
            "ANTHROPIC_API_KEY is not set. "
            "Please copy .env.example to .env and fill in your Anthropic API key."
        )
