"""System audit log inspection API router.

Provides administrative visibility into immutable system audit logs.
"""

from datetime import datetime
import logging
import math
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import require_roles
from app.core.database import get_db
from app.models.audit import AuditLog
from app.schemas.audit import AuditLogResponse, PaginatedAuditLogs

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/audit-logs",
    tags=["audit-logs"],
    dependencies=[Depends(require_roles("admin"))],
)


def parse_query_datetime(val: Optional[str]) -> Optional[datetime]:
    """Parse query parameter datetime supporting ISO formats, URL unescaped spaces, and trailing Z."""
    if not val:
        return None
    try:
        cleaned = val.strip().replace(" ", "+")
        if cleaned.endswith("Z"):
            cleaned = cleaned[:-1] + "+00:00"
        return datetime.fromisoformat(cleaned)
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid datetime format: '{val}'. Expected ISO 8601 format.",
        )


@router.get(
    "",
    response_model=PaginatedAuditLogs,
    status_code=status.HTTP_200_OK,
    summary="List audit log entries (admin only)",
)
async def list_audit_logs(
    action: Optional[str] = Query(None, description="Filter by audit action (e.g. auth.login, ai_decision.created)"),
    entity_type: Optional[str] = Query(None, description="Filter by entity type (e.g. user, signal, incident)"),
    actor_user_id: Optional[int] = Query(None, description="Filter by actor user ID"),
    from_date: Optional[str] = Query(None, alias="from", description="Created from timestamp (inclusive, ISO 8601)"),
    to_date: Optional[str] = Query(None, alias="to", description="Created to timestamp (inclusive, ISO 8601)"),
    created_from: Optional[str] = Query(None, description="Created from timestamp (alias, ISO 8601)"),
    created_to: Optional[str] = Query(None, description="Created to timestamp (alias, ISO 8601)"),
    page: int = Query(1, ge=1, description="Page number"),
    per_page: int = Query(20, ge=1, le=100, description="Items per page (max 100)"),
    db: AsyncSession = Depends(get_db),
) -> PaginatedAuditLogs:
    """Retrieve paginated immutable audit log events with filtering (admin restricted)."""
    conditions = []
    if action:
        conditions.append(AuditLog.action == action)
    if entity_type:
        conditions.append(AuditLog.entity_type == entity_type)
    if actor_user_id is not None:
        conditions.append(AuditLog.actor_user_id == actor_user_id)

    raw_start = from_date or created_from
    raw_end = to_date or created_to
    dt_start = parse_query_datetime(raw_start)
    dt_end = parse_query_datetime(raw_end)

    if dt_start is not None:
        conditions.append(AuditLog.created_at >= dt_start)
    if dt_end is not None:
        conditions.append(AuditLog.created_at <= dt_end)

    count_stmt = select(func.count(AuditLog.id))
    if conditions:
        count_stmt = count_stmt.where(*conditions)
    total_result = await db.execute(count_stmt)
    total = total_result.scalar() or 0

    offset = (page - 1) * per_page
    stmt = (
        select(AuditLog)
        .options(selectinload(AuditLog.actor))
    )
    if conditions:
        stmt = stmt.where(*conditions)
    stmt = stmt.order_by(AuditLog.created_at.desc(), AuditLog.id.desc()).offset(offset).limit(per_page)

    result = await db.execute(stmt)
    items = list(result.scalars().all())

    pages = math.ceil(total / per_page) if total > 0 else 1

    return PaginatedAuditLogs(
        items=items,
        total=total,
        page=page,
        per_page=per_page,
        pages=pages,
    )
