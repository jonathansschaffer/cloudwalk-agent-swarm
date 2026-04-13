"""
CLI script to build (or rebuild) the InfinitePay knowledge base.

Usage:
    python scripts/build_knowledge_base.py            # build if empty
    python scripts/build_knowledge_base.py --rebuild  # force full rebuild
    python scripts/build_knowledge_base.py --no-cache # skip scraping cache
"""

import sys
import argparse
import logging

# Add project root to path
sys.path.insert(0, ".")

from app.utils.logger import setup_logging
from app.config import validate_config
from app.rag.pipeline import build_knowledge_base
from app.rag.scraper import scrape_all_urls

setup_logging()
logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the InfinitePay RAG knowledge base.")
    parser.add_argument(
        "--rebuild",
        action="store_true",
        help="Force a complete rebuild, deleting existing data.",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Ignore scraping cache and re-scrape all URLs.",
    )
    args = parser.parse_args()

    validate_config()

    if args.no_cache:
        import os
        from app.config import SCRAPED_CACHE_PATH
        cache_file = os.path.join(SCRAPED_CACHE_PATH, "scraped_documents.json")
        if os.path.exists(cache_file):
            os.remove(cache_file)
            logger.info("Scraping cache cleared.")

    logger.info("Starting knowledge base build (force_rebuild=%s)...", args.rebuild)
    doc_count = build_knowledge_base(force_rebuild=args.rebuild)

    if doc_count > 0:
        logger.info("SUCCESS: Knowledge base built with %d document chunks.", doc_count)
    else:
        logger.error("FAILED: No documents were indexed. Check logs above for errors.")
        sys.exit(1)


if __name__ == "__main__":
    main()
