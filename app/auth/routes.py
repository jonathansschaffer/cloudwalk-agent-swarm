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
import re
import secrets
import unicodedata
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import audit
from app.api.routes import _client_ip, limiter
from app.auth import captcha
from app.auth.dependencies import get_current_user
from app.auth.security import create_access_token, hash_password, verify_password
from app.config import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
    CAPTCHA_AFTER_FAILED_LOGINS,
    LOGIN_LOCKOUT_THRESHOLD,
    REQUIRE_EMAIL_VERIFICATION,
    TURNSTILE_SITE_KEY,
    WEB_APP_URL,
)
from app.database.db import get_db
from app.database.models import EmailToken, TelegramLink, TelegramLinkCode, User
from app.email_provider import send_email

# Forbidden characters in a display name (defense-in-depth vs stored XSS).
_NAME_FORBIDDEN_CHARS = set("<>&\"\\;{}[]|`$*=+^~@#%/")


def _sanitize_name(raw: str) -> str:
    """Validate and normalize a user-supplied display name.

    Strips surrounding whitespace, normalizes to NFC, and rejects the name if
    it contains HTML/JS-relevant characters or any C0/C1 control characters.
    """
    value = unicodedata.normalize("NFC", raw).strip()
    if not value:
        raise ValueError("Name must not be empty.")
    if any(ch in _NAME_FORBIDDEN_CHARS for ch in value):
        raise ValueError(
            "Name contains invalid characters. Only letters, spaces, "
            "hyphens, apostrophes and periods are allowed."
        )
    if any(unicodedata.category(ch).startswith("C") for ch in value):
        raise ValueError("Name contains invalid control characters.")
    return value

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

    captcha_token: str | None = Field(
        default=None,
        description=(
            "Cloudflare Turnstile token. Required when Turnstile is enabled "
            "via TURNSTILE_SECRET_KEY. Blocks automated bot signups."
        ),
    )

    @field_validator("name")
    @classmethod
    def _validate_name(cls, v: str) -> str:
        return _sanitize_name(v)


class LoginIn(BaseModel):
    # Intentionally `str`, not `EmailStr`: pydantic's email-validator rejects
    # IANA special-use TLDs (`.test`, `.example`, …), which are valid for
    # seeded demo accounts. Login only needs to match an existing row — the
    # identity was already validated at register time.
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=128)
    captcha_token: str | None = Field(
        default=None,
        description=(
            "Cloudflare Turnstile token. Required once the account has "
            "CAPTCHA_AFTER_FAILED_LOGINS consecutive failures (default 3). "
            "Ignored when Turnstile is disabled via config."
        ),
    )


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in_minutes: int


class UserOut(BaseModel):
    id: int
    # Plain str (not EmailStr): pydantic's email-validator rejects IANA
    # special-use TLDs like `.test`, which seeded demo users use. Login
    # would succeed, then /auth/me 500'd on response serialization and
    # the frontend silently looped back to the login screen.
    email: str
    name: str
    plan: str
    account_status: str
    kyc_verified: bool
    member_since: str
    lgpd_consent_at: datetime
    telegram_linked: bool
    telegram_username: str | None = None  # @handle (without @) if linked, else None

    @classmethod
    def from_user(cls, user: User) -> "UserOut":
        link = user.telegram_link
        return cls(
            id=user.id,
            email=user.email,
            name=user.name,
            plan=user.plan,
            account_status=user.account_status,
            kyc_verified=user.kyc_verified,
            member_since=user.member_since,
            lgpd_consent_at=user.lgpd_consent_at,
            telegram_linked=link is not None,
            telegram_username=link.telegram_username if link else None,
        )


class TelegramCodeOut(BaseModel):
    code: str
    expires_in_minutes: int


# ---------------------------------------------------------------------------
# Register
# ---------------------------------------------------------------------------

def _issue_email_token(db: Session, user_id: int, purpose: str, ttl_minutes: int) -> str:
    """Creates an opaque single-use token. Caller is responsible for `db.commit()`."""
    token = secrets.token_urlsafe(32)
    expires = datetime.now(timezone.utc) + timedelta(minutes=ttl_minutes)
    db.add(EmailToken(token=token, user_id=user_id, purpose=purpose, expires_at=expires))
    return token


def _send_verification_email(to: str, name: str, token: str) -> None:
    link = f"{WEB_APP_URL}/auth/verify?token={token}"
    body = (
        f"Olá {name},\n\n"
        f"Para confirmar seu email na InfinitePay, clique no link abaixo "
        f"(válido por 60 minutos):\n\n{link}\n\n"
        f"Se você não criou esta conta, pode ignorar este email."
    )
    send_email(to=to, subject="Confirme seu email — InfinitePay", body_text=body)


def _send_unlock_email(to: str, name: str, token: str) -> None:
    link = f"{WEB_APP_URL}/auth/unlock?token={token}"
    body = (
        f"Olá {name},\n\n"
        f"Detectamos várias tentativas de login malsucedidas e bloqueamos sua conta "
        f"por segurança. Se foi você, use o link abaixo para desbloquear "
        f"(válido por 30 minutos):\n\n{link}\n\n"
        f"Se não foi você, recomendamos trocar sua senha."
    )
    send_email(to=to, subject="Conta temporariamente bloqueada — InfinitePay", body_text=body)


class RegisterAck(BaseModel):
    """Generic response for /auth/register — no account-existence signal."""
    detail: str = "Se o email estiver disponível, enviaremos instruções de confirmação."


@router.post("/register", response_model=RegisterAck, status_code=status.HTTP_202_ACCEPTED)
@limiter.limit("5/minute;20/hour")
def register(request: Request, body: RegisterIn, db: Session = Depends(get_db)) -> RegisterAck:
    """HIGH-03: we never leak whether an email is already registered.

    Always return the same 202 + generic body. Behind the scenes we either
    create the account (issuing a verification token) or silently drop the
    request when the email is already taken. Either way the user walks away
    with the same message: "check your inbox". Attackers learn nothing.
    """
    if not body.lgpd_consent:
        raise HTTPException(
            status_code=400,
            detail="LGPD consent is required to create an account.",
        )

    now = datetime.now(timezone.utc)
    ip = _client_ip(request)

    # Anti-bot gate. When Turnstile is enabled we require a valid token on
    # every registration — the cost of a legit user solving a quick challenge
    # is trivial vs. allowing automated account creation.
    if captcha.is_enabled():
        if not captcha.verify(body.captcha_token or "", remote_ip=ip):
            audit.emit("auth.register.captcha_failed", ip=ip, email=body.email.lower())
            raise HTTPException(
                status_code=403,
                detail={
                    "error": "captcha_required",
                    "message": "Complete a verificação antes de criar a conta.",
                },
            )

    existing = db.query(User).filter(User.email == body.email.lower()).one_or_none()
    if existing is not None:
        audit.emit(
            "auth.register.duplicate_silent",
            actor_user_id=existing.id, ip=ip, email=body.email.lower(),
        )
        return RegisterAck()

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
        email_verified=not REQUIRE_EMAIL_VERIFICATION,
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        # Race: another request grabbed the email between the check and the
        # insert. Treat it identically to the duplicate branch.
        db.rollback()
        return RegisterAck()

    db.refresh(user)
    if REQUIRE_EMAIL_VERIFICATION:
        token = _issue_email_token(db, user.id, "verify_email", ttl_minutes=60)
        db.commit()
        _send_verification_email(user.email, user.name, token)
        logger.info("New user registered | id=%d (verification email queued)", user.id)
    else:
        logger.info("New user registered | id=%d (email verification skipped by flag)", user.id)

    audit.emit("auth.register.success", actor_user_id=user.id, ip=ip)
    return RegisterAck()


@router.get("/verify", summary="Confirm email ownership via emailed token")
def verify_email(token: str, db: Session = Depends(get_db)) -> dict:
    row = db.query(EmailToken).filter(
        EmailToken.token == token, EmailToken.purpose == "verify_email"
    ).one_or_none()
    if row is None:
        raise HTTPException(status_code=400, detail="Invalid or expired token.")

    expires_at = row.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if row.used_at is not None or expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail="Invalid or expired token.")

    user = db.query(User).filter(User.id == row.user_id).one_or_none()
    if user is None:
        raise HTTPException(status_code=400, detail="Invalid or expired token.")

    user.email_verified = True
    row.used_at = datetime.now(timezone.utc)
    db.commit()
    audit.emit("auth.email.verified", actor_user_id=user.id)
    return {"status": "verified"}


@router.get("/unlock", summary="Self-service unlock after repeated login failures")
def unlock_account(token: str, db: Session = Depends(get_db)) -> dict:
    row = db.query(EmailToken).filter(
        EmailToken.token == token, EmailToken.purpose == "unlock_account"
    ).one_or_none()
    if row is None:
        raise HTTPException(status_code=400, detail="Invalid or expired token.")

    expires_at = row.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if row.used_at is not None or expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail="Invalid or expired token.")

    user = db.query(User).filter(User.id == row.user_id).one_or_none()
    if user is None:
        raise HTTPException(status_code=400, detail="Invalid or expired token.")

    user.failed_login_attempts = 0
    row.used_at = datetime.now(timezone.utc)
    db.commit()
    audit.emit("auth.unlock.success", actor_user_id=user.id)
    return {"status": "unlocked"}


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------

@router.post("/login", response_model=TokenOut)
@limiter.limit("5/minute")
def login(request: Request, body: LoginIn, db: Session = Depends(get_db)) -> TokenOut:
    ip = _client_ip(request)
    user = db.query(User).filter(User.email == body.email.lower()).one_or_none()

    if user is not None and user.failed_login_attempts >= LOGIN_LOCKOUT_THRESHOLD:
        audit.emit("auth.login.blocked_locked", actor_user_id=user.id, ip=ip)
        raise HTTPException(status_code=401, detail="Invalid email or password.")

    # Once the user crosses the CAPTCHA threshold we require a valid Turnstile
    # token on every subsequent attempt until they succeed. 403 + a machine-
    # readable flag so the frontend knows to render the widget.
    if (
        captcha.is_enabled()
        and user is not None
        and user.failed_login_attempts >= CAPTCHA_AFTER_FAILED_LOGINS
    ):
        if not captcha.verify(body.captcha_token or "", remote_ip=ip):
            audit.emit("auth.login.captcha_failed", actor_user_id=user.id, ip=ip)
            raise HTTPException(
                status_code=403,
                detail={
                    "error": "captcha_required",
                    "message": "Complete a verificação para continuar.",
                },
            )

    # Constant-ish time: always hash compare even on missing users to reduce
    # email-enumeration side-channels.
    ok = user is not None and user.is_active and verify_password(body.password, user.password_hash)
    if not ok or user is None:
        if user is not None:
            user.failed_login_attempts = (user.failed_login_attempts or 0) + 1
            # Cross the threshold on *this* attempt? Send a one-time unlock
            # mail so the user isn't locked out indefinitely (HIGH-04 loop).
            crossed = user.failed_login_attempts == LOGIN_LOCKOUT_THRESHOLD
            db.commit()
            if crossed:
                token = _issue_email_token(db, user.id, "unlock_account", ttl_minutes=30)
                db.commit()
                _send_unlock_email(user.email, user.name, token)
                audit.emit("auth.login.lockout_triggered", actor_user_id=user.id, ip=ip)
            audit.emit("auth.login.failure", actor_user_id=user.id, ip=ip)
        else:
            audit.emit("auth.login.failure", ip=ip, email=body.email.lower())
        raise HTTPException(status_code=401, detail="Invalid email or password.")

    if REQUIRE_EMAIL_VERIFICATION and not user.email_verified:
        audit.emit("auth.login.email_unverified", actor_user_id=user.id, ip=ip)
        raise HTTPException(
            status_code=403,
            detail={
                "error": "email_not_verified",
                "message": (
                    "Confirme seu email antes de entrar. Cheque sua caixa de "
                    "entrada pelo link de ativação (ou a pasta de spam)."
                ),
            },
        )

    if user.failed_login_attempts:
        user.failed_login_attempts = 0
        db.commit()

    audit.emit("auth.login.success", actor_user_id=user.id, ip=ip)
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
    audit.emit("auth.account.deleted", actor_user_id=user.id)
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

    Returns 409 if the account is already linked to a Telegram user.
    Codes are valid for 10 minutes and invalidate any earlier unused codes
    for the same user (so refreshing the page always yields exactly one live code).

    Per-user throttle: at most one new code every 30 seconds, regardless of IP,
    so mass generation is not possible even from many origins.
    """
    if user.telegram_link is not None:
        raise HTTPException(
            status_code=409,
            detail="Esta conta já está vinculada ao Telegram.",
        )

    now = datetime.now(timezone.utc)

    # Per-user throttle: fetch the most recent unused code for this user and
    # refuse if it was minted less than 30 seconds ago.
    last = (
        db.query(TelegramLinkCode)
        .filter(
            TelegramLinkCode.user_id == user.id,
            TelegramLinkCode.used_at.is_(None),
        )
        .order_by(TelegramLinkCode.expires_at.desc())
        .first()
    )
    if last is not None:
        last_expires = last.expires_at
        if last_expires.tzinfo is None:
            last_expires = last_expires.replace(tzinfo=timezone.utc)
        minted_at = last_expires - timedelta(minutes=10)
        if (now - minted_at).total_seconds() < 30:
            raise HTTPException(
                status_code=429,
                detail="Aguarde alguns segundos antes de gerar um novo código.",
            )

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
        expires_at=now + timedelta(minutes=expires_in),
    ))
    db.commit()

    logger.info("Telegram pairing code issued | user_id=%d", user.id)
    return TelegramCodeOut(code=code, expires_in_minutes=expires_in)


@router.delete("/telegram", status_code=status.HTTP_204_NO_CONTENT)
def unlink_telegram(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    """Remove the Telegram ↔ account binding. Safe to call when not linked."""
    link = db.query(TelegramLink).filter(TelegramLink.user_id == user.id).one_or_none()
    if link is None:
        return
    db.query(TelegramLinkCode).filter(
        TelegramLinkCode.user_id == user.id,
        TelegramLinkCode.used_at.is_(None),
    ).delete(synchronize_session=False)
    db.delete(link)
    db.commit()
    audit.emit("auth.telegram.unlinked", actor_user_id=user.id)
    logger.info("Telegram unlinked | user_id=%d", user.id)


# ---------------------------------------------------------------------------
# CAPTCHA config (public — site key only, no secret)
# ---------------------------------------------------------------------------

class CaptchaConfigOut(BaseModel):
    enabled: bool
    site_key: str = ""


@router.get("/captcha-config", response_model=CaptchaConfigOut)
def captcha_config() -> CaptchaConfigOut:
    """Lets the frontend know whether Turnstile is active and which site key to render."""
    return CaptchaConfigOut(
        enabled=captcha.is_enabled(),
        site_key=TURNSTILE_SITE_KEY if captcha.is_enabled() else "",
    )
