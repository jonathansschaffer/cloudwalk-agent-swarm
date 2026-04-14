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

_DUPLICATE_TICKET_PROMPT = """You are an empathetic customer service representative for InfinitePay. \
A customer wants to escalate to a human agent, but they already have an open support ticket.

Context:
- Customer ID: {user_id}
- Customer's original message: "{message}"
- Existing open ticket number: {ticket_id}
- Ticket created recently (within the last 24 hours)

Your task: Write a warm, reassuring message that:
1. Acknowledges the customer's concern with empathy
2. Informs them that they already have an open ticket ({ticket_id}) being handled by our team
3. Assures them they do NOT need to open a new ticket — the existing one covers their case
4. Reminds them of our contact channels if they need urgent help:
   - Email: suporte@infinitepay.io
   - Phone: 0800-722-0803 (Monday to Friday, 9am–6pm BRT)
   - Chat: app.infinitepay.io (24/7)
5. Gives an estimated response time (within 2 hours during business hours)

**CRITICAL**: Write the ENTIRE response in {language}. \
If language is "pt", write in Brazilian Portuguese. If "en", write in English.

Be warm, concise (2-3 short paragraphs), and reassuring."""


def run(
    message: str,
    user_id: str,
    language: str = "en",
    investigation_summary: str = "",
) -> dict:
    """
    Generates an escalation response and creates (or reuses) an escalation ticket.

    If the user already has an open ticket from the last 24 hours, the existing
    ticket is referenced instead of creating a duplicate.

    Args:
        message:                The customer's original message.
        user_id:                The customer's unique identifier.
        language:               Detected language ("pt" or "en").
        investigation_summary:  What the support agent already tried/found.

    Returns:
        {"response": str, "ticket_id": str}
    """
    # Reuse an existing open ticket if one exists within the dedup window.
    ticket = mock_tickets.create_ticket(
        user_id=user_id,
        issue=f"Escalated: {message[:200]}",
        priority="high",
    )
    ticket_id = ticket["ticket_id"]
    is_duplicate = ticket.get("is_duplicate", False)
    lang_name = "Brazilian Portuguese" if language == "pt" else "English"

    if is_duplicate:
        prompt = _DUPLICATE_TICKET_PROMPT.format(
            user_id=user_id,
            message=message[:300],
            ticket_id=ticket_id,
            language=lang_name,
        )
        logger.info("Reusing existing open ticket %s for user %s (dedup)", ticket_id, user_id)
    else:
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
        if is_duplicate:
            if language == "pt":
                response_text = (
                    f"Você já possui um ticket de atendimento aberto: **{ticket_id}**.\n\n"
                    f"Nossa equipe está analisando o seu caso e entrará em contato em breve.\n"
                    f"Contato: suporte@infinitepay.io | 0800-722-0803"
                )
            else:
                response_text = (
                    f"You already have an open support ticket: **{ticket_id}**.\n\n"
                    f"Our team is reviewing your case and will be in touch shortly.\n"
                    f"Contact us: suporte@infinitepay.io | 0800-722-0803"
                )
        elif language == "pt":
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

    action = "reused" if is_duplicate else "created"
    logger.info("Escalation ticket %s: %s for user: %s", action, ticket_id, user_id)
    return {"response": response_text, "ticket_id": ticket_id}
