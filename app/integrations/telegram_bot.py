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
import time
import uuid
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
from app.config import WEB_APP_URL
from app.database.db import SessionLocal
from app.database.models import TelegramLink, TelegramLinkCode, User
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# Serializes agent calls — prevents concurrent Anthropic API requests from
# multiple simultaneous Telegram messages hitting rate limits or connection errors.
_AGENT_EXECUTOR = ThreadPoolExecutor(max_workers=1)

# ---------------------------------------------------------------------------
# Markdown → Telegram HTML converter
# ---------------------------------------------------------------------------

# Telegram HTML supports only these tags — anything else must be escaped
_TELEGRAM_SAFE_TAGS = frozenset(
    {"b", "strong", "i", "em", "u", "ins", "s", "strike", "del",
     "code", "pre", "a", "blockquote", "span", "br"}
)
# Matches any HTML/XML-like tag (opening, closing, self-closing)
_HTML_TAG_RE = re.compile(r"<(/?)([a-zA-Z][a-zA-Z0-9]*)([^>]*)>")


def _inline_to_html(text: str) -> str:
    """
    Convert inline Markdown to Telegram HTML.

    Also handles the case where the LLM already emitted HTML tags (e.g. <b>…</b>):
    valid Telegram tags are passed through unchanged; unknown tags are escaped.
    """
    # Stash inline code spans so their content is not further processed
    stash: dict[str, str] = {}

    def _stash_code(m: re.Match) -> str:
        key = f"\x01{len(stash)}\x01"
        stash[key] = f"<code>{html.escape(m.group(1))}</code>"
        return key

    text = re.sub(r"`([^`\n]+)`", _stash_code, text)

    # If the LLM already emitted HTML tags, handle text and tags separately
    # so we don't double-escape valid tags.
    if _HTML_TAG_RE.search(text):
        parts = _HTML_TAG_RE.split(text)
        # split() with a capturing group returns: [text, slash, name, attrs, text, …]
        out: list[str] = []
        i = 0
        while i < len(parts):
            chunk = parts[i]
            if i % 4 == 0:
                # Text fragment between tags — escape HTML special chars
                out.append(html.escape(chunk))
            else:
                # Reassemble the tag from its capture groups: slash, name, attrs
                slash = parts[i]       # group 1: "/" or ""
                name = parts[i + 1]    # group 2: tag name
                attrs = parts[i + 2]   # group 3: attributes
                i += 2
                if name.lower() in _TELEGRAM_SAFE_TAGS:
                    out.append(f"<{slash}{name}{attrs}>")
                else:
                    out.append(html.escape(f"<{slash}{name}{attrs}>"))
            i += 1
        text = "".join(out)
    else:
        # No HTML tags — safe to escape everything
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

_LANGUAGE_LABELS = {"pt": "🇧🇷 PT", "en": "🇺🇸 EN"}


def _normalize_blank_lines(text: str) -> str:
    """Collapse 3+ consecutive newlines into exactly 2 (one blank line)."""
    return re.sub(r"\n{3,}", "\n\n", text).strip()


# ---------------------------------------------------------------------------
# Telegram ↔ App user linking
# ---------------------------------------------------------------------------

def _resolve_linked_user(telegram_user_id: int) -> int | None:
    """Returns the App user_id linked to this Telegram account, or None."""
    with SessionLocal() as db:
        link = db.query(TelegramLink).filter(
            TelegramLink.telegram_user_id == str(telegram_user_id)
        ).one_or_none()
        return link.user_id if link else None


def _consume_link_code(code: str, telegram_user_id: int, telegram_username: str | None = None) -> tuple[bool, str]:
    """
    Validates and consumes a one-shot linking code.

    Returns (success, human_message).
    """
    code = code.strip().upper()
    if not re.fullmatch(r"[A-Z0-9]{6}", code):
        return False, "Código inválido. O formato esperado é 6 caracteres (A-Z, 0-9)."

    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        row = db.query(TelegramLinkCode).filter(TelegramLinkCode.code == code).one_or_none()
        if row is None:
            return False, "Código não encontrado. Gere um novo no app web."
        if row.used_at is not None:
            return False, "Este código já foi usado."
        # SQLite returns naive datetimes even if stored as UTC-aware. Normalize
        # both sides to aware-UTC before comparing so this doesn't crash on SQLite.
        expires_at = row.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at < now:
            return False, "Este código expirou. Gere um novo no app web."

        # Replace any existing link for this Telegram account
        existing = db.query(TelegramLink).filter(
            TelegramLink.telegram_user_id == str(telegram_user_id)
        ).one_or_none()
        if existing:
            db.delete(existing)
            db.flush()

        # Replace any existing link this user might already have to a different TG account
        prev = db.query(TelegramLink).filter(TelegramLink.user_id == row.user_id).one_or_none()
        if prev:
            db.delete(prev)
            db.flush()

        db.add(TelegramLink(
            telegram_user_id=str(telegram_user_id),
            user_id=row.user_id,
            linked_at=now,
            telegram_username=telegram_username,
        ))
        row.used_at = now
        user = db.query(User).filter(User.id == row.user_id).one()
        db.commit()
        return True, f"✅ Conta vinculada com sucesso a <b>{html.escape(user.name)}</b>."

# Use HTML parse mode — more reliable than Markdown for messages with emojis
_WELCOME_MESSAGE = textwrap.dedent(f"""
    👋 Olá! Sou o assistente da <b>InfinitePay</b>.

    Para conversar comigo aqui no Telegram, você precisa vincular sua conta InfinitePay primeiro:

    1️⃣ Acesse o app web: <a href="{WEB_APP_URL}">{WEB_APP_URL}</a>
    2️⃣ Faça login, vá em "Vincular Telegram" e gere um código de 6 caracteres
    3️⃣ Envie aqui: <code>/link SEU_CODIGO</code>

    Depois disso, é só perguntar — em português ou inglês.
    Use /help para exemplos.
""").strip()

_NOT_LINKED_MESSAGE = textwrap.dedent(f"""
    🔒 Sua conta do Telegram ainda não está vinculada a uma conta InfinitePay.

    Para vincular:
    1️⃣ Acesse o app web: <a href="{WEB_APP_URL}">{WEB_APP_URL}</a>
    2️⃣ Em "Vincular Telegram", gere um código
    3️⃣ Envie aqui: <code>/link SEU_CODIGO</code>
""").strip()

_HELP_MESSAGE = textwrap.dedent(f"""
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

    🤝 <b>Atendimento Humano:</b>
    • "Quero falar com um atendente humano"
    • "I need to speak with a human agent"

    <i>Basta digitar sua pergunta normalmente!</i>

    🌐 App web: <a href="{WEB_APP_URL}">{WEB_APP_URL}</a>
""").strip()


# ---------------------------------------------------------------------------
# Helper: send message with retry + HTML→plain fallback
# ---------------------------------------------------------------------------

async def _safe_reply(
    update: Update,
    text: str,
    parse_mode: str | None = None,
    msg_id: str = "",
) -> bool:
    """
    Sends a reply with up to 3 attempts.

    Attempt 1: original parse_mode (HTML)
    Attempt 2: plain text (strips all formatting — avoids invalid HTML rejections)
    Attempt 3: plain text after 2s delay (transient network error recovery)

    Returns True if message was delivered, False if all attempts failed.
    """
    # Strip HTML tags for the plain-text fallback
    plain_text = re.sub(r"<[^>]+>", "", text).strip()

    attempts = [
        (text, parse_mode),
        (plain_text, None),
    ]

    for attempt_num, (msg, mode) in enumerate(attempts, start=1):
        try:
            await update.message.reply_text(msg, parse_mode=mode)
            if attempt_num > 1:
                logger.info("[%s] Message delivered on attempt %d (plain text)", msg_id, attempt_num)
            return True
        except TelegramError as exc:
            logger.warning(
                "[%s] Send attempt %d/%d failed (parse_mode=%s): %s",
                msg_id, attempt_num, len(attempts), mode, exc,
            )
            if attempt_num < len(attempts):
                await asyncio.sleep(1.5)

    # Final fallback: wait and retry plain text once more
    try:
        await asyncio.sleep(2)
        await update.message.reply_text(plain_text)
        logger.info("[%s] Message delivered on final retry", msg_id)
        return True
    except TelegramError as exc:
        logger.error("[%s] All send attempts failed — message NOT delivered: %s", msg_id, exc)
        return False


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the /start command — sends the welcome message."""
    await _safe_reply(update, _WELCOME_MESSAGE, parse_mode=ParseMode.HTML, msg_id="start")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the /help command — sends usage examples."""
    await _safe_reply(update, _HELP_MESSAGE, parse_mode=ParseMode.HTML, msg_id="help")


async def link_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles /link <code> — pairs this Telegram account to an InfinitePay user."""
    args = context.args or []
    if not args:
        await _safe_reply(
            update,
            "Uso: <code>/link SEU_CODIGO</code>\n\nGere o código no app web em \"Vincular Telegram\".",
            parse_mode=ParseMode.HTML,
            msg_id="link",
        )
        return

    tg_user = update.effective_user
    success, message = _consume_link_code(args[0], tg_user.id, tg_user.username)
    await _safe_reply(update, message, parse_mode=ParseMode.HTML, msg_id="link")


# ---------------------------------------------------------------------------
# Message handler
# ---------------------------------------------------------------------------

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Processes any text message through the Agent Swarm and replies.

    Each message is assigned a correlation ID (msg_id) that appears in every
    log line, making it easy to trace a single conversation turn end-to-end
    (received → agent processing → reply sent / failed).
    """
    user_text = update.message.text
    telegram_user_id = update.effective_user.id
    msg_id = uuid.uuid4().hex[:8]  # short unique ID for log correlation
    start_ts = time.monotonic()

    linked_user_id = _resolve_linked_user(telegram_user_id)
    if linked_user_id is None:
        logger.info("[%s] REJECTED unlinked telegram_user=%s", msg_id, telegram_user_id)
        await _safe_reply(update, _NOT_LINKED_MESSAGE, parse_mode=ParseMode.HTML, msg_id=msg_id)
        return

    user_id = str(linked_user_id)
    logger.info("[%s] RECEIVED user=%s message='%s'", msg_id, user_id, user_text[:80])

    # Show "typing..." indicator and keep refreshing it every 4s while processing
    async def _keep_typing():
        while True:
            try:
                await context.bot.send_chat_action(
                    chat_id=update.effective_chat.id, action="typing"
                )
            except Exception:
                pass
            await asyncio.sleep(4)

    typing_task = asyncio.create_task(_keep_typing())

    try:
        loop = asyncio.get_running_loop()
        logger.info("[%s] Agent processing started", msg_id)
        state = await loop.run_in_executor(_AGENT_EXECUTOR, process_message, user_text, user_id)
        elapsed = time.monotonic() - start_ts
        logger.info(
            "[%s] Agent processing completed in %.1fs | agent=%s intent=%s",
            msg_id, elapsed, state.get("agent_used"), state.get("intent"),
        )
    except Exception as exc:
        typing_task.cancel()
        elapsed = time.monotonic() - start_ts
        logger.error("[%s] Agent error after %.1fs: %s", msg_id, elapsed, exc, exc_info=True)
        await _safe_reply(
            update,
            "⚠️ Ocorreu um erro ao processar sua mensagem. "
            "Tente novamente ou acesse suporte@infinitepay.io",
            msg_id=msg_id,
        )
        return
    finally:
        typing_task.cancel()

    # Build the reply
    response_text = state.get("response", "")
    agent_used = state.get("agent_used", "")
    ticket_id = state.get("ticket_id")
    escalated = state.get("escalated", False)
    language = state.get("language", "en")

    # Convert Markdown to Telegram HTML so bold, headers, tables render properly,
    # then collapse runs of blank lines so the body stays tight.
    html_body = _normalize_blank_lines(_md_to_html(response_text))

    from app.config import SHOW_AGENT_BADGE

    footer_lines: list[str] = []
    if SHOW_AGENT_BADGE:
        agent_label = _AGENT_LABELS.get(agent_used, html.escape(agent_used))
        lang_label = _LANGUAGE_LABELS.get(language, language.upper())
        footer_lines.append(f"— {agent_label} · {lang_label}")

    if ticket_id:
        footer_lines.append(f"🎫 Ticket: {html.escape(str(ticket_id))}")

    if escalated and agent_used != "escalation_agent":
        footer_lines.append("⚠️ Esta conversa foi encaminhada para nossa equipe humana.")

    full_message = html_body + ("\n\n" + "\n".join(footer_lines) if footer_lines else "")

    # Telegram has a 4096 character limit per message
    if len(full_message) > 4000:
        full_message = full_message[:3990] + "\n\n[mensagem truncada]"

    delivered = await _safe_reply(update, full_message, parse_mode=ParseMode.HTML, msg_id=msg_id)
    if delivered:
        logger.info("[%s] Reply delivered (total %.1fs)", msg_id, time.monotonic() - start_ts)
    else:
        logger.error("[%s] Reply NOT delivered after all retries", msg_id)


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
    application.add_handler(CommandHandler("link", link_command))
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
    )
    application.add_error_handler(error_handler)

    return application
