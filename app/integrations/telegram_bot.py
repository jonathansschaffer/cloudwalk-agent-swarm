"""
Telegram Bot Integration for the InfinitePay Agent Swarm.

Runs as a background task within the FastAPI lifespan using long polling
(no public HTTPS URL required). Each Telegram user is assigned a unique
user_id prefixed with 'tg_' so they interact with the mock CRM system.

Setup:
    1. Create a bot via @BotFather on Telegram
    2. Copy the token to TELEGRAM_BOT_TOKEN in your .env file
    3. Restart the server — the bot starts automatically

Commands:
    /start  — Welcome message with usage instructions
    /help   — Example questions and available features
"""

import asyncio
import logging
import textwrap

from telegram import Update
from telegram.constants import ParseMode
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

_WELCOME_MESSAGE = textwrap.dedent("""
    👋 *Olá! Bem-vindo ao InfinitePay Agent Swarm!*

    Sou um assistente inteligente da InfinitePay. Posso ajudar com:

    • 💳 *Produtos e taxas* — Maquininha, Pix, Conta Digital, etc.
    • 🔧 *Suporte à conta* — problemas de login, transferências, bloqueios
    • 🌐 *Perguntas gerais* — notícias, esportes, informações do dia a dia
    • 🤝 *Escalação* — precisa falar com um humano? É só pedir!

    Use /help para ver exemplos de perguntas.

    _Pode me perguntar em português ou inglês!_ 🇧🇷🇺🇸
""").strip()

_HELP_MESSAGE = textwrap.dedent("""
    📋 *Exemplos de perguntas que posso responder:*

    💳 *Sobre InfinitePay:*
    • "Quais as taxas da Maquininha Smart?"
    • "Como funciona o Pix Parcelado?"
    • "O que é a Conta Digital InfinitePay?"
    • "What are the fees for credit card payments?"

    🔧 *Suporte à conta:*
    • "Não consigo fazer transferências"
    • "Minha conta está bloqueada"
    • "I can't sign in to my account"

    🌐 *Perguntas gerais:*
    • "Qual o resultado do último jogo do Palmeiras?"
    • "Quais as principais notícias de hoje?"

    🤝 *Escalação:*
    • "Quero falar com um atendente humano"
    • "I need to speak with a human agent"

    _Basta digitar sua pergunta normalmente!_
""").strip()


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the /start command — sends the welcome message."""
    await update.message.reply_text(_WELCOME_MESSAGE, parse_mode=ParseMode.MARKDOWN)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the /help command — sends usage examples."""
    await update.message.reply_text(_HELP_MESSAGE, parse_mode=ParseMode.MARKDOWN)


# ---------------------------------------------------------------------------
# Message handler
# ---------------------------------------------------------------------------

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Processes any text message through the Agent Swarm and replies.

    The user_id is derived from the Telegram user ID to ensure each
    user has a consistent session. A typing indicator is shown while
    the agent processes the request.
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
        # process_message is synchronous and CPU/IO bound — run in thread pool
        loop = asyncio.get_event_loop()
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

    # Compose footer with agent badge
    agent_label = _AGENT_LABELS.get(agent_used, agent_used)
    footer_parts = [f"\n\n— _{agent_label}_"]

    if ticket_id:
        footer_parts.append(f"\n🎫 *Ticket criado:* `{ticket_id}`")

    if escalated and agent_used != "escalation_agent":
        footer_parts.append(
            "\n\n⚠️ _Esta conversa foi escalada para nossa equipe humana._"
        )

    full_message = response_text + "".join(footer_parts)

    # Telegram has a 4096 character limit per message
    if len(full_message) > 4000:
        full_message = full_message[:3990] + "\n\n_[mensagem truncada]_"

    await update.message.reply_text(full_message, parse_mode=ParseMode.MARKDOWN)


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

    return application
