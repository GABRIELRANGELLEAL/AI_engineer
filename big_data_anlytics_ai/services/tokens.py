"""JWT and opaque token helpers."""

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta
from typing import Any, Optional

import jwt

from config import get_settings


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def generate_opaque_token() -> str:
    return secrets.token_urlsafe(32)


def create_access_token(
    user_id: uuid.UUID,
    workspace_id: Optional[uuid.UUID] = None,
) -> str:
    settings = get_settings()
    expire = datetime.utcnow() + timedelta(
        minutes=settings.jwt_access_token_expire_minutes
    )
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "exp": expire,
        "type": "access",
    }
    if workspace_id:
        payload["workspace_id"] = str(workspace_id)
    return jwt.encode(
        payload,
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )


def decode_access_token(token: str) -> dict[str, Any]:
    settings = get_settings()
    return jwt.decode(
        token,
        settings.jwt_secret_key,
        algorithms=[settings.jwt_algorithm],
    )


def refresh_token_expires_at() -> datetime:
    settings = get_settings()
    return datetime.utcnow() + timedelta(hours=settings.jwt_refresh_token_expire_hours)
