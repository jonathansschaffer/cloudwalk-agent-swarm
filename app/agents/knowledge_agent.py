"""
Knowledge Agent: handles product/service questions (RAG) and general questions (web search).
Uses a ReAct loop via LangChain's tool-calling agent.
"""

import logging
from langchain_anthropic import ChatAnthropic
from langchain.agents import create_tool_calling_agent, AgentExecutor
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.messages import SystemMessage

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
- Be friendly and professional."""

_agent_executor: AgentExecutor | None = None


def _get_agent_executor() -> AgentExecutor:
    global _agent_executor
    if _agent_executor is None:
        llm = ChatAnthropic(
            model=LLM_MODEL,
            api_key=ANTHROPIC_API_KEY,
            max_tokens=LLM_MAX_TOKENS,
            temperature=LLM_TEMPERATURE,
        )

        tools = [infinitepay_knowledge_base, web_search]

        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", KNOWLEDGE_SYSTEM_PROMPT),
                ("human", "{input}"),
                MessagesPlaceholder("agent_scratchpad"),
            ]
        )

        agent = create_tool_calling_agent(llm, tools, prompt)
        _agent_executor = AgentExecutor(
            agent=agent,
            tools=tools,
            verbose=False,
            max_iterations=5,
            handle_parsing_errors=True,
        )
        logger.info("Knowledge Agent initialized.")
    return _agent_executor


def run(message: str) -> str:
    """
    Runs the Knowledge Agent on a user message.

    Args:
        message: The user's question (product or general).

    Returns:
        The agent's answer as a string.
    """
    executor = _get_agent_executor()
    try:
        result = executor.invoke({"input": message})
        return result.get("output", "I was unable to find an answer. Please contact our support team.")
    except Exception as exc:
        logger.error("Knowledge Agent error: %s", exc)
        return (
            "I encountered an error while looking up the information. "
            "Please try again or contact InfinitePay support at suporte@infinitepay.io"
        )
