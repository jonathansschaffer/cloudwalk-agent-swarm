"""
Customer Support Agent: handles account issues using CRM tools.
Uses LangGraph's create_react_agent with three tools.
"""

import logging
import re
import threading
from langchain_anthropic import ChatAnthropic
from tenacity import retry, stop_after_attempt, wait_exponential, before_sleep_log
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.prebuilt import create_react_agent

from app.config import ANTHROPIC_API_KEY, LLM_MODEL, LLM_MAX_TOKENS, LLM_TEMPERATURE
from app.tools.account_tools import lookup_account_status, get_transaction_history, create_support_ticket

logger = logging.getLogger(__name__)

SUPPORT_SYSTEM_PROMPT = """You are a customer support specialist for InfinitePay, a Brazilian fintech. \
Your goal is to diagnose and resolve account-related issues for customers.

## Your Tools
1. **lookup_account_status**: ALWAYS call this first. Returns account status, KYC verification, \
   transfer limits, and diagnostic hints about the customer's account.
2. **get_transaction_history**: Use when the customer reports issues with payments, transfers, \
   missing transactions, or unexpected charges.
3. **create_support_ticket**: Use when the issue requires manual review by the support team \
   and cannot be resolved automatically.

## Workflow
1. Always start by calling `lookup_account_status` with the provided user_id.
2. Analyze the account data and diagnostic hints to understand the root cause.
3. If the issue involves transactions, call `get_transaction_history`.
4. Provide a clear, specific explanation of what you found and what the customer can do.
5. If the issue cannot be resolved automatically, create a support ticket with `create_support_ticket`.

## Escalation
If the customer's issue is very complex, requires human judgment, or the customer is very frustrated,
include the text "ESCALATE_TO_HUMAN" at the very end of your response (on its own line).

## Rules
- **CRITICAL**: Always respond in the EXACT SAME LANGUAGE as the user's message. \
  Portuguese message → respond in Portuguese. English message → respond in English.
- Be empathetic and professional. Acknowledge the customer's frustration.
- Always give specific, actionable next steps based on actual account data.
- Never invent account data — only use what the tools return.
- When creating a ticket, always tell the customer the ticket number and estimated resolution time."""

_agent = None
_agent_lock = threading.Lock()

_ERROR_MESSAGES = {
    "pt": (
        "Estou com dificuldades para acessar os detalhes da sua conta agora. "
        "Por favor, entre em contato com nossa equipe de suporte em suporte@infinitepay.io "
        "ou ligue para 0800-722-0803."
    ),
    "en": (
        "I'm having trouble accessing your account details right now. "
        "Please contact our support team directly at suporte@infinitepay.io "
        "or call 0800-722-0803."
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
                tools = [lookup_account_status, get_transaction_history, create_support_ticket]
                _agent = create_react_agent(llm, tools, prompt=SUPPORT_SYSTEM_PROMPT)
                logger.info("Support Agent initialized.")
    return _agent


def run(message: str, user_id: str, language: str = "en", history: list[dict] | None = None) -> dict:
    """
    Runs the Customer Support Agent on a user message.

    Args:
        message:  The user's support request.
        user_id:  The customer's unique identifier.
        language: Detected language ("pt" or "en") for error messages.

    Returns:
        {"response": str, "escalate": bool, "ticket_id": str | None}
    """
    agent = _get_agent()
    lang_name = {"pt": "Portuguese (Brazilian)", "en": "English"}.get(language, "English")
    full_input = (
        f"Customer ID: {user_id}\n"
        f"[Respond strictly in {lang_name}.]\n"
        f"Customer message: {message}"
    )

    prior: list = []
    for turn in (history or [])[-3:]:
        u = (turn.get("user") or "")[:500]
        b = (turn.get("bot") or "")[:500]
        if u:
            prior.append(HumanMessage(content=u))
        if b:
            prior.append(AIMessage(content=b))

    try:
        result = _invoke_with_retry(
            agent,
            {"messages": prior + [HumanMessage(content=full_input)]},
        )
        response_text: str = result["messages"][-1].content

        # Check for escalation flag
        escalate = "ESCALATE_TO_HUMAN" in response_text
        if escalate:
            response_text = response_text.replace("ESCALATE_TO_HUMAN", "").strip()

        # Extract ticket ID if present
        ticket_id = None
        match = re.search(r"TKT-\d{8}-[A-Z0-9]{6}", response_text)
        if match:
            ticket_id = match.group(0)

        return {
            "response": response_text,
            "escalate": escalate,
            "ticket_id": ticket_id,
        }

    except Exception as exc:
        logger.error("Support Agent error after retries: %s", exc)
        return {
            "response": _ERROR_MESSAGES.get(language, _ERROR_MESSAGES["en"]),
            "escalate": True,
            "ticket_id": None,
        }
