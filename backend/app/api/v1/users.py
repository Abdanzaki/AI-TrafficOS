"""User management API router.

Provides administrator-only endpoints for listing, creating, updating,
and deactivating users with role-based access control and audit logging.
"""

import logging
import math
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.api.deps import require_roles
from app.api.v1.auth import get_client_ip
from app.core.audit import log_audit
from app.core.database import get_db
from app.core.security import hash_password
from app.models.auth import Role, User
from app.schemas.user import (
    PaginatedUsers,
    UserCreate,
    UserResponse,
    UserUpdate,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/users",
    tags=["users"],
    dependencies=[Depends(require_roles("admin"))],
)


@router.get(
    "",
    response_model=PaginatedUsers,
    status_code=status.HTTP_200_OK,
    summary="List users with pagination (admin only)",
)
async def list_users(
    page: int = Query(1, ge=1, description="Page number"),
    per_page: int = Query(20, ge=1, le=100, description="Items per page (max 100)"),
    db: AsyncSession = Depends(get_db),
    admin_user: User = Depends(require_roles("admin")),
) -> PaginatedUsers:
    """Retrieve paginated list of user accounts."""
    count_stmt = select(func.count(User.id))
    total_result = await db.execute(count_stmt)
    total = total_result.scalar() or 0

    offset = (page - 1) * per_page
    stmt = (
        select(User)
        .options(joinedload(User.role))
        .order_by(User.id.asc())
        .offset(offset)
        .limit(per_page)
    )
    result = await db.execute(stmt)
    users = list(result.scalars().all())

    pages = math.ceil(total / per_page) if total > 0 else 1

    return PaginatedUsers(
        items=users,
        total=total,
        page=page,
        per_page=per_page,
        pages=pages,
    )


@router.post(
    "",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a user with explicit role (admin only)",
)
async def create_user(
    payload: UserCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin_user: User = Depends(require_roles("admin")),
) -> User:
    """Create a new user account with an explicitly assigned role."""
    normalized_email = payload.email.lower()
    existing_stmt = select(User).where(User.email == normalized_email)
    existing_user = (await db.execute(existing_stmt)).scalars().first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email is already registered",
        )

    # Determine assigned role
    if payload.role_id is not None:
        role_stmt = select(Role).where(Role.id == payload.role_id)
        role = (await db.execute(role_stmt)).scalars().first()
    elif payload.role_name is not None:
        role_stmt = select(Role).where(Role.name == payload.role_name)
        role = (await db.execute(role_stmt)).scalars().first()
    else:
        role_stmt = select(Role).where(Role.name == "analyst")
        role = (await db.execute(role_stmt)).scalars().first()

    if not role:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Specified role was not found",
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
        action="user.created",
        actor_user_id=admin_user.id,
        entity_type="user",
        entity_id=user.id,
        details={"email": user.email, "role": role.name},
        ip_address=client_ip,
    )
    await db.commit()
    await db.refresh(user, attribute_names=["role"])

    logger.info(
        "Admin user id=%s created new user id=%s email=%s with role=%s",
        admin_user.id,
        user.id,
        user.email,
        role.name,
    )
    return user


@router.patch(
    "/{user_id}",
    response_model=UserResponse,
    status_code=status.HTTP_200_OK,
    summary="Update user account details (admin only)",
)
async def update_user(
    user_id: int,
    payload: UserUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin_user: User = Depends(require_roles("admin")),
) -> User:
    """Update fields on an existing user account."""
    stmt = select(User).options(joinedload(User.role)).where(User.id == user_id)
    user = (await db.execute(stmt)).scalars().first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    changes: dict[str, object] = {}

    old_role_name = user.role.name if user.role else None

    if payload.full_name is not None:
        user.full_name = payload.full_name
        changes["full_name"] = payload.full_name

    if payload.is_active is not None:
        user.is_active = payload.is_active
        changes["is_active"] = payload.is_active

    if payload.role_id is not None:
        role_stmt = select(Role).where(Role.id == payload.role_id)
        role = (await db.execute(role_stmt)).scalars().first()
        if not role:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Specified role_id does not exist",
            )
        user.role_id = role.id
        changes["role_id"] = role.id
        changes["role"] = role.name
    elif payload.role_name is not None:
        role_stmt = select(Role).where(Role.name == payload.role_name)
        role = (await db.execute(role_stmt)).scalars().first()
        if not role:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Specified role_name does not exist",
            )
        user.role_id = role.id
        changes["role"] = role.name

    client_ip = get_client_ip(request)
    await log_audit(
        db=db,
        action="user.updated",
        actor_user_id=admin_user.id,
        entity_type="user",
        entity_id=user.id,
        details=changes,
        ip_address=client_ip,
    )

    if ("role" in changes or "role_id" in changes) and changes.get("role") != old_role_name:
        await log_audit(
            db=db,
            action="user.role_changed",
            actor_user_id=admin_user.id,
            entity_type="user",
            entity_id=user.id,
            details={"previous_role": old_role_name, "new_role": changes.get("role")},
            ip_address=client_ip,
        )

    await db.commit()
    await db.refresh(user, attribute_names=["role"])

    logger.info(
        "Admin user id=%s updated user id=%s: %s",
        admin_user.id,
        user.id,
        changes,
    )
    return user


@router.delete(
    "/{user_id}",
    response_model=UserResponse,
    status_code=status.HTTP_200_OK,
    summary="Soft-delete/deactivate a user (admin only)",
)
async def delete_user(
    user_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin_user: User = Depends(require_roles("admin")),
) -> User:
    """Soft-delete a user by setting is_active=False."""
    stmt = select(User).options(joinedload(User.role)).where(User.id == user_id)
    user = (await db.execute(stmt)).scalars().first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    user.is_active = False

    client_ip = get_client_ip(request)
    await log_audit(
        db=db,
        action="user.deactivated",
        actor_user_id=admin_user.id,
        entity_type="user",
        entity_id=user.id,
        details={"email": user.email},
        ip_address=client_ip,
    )
    await db.commit()
    await db.refresh(user, attribute_names=["role"])

    logger.info(
        "Admin user id=%s deactivated user id=%s (%s)",
        admin_user.id,
        user.id,
        user.email,
    )
    return user
