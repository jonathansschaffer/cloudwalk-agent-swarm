import os
from dotenv import load_dotenv

load_dotenv()

# --- API Keys ---
ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")

# --- Paths ---
CHROMA_DB_PATH: str = os.getenv("CHROMA_DB_PATH", "./data/chroma_db")
SCRAPED_CACHE_PATH: str = os.getenv("SCRAPED_CACHE_PATH", "./data/scraped_cache")

# --- ChromaDB ---
COLLECTION_NAME: str = os.getenv("COLLECTION_NAME", "infinitepay_knowledge")

# --- RAG Parameters ---
CHUNK_SIZE: int = 800
CHUNK_OVERLAP: int = 100
TOP_K_RETRIEVAL: int = 5
EMBEDDING_MODEL: str = "all-MiniLM-L6-v2"

# --- LLM ---
LLM_MODEL: str = "claude-sonnet-4-6"
LLM_MAX_TOKENS: int = 2048
LLM_TEMPERATURE: float = 0.0

# --- Logging ---
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

# --- InfinitePay URLs to scrape ---
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
]


def validate_config() -> None:
    """Raise an error on startup if required config values are missing."""
    if not ANTHROPIC_API_KEY:
        raise ValueError(
            "ANTHROPIC_API_KEY is not set. "
            "Please copy .env.example to .env and fill in your API key."
        )
