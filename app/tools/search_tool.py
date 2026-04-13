"""
Web search tool using DuckDuckGo (free, no API key required).
Used by the Knowledge Agent for general-purpose questions not covered by the knowledge base.
"""

import logging
from langchain_core.tools import tool

logger = logging.getLogger(__name__)


@tool
def web_search(query: str) -> str:
    """
    Search the web for general knowledge questions NOT related to InfinitePay products.

    Use this for: current events, sports results, news, weather, general facts,
    or any topic that is NOT about InfinitePay products or services.

    Do NOT use this for InfinitePay questions — use infinitepay_knowledge_base instead.

    Args:
        query: The search query.

    Returns:
        Search results as formatted text.
    """
    logger.info("Web search query: %s", query)
    try:
        try:
            from ddgs import DDGS
        except ImportError:
            from duckduckgo_search import DDGS

        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=5))

        if not results:
            return "No results found for this query."

        formatted = []
        for r in results:
            title = r.get("title", "")
            body = r.get("body", "")
            href = r.get("href", "")
            formatted.append(f"**{title}**\n{body}\nSource: {href}")

        return "\n\n".join(formatted)

    except Exception as exc:
        logger.error("Web search failed: %s", exc)
        return f"Web search is temporarily unavailable. Error: {exc}"
