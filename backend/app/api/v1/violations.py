"""Traffic violations management and lifecycle API router."""

from datetime import datetime
import logging
import math
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_current_user, require_roles
from app.api.v1.auth import get_client_ip
from app.core.audit import log_audit
from app.core.database import get_db
from app.models.auth import User
from app.models.intersection import Intersection
from app.models.violation import Violation
from app.schemas.violation import (
    PaginatedViolations,
    ViolationCreate,
    ViolationRead,
    ViolationUpdate,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/violations",
    tags=["violations"],
    dependencies=[Depends(get_current_user)],
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
    response_model=PaginatedViolations,
    status_code=status.HTTP_200_OK,
    summary="List violations with pagination and filters",
)
async def list_violations(
    violation_type: Optional[str] = Query(None, description="Filter by violation type (red_light, wrong_way, no_helmet)"),
    intersection_id: Optional[int] = Query(None, description="Filter by intersection ID"),
    camera_id: Optional[str] = Query(None, description="Filter by camera ID"),
    status_filter: Optional[str] = Query(None, alias="status", description="Filter by status (recorded, reviewed, dismissed, escalated)"),
    from_date: Optional[str] = Query(None, alias="from", description="Detected from timestamp (inclusive, ISO 8601)"),
    to_date: Optional[str] = Query(None, alias="to", description="Detected to timestamp (inclusive, ISO 8601)"),
    created_from: Optional[str] = Query(None, description="Detected from timestamp (alias, ISO 8601)"),
    created_to: Optional[str] = Query(None, description="Detected to timestamp (alias, ISO 8601)"),
    page: int = Query(1, ge=1, description="Page number"),
    per_page: int = Query(20, ge=1, le=100, description="Items per page (max 100)"),
    db: AsyncSession = Depends(get_db),
) -> PaginatedViolations:
    """Retrieve paginated traffic violations matching filter criteria."""
    conditions = []
    if violation_type:
        conditions.append(Violation.violation_type == violation_type.strip().lower())
    if intersection_id is not None:
        conditions.append(Violation.intersection_id == intersection_id)
    if camera_id:
        conditions.append(Violation.camera_id == camera_id.strip())
    if status_filter:
        conditions.append(Violation.status == status_filter.strip().lower())

    raw_start = from_date or created_from
    raw_end = to_date or created_to
    dt_start = parse_query_datetime(raw_start)
    dt_end = parse_query_datetime(raw_end)
    if dt_start is not None:
        conditions.append(Violation.detected_at >= dt_start)
    if dt_end is not None:
        conditions.append(Violation.detected_at <= dt_end)

    count_stmt = select(func.count(Violation.id))
    if conditions:
        count_stmt = count_stmt.where(*conditions)
    total_result = await db.execute(count_stmt)
    total = total_result.scalar() or 0

    offset = (page - 1) * per_page
    stmt = (
        select(Violation)
        .options(
            selectinload(Violation.intersection),
        )
    )
    if conditions:
        stmt = stmt.where(*conditions)
    stmt = stmt.order_by(Violation.detected_at.desc(), Violation.id.desc()).offset(offset).limit(per_page)

    result = await db.execute(stmt)
    items = list(result.scalars().all())

    pages = math.ceil(total / per_page) if total > 0 else 1

    return PaginatedViolations(
        items=items,
        total=total,
        page=page,
        per_page=per_page,
        pages=pages,
    )


@router.post(
    "",
    response_model=ViolationRead,
    status_code=status.HTTP_201_CREATED,
    summary="Record traffic violation (officer, admin, or vision pipeline)",
)
async def create_violation(
    payload: ViolationCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles("admin", "traffic_officer")),
) -> Violation:
    """Record a newly identified traffic violation."""
    if payload.intersection_id is not None:
        intersection = await db.get(Intersection, payload.intersection_id)
        if not intersection:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Intersection with id {payload.intersection_id} not found",
            )

    violation = Violation(
        violation_type=payload.violation_type,
        detected_at=payload.detected_at,
        intersection_id=payload.intersection_id,
        camera_id=payload.camera_id,
        confidence=payload.confidence,
        status=payload.status,
        evidence_ref=payload.evidence_ref,
        details=payload.details,
    )
    db.add(violation)
    await db.flush()

    client_ip = get_client_ip(request)
    await log_audit(
        db=db,
        action="violation.created",
        actor_user_id=current_user.id,
        entity_type="violation",
        entity_id=violation.id,
        details={
            "violation_type": violation.violation_type,
            "status": violation.status,
            "intersection_id": violation.intersection_id,
            "confidence": violation.confidence,
        },
        ip_address=client_ip,
    )
    await db.commit()
    await db.refresh(violation)

    return violation


@router.get(
    "/{violation_id}",
    response_model=ViolationRead,
    status_code=status.HTTP_200_OK,
    summary="Get violation detail",
)
async def get_violation(
    violation_id: int,
    db: AsyncSession = Depends(get_db),
) -> Violation:
    """Retrieve detailed information for a single violation."""
    stmt = (
        select(Violation)
        .options(
            selectinload(Violation.intersection),
        )
        .where(Violation.id == violation_id)
    )
    result = await db.execute(stmt)
    violation = result.scalars().first()
    if not violation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Violation with id {violation_id} not found",
        )
    return violation


@router.patch(
    "/{violation_id}",
    response_model=ViolationRead,
    status_code=status.HTTP_200_OK,
    summary="Update violation status (officer and admin only)",
)
async def update_violation(
    violation_id: int,
    payload: ViolationUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles("admin", "traffic_officer")),
) -> Violation:
    """Update violation status, confidence, or evidence reference."""
    stmt = (
        select(Violation)
        .options(
            selectinload(Violation.intersection),
        )
        .where(Violation.id == violation_id)
    )
    result = await db.execute(stmt)
    violation = result.scalars().first()
    if not violation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Violation with id {violation_id} not found",
        )

    if payload.status is not None:
        violation.status = payload.status
    if payload.confidence is not None:
        violation.confidence = payload.confidence
    if payload.evidence_ref is not None:
        violation.evidence_ref = payload.evidence_ref
    if payload.details is not None:
        violation.details = payload.details

    await db.flush()

    client_ip = get_client_ip(request)
    await log_audit(
        db=db,
        action="violation.updated",
        actor_user_id=current_user.id,
        entity_type="violation",
        entity_id=violation.id,
        details={
            "status": violation.status,
            "confidence": violation.confidence,
        },
        ip_address=client_ip,
    )
    await db.commit()
    await db.refresh(violation)

    return violation
