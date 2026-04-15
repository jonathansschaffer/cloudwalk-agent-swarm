"""
Seeds the 5 legacy mock users (client789, user_002..005) on first boot.

Each seed user keeps its original CRM profile so test scripts and automated
tests continue to work, but now authentication is required. Passwords are
the same for all seed accounts (`MOCK_USER_PASSWORD`, default `Test123!`).

Idempotent: if a seed user already exists (matched by email), it is skipped.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.auth.security import hash_password
from app.config import MOCK_USER_PASSWORD, SEED_MOCK_USERS
from app.database.models import Transaction, User

logger = logging.getLogger(__name__)


_SEED_USERS: list[dict] = [
    {
        "email": "carlos.andrade@infinitepay.test",
        "name": "Carlos Andrade",
        "account_status": "active",
        "kyc_verified": True,
        "plan": "InfinitePay Pro",
        "member_since": "2023-06-10",
        "transfer_limit_daily": 10000.00,
        "transfer_limit_remaining": 10000.00,
        "failed_login_attempts": 0,
        "transactions": [
            {"id": "txn_001", "type": "pix_out", "amount": 250.00,
             "date": "2026-04-10", "status": "completed", "description": "Pagamento fornecedor"},
            {"id": "txn_002", "type": "card_payment_received", "amount": 1500.00,
             "date": "2026-04-11", "status": "completed", "description": "Venda débito"},
            {"id": "txn_003", "type": "pix_in", "amount": 300.00,
             "date": "2026-04-12", "status": "completed", "description": "Recebimento cliente"},
        ],
    },
    {
        "email": "maria.souza@infinitepay.test",
        "name": "Maria Souza",
        "account_status": "suspended",
        "kyc_verified": False,
        "plan": "InfinitePay Basic",
        "member_since": "2022-08-20",
        "transfer_limit_daily": 1000.00,
        "transfer_limit_remaining": 0.00,
        "failed_login_attempts": 6,
        "transactions": [],
    },
    {
        "email": "joao.silva@infinitepay.test",
        "name": "João Silva",
        "account_status": "pending_kyc",
        "kyc_verified": False,
        "plan": "InfinitePay Basic",
        "member_since": "2026-03-01",
        "transfer_limit_daily": 500.00,
        "transfer_limit_remaining": 500.00,
        "failed_login_attempts": 0,
        "transactions": [],
    },
    {
        "email": "ana.lima@infinitepay.test",
        "name": "Ana Lima",
        "account_status": "active",
        "kyc_verified": True,
        "plan": "InfinitePay Enterprise",
        "member_since": "2021-11-05",
        "transfer_limit_daily": 50000.00,
        "transfer_limit_remaining": 0.00,
        "failed_login_attempts": 0,
        "transactions": [
            {"id": "txn_010", "type": "pix_out", "amount": 50000.00,
             "date": "2026-04-13", "status": "completed",
             "description": "Pagamento mensal fornecedores"},
        ],
    },
    {
        "email": "pedro.costa@infinitepay.test",
        "name": "Pedro Costa",
        "account_status": "active",
        "kyc_verified": True,
        "plan": "InfinitePay Pro",
        "member_since": "2024-01-15",
        "transfer_limit_daily": 5000.00,
        "transfer_limit_remaining": 4800.00,
        "failed_login_attempts": 2,
        "transactions": [
            {"id": "txn_020", "type": "card_payment_received", "amount": 199.90,
             "date": "2026-04-12", "status": "failed",
             "description": "Tentativa de venda crédito - falhou"},
        ],
    },
]


def seed_mock_users(db: Session) -> int:
    """Inserts missing seed users and returns the number of rows created."""
    if not SEED_MOCK_USERS:
        logger.info("SEED_MOCK_USERS is disabled — skipping seed.")
        return 0

    password_hash = hash_password(MOCK_USER_PASSWORD)
    now = datetime.now(timezone.utc)
    inserted = 0

    for seed in _SEED_USERS:
        existing = db.query(User).filter(User.email == seed["email"]).one_or_none()
        if existing is not None:
            continue

        user = User(
            email=seed["email"],
            password_hash=password_hash,
            name=seed["name"],
            is_active=True,
            email_verified=True,  # demo users are always ready for login
            lgpd_consent_at=now,
            created_at=now,
            account_status=seed["account_status"],
            kyc_verified=seed["kyc_verified"],
            plan=seed["plan"],
            member_since=seed["member_since"],
            transfer_limit_daily=seed["transfer_limit_daily"],
            transfer_limit_remaining=seed["transfer_limit_remaining"],
            failed_login_attempts=seed["failed_login_attempts"],
        )
        db.add(user)
        db.flush()  # assigns user.id

        for txn in seed["transactions"]:
            db.add(Transaction(user_id=user.id, **txn))

        inserted += 1

    db.commit()
    if inserted:
        logger.info("Seeded %d mock users (password='%s').", inserted, MOCK_USER_PASSWORD)
    return inserted
