"""Emergency events dispatch and telemetry API router."""

from datetime import datetime, timezone
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
from app.models.emergency import EmergencyEvent
from app.models.event import Incident
from app.models.intersection import Intersection
from app.realtime import emit_emergency_created, emit_emergency_updated
from app.schemas.emergency import (
    VALID_EMERGENCY_STATUSES,
    EmergencyEventCreate,
    EmergencyEventResponse,
    EmergencyEventUpdate,
    PaginatedEmergencyEvents,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/emergency-events",
    tags=["emergency-events"],
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
    response_model=PaginatedEmergencyEvents,
    status_code=status.HTTP_200_OK,
    summary="List emergency events with pagination and filters",
)
async def list_emergency_events(
    status_filter: Optional[str] = Query(None, alias="status", description="Filter by status (active, dispatched, on_scene, resolved)"),
    priority: Optional[int] = Query(None, description="Filter by priority level"),
    from_date: Optional[str] = Query(None, alias="from", description="Detected from timestamp (inclusive, ISO 8601)"),
    to_date: Optional[str] = Query(None, alias="to", description="Detected to timestamp (inclusive, ISO 8601)"),
    detected_from: Optional[str] = Query(None, description="Detected from timestamp (alias, ISO 8601)"),
    detected_to: Optional[str] = Query(None, description="Detected to timestamp (alias, ISO 8601)"),
    page: int = Query(1, ge=1, description="Page number"),
    per_page: int = Query(20, ge=1, le=100, description="Items per page (max 100)"),
    db: AsyncSession = Depends(get_db),
) -> PaginatedEmergencyEvents:
    """Retrieve paginated emergency vehicle transit and dispatch events."""
    conditions = []
    if status_filter:
        conditions.append(EmergencyEvent.status == status_filter)
    if priority is not None:
        conditions.append(EmergencyEvent.priority == priority)

    raw_start = from_date or detected_from
    raw_end = to_date or detected_to
    dt_start = parse_query_datetime(raw_start)
    dt_end = parse_query_datetime(raw_end)
    if dt_start is not None:
        conditions.append(EmergencyEvent.detected_at >= dt_start)
    if dt_end is not None:
        conditions.append(EmergencyEvent.detected_at <= dt_end)

    count_stmt = select(func.count(EmergencyEvent.id))
    if conditions:
        count_stmt = count_stmt.where(*conditions)
    total_result = await db.execute(count_stmt)
    total = total_result.scalar() or 0

    offset = (page - 1) * per_page
    stmt = (
        select(EmergencyEvent)
        .options(selectinload(EmergencyEvent.incident))
    )
    if conditions:
        stmt = stmt.where(*conditions)
    stmt = stmt.order_by(EmergencyEvent.detected_at.desc(), EmergencyEvent.id.desc()).offset(offset).limit(per_page)

    result = await db.execute(stmt)
    items = list(result.scalars().all())

    # Populate auto-suggested intersection_id in response items
    for item in items:
        if item.incident and hasattr(item.incident, "intersection_id"):
            setattr(item, "intersection_id", item.incident.intersection_id)

    pages = math.ceil(total / per_page) if total > 0 else 1

    return PaginatedEmergencyEvents(
        items=items,
        total=total,
        page=page,
        per_page=per_page,
        pages=pages,
    )


@router.post(
    "",
    response_model=EmergencyEventResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create emergency event (officer and admin only)",
)
async def create_emergency_event(
    payload: EmergencyEventCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles("admin", "traffic_officer")),
) -> EmergencyEvent:
    """Dispatch or register emergency transit event. Auto-suggests intersection from linked incident if omitted."""
    suggested_intersection_id = payload.intersection_id

    if payload.incident_id is not None:
        incident = await db.get(Incident, payload.incident_id)
        if not incident:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Incident with id {payload.incident_id} not found",
            )
        # Auto-suggest: copy intersection from incident if not explicitly provided
        if suggested_intersection_id is None:
            suggested_intersection_id = incident.intersection_id

    if suggested_intersection_id is not None:
        intersection = await db.get(Intersection, suggested_intersection_id)
        if not intersection:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Intersection with id {suggested_intersection_id} not found",
            )

    cleared_at = payload.cleared_at
    if payload.status == "resolved" and cleared_at is None:
        cleared_at = datetime.now(timezone.utc)

    event = EmergencyEvent(
        incident_id=payload.incident_id,
        vehicle_type=payload.vehicle_type,
        priority=payload.priority,
        status=payload.status,
        detected_at=payload.detected_at or datetime.now(timezone.utc),
        cleared_at=cleared_at,
    )
    db.add(event)
    await db.flush()

    setattr(event, "intersection_id", suggested_intersection_id)

    client_ip = get_client_ip(request)
    await log_audit(
        db=db,
        action="emergency.created",
        actor_user_id=current_user.id,
        entity_type="emergency_event",
        entity_id=event.id,
        details={
            "vehicle_type": event.vehicle_type,
            "priority": event.priority,
            "incident_id": event.incident_id,
            "intersection_id": suggested_intersection_id,
        },
        ip_address=client_ip,
    )
    await db.commit()
    await db.refresh(event)

    setattr(event, "intersection_id", suggested_intersection_id)

    await emit_emergency_created(
        event_id=event.id,
        status=event.status,
        priority=event.priority,
        vehicle_type=event.vehicle_type,
        intersection_id=suggested_intersection_id,
        incident_id=event.incident_id,
    )

    return event


@router.get(
    "/{emergency_id}",
    response_model=EmergencyEventResponse,
    status_code=status.HTTP_200_OK,
    summary="Get emergency event detail",
)
async def get_emergency_event(
    emergency_id: int,
    db: AsyncSession = Depends(get_db),
) -> EmergencyEvent:
    """Retrieve detailed information for a single emergency event."""
    stmt = (
        select(EmergencyEvent)
        .options(selectinload(EmergencyEvent.incident))
        .where(EmergencyEvent.id == emergency_id)
    )
    result = await db.execute(stmt)
    event = result.scalars().first()
    if not event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Emergency event with id {emergency_id} not found",
        )

    if event.incident and hasattr(event.incident, "intersection_id"):
        setattr(event, "intersection_id", event.incident.intersection_id)

    return event


@router.patch(
    "/{emergency_id}",
    response_model=EmergencyEventResponse,
    status_code=status.HTTP_200_OK,
    summary="Update emergency event status and priority (officer and admin only)",
)
async def update_emergency_event(
    emergency_id: int,
    payload: EmergencyEventUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles("admin", "traffic_officer")),
) -> EmergencyEvent:
    """Update emergency event status and priority."""
    stmt = (
        select(EmergencyEvent)
        .options(selectinload(EmergencyEvent.incident))
        .where(EmergencyEvent.id == emergency_id)
    )
    result = await db.execute(stmt)
    event = result.scalars().first()
    if not event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Emergency event with id {emergency_id} not found",
        )

    changes: dict[str, str | int | None] = {}

    if payload.status is not None:
        if payload.status not in VALID_EMERGENCY_STATUSES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid status '{payload.status}'. Valid statuses: {sorted(list(VALID_EMERGENCY_STATUSES))}",
            )
        if payload.status != event.status:
            changes["old_status"] = event.status
            changes["new_status"] = payload.status
            event.status = payload.status

            if payload.status == "resolved" and event.cleared_at is None:
                event.cleared_at = payload.cleared_at or datetime.now(timezone.utc)
            elif payload.status != "resolved" and payload.cleared_at is None:
                event.cleared_at = None

    if payload.priority is not None:
        if payload.priority != event.priority:
            changes["old_priority"] = event.priority
            changes["new_priority"] = payload.priority
            event.priority = payload.priority

    if payload.cleared_at is not None:
        event.cleared_at = payload.cleared_at

    client_ip = get_client_ip(request)
    await log_audit(
        db=db,
        action="emergency.updated",
        actor_user_id=current_user.id,
        entity_type="emergency_event",
        entity_id=event.id,
        details=changes,
        ip_address=client_ip,
    )
    await db.commit()
    await db.refresh(event)

    if event.incident and hasattr(event.incident, "intersection_id"):
        setattr(event, "intersection_id", event.incident.intersection_id)

    if "old_status" in changes and changes["old_status"] != event.status:
        await emit_emergency_updated(
            event_id=event.id,
            old_status=str(changes["old_status"]),
            new_status=event.status,
        )

    return event
