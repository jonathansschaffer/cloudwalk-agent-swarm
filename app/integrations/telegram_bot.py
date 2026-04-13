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
import html
import logging
import re
import textwrap
from concurrent.futures import ThreadPoolExecutor

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

# Serializes agent calls — prevents concurrent Anthropic API requests from
# multiple simultaneous Telegram messages hitting rate limits or connection errors.
_AGENT_EXECUTOR = ThreadPoolExecutor(max_workers=1)

# ---------------------------------------------------------------------------
# Markdown → Telegram HTML converter
# ---------------------------------------------------------------------------

def _inline_to_html(text: str) -> str:
    """Convert inline Markdown (bold, italic, code, links) to Telegram HTML."""
    # Stash inline code spans so their content is not further processed
    stash: dict[str, str] = {}

    def _stash_code(m: re.Match) -> str:
        key = f"\x01{len(stash)}\x01"
        stash[key] = f"<code>{html.escape(m.group(1))}</code>"
        return key

    text = re.sub(r"`([^`\n]+)`", _stash_code, text)

    # Escape HTML special chars in the remaining text
    text = html.escape(text)

    # Bold: **…** or __…__
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text, flags=re.DOTALL)
    text = re.sub(r"__(.+?)__", r"<b>\1</b>", text, flags=re.DOTALL)

    # Italic: *…* or _…_ (avoid word-boundary _ false matches)
    text = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"<i>\1</i>", text)
    text = re.sub(r"(?<!\w)_(?!_)(.+?)(?<!_)_(?!\w)", r"<i>\1</i>", text)

    # Links: [text](url)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', text)

    # Restore code stash
    for key, val in stash.items():
        text = text.replace(html.escape(key), val)
        text = text.replace(key, val)

    return text


def _table_to_text(table_lines: list[str]) -> str:
    """Convert a Markdown table to readable text for Telegram (no HTML tables)."""
    parsed: list[list[str]] = []
    for row in table_lines:
        # Skip separator rows: |---|---|
        if re.match(r"^\s*\|[\s\-:|]+\|\s*$", row):
            continue
        cells = [c.strip() for c in row.strip().strip("|").split("|")]
        parsed.append(cells)

    if not parsed:
        return ""

    lines: list[str] = []
    for idx, cells in enumerate(parsed):
        converted = [_inline_to_html(c) for c in cells]
        if idx == 0:
            lines.append("<b>" + " | ".join(converted) + "</b>")
        else:
            lines.append(" | ".join(converted))
    return "\n".join(lines)


def _line_to_html(line: str) -> str:
    """Convert a single non-table Markdown line to Telegram HTML."""
    # Horizontal rule
    if re.match(r"^\s*-{3,}\s*$", line):
        return ""

    # ATX headers: #, ##, ###
    m = re.match(r"^(#{1,6})\s+(.*)", line)
    if m:
        return "<b>" + _inline_to_html(m.group(2)) + "</b>"

    # Blockquote
    if line.startswith("> "):
        return "<blockquote>" + _inline_to_html(line[2:]) + "</blockquote>"

    # Unordered list
    m = re.match(r"^(\s*)[-*+]\s+(.*)", line)
    if m:
        depth = len(m.group(1)) // 2
        return "  " * depth + "• " + _inline_to_html(m.group(2))

    # Ordered list
    m = re.match(r"^(\s*)\d+\.\s+(.*)", line)
    if m:
        return _inline_to_html(m.group(2))

    return _inline_to_html(line)


def _md_to_html(text: str) -> str:
    """
    Convert a Markdown-formatted agent response to Telegram-compatible HTML.
    Handles: headers, bold, italic, code blocks, tables, blockquotes, lists, HR.
    """
    lines = text.split("\n")
    out: list[str] = []
    i = 0

    while i < len(lines):
        line = lines[i]

        # Fenced code block
        if line.strip().startswith("```"):
            code: list[str] = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                code.append(html.escape(lines[i]))
                i += 1
            out.append("<pre>" + "\n".join(code) + "</pre>")
            i += 1  # skip closing ```
            continue

        # Markdown table
        if re.match(r"^\s*\|", line):
            table: list[str] = []
            while i < len(lines) and re.match(r"^\s*\|", lines[i]):
                table.append(lines[i])
                i += 1
            out.append(_table_to_text(table))
            continue

        out.append(_line_to_html(line))
        i += 1

    return "\n".join(out)


# ---------------------------------------------------------------------------
# Agent badge labels for each agent type
# ---------------------------------------------------------------------------

_AGENT_LABELS = {
    "knowledge_agent": "🔍 Knowledge Agent",
    "support_agent": "🛠️ Support Agent",
    "escalation_agent": "🚨 Atendimento Humano",
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
        # process_message is synchronous/blocking — run in the dedicated executor.
        # Using max_workers=1 serializes calls so only one Anthropic API request
        # is in flight at a time, preventing rate-limit errors under concurrent load.
        loop = asyncio.get_running_loop()
        state = await loop.run_in_executor(_AGENT_EXECUTOR, process_message, user_text, user_id)
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

    # Convert Markdown to Telegram HTML so bold, headers, tables render properly
    html_body = _md_to_html(response_text)

    agent_label = _AGENT_LABELS.get(agent_used, html.escape(agent_used))
    footer = f"\n\n— {agent_label}"

    if ticket_id:
        footer += f"\n🎫 Ticket: {html.escape(str(ticket_id))}"

    if escalated and agent_used != "escalation_agent":
        footer += "\n\n⚠️ Esta conversa foi encaminhada para nossa equipe humana."

    full_message = html_body + footer

    # Telegram has a 4096 character limit per message
    if len(full_message) > 4000:
        full_message = full_message[:3990] + "\n\n[mensagem truncada]"

    await _safe_reply(update, full_message, parse_mode=ParseMode.HTML)


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
