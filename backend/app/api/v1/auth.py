"""Authentication API router.

Provides registration, login, token refresh, and profile inspection endpoints.
"""

from datetime import datetime, timezone
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
import jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.api.deps import get_current_active_user
from app.core.audit import log_audit
from app.core.config import settings
from app.core.database import get_db
from app.core.rate_limit import rate_limit_auth
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    is_token_revoked,
    revoke_token,
    verify_password,
)
from app.models.auth import Role, User
from app.schemas.auth import (
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    TokenResponse,
)
from app.schemas.user import UserResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


def get_client_ip(request: Request) -> Optional[str]:
    """Extract client IP address from proxy headers or connection details."""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host
    return None


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit_auth)],
    summary="Register a new analyst account",
)
async def register(
    payload: RegisterRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> User:
    """Register a new user account with default role 'analyst'.

    Prevents privilege escalation and duplicate email registrations.
    """
    normalized_email = payload.email.lower()
    existing_user_stmt = select(User).where(User.email == normalized_email)
    existing_user = (await db.execute(existing_user_stmt)).scalars().first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email is already registered",
        )

    # Fetch default analyst role
    role_stmt = select(Role).where(Role.name == "analyst")
    role = (await db.execute(role_stmt)).scalars().first()
    if not role:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Default role 'analyst' not found in system",
        )

    user = User(
        email=normalized_email,
        hashed_password=hash_password(payload.password),
        full_name=payload.full_name,
        role_id=role.id,
        is_active=True,
    )
    db.add(user)
    await db.flush()

    client_ip = get_client_ip(request)
    await log_audit(
        db=db,
        action="auth.register",
        actor_user_id=user.id,
        entity_type="user",
        entity_id=user.id,
        details={"email": user.email, "role": role.name},
        ip_address=client_ip,
    )
    await db.commit()
    await db.refresh(user, attribute_names=["role"])

    return user


@router.post(
    "/login",
    response_model=TokenResponse,
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(rate_limit_auth)],
    summary="User credentials authentication",
)
async def login(
    payload: LoginRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    """Authenticate email and password and return access and refresh JWTs."""
    client_ip = get_client_ip(request)
    normalized_email = payload.email.lower()

    stmt = select(User).options(joinedload(User.role)).where(User.email == normalized_email)
    user = (await db.execute(stmt)).scalars().first()

    if not user or not verify_password(payload.password, user.hashed_password):
        logger.warning(
            "Failed login attempt for email: %s from IP: %s",
            normalized_email,
            client_ip,
        )
        await log_audit(
            db=db,
            action="auth.login_failed",
            actor_user_id=user.id if user else None,
            entity_type="user",
            entity_id=user.id if user else None,
            details={"email": normalized_email, "reason": "invalid_credentials"},
            ip_address=client_ip,
        )
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    if not user.is_active:
        logger.warning(
            "Login attempt for deactivated user: %s from IP: %s",
            normalized_email,
            client_ip,
        )
        await log_audit(
            db=db,
            action="auth.login_failed",
            actor_user_id=user.id,
            entity_type="user",
            entity_id=user.id,
            details={"email": normalized_email, "reason": "inactive_user"},
            ip_address=client_ip,
        )
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account is inactive",
        )

    user.last_login_at = datetime.now(timezone.utc)
    await log_audit(
        db=db,
        action="auth.login",
        actor_user_id=user.id,
        entity_type="user",
        entity_id=user.id,
        details={"email": user.email},
        ip_address=client_ip,
    )
    await db.commit()

    role_name = user.role.name if user.role else "analyst"
    access_token = create_access_token(user_id=user.id, role=role_name)
    refresh_token = create_refresh_token(user_id=user.id)
    expires_in = settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        expires_in=expires_in,
    )


@router.post(
    "/refresh",
    response_model=TokenResponse,
    status_code=status.HTTP_200_OK,
    summary="Rotate access and refresh tokens",
)
async def refresh_tokens(
    payload: RefreshRequest,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    """Validate refresh token and issue rotated access and refresh tokens.
    
    Enforces strict single-use token rotation: the supplied refresh token is invalidated
    upon successful exchange, and subsequent reuse of an already-used token is rejected.
    """
    try:
        decoded = decode_token(payload.refresh_token)
    except jwt.PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )

    if decoded.get("type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token type",
        )

    # Invalidation check: reject already used or revoked refresh tokens
    token_identifier = decoded.get("jti") or payload.refresh_token
    if await is_token_revoked(token_identifier):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token has already been used or revoked",
        )

    sub = decoded.get("sub")
    if not sub:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
        )

    try:
        user_id = int(sub)
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
        )

    stmt = select(User).options(joinedload(User.role)).where(User.id == user_id)
    user = (await db.execute(stmt)).scalars().first()

    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
        )

    # Rotate: invalidate the consumed refresh token before issuing the new pair
    await revoke_token(token_identifier)

    role_name = user.role.name if user.role else "analyst"
    new_access_token = create_access_token(user_id=user.id, role=role_name)
    new_refresh_token = create_refresh_token(user_id=user.id)
    expires_in = settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60

    return TokenResponse(
        access_token=new_access_token,
        refresh_token=new_refresh_token,
        token_type="bearer",
        expires_in=expires_in,
    )


@router.get(
    "/me",
    response_model=UserResponse,
    status_code=status.HTTP_200_OK,
    summary="Retrieve current authenticated user profile",
)
async def get_me(
    current_user: User = Depends(get_current_active_user),
) -> User:
    """Return profile details for the currently authenticated user."""
    return current_user
