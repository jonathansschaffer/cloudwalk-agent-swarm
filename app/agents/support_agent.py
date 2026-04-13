"""
Customer Support Agent: handles account issues using CRM tools.
Uses a ReAct loop with three tools: account lookup, transaction history, and ticket creation.
"""

import logging
from langchain_anthropic import ChatAnthropic
from langchain.agents import create_tool_calling_agent, AgentExecutor
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

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

        tools = [lookup_account_status, get_transaction_history, create_support_ticket]

        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", SUPPORT_SYSTEM_PROMPT),
                ("human", "{input}"),
                MessagesPlaceholder("agent_scratchpad"),
            ]
        )

        agent = create_tool_calling_agent(llm, tools, prompt)
        _agent_executor = AgentExecutor(
            agent=agent,
            tools=tools,
            verbose=False,
            max_iterations=6,
            handle_parsing_errors=True,
        )
        logger.info("Support Agent initialized.")
    return _agent_executor


def run(message: str, user_id: str) -> dict:
    """
    Runs the Customer Support Agent on a user message.

    Args:
        message: The user's support request.
        user_id: The customer's unique identifier.

    Returns:
        {"response": str, "escalate": bool, "ticket_id": str | None}
    """
    executor = _get_agent_executor()
    full_input = f"Customer ID: {user_id}\nCustomer message: {message}"

    try:
        result = executor.invoke({"input": full_input})
        response_text: str = result.get("output", "")

        # Check for escalation flag
        escalate = "ESCALATE_TO_HUMAN" in response_text
        if escalate:
            response_text = response_text.replace("ESCALATE_TO_HUMAN", "").strip()

        # Extract ticket ID if present
        ticket_id = None
        if "TKT-" in response_text:
            import re
            match = re.search(r"TKT-\d{8}-[A-Z0-9]{6}", response_text)
            if match:
                ticket_id = match.group(0)

        return {
            "response": response_text,
            "escalate": escalate,
            "ticket_id": ticket_id,
        }

    except Exception as exc:
        logger.error("Support Agent error: %s", exc)
        return {
            "response": (
                "I'm having trouble accessing your account details right now. "
                "Please contact our support team directly at suporte@infinitepay.io "
                "or call 0800-XXX-XXXX."
            ),
            "escalate": True,
            "ticket_id": None,
        }
