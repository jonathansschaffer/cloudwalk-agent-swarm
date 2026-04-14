"""
FastAPI auth dependencies — `get_current_user` reads the Bearer token,
decodes it, and returns the matching User row.
"""

from __future__ import annotations

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.auth.security import decode_access_token
from app.database.db import get_db
from app.database.models import User

_bearer = HTTPBearer(auto_error=False)

_CREDENTIALS_EXC = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Authentication required.",
    headers={"WWW-Authenticate": "Bearer"},
)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None or not credentials.credentials:
        raise _CREDENTIALS_EXC
    try:
        payload = decode_access_token(credentials.credentials)
        user_id = int(payload["sub"])
    except (jwt.InvalidTokenError, KeyError, ValueError):
        raise _CREDENTIALS_EXC

    user = db.query(User).filter(User.id == user_id, User.is_active.is_(True)).one_or_none()
    if user is None:
        raise _CREDENTIALS_EXC
    return user
