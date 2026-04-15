"""
SQLAlchemy ORM models.

Consolidates the previously in-memory data stores (users, tickets, chat
history, telegram links) into a single relational schema.

LGPD compliance notes:
  * `lgpd_consent_at` is mandatory on registration — no consent, no account.
  * Users may self-delete via DELETE /auth/me, which cascades through all
    linked personal data (tickets, chat history, telegram link, transactions).
  * Sensitive fields (password) are never stored in plaintext — bcrypt only.
"""

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text
)
from sqlalchemy.orm import relationship

from app.database.db import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    """Authenticated user + inline CRM profile (single-table simplicity)."""

    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # --- Auth identity ------------------------------------------------------
    email = Column(String(255), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    name = Column(String(120), nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)

    # --- LGPD -------------------------------------------------------------
    lgpd_consent_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)

    # --- CRM profile ------------------------------------------------------
    account_status = Column(String(32), nullable=False, default="active")
    kyc_verified = Column(Boolean, nullable=False, default=False)
    plan = Column(String(64), nullable=False, default="InfinitePay Basic")
    member_since = Column(String(10), nullable=False, default="")  # YYYY-MM-DD
    transfer_limit_daily = Column(Float, nullable=False, default=1000.0)
    transfer_limit_remaining = Column(Float, nullable=False, default=1000.0)
    failed_login_attempts = Column(Integer, nullable=False, default=0)

    # --- Admin / moderation ----------------------------------------------
    is_admin = Column(Boolean, nullable=False, default=False)
    # True once the user clicked the email-verification link. Login is still
    # allowed when email_verified=False so existing seeded accounts and pre-flow
    # registrations keep working — enforcement is a separate flag so we can
    # ratchet it on when the email provider is wired in.
    email_verified = Column(Boolean, nullable=False, default=False)

    transactions = relationship(
        "Transaction", back_populates="user",
        cascade="all, delete-orphan", passive_deletes=True,
    )
    tickets = relationship(
        "Ticket", back_populates="user",
        cascade="all, delete-orphan", passive_deletes=True,
    )
    chat_messages = relationship(
        "ChatMessage", back_populates="user",
        cascade="all, delete-orphan", passive_deletes=True,
    )
    telegram_link = relationship(
        "TelegramLink", back_populates="user", uselist=False,
        cascade="all, delete-orphan", passive_deletes=True,
    )


class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(String(32), primary_key=True)  # e.g. "txn_001"
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    type = Column(String(32), nullable=False)
    amount = Column(Float, nullable=False)
    date = Column(String(10), nullable=False)
    status = Column(String(32), nullable=False)
    description = Column(String(255), nullable=False, default="")

    user = relationship("User", back_populates="transactions")


class Ticket(Base):
    __tablename__ = "tickets"

    id = Column(String(32), primary_key=True)  # e.g. "TKT-20260413-A1B2C3"
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    issue = Column(Text, nullable=False)
    priority = Column(String(16), nullable=False, default="medium")
    status = Column(String(16), nullable=False, default="open")
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    estimated_resolution = Column(String(64), nullable=False, default="")

    user = relationship("User", back_populates="tickets")


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    user_message = Column(Text, nullable=False)
    bot_response = Column(Text, nullable=False)
    agent_used = Column(String(32), nullable=False, default="")
    intent = Column(String(32), nullable=False, default="")
    ticket_id = Column(String(32), nullable=True)
    escalated = Column(Boolean, nullable=False, default=False)
    language = Column(String(16), nullable=False, default="en")
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow, index=True)

    user = relationship("User", back_populates="chat_messages")


class TelegramLink(Base):
    """One Telegram account ↔ one App user (enforced by unique constraints)."""

    __tablename__ = "telegram_links"

    telegram_user_id = Column(String(32), primary_key=True)  # Telegram's numeric id as str
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False)
    linked_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    telegram_username = Column(String(64), nullable=True)  # @handle without the @, may be None

    user = relationship("User", back_populates="telegram_link")


class EmailToken(Base):
    """Opaque single-use tokens for email-driven flows.

    Purposes:
        * ``verify_email``    — emitted on registration; marks email_verified.
        * ``unlock_account`` — emitted after account lockout; resets failed_login_attempts.
        * ``password_reset`` — future, not yet wired.
    """

    __tablename__ = "email_tokens"

    token = Column(String(64), primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    purpose = Column(String(32), nullable=False, index=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    used_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)


class AuditEvent(Base):
    """Append-only audit trail of security-relevant actions.

    Rows are never mutated or deleted in app code. Retained for LGPD / SOC 2
    investigation. `actor_user_id` is nullable for pre-auth events (failed
    login against unknown email, registration, etc.).
    """

    __tablename__ = "audit_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow, index=True)
    event_type = Column(String(64), nullable=False, index=True)
    actor_user_id = Column(Integer, nullable=True, index=True)
    ip_address = Column(String(64), nullable=True)
    # Freeform JSON-ish text blob — keep it a string to stay DB-portable
    # (SQLite has no JSON column; Postgres does but we favor the LCD).
    details = Column(Text, nullable=False, default="")


class TelegramLinkCode(Base):
    """Short-lived one-shot codes generated in the web UI to pair a Telegram account."""

    __tablename__ = "telegram_link_codes"

    code = Column(String(16), primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    used_at = Column(DateTime(timezone=True), nullable=True)
