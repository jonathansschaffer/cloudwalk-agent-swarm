"""
RAG retrieval wrapped as a LangChain tool.
Used by the Knowledge Agent to query the InfinitePay knowledge base.
"""

import json
import logging
from langchain_core.tools import tool
from app.rag.vector_store import similarity_search

logger = logging.getLogger(__name__)


@tool
def infinitepay_knowledge_base(query: str) -> str:
    """
    Search the InfinitePay knowledge base for information about products, services,
    fees, features, tap-to-pay, maquininha, conta digital, PIX, cartão, empréstimo,
    PDV, link de pagamento, boleto, rendimento, gestão de cobrança, and loja online.

    Use this tool FIRST for any question related to InfinitePay products or services.
    Query in the same language as the user's message.

    Args:
        query: The search query about InfinitePay products/services.

    Returns:
        Relevant text excerpts from the InfinitePay website with source URLs.
    """
    logger.info("RAG search query: %s", query)
    results = similarity_search(query)

    if not results:
        return (
            "No relevant information found in the InfinitePay knowledge base for this query. "
            "The customer may need to contact InfinitePay support directly."
        )

    formatted_results = []
    for i, r in enumerate(results, 1):
        formatted_results.append(
            f"[Source {i}] ({r['source_url']})\n{r['content']}"
        )

    return "\n\n---\n\n".join(formatted_results)
