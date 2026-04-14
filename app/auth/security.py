"""
Password hashing (bcrypt) and JWT token issuance/verification.

bcrypt is used through passlib for forward-compat with parameter tuning.
JWT tokens are signed with HS256 and carry a short-lived `sub` + `exp` claim;
nothing sensitive is embedded in the payload.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from passlib.context import CryptContext

from app.config import ACCESS_TOKEN_EXPIRE_MINUTES, JWT_ALGORITHM, JWT_SECRET

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return _pwd_context.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    try:
        return _pwd_context.verify(password, hashed)
    except Exception:
        return False


def create_access_token(user_id: int, email: str, extra: dict[str, Any] | None = None) -> str:
    """Issue a short-lived JWT. `sub` is the user id as a string (JWT convention)."""
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "email": email,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)).timestamp()),
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> dict[str, Any]:
    """Raises jwt.InvalidTokenError / ExpiredSignatureError on failure."""
    return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
