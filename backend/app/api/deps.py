"""FastAPI dependencies for authentication, database access, and RBAC."""

from typing import Callable, Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
import jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.core.audit import log_audit
from app.core.database import get_db
from app.core.security import decode_token
from app.models.auth import User

# HTTPBearer with auto_error=False to allow clean 401s and optional authentication
http_bearer = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(http_bearer),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Validate JWT access token and load the active user from the database.

    Rejects missing/invalid tokens and inactive/deleted users with 401 Unauthorized.
    """
    if not credentials or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials
    try:
        payload = decode_token(token)
    except jwt.PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token_type = payload.get("type")
    if token_type != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token type",
            headers={"WWW-Authenticate": "Bearer"},
        )

    sub = payload.get("sub")
    if not sub:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        user_id = int(sub)
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    stmt = select(User).options(joinedload(User.role)).where(User.id == user_id)
    result = await db.execute(stmt)
    user = result.scalars().first()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Inactive user",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user


async def get_current_active_user(
    current_user: User = Depends(get_current_user),
) -> User:
    """Ensure the authenticated user account is active."""
    if not current_user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Inactive user",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return current_user


def require_roles(*role_names: str) -> Callable[..., User]:
    """Role-based access control guard factory.

    Returns a dependency callable that checks if the authenticated user
    has one of the specified roles, recording an audit log entry and
    returning 403 Forbidden otherwise.
    """
    async def role_checker(
        request: Request,
        current_user: User = Depends(get_current_active_user),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        user_role = current_user.role.name if current_user.role else None
        if user_role not in role_names:
            client_ip = None
            forwarded = request.headers.get("X-Forwarded-For")
            if forwarded:
                client_ip = forwarded.split(",")[0].strip()
            elif request.client:
                client_ip = request.client.host

            await log_audit(
                db=db,
                action="rbac.denied",
                actor_user_id=current_user.id,
                entity_type="endpoint",
                entity_id=None,
                details={
                    "path": request.url.path,
                    "method": request.method,
                    "user_role": user_role,
                    "required_roles": list(role_names),
                },
                ip_address=client_ip,
            )
            await db.commit()

            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Forbidden: requires role in {list(role_names)}",
            )
        return current_user

    return role_checker


async def get_current_user_optional(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(http_bearer),
    db: AsyncSession = Depends(get_db),
) -> Optional[User]:
    """Optional user dependency for public-but-personalized endpoints.

    Returns None if token is omitted, invalid, or belongs to an inactive user.
    """
    if not credentials or not credentials.credentials:
        return None

    try:
        payload = decode_token(credentials.credentials)
        if payload.get("type") != "access":
            return None
        sub = payload.get("sub")
        if not sub:
            return None
        user_id = int(sub)
        stmt = select(User).options(joinedload(User.role)).where(User.id == user_id)
        result = await db.execute(stmt)
        user = result.scalars().first()
        if not user or not user.is_active:
            return None
        return user
    except Exception:
        return None
