"""
Text chunker for RAG pipeline.
Splits scraped documents into overlapping chunks while preserving source metadata.
"""

import logging
from langchain_text_splitters import RecursiveCharacterTextSplitter
from app.config import CHUNK_SIZE, CHUNK_OVERLAP

logger = logging.getLogger(__name__)


def split_documents(documents: list[dict]) -> list[dict]:
    """
    Splits a list of scraped documents into smaller chunks.

    Args:
        documents: List of {"url", "title", "content"} dicts from the scraper.

    Returns:
        List of {"content", "url", "title", "chunk_index"} dicts ready for embedding.
    """
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        separators=["\n\n", "\n", ". ", " ", ""],
    )

    chunks = []
    for doc in documents:
        if not doc.get("content"):
            continue

        split_texts = splitter.split_text(doc["content"])

        for idx, text in enumerate(split_texts):
            chunks.append(
                {
                    "content": text,
                    "url": doc["url"],
                    "title": doc["title"],
                    "chunk_index": idx,
                }
            )

    logger.info(
        "Split %d documents into %d chunks (chunk_size=%d, overlap=%d).",
        len(documents),
        len(chunks),
        CHUNK_SIZE,
        CHUNK_OVERLAP,
    )
    return chunks
