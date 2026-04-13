"""
Telegram Bot Integration for the InfinitePay Agent Swarm.

Runs as a background task within the FastAPI lifespan using long polling
(no public HTTPS URL required). Each Telegram user is assigned a unique
user_id prefixed with 'tg_' so they interact with the mock CRM system.

Setup:
    1. Create a bot via @BotFather on Telegram
    2. Copy the token to TELEGRAM_BOT_TOKEN in your .env file
    3. Restart the server — the bot starts automatically

Bot: @CloudWalk_Challenge_Bot

Commands:
    /start  — Welcome message with usage instructions
    /help   — Example questions and available features
"""

import asyncio
import logging
import textwrap

from telegram import Update
from telegram.constants import ParseMode
from telegram.error import TelegramError
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from app.agents.router_agent import process_message

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Agent badge labels for each agent type
# ---------------------------------------------------------------------------

_AGENT_LABELS = {
    "knowledge_agent": "🔍 Knowledge Agent",
    "support_agent": "🛠️ Support Agent",
    "escalation_agent": "🚨 Escalation Agent",
    "guardrails": "🛡️ Guardrails",
}

# Use HTML parse mode — more reliable than Markdown for messages with emojis
_WELCOME_MESSAGE = textwrap.dedent("""
    👋 Olá! Sou o assistente da <b>InfinitePay</b>.

    Pergunte sobre produtos, taxas, sua conta ou qualquer coisa — em português ou inglês.

    Use /help para ver exemplos.
""").strip()

_HELP_MESSAGE = textwrap.dedent("""
    📋 <b>Exemplos de perguntas que posso responder:</b>

    💳 <b>Sobre InfinitePay:</b>
    • "Quais as taxas da Maquininha Smart?"
    • "Como funciona o Pix Parcelado?"
    • "O que é a Conta Digital InfinitePay?"
    • "What are the fees for credit card payments?"

    🔧 <b>Suporte à conta:</b>
    • "Não consigo fazer transferências"
    • "Minha conta está bloqueada"
    • "I can't sign in to my account"

    🌐 <b>Perguntas gerais:</b>
    • "Qual o resultado do último jogo do Santos?"
    • "Quais as principais notícias de hoje?"

    🤝 <b>Escalação:</b>
    • "Quero falar com um atendente humano"
    • "I need to speak with a human agent"

    <i>Basta digitar sua pergunta normalmente!</i>
""").strip()


# ---------------------------------------------------------------------------
# Helper: send message with Markdown fallback to plain text
# ---------------------------------------------------------------------------

async def _safe_reply(update: Update, text: str, parse_mode: str | None = None) -> None:
    """
    Sends a reply with the given parse mode, falling back to plain text on error.

    Args:
        update:     Telegram update object.
        text:       Message text to send.
        parse_mode: ParseMode.HTML, ParseMode.MARKDOWN, or None (plain text).
    """
    try:
        await update.message.reply_text(text, parse_mode=parse_mode)
    except TelegramError as exc:
        if parse_mode is None:
            logger.error("Failed to send plain text reply: %s", exc)
            return
        logger.warning("Failed to send with parse_mode=%s (%s). Retrying as plain text.", parse_mode, exc)
        try:
            await update.message.reply_text(text)
        except TelegramError as exc2:
            logger.error("Failed to send plain text fallback reply: %s", exc2)


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the /start command — sends the welcome message."""
    await _safe_reply(update, _WELCOME_MESSAGE, parse_mode=ParseMode.HTML)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the /help command — sends usage examples."""
    await _safe_reply(update, _HELP_MESSAGE, parse_mode=ParseMode.HTML)


# ---------------------------------------------------------------------------
# Message handler
# ---------------------------------------------------------------------------

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Processes any text message through the Agent Swarm and replies.

    The user_id is derived from the Telegram user ID to ensure each
    user has a consistent session. A typing indicator is shown while
    the agent processes the request (process_message is synchronous,
    so it runs in a thread pool to avoid blocking the event loop).
    """
    user_text = update.message.text
    telegram_user_id = update.effective_user.id
    user_id = f"tg_{telegram_user_id}"

    logger.info("Telegram message from user=%s: %s", user_id, user_text[:80])

    # Show "typing..." indicator
    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id,
        action="typing",
    )

    try:
        # process_message is synchronous/blocking — run in thread pool
        # Use get_running_loop() (not deprecated get_event_loop()) to get
        # the loop that is actually running this coroutine
        loop = asyncio.get_running_loop()
        state = await loop.run_in_executor(None, process_message, user_text, user_id)
    except Exception as exc:
        logger.error("Agent Swarm error for Telegram user %s: %s", user_id, exc)
        await update.message.reply_text(
            "⚠️ Ocorreu um erro ao processar sua mensagem. "
            "Tente novamente ou acesse suporte@infinitepay.io"
        )
        return

    # Build the reply
    response_text = state.get("response", "")
    agent_used = state.get("agent_used", "")
    ticket_id = state.get("ticket_id")
    escalated = state.get("escalated", False)

    # Compose footer with agent badge (plain text — no parse mode to avoid
    # issues with markdown symbols like %, |, >, * in agent responses)
    agent_label = _AGENT_LABELS.get(agent_used, agent_used)
    footer_parts = [f"\n\n— {agent_label}"]

    if ticket_id:
        footer_parts.append(f"\n🎫 Ticket criado: {ticket_id}")

    if escalated and agent_used != "escalation_agent":
        footer_parts.append("\n\n⚠️ Esta conversa foi escalada para nossa equipe humana.")

    full_message = response_text + "".join(footer_parts)

    # Telegram has a 4096 character limit per message
    if len(full_message) > 4000:
        full_message = full_message[:3990] + "\n\n[mensagem truncada]"

    # Send as plain text (no parse_mode) — agent responses contain markdown
    # tables, %, |, > characters that would break HTML or Markdown parsing
    await _safe_reply(update, full_message, parse_mode=None)


# ---------------------------------------------------------------------------
# Error handler
# ---------------------------------------------------------------------------

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Logs all Telegram errors so they are visible in the server logs
    instead of being swallowed silently by the polling loop.
    """
    logger.error("Telegram bot encountered an error: %s", context.error, exc_info=context.error)


# ---------------------------------------------------------------------------
# Application builder
# ---------------------------------------------------------------------------

def build_application(token: str) -> Application:
    """
    Builds and configures the Telegram Application with all handlers.

    Args:
        token: The bot token from @BotFather.

    Returns:
        A configured (but not yet started) Application instance.
    """
    application = Application.builder().token(token).build()

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
    )
    application.add_error_handler(error_handler)

    return application
