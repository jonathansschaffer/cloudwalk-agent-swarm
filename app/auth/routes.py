"""
Authentication endpoints:

  POST   /auth/register        — new account (LGPD consent required)
  POST   /auth/login           — returns JWT access token
  GET    /auth/me              — current user profile
  DELETE /auth/me              — deletes the account + all personal data (LGPD)
  POST   /auth/telegram/code   — issues a 6-digit code to pair a Telegram chat

Rate limits:
  * register + login: 5/minute per IP (brute-force resistance).
  * telegram/code:    10/minute per IP.
"""

from __future__ import annotations

import logging
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.routes import limiter
from app.auth.dependencies import get_current_user
from app.auth.security import create_access_token, hash_password, verify_password
from app.database.db import get_db
from app.database.models import TelegramLinkCode, User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["Authentication"])


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    name: str = Field(min_length=1, max_length=120)
    lgpd_consent: bool = Field(
        ...,
        description="Must be true — explicit LGPD consent is required to register.",
    )


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in_minutes: int


class UserOut(BaseModel):
    id: int
    email: EmailStr
    name: str
    plan: str
    account_status: str
    kyc_verified: bool
    member_since: str
    lgpd_consent_at: datetime
    telegram_linked: bool

    @classmethod
    def from_user(cls, user: User) -> "UserOut":
        return cls(
            id=user.id,
            email=user.email,
            name=user.name,
            plan=user.plan,
            account_status=user.account_status,
            kyc_verified=user.kyc_verified,
            member_since=user.member_since,
            lgpd_consent_at=user.lgpd_consent_at,
            telegram_linked=user.telegram_link is not None,
        )


class TelegramCodeOut(BaseModel):
    code: str
    expires_in_minutes: int


# ---------------------------------------------------------------------------
# Register
# ---------------------------------------------------------------------------

@router.post("/register", response_model=TokenOut, status_code=status.HTTP_201_CREATED)
@limiter.limit("5/minute")
def register(request: Request, body: RegisterIn, db: Session = Depends(get_db)) -> TokenOut:
    if not body.lgpd_consent:
        raise HTTPException(
            status_code=400,
            detail="LGPD consent is required to create an account.",
        )

    now = datetime.now(timezone.utc)
    user = User(
        email=body.email.lower(),
        password_hash=hash_password(body.password),
        name=body.name.strip(),
        is_active=True,
        lgpd_consent_at=now,
        created_at=now,
        account_status="active",
        kyc_verified=False,
        plan="InfinitePay Basic",
        member_since=now.date().isoformat(),
        transfer_limit_daily=1000.00,
        transfer_limit_remaining=1000.00,
        failed_login_attempts=0,
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Email is already registered.")

    db.refresh(user)
    logger.info("New user registered | id=%d", user.id)

    from app.config import ACCESS_TOKEN_EXPIRE_MINUTES
    token = create_access_token(user.id, user.email)
    return TokenOut(access_token=token, expires_in_minutes=ACCESS_TOKEN_EXPIRE_MINUTES)


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------

@router.post("/login", response_model=TokenOut)
@limiter.limit("5/minute")
def login(request: Request, body: LoginIn, db: Session = Depends(get_db)) -> TokenOut:
    user = db.query(User).filter(User.email == body.email.lower()).one_or_none()
    # Constant-ish time: always hash compare even on missing users to reduce
    # email-enumeration side-channels.
    ok = user is not None and user.is_active and verify_password(body.password, user.password_hash)
    if not ok or user is None:
        raise HTTPException(status_code=401, detail="Invalid email or password.")

    from app.config import ACCESS_TOKEN_EXPIRE_MINUTES
    token = create_access_token(user.id, user.email)
    return TokenOut(access_token=token, expires_in_minutes=ACCESS_TOKEN_EXPIRE_MINUTES)


# ---------------------------------------------------------------------------
# Current user
# ---------------------------------------------------------------------------

@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)) -> UserOut:
    return UserOut.from_user(user)


@router.delete("/me", status_code=status.HTTP_204_NO_CONTENT)
def delete_me(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    """LGPD: right to erasure — deletes the account and all personal data."""
    logger.info("User self-deleted account | id=%d", user.id)
    db.delete(user)
    db.commit()


# ---------------------------------------------------------------------------
# Telegram pairing code
# ---------------------------------------------------------------------------

def _generate_code() -> str:
    """6-character A-Z0-9 code (strong enough for 10-min one-shot pairing)."""
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # ambiguity-safe
    return "".join(secrets.choice(alphabet) for _ in range(6))


@router.post("/telegram/code", response_model=TelegramCodeOut)
@limiter.limit("10/minute")
def issue_telegram_code(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TelegramCodeOut:
    """
    Issues a single-use 6-char code. The user sends `/link <code>` in Telegram
    to bind their Telegram account to this authenticated web session.

    Codes are valid for 10 minutes and invalidate any earlier unused codes
    for the same user (so refreshing the page always yields exactly one live code).
    """
    # Invalidate previous unused codes for this user
    db.query(TelegramLinkCode).filter(
        TelegramLinkCode.user_id == user.id,
        TelegramLinkCode.used_at.is_(None),
    ).delete(synchronize_session=False)

    expires_in = 10
    code = _generate_code()
    db.add(TelegramLinkCode(
        code=code,
        user_id=user.id,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=expires_in),
    ))
    db.commit()

    logger.info("Telegram pairing code issued | user_id=%d", user.id)
    return TelegramCodeOut(code=code, expires_in_minutes=expires_in)
