"""
Escalation Agent (4th Agent): handles human redirect requests.
Generates empathetic escalation messages with context for human agents.
"""

import logging
from anthropic import Anthropic
from app.config import ANTHROPIC_API_KEY, LLM_MODEL
from app.database import mock_tickets

logger = logging.getLogger(__name__)

_client: Anthropic | None = None


def _get_client() -> Anthropic:
    global _client
    if _client is None:
        _client = Anthropic(api_key=ANTHROPIC_API_KEY)
    return _client


_ESCALATION_PROMPT = """You are an empathetic customer service representative for InfinitePay. \
A customer needs to be connected to a human support agent.

Context:
- Customer ID: {user_id}
- Customer's original message: "{message}"
- Previous investigation summary: {investigation_summary}

Your task: Write a warm, professional escalation message that:
1. Acknowledges the customer's situation with empathy
2. Explains that a specialized human agent will assist them
3. Provides our human support contact information:
   - Email: suporte@infinitepay.io
   - Phone: 0800-722-0803 (Monday to Friday, 9am–6pm BRT)
   - Chat: Available at app.infinitepay.io (24/7)
4. Mentions their escalation ticket number: {ticket_id}
5. Gives an estimated response time (within 2 hours during business hours)

**CRITICAL**: Write the ENTIRE response in {language}. \
If language is "pt", write in Brazilian Portuguese. If "en", write in English.

Be warm, concise (3-4 short paragraphs), and reassuring."""


def run(
    message: str,
    user_id: str,
    language: str = "en",
    investigation_summary: str = "",
) -> dict:
    """
    Generates an escalation response and creates an escalation ticket.

    Args:
        message:                The customer's original message.
        user_id:                The customer's unique identifier.
        language:               Detected language ("pt" or "en").
        investigation_summary:  What the support agent already tried/found.

    Returns:
        {"response": str, "ticket_id": str}
    """
    # Create an escalation ticket
    ticket = mock_tickets.create_ticket(
        user_id=user_id,
        issue=f"Escalated: {message[:200]}",
        priority="high",
    )
    ticket_id = ticket["ticket_id"]
    lang_name = "pt" if language == "pt" else "en"

    prompt = _ESCALATION_PROMPT.format(
        user_id=user_id,
        message=message[:300],
        investigation_summary=investigation_summary or "No prior investigation.",
        ticket_id=ticket_id,
        language=lang_name,
    )

    try:
        client = _get_client()
        response = client.messages.create(
            model=LLM_MODEL,
            max_tokens=512,
            messages=[{"role": "user", "content": prompt}],
        )
        response_text = response.content[0].text.strip()
    except Exception as exc:
        logger.error("Escalation Agent error: %s", exc)
        if language == "pt":
            response_text = (
                f"Entendemos a sua situação e lamentamos o inconveniente. "
                f"Um agente especializado da InfinitePay entrará em contato com você em breve.\n\n"
                f"Seu ticket de atendimento: **{ticket_id}**\n"
                f"Entre em contato: suporte@infinitepay.io | 0800-722-0803"
            )
        else:
            response_text = (
                f"We understand your situation and apologize for the inconvenience. "
                f"A specialized InfinitePay agent will be in touch shortly.\n\n"
                f"Your support ticket: **{ticket_id}**\n"
                f"Contact us: suporte@infinitepay.io | 0800-722-0803"
            )

    logger.info("Escalation ticket created: %s for user: %s", ticket_id, user_id)
    return {"response": response_text, "ticket_id": ticket_id}
