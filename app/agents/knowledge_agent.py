"""
Knowledge Agent: handles product/service questions (RAG) and general questions (web search).
Uses LangGraph's create_react_agent with a ReAct loop.
"""

import logging
import threading
from datetime import date
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.prebuilt import create_react_agent
from tenacity import retry, stop_after_attempt, wait_exponential, before_sleep_log

from app.config import ANTHROPIC_API_KEY, LLM_MODEL, LLM_MAX_TOKENS, LLM_TEMPERATURE
from app.tools.rag_tool import infinitepay_knowledge_base
from app.tools.search_tool import web_search

logger = logging.getLogger(__name__)

KNOWLEDGE_SYSTEM_PROMPT = """You are a knowledgeable and helpful assistant for InfinitePay, \
a Brazilian fintech company. You help customers learn about InfinitePay's products and services, \
and you also answer general knowledge questions.

## Your Tools
1. **infinitepay_knowledge_base**: Use for ANY question about InfinitePay products, services, \
fees, features, or how things work. Always try this tool FIRST for InfinitePay topics.
2. **web_search**: Use for general knowledge questions NOT related to InfinitePay \
(e.g., sports results, current news, weather, general facts).

## Rules
- ALWAYS use `infinitepay_knowledge_base` for InfinitePay questions before attempting to answer from memory.
- ALWAYS use `web_search` for general questions (e.g., "Quando foi o último jogo do Palmeiras?").
- If the knowledge base returns no relevant results, say so honestly and suggest contacting support.
- **CRITICAL**: Always respond in the EXACT SAME LANGUAGE as the user's message. \
  If the user writes in Portuguese, respond entirely in Portuguese. \
  If the user writes in English, respond entirely in English. Never mix languages.
- Be concise and factual. Do not invent prices, fees, or features not found in the sources.
- When citing InfinitePay information, mention the source URL when available.
- Be friendly and professional.

## Date Awareness
The user's message will include the current date in a [Date] tag at the beginning. \
Use this to correctly interpret relative time expressions like "last weekend", "yesterday", \
"recently", "this week". When search results are from a different time period than the user \
asked about, explicitly acknowledge this and clarify the actual date of the information found.

## Web Search Strategy
When searching for recent sports results or news:
- First search: use the specific team/topic + "resultado" or "score"
- If results are incomplete or from the wrong date, search AGAIN with a more specific query \
  including the date (e.g., "Santos FC resultado abril 2026")
- Combine information from multiple search results when needed
- If after two searches you still cannot find specific details, say what you DID find \
  (partial info, approximate date) rather than giving up entirely."""

_agent = None
_agent_lock = threading.Lock()


def _get_agent():
    global _agent
    if _agent is None:
        with _agent_lock:
            if _agent is None:
                llm = ChatAnthropic(
                    model=LLM_MODEL,
                    api_key=ANTHROPIC_API_KEY,
                    max_tokens=LLM_MAX_TOKENS,
                    temperature=LLM_TEMPERATURE,
                )
                tools = [infinitepay_knowledge_base, web_search]
                _agent = create_react_agent(llm, tools, prompt=KNOWLEDGE_SYSTEM_PROMPT)
                logger.info("Knowledge Agent initialized.")
    return _agent


_ERROR_MESSAGES = {
    "pt": (
        "Encontrei um erro ao buscar as informações. "
        "Por favor, tente novamente ou entre em contato com o suporte em suporte@infinitepay.io"
    ),
    "en": (
        "I encountered an error while looking up the information. "
        "Please try again or contact InfinitePay support at suporte@infinitepay.io"
    ),
}


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    before_sleep=before_sleep_log(logger, logging.WARNING),
    reraise=True,
)
def _invoke_with_retry(agent, messages: dict) -> dict:
    """Calls agent.invoke() with up to 3 retries and exponential backoff."""
    return agent.invoke(messages)


def run(message: str, language: str = "en") -> str:
    """
    Runs the Knowledge Agent on a user message.

    Injects the current date into the message so the agent can correctly
    interpret relative time expressions ("last weekend", "yesterday", etc.)
    and validate that search results match the requested time period.

    Args:
        message:  The user's question (product or general).
        language: Detected language ("pt" or "en") for error messages.

    Returns:
        The agent's answer as a string.
    """
    agent = _get_agent()
    today = date.today().strftime("%A, %B %d, %Y")
    dated_message = f"[Date: {today}]\n\n{message}"
    try:
        result = _invoke_with_retry(agent, {"messages": [HumanMessage(content=dated_message)]})
        # The last message in the list is the final AI response
        last_message = result["messages"][-1]
        return last_message.content
    except Exception as exc:
        logger.error("Knowledge Agent error after retries: %s", exc)
        return _ERROR_MESSAGES.get(language, _ERROR_MESSAGES["en"])
