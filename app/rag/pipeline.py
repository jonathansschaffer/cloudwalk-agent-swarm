"""
RAG pipeline orchestrator.
Runs the full scrape → chunk → embed → store sequence.
"""

import logging
from app.rag.scraper import scrape_all_urls
from app.rag.chunker import split_documents
from app.rag.vector_store import add_documents, get_document_count, reset_collection
from app.config import INFINITEPAY_URLS

logger = logging.getLogger(__name__)


def build_knowledge_base(force_rebuild: bool = False) -> int:
    """
    Builds the vector store knowledge base from InfinitePay URLs.

    Steps:
        1. Check if knowledge base already exists (skip if not force_rebuild).
        2. Scrape all InfinitePay pages.
        3. Split scraped text into chunks.
        4. Generate embeddings and store in ChromaDB.

    Args:
        force_rebuild: If True, wipes existing data before rebuilding.

    Returns:
        Total number of indexed document chunks.
    """
    if not force_rebuild and get_document_count() > 0:
        count = get_document_count()
        logger.info("Knowledge base already populated (%d documents). Skipping build.", count)
        return count

    if force_rebuild:
        logger.info("Force rebuild requested — clearing existing knowledge base.")
        reset_collection()

    logger.info("=== Building Knowledge Base ===")
    logger.info("Step 1/3: Scraping %d URLs...", len(INFINITEPAY_URLS))
    documents = scrape_all_urls()

    if not documents:
        logger.error("No documents scraped. Aborting knowledge base build.")
        return 0

    logger.info("Step 2/3: Splitting %d documents into chunks...", len(documents))
    chunks = split_documents(documents)

    logger.info("Step 3/3: Indexing %d chunks into ChromaDB...", len(chunks))
    add_documents(chunks)

    total = get_document_count()
    logger.info("=== Knowledge Base Ready: %d documents indexed. ===", total)
    return total
