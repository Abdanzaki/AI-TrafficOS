"""Notification and operator alert API router."""

import logging
import math
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_roles
from app.api.v1.auth import get_client_ip
from app.core.audit import log_audit
from app.core.database import get_db
from app.models.auth import User
from app.models.notification import Notification
from app.realtime import emit_notification_created
from app.schemas.notification import (
    NotificationBroadcastCreate,
    NotificationCreate,
    NotificationResponse,
    PaginatedNotifications,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/notifications",
    tags=["notifications"],
    dependencies=[Depends(get_current_user)],
)


@router.get(
    "/me",
    response_model=PaginatedNotifications,
    status_code=status.HTTP_200_OK,
    summary="List notifications for the authenticated user and system broadcasts",
)
async def get_my_notifications(
    is_read: Optional[bool] = Query(None, description="Filter by read/unread status"),
    severity: Optional[str] = Query(None, description="Filter by severity level"),
    page: int = Query(1, ge=1, description="Page number"),
    per_page: int = Query(20, ge=1, le=100, description="Items per page (max 100)"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PaginatedNotifications:
    """Retrieve current user's targeted notifications plus global broadcast notifications."""
    conditions = [
        or_(
            Notification.user_id == current_user.id,
            Notification.user_id.is_(None),
        )
    ]
    if is_read is not None:
        conditions.append(Notification.is_read == is_read)
    if severity is not None:
        conditions.append(Notification.severity == severity)

    count_stmt = select(func.count(Notification.id)).where(*conditions)
    total_result = await db.execute(count_stmt)
    total = total_result.scalar() or 0

    offset = (page - 1) * per_page
    stmt = (
        select(Notification)
        .where(*conditions)
        .order_by(Notification.created_at.desc(), Notification.id.desc())
        .offset(offset)
        .limit(per_page)
    )

    result = await db.execute(stmt)
    items = list(result.scalars().all())

    pages = math.ceil(total / per_page) if total > 0 else 1

    return PaginatedNotifications(
        items=items,
        total=total,
        page=page,
        per_page=per_page,
        pages=pages,
    )


@router.patch(
    "/{notification_id}/read",
    response_model=NotificationResponse,
    status_code=status.HTTP_200_OK,
    summary="Mark own notification or broadcast as read",
)
async def mark_notification_read(
    notification_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Notification:
    """Mark a notification as read. Forbidden (403) if targeted to another user."""
    notification = await db.get(Notification, notification_id)
    if not notification:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Notification with id {notification_id} not found",
        )

    # 403 Forbidden if it belongs to another user
    if notification.user_id is not None and notification.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: Cannot mark notification belonging to another user",
        )

    notification.is_read = True

    client_ip = get_client_ip(request)
    await log_audit(
        db=db,
        action="notification.read",
        actor_user_id=current_user.id,
        entity_type="notification",
        entity_id=notification.id,
        details={"title": notification.title, "user_id": notification.user_id},
        ip_address=client_ip,
    )
    await db.commit()
    await db.refresh(notification)

    return notification


async def create_notification(
    db: AsyncSession,
    *,
    user_id: Optional[int],
    title: str,
    message: str,
    severity: str,
    entity_type: Optional[str] = None,
    entity_id: Optional[int] = None,
    actor_user_id: Optional[int] = None,
    client_ip: Optional[str] = None,
    audit_action: str = "notification.created",
    audit_details: Optional[dict[str, Any]] = None,
) -> Notification:
    """Shared notification creation helper.

    Guarantees:
    - Persists Notification record to database.
    - Emits audit log entry.
    - Commits transaction and refreshes model.
    - Emits real-time notification.created event exactly once across all creation paths.
    """
    notification = Notification(
        user_id=user_id,
        title=title,
        message=message,
        severity=severity,
        entity_type=entity_type,
        entity_id=entity_id,
        is_read=False,
    )
    db.add(notification)
    await db.flush()

    if actor_user_id is not None:
        await log_audit(
            db=db,
            action=audit_action,
            actor_user_id=actor_user_id,
            entity_type="notification",
            entity_id=notification.id,
            details=audit_details or {"title": notification.title, "severity": notification.severity},
            ip_address=client_ip,
        )

    await db.commit()
    await db.refresh(notification)

    # Real-time event publishing hook: emit notification.created delta
    await emit_notification_created(
        notification_id=notification.id,
        severity=notification.severity,
        title=notification.title,
    )

    return notification


@router.post(
    "/broadcast",
    response_model=NotificationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create broadcast notification (admin only)",
)
async def create_broadcast_notification(
    payload: NotificationBroadcastCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles("admin")),
) -> Notification:
    """Broadcast an alert system-wide across all platform operators (user_id is NULL)."""
    return await create_notification(
        db=db,
        user_id=None,
        title=payload.title,
        message=payload.message,
        severity=payload.severity,
        entity_type=payload.entity_type,
        entity_id=payload.entity_id,
        actor_user_id=current_user.id,
        client_ip=get_client_ip(request),
        audit_action="notification.broadcast",
        audit_details={"title": payload.title, "severity": payload.severity},
    )


@router.post(
    "",
    response_model=NotificationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create targeted notification (admin and officer only)",
)
async def create_targeted_notification(
    payload: NotificationCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles("admin", "traffic_officer")),
) -> Notification:
    """Send targeted notification to a specific user (validates recipient exists)."""
    target_user = await db.get(User, payload.user_id)
    if not target_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Target user with id {payload.user_id} not found",
        )

    return await create_notification(
        db=db,
        user_id=payload.user_id,
        title=payload.title,
        message=payload.message,
        severity=payload.severity,
        entity_type=payload.entity_type,
        entity_id=payload.entity_id,
        actor_user_id=current_user.id,
        client_ip=get_client_ip(request),
        audit_action="notification.created",
        audit_details={"title": payload.title, "target_user_id": payload.user_id},
    )


@router.get(
    "/{notification_id}",
    response_model=NotificationResponse,
    status_code=status.HTTP_200_OK,
    summary="Get single notification detail",
)
async def get_notification(
    notification_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Notification:
    """Retrieve single notification detail."""
    notification = await db.get(Notification, notification_id)
    if not notification:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Notification with id {notification_id} not found",
        )
    return notification
