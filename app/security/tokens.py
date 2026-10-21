import uuid
from datetime import UTC, datetime, timedelta
from typing import Literal

import jwt

from app.core.config import get_settings

TokenType = Literal["access", "refresh"]


class TokenError(Exception):
    pass


def create_token(
    *, subject: uuid.UUID, token_type: TokenType, ttl: timedelta, extra: dict | None = None
) -> str:
    settings = get_settings()
    now = datetime.now(UTC)
    payload = {
        "sub": str(subject),
        "type": token_type,
        "iat": now,
        "exp": now + ttl,
        "jti": str(uuid.uuid4()),
        **(extra or {}),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_token(token: str, expected_type: TokenType) -> dict:
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError as exc:
        raise TokenError("invalid token") from exc
    if payload.get("type") != expected_type:
        raise TokenError("wrong token type")
    return payload
