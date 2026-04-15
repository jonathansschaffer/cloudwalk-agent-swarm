"""
SQLAlchemy engine, session factory, and FastAPI dependency.

Supports PostgreSQL (production, via Railway addon) and SQLite (local dev
fallback). The DATABASE_URL env var is normalized so that the Railway-injected
`postgresql://` scheme works without manual editing.

Call `init_db()` on startup to create all tables (idempotent — uses
metadata.create_all, which is safe on an existing schema).
"""

import logging
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker, declarative_base

from app.config import DATABASE_URL

logger = logging.getLogger(__name__)

Base = declarative_base()


def _normalize_url(url: str) -> str:
    """Railway ships postgresql:// — SQLAlchemy 2.x wants postgresql+psycopg2://."""
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg2://", 1)
    return url


def _build_engine() -> Engine:
    url = _normalize_url(DATABASE_URL)
    kwargs: dict = {"pool_pre_ping": True, "future": True}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    return create_engine(url, **kwargs)


engine: Engine = _build_engine()
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, future=True)


def init_db() -> None:
    """Creates all tables. Safe to call on every startup."""
    from app.database import models  # noqa: F401
    Base.metadata.create_all(bind=engine)
    _run_schema_patches()
    logger.info("Database schema ready (url=%s)", engine.url.render_as_string(hide_password=True))


def _run_schema_patches() -> None:
    """Idempotent ALTER TABLE patches for columns that changed type after initial creation.

    Only runs on PostgreSQL — SQLite recreates tables fresh each run.
    Each statement is wrapped in its own try/except so one failure doesn't
    block the rest.
    """
    from sqlalchemy import text
    if not str(engine.url).startswith("postgresql"):
        return
    patches = [
        # language VARCHAR(4) → VARCHAR(16) to accommodate values like 'other'
        "ALTER TABLE chat_messages ALTER COLUMN language TYPE VARCHAR(16)",
        # telegram_username column added after initial schema creation
        "ALTER TABLE telegram_links ADD COLUMN IF NOT EXISTS telegram_username VARCHAR(64)",
        # Phase 1.5 Commit C: admin flag + email-verification marker on users.
        # Without these the seeded-user SELECT on startup fails against prod
        # Postgres (ORM selects every column; missing columns → UndefinedColumn
        # → seed crashes → /health never comes up → Railway healthcheck fails).
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_admin BOOLEAN NOT NULL DEFAULT FALSE",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS email_verified BOOLEAN NOT NULL DEFAULT FALSE",
    ]
    with engine.connect() as conn:
        for sql in patches:
            try:
                conn.execute(text(sql))
                conn.commit()
            except Exception as exc:
                conn.rollback()
                logger.debug("Schema patch skipped (%s): %s", sql[:60], exc)


def get_db() -> Iterator[Session]:
    """FastAPI dependency — yields a session and closes it after the request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
