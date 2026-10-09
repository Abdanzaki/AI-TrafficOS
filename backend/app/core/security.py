"""Security and cryptographic operations.

Provides bcrypt password hashing and PyJWT token generation and verification.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import bcrypt
import jwt

from app.core.config import settings

ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    """Hash a plain text password using bcrypt."""
    pw_bytes = password.encode("utf-8")
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(pw_bytes, salt).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plain text password against a stored bcrypt hash."""
    try:
        return bcrypt.checkpw(
            plain_password.encode("utf-8"),
            hashed_password.encode("utf-8"),
        )
    except (ValueError, TypeError):
        return False


def create_access_token(
    user_id: int,
    role: str,
    expires_delta: Optional[timedelta] = None,
) -> str:
    """Create a signed JWT access token containing subject and role claims."""
    now = datetime.now(timezone.utc)
    if expires_delta is not None:
        expire = now + expires_delta
    else:
        expire = now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)

    payload: dict[str, Any] = {
        "sub": str(user_id),
        "role": role,
        "type": "access",
        "iat": int(now.timestamp()),
        "exp": int(expire.timestamp()),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=ALGORITHM)


import uuid

# In-memory revocation cache for rotated refresh tokens
_REVOKED_TOKENS: set[str] = set()


def create_refresh_token(
    user_id: int,
    expires_delta: Optional[timedelta] = None,
    jti: Optional[str] = None,
) -> str:
    """Create a signed JWT refresh token containing the subject claim and unique jti."""
    now = datetime.now(timezone.utc)
    if expires_delta is not None:
        expire = now + expires_delta
    else:
        expire = now + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)

    token_jti = jti or uuid.uuid4().hex
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "type": "refresh",
        "jti": token_jti,
        "iat": int(now.timestamp()),
        "exp": int(expire.timestamp()),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=ALGORITHM)


async def revoke_token(token_identifier: str) -> None:
    """Mark a refresh token as revoked/used to prevent replay attacks."""
    _REVOKED_TOKENS.add(token_identifier)
    try:
        from app.realtime import get_bus
        bus = get_bus()
        if bus.is_connected and bus._redis is not None:
            await bus._redis.set(
                f"trafficos:revoked_token:{token_identifier}",
                "1",
                ex=settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400,
            )
    except Exception:
        pass


async def is_token_revoked(token_identifier: str) -> bool:
    """Check if a refresh token has already been rotated or revoked."""
    if token_identifier in _REVOKED_TOKENS:
        return True
    try:
        from app.realtime import get_bus
        bus = get_bus()
        if bus.is_connected and bus._redis is not None:
            val = await bus._redis.get(f"trafficos:revoked_token:{token_identifier}")
            if val is not None:
                _REVOKED_TOKENS.add(token_identifier)
                return True
    except Exception:
        pass
    return False


def decode_token(token: str) -> dict[str, Any]:
    """Validate and decode a JWT token against SECRET_KEY.

    Raises jwt.PyJWTError (e.g. ExpiredSignatureError, InvalidTokenError)
    if the signature or expiry is invalid.
    """
    return jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
