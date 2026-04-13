"""
Embedding generator using sentence-transformers.
Uses a singleton pattern so the model is loaded only once per process.
"""

import logging
from sentence_transformers import SentenceTransformer
from app.config import EMBEDDING_MODEL

logger = logging.getLogger(__name__)

_model: SentenceTransformer | None = None


def _get_model() -> SentenceTransformer:
    """Lazy-loads and caches the embedding model."""
    global _model
    if _model is None:
        logger.info("Loading embedding model: %s", EMBEDDING_MODEL)
        _model = SentenceTransformer(EMBEDDING_MODEL)
        logger.info("Embedding model loaded.")
    return _model


def embed_texts(texts: list[str]) -> list[list[float]]:
    """
    Generates embeddings for a list of text strings.

    Args:
        texts: List of strings to embed.

    Returns:
        List of float vectors (one per input text).
    """
    model = _get_model()
    vectors = model.encode(texts, show_progress_bar=False, convert_to_numpy=True)
    return vectors.tolist()


def embed_query(query: str) -> list[float]:
    """
    Generates an embedding for a single query string.

    Args:
        query: The search query.

    Returns:
        A single float vector.
    """
    return embed_texts([query])[0]
