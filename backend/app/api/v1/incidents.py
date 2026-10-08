"""Incidents management and lifecycle API router."""

from datetime import datetime, timezone
import logging
import math
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_current_user, require_roles
from app.api.v1.auth import get_client_ip
from app.core.audit import log_audit
from app.core.database import get_db
from app.models.auth import User
from app.models.event import Incident
from app.models.intersection import Intersection
from app.realtime import emit_incident_created, emit_incident_updated
from app.schemas.incident import (
    VALID_INCIDENT_STATUSES,
    IncidentCreate,
    IncidentResponse,
    IncidentUpdate,
    PaginatedIncidents,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/incidents",
    tags=["incidents"],
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
    response_model=PaginatedIncidents,
    status_code=status.HTTP_200_OK,
    summary="List incidents with pagination and filters",
)
async def list_incidents(
    status_filter: Optional[str] = Query(None, alias="status", description="Filter by status (reported, acknowledged, resolved)"),
    severity: Optional[str] = Query(None, description="Filter by severity (low, medium, high, critical, unknown)"),
    intersection_id: Optional[int] = Query(None, description="Filter by intersection ID"),
    from_date: Optional[str] = Query(None, alias="from", description="Created from timestamp (inclusive, ISO 8601)"),
    to_date: Optional[str] = Query(None, alias="to", description="Created to timestamp (inclusive, ISO 8601)"),
    created_from: Optional[str] = Query(None, description="Created from timestamp (alias, ISO 8601)"),
    created_to: Optional[str] = Query(None, description="Created to timestamp (alias, ISO 8601)"),
    page: int = Query(1, ge=1, description="Page number"),
    per_page: int = Query(20, ge=1, le=100, description="Items per page (max 100)"),
    db: AsyncSession = Depends(get_db),
) -> PaginatedIncidents:
    """Retrieve paginated incidents matching filter criteria."""
    conditions = []
    if status_filter:
        conditions.append(Incident.status == status_filter)
    if severity:
        conditions.append(Incident.severity == severity)
    if intersection_id is not None:
        conditions.append(Incident.intersection_id == intersection_id)

    raw_start = from_date or created_from
    raw_end = to_date or created_to
    dt_start = parse_query_datetime(raw_start)
    dt_end = parse_query_datetime(raw_end)
    if dt_start is not None:
        conditions.append(Incident.created_at >= dt_start)
    if dt_end is not None:
        conditions.append(Incident.created_at <= dt_end)

    count_stmt = select(func.count(Incident.id))
    if conditions:
        count_stmt = count_stmt.where(*conditions)
    total_result = await db.execute(count_stmt)
    total = total_result.scalar() or 0

    offset = (page - 1) * per_page
    stmt = (
        select(Incident)
        .options(
            selectinload(Incident.intersection),
            selectinload(Incident.reporter),
            selectinload(Incident.emergency_events),
        )
    )
    if conditions:
        stmt = stmt.where(*conditions)
    stmt = stmt.order_by(Incident.created_at.desc(), Incident.id.desc()).offset(offset).limit(per_page)

    result = await db.execute(stmt)
    items = list(result.scalars().all())

    pages = math.ceil(total / per_page) if total > 0 else 1

    return PaginatedIncidents(
        items=items,
        total=total,
        page=page,
        per_page=per_page,
        pages=pages,
    )


@router.post(
    "",
    response_model=IncidentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create incident (officer and admin only)",
)
async def create_incident(
    payload: IncidentCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles("admin", "traffic_officer")),
) -> Incident:
    """Report a new traffic incident or hazard."""
    if payload.intersection_id is not None:
        intersection = await db.get(Intersection, payload.intersection_id)
        if not intersection:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Intersection with id {payload.intersection_id} not found",
            )

    resolved_at = datetime.now(timezone.utc) if payload.status == "resolved" else None

    incident = Incident(
        intersection_id=payload.intersection_id,
        severity=payload.severity,
        status=payload.status,
        description=payload.description,
        reported_by=current_user.id,
        resolved_at=resolved_at,
        lat=payload.lat,
        lon=payload.lon,
    )
    db.add(incident)
    await db.flush()

    client_ip = get_client_ip(request)
    await log_audit(
        db=db,
        action="incident.created",
        actor_user_id=current_user.id,
        entity_type="incident",
        entity_id=incident.id,
        details={
            "status": incident.status,
            "severity": incident.severity,
            "intersection_id": incident.intersection_id,
        },
        ip_address=client_ip,
    )
    await db.commit()
    await db.refresh(incident)

    await emit_incident_created(
        incident_id=incident.id,
        severity=incident.severity,
        intersection_id=incident.intersection_id,
        status=incident.status,
    )

    return incident


@router.get(
    "/{incident_id}",
    response_model=IncidentResponse,
    status_code=status.HTTP_200_OK,
    summary="Get incident detail",
)
async def get_incident(
    incident_id: int,
    db: AsyncSession = Depends(get_db),
) -> Incident:
    """Retrieve detailed information for a single incident."""
    stmt = (
        select(Incident)
        .options(
            selectinload(Incident.intersection),
            selectinload(Incident.reporter),
            selectinload(Incident.emergency_events),
        )
        .where(Incident.id == incident_id)
    )
    result = await db.execute(stmt)
    incident = result.scalars().first()
    if not incident:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Incident with id {incident_id} not found",
        )
    return incident


@router.patch(
    "/{incident_id}",
    response_model=IncidentResponse,
    status_code=status.HTTP_200_OK,
    summary="Update incident and lifecycle status (officer and admin only)",
)
async def update_incident(
    incident_id: int,
    payload: IncidentUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles("admin", "traffic_officer")),
) -> Incident:
    """Update incident attributes and validate lifecycle transitions."""
    stmt = (
        select(Incident)
        .options(
            selectinload(Incident.intersection),
            selectinload(Incident.reporter),
            selectinload(Incident.emergency_events),
        )
        .where(Incident.id == incident_id)
    )
    result = await db.execute(stmt)
    incident = result.scalars().first()
    if not incident:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Incident with id {incident_id} not found",
        )

    if payload.intersection_id is not None:
        intersection = await db.get(Intersection, payload.intersection_id)
        if not intersection:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Intersection with id {payload.intersection_id} not found",
            )
        incident.intersection_id = payload.intersection_id

    changes: dict[str, str | None] = {}

    if payload.status is not None:
        if payload.status not in VALID_INCIDENT_STATUSES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid status '{payload.status}'. Valid statuses: {sorted(list(VALID_INCIDENT_STATUSES))}",
            )
        # Status transition validation: cannot transition from resolved to reported
        if incident.status == "resolved" and payload.status == "reported":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid status transition: cannot transition incident from resolved to reported",
            )
        if payload.status != incident.status:
            changes["old_status"] = incident.status
            changes["new_status"] = payload.status
            incident.status = payload.status

            if payload.status == "resolved" and incident.resolved_at is None:
                incident.resolved_at = payload.resolved_at or datetime.now(timezone.utc)
            elif payload.status != "resolved" and payload.resolved_at is None:
                # If reopening or changing away from resolved without explicit timestamp
                incident.resolved_at = None

    if payload.resolved_at is not None:
        incident.resolved_at = payload.resolved_at

    if payload.severity is not None:
        changes["severity"] = payload.severity
        incident.severity = payload.severity

    if payload.description is not None:
        incident.description = payload.description

    if payload.lat is not None:
        incident.lat = payload.lat

    if payload.lon is not None:
        incident.lon = payload.lon

    client_ip = get_client_ip(request)
    await log_audit(
        db=db,
        action="incident.updated",
        actor_user_id=current_user.id,
        entity_type="incident",
        entity_id=incident.id,
        details=changes,
        ip_address=client_ip,
    )
    await db.commit()
    await db.refresh(incident)

    if "old_status" in changes and changes["old_status"] != incident.status:
        await emit_incident_updated(
            incident_id=incident.id,
            old_status=str(changes["old_status"]),
            new_status=incident.status,
        )

    return incident


@router.delete(
    "/{incident_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete incident (admin only)",
)
async def delete_incident(
    incident_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles("admin")),
) -> Response:
    """Delete an incident permanently (admin only)."""
    incident = await db.get(Incident, incident_id)
    if not incident:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Incident with id {incident_id} not found",
        )

    client_ip = get_client_ip(request)
    await log_audit(
        db=db,
        action="incident.deleted",
        actor_user_id=current_user.id,
        entity_type="incident",
        entity_id=incident.id,
        details={"status": incident.status, "description": incident.description},
        ip_address=client_ip,
    )
    await db.delete(incident)
    await db.commit()

    return Response(status_code=status.HTTP_204_NO_CONTENT)
