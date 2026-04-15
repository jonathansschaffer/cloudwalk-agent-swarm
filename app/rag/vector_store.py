"""
ChromaDB vector store wrapper.
Handles creation, indexing, and similarity search of document embeddings.
"""

import logging
import os
from typing import Optional

import chromadb
from chromadb import Collection

from app.config import CHROMA_DB_PATH, COLLECTION_NAME, TOP_K_RETRIEVAL
from app.rag.embedder import embed_texts, embed_query

logger = logging.getLogger(__name__)

_collection: Optional[Collection] = None


def _get_collection() -> Collection:
    """Lazy-initialises and returns the ChromaDB collection.

    Re-initialises if the cached collection becomes invalid (e.g. after a
    SQLite lock is released when a competing process exits).
    """
    global _collection
    if _collection is not None:
        # Validate cached collection is still accessible
        try:
            _collection.count()
            return _collection
        except Exception:
            logger.warning("Cached ChromaDB collection became invalid — reinitialising.")
            _collection = None

    os.makedirs(CHROMA_DB_PATH, exist_ok=True)
    client = chromadb.PersistentClient(path=CHROMA_DB_PATH)
    _collection = client.get_or_create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )
    logger.info(
        "ChromaDB collection '%s' ready (%d documents).",
        COLLECTION_NAME,
        _collection.count(),
    )
    return _collection


def get_document_count() -> int:
    """Returns the number of documents currently stored."""
    return _get_collection().count()


def add_documents(chunks: list[dict]) -> None:
    """
    Adds document chunks to the vector store.

    Args:
        chunks: List of {"content", "url", "title", "chunk_index"} dicts.
    """
    if not chunks:
        return

    collection = _get_collection()

    # Build batch inputs
    ids = [f"{c['url']}__chunk_{c['chunk_index']}" for c in chunks]
    documents = [c["content"] for c in chunks]
    metadatas = [
        {
            "url": c["url"],
            "title": c["title"],
            # Per-URL content hash — same value on every chunk from the same
            # URL. Used by the incremental pipeline to decide whether to
            # re-scrape/re-embed (see app/rag/pipeline.build_knowledge_base).
            "content_hash": c.get("content_hash", ""),
        }
        for c in chunks
    ]

    # Generate embeddings in one batch
    logger.info("Generating embeddings for %d chunks...", len(chunks))
    embeddings = embed_texts(documents)

    # ChromaDB recommends batches of ≤ 5000
    batch_size = 500
    for i in range(0, len(ids), batch_size):
        collection.add(
            ids=ids[i : i + batch_size],
            documents=documents[i : i + batch_size],
            embeddings=embeddings[i : i + batch_size],
            metadatas=metadatas[i : i + batch_size],
        )
        logger.info("Indexed batch %d–%d.", i, min(i + batch_size, len(ids)))

    logger.info("Successfully indexed %d chunks.", len(chunks))


def similarity_search(query: str, k: int = TOP_K_RETRIEVAL) -> list[dict]:
    """
    Finds the top-k most relevant chunks for a query.

    Args:
        query: The user's question in natural language.
        k:     Number of results to return.

    Returns:
        List of {"content": str, "source_url": str, "title": str} dicts.
    """
    collection = _get_collection()

    if collection.count() == 0:
        logger.warning("Vector store is empty — no results can be returned.")
        return []

    query_vector = embed_query(query)

    results = collection.query(
        query_embeddings=[query_vector],
        n_results=min(k, collection.count()),
        include=["documents", "metadatas", "distances"],
    )

    output = []
    for doc, meta, dist in zip(
        results["documents"][0],
        results["metadatas"][0],
        results["distances"][0],
    ):
        output.append(
            {
                "content": doc,
                "source_url": meta.get("url", ""),
                "title": meta.get("title", ""),
                "similarity_score": round(1 - dist, 4),  # cosine distance → similarity
            }
        )

    return output


def get_indexed_url_hashes() -> dict[str, str]:
    """Returns {url: content_hash} for every URL currently indexed.

    Used by the incremental pipeline: if the freshly-scraped hash matches what
    we already stored, we skip re-chunking + re-embedding that URL entirely.
    """
    collection = _get_collection()
    if collection.count() == 0:
        return {}
    try:
        data = collection.get(include=["metadatas"])
    except Exception as exc:
        logger.warning("Failed to enumerate existing metadatas: %s", exc)
        return {}
    out: dict[str, str] = {}
    for meta in data.get("metadatas", []) or []:
        if not meta:
            continue
        url = meta.get("url")
        h = meta.get("content_hash") or ""
        if url and url not in out:
            out[url] = h
    return out


def delete_by_url(url: str) -> int:
    """Removes every chunk belonging to a given URL. Returns deletion count."""
    collection = _get_collection()
    try:
        existing = collection.get(where={"url": url}, include=[])
        ids = existing.get("ids") or []
        if not ids:
            return 0
        collection.delete(ids=ids)
        return len(ids)
    except Exception as exc:
        logger.warning("delete_by_url(%s) failed: %s", url, exc)
        return 0


def reset_collection() -> None:
    """Deletes all documents from the collection (for re-indexing)."""
    global _collection
    os.makedirs(CHROMA_DB_PATH, exist_ok=True)
    client = chromadb.PersistentClient(path=CHROMA_DB_PATH)
    try:
        client.delete_collection(COLLECTION_NAME)
        logger.info("Collection '%s' deleted.", COLLECTION_NAME)
    except Exception:
        pass
    _collection = None
