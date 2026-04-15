"""
RAG pipeline orchestrator.
Runs the full scrape → chunk → embed → store sequence.
"""

import hashlib
import logging
from app.rag.scraper import scrape_all_urls
from app.rag.chunker import split_documents
from app.rag.vector_store import (
    add_documents,
    delete_by_url,
    get_document_count,
    get_indexed_url_hashes,
    reset_collection,
)
from app.config import INFINITEPAY_URLS

# ---------------------------------------------------------------------------
# Manually curated seed documents for pages that cannot be scraped
# (anti-scraping protection, JS-rendered content, or 404 redirects)
# ---------------------------------------------------------------------------
_SEED_DOCUMENTS: list[dict] = [
    {
        "url": "https://www.infinitepay.io/jim",
        "title": "JIM — Inteligência Artificial da InfinitePay",
        "content": (
            "JIM é a inteligência artificial da InfinitePay, disponível dentro do aplicativo. "
            "O JIM foi criado para facilitar o dia a dia financeiro dos usuários, "
            "especialmente na hora de fazer Pix. "
            "Com o JIM, você pode fazer Pix por mensagem de texto, áudio ou foto — "
            "o JIM interpreta as informações e realiza o pagamento automaticamente. "
            "O JIM suporta vários formatos: Pix Copia e Cola, QR Code, mensagem ou áudio. "
            "O processo é rápido e seguro: o JIM só conclui o Pix após você confirmar o valor e o destinatário. "
            "O JIM elimina a necessidade de digitar dados manualmente, tornando as transferências muito mais práticas. "
            "Além do Pix, o JIM também cria campanhas de marketing, faz pagamentos, "
            "lembra compromissos e fornece insights sobre o negócio. "
            "O JIM é um funcionário gratuito, focado 24h por dia em aumentar seu lucro. "
            "Para usar o JIM, basta acessar o aplicativo da InfinitePay."
        ),
    },
]

logger = logging.getLogger(__name__)


def _content_hash(content: str) -> str:
    """Stable per-URL fingerprint used by the incremental pipeline."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]


def _attach_hashes(documents: list[dict]) -> list[dict]:
    """Computes + attaches `content_hash` to every scraped document."""
    for d in documents:
        d["content_hash"] = _content_hash(d.get("content", ""))
    return documents


def build_knowledge_base(force_rebuild: bool = False, incremental: bool = False) -> int:
    """Builds (or refreshes) the vector-store knowledge base.

    Modes:
      * default — skip if already populated; full build when empty.
      * force_rebuild — wipe everything and re-index from scratch.
      * incremental — scrape, diff per-URL `content_hash` against the index,
        only re-chunk + re-embed URLs whose content changed. Safe to run on a
        populated KB; no-op for untouched URLs.
    """
    if not force_rebuild and not incremental and get_document_count() > 0:
        count = get_document_count()
        logger.info("Knowledge base already populated (%d documents). Skipping build.", count)
        return count

    if force_rebuild:
        logger.info("Force rebuild requested — clearing existing knowledge base.")
        reset_collection()

    logger.info("=== Building Knowledge Base (incremental=%s) ===", incremental)
    logger.info("Step 1/3: Scraping %d URLs...", len(INFINITEPAY_URLS))
    documents = scrape_all_urls()

    if not documents:
        logger.error("No documents scraped. Aborting knowledge base build.")
        return 0

    # Append manually curated seed documents only for URLs not already scraped
    scraped_urls = {doc["url"] for doc in documents}
    missing_seeds = [d for d in _SEED_DOCUMENTS if d["url"] not in scraped_urls]
    if missing_seeds:
        documents.extend(missing_seeds)
        logger.info("Added %d seed documents (manually curated).", len(missing_seeds))
    else:
        logger.info("All seed URLs already scraped — skipping seed injection.")

    _attach_hashes(documents)

    if incremental and not force_rebuild:
        existing = get_indexed_url_hashes()
        changed = [d for d in documents if existing.get(d["url"]) != d["content_hash"]]
        unchanged = len(documents) - len(changed)
        logger.info(
            "Incremental diff: %d URL(s) changed, %d unchanged — will re-embed only changed.",
            len(changed),
            unchanged,
        )
        if not changed:
            total = get_document_count()
            logger.info("=== Knowledge Base unchanged: %d documents. ===", total)
            return total
        # Wipe stale chunks for each changed URL, then re-chunk + add.
        for doc in changed:
            removed = delete_by_url(doc["url"])
            if removed:
                logger.info("Deleted %d stale chunks for %s.", removed, doc["url"])
        documents = changed

    logger.info("Step 2/3: Splitting %d documents into chunks...", len(documents))
    chunks = split_documents(documents)
    # Propagate the per-URL hash down to every chunk so the metadata survives.
    url_to_hash = {d["url"]: d["content_hash"] for d in documents}
    for c in chunks:
        c["content_hash"] = url_to_hash.get(c["url"], "")

    logger.info("Step 3/3: Indexing %d chunks into ChromaDB...", len(chunks))
    add_documents(chunks)

    total = get_document_count()
    logger.info("=== Knowledge Base Ready: %d documents indexed. ===", total)
    return total
