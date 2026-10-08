"""Vehicle events ingest and telemetry API router."""

from datetime import datetime, timezone
import logging
import math
from typing import Optional, Union

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, insert, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_current_user, require_roles
from app.api.v1.auth import get_client_ip
from app.core.audit import log_audit
from app.core.database import get_db
from app.models.auth import User
from app.models.event import VehicleEvent
from app.models.intersection import Intersection
from app.models.road import Lane
from app.realtime import emit_traffic_update
from app.schemas.vehicle_event import (
    PaginatedVehicleEvents,
    VehicleEventBatchCreate,
    VehicleEventBatchResponse,
    VehicleEventCreate,
    VehicleEventResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/vehicle-events",
    tags=["vehicle-events"],
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
    response_model=PaginatedVehicleEvents,
    status_code=status.HTTP_200_OK,
    summary="List vehicle events with pagination and filters",
)
async def list_vehicle_events(
    intersection_id: Optional[int] = Query(None, description="Filter by intersection ID"),
    lane_id: Optional[int] = Query(None, description="Filter by lane ID"),
    vehicle_type: Optional[str] = Query(None, description="Filter by vehicle type"),
    detected_from: Optional[str] = Query(None, description="Start timestamp (inclusive, ISO 8601)"),
    detected_to: Optional[str] = Query(None, description="End timestamp (inclusive, ISO 8601)"),
    page: int = Query(1, ge=1, description="Page number"),
    per_page: int = Query(20, ge=1, le=100, description="Items per page (max 100)"),
    db: AsyncSession = Depends(get_db),
) -> PaginatedVehicleEvents:
    """Retrieve paginated list of vehicle events with filtering."""
    conditions = []
    if intersection_id is not None:
        conditions.append(VehicleEvent.intersection_id == intersection_id)
    if lane_id is not None:
        conditions.append(VehicleEvent.lane_id == lane_id)
    if vehicle_type is not None:
        conditions.append(VehicleEvent.vehicle_type == vehicle_type)

    dt_from = parse_query_datetime(detected_from)
    dt_to = parse_query_datetime(detected_to)
    if dt_from is not None:
        conditions.append(VehicleEvent.detected_at >= dt_from)
    if dt_to is not None:
        conditions.append(VehicleEvent.detected_at <= dt_to)

    count_stmt = select(func.count(VehicleEvent.id))
    if conditions:
        count_stmt = count_stmt.where(*conditions)
    total_result = await db.execute(count_stmt)
    total = total_result.scalar() or 0

    offset = (page - 1) * per_page
    stmt = (
        select(VehicleEvent)
        .options(
            selectinload(VehicleEvent.intersection),
            selectinload(VehicleEvent.lane),
        )
    )
    if conditions:
        stmt = stmt.where(*conditions)
    stmt = stmt.order_by(VehicleEvent.detected_at.desc(), VehicleEvent.id.desc()).offset(offset).limit(per_page)

    result = await db.execute(stmt)
    items = list(result.scalars().all())

    pages = math.ceil(total / per_page) if total > 0 else 1

    return PaginatedVehicleEvents(
        items=items,
        total=total,
        page=page,
        per_page=per_page,
        pages=pages,
    )


@router.post(
    "",
    response_model=VehicleEventResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Ingest single vehicle event (officer and admin only)",
)
async def create_vehicle_event(
    payload: VehicleEventCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles("admin", "traffic_officer")),
) -> VehicleEvent:
    """Ingest a single computer vision vehicle detection event."""
    if payload.intersection_id is not None:
        intersection = await db.get(Intersection, payload.intersection_id)
        if not intersection:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Intersection with id {payload.intersection_id} not found",
            )

    if payload.lane_id is not None:
        lane = await db.get(Lane, payload.lane_id)
        if not lane:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Lane with id {payload.lane_id} not found",
            )

    event = VehicleEvent(
        intersection_id=payload.intersection_id,
        lane_id=payload.lane_id,
        event_type=payload.event_type or "detection",
        vehicle_type=payload.vehicle_type or "car",
        speed_kmh=payload.speed_kmh,
        direction=payload.direction,
        confidence=payload.confidence,
        detected_at=payload.detected_at or datetime.now(timezone.utc),
    )
    db.add(event)
    await db.flush()

    client_ip = get_client_ip(request)
    await log_audit(
        db=db,
        action="vehicle_event.created",
        actor_user_id=current_user.id,
        entity_type="vehicle_event",
        entity_id=event.id,
        details={
            "vehicle_type": event.vehicle_type,
            "intersection_id": event.intersection_id,
            "lane_id": event.lane_id,
        },
        ip_address=client_ip,
    )
    await db.commit()
    await db.refresh(event)

    return event


@router.post(
    "/batch",
    response_model=VehicleEventBatchResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Batch ingest vehicle events (officer and admin only)",
)
async def batch_ingest_vehicle_events(
    request: Request,
    payload: Union[VehicleEventBatchCreate, list[VehicleEventCreate]] = Body(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles("admin", "traffic_officer")),
) -> VehicleEventBatchResponse:
    """Bulk ingest up to 500 vehicle events in a single executemany/insert query."""
    events = payload.events if isinstance(payload, VehicleEventBatchCreate) else payload

    if not events:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Batch cannot be empty",
        )
    if len(events) > 500:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Batch size exceeds maximum limit of 500 events (received {len(events)})",
        )

    # Validate foreign keys
    intersection_ids = {e.intersection_id for e in events if e.intersection_id is not None}
    if intersection_ids:
        stmt = select(Intersection.id).where(Intersection.id.in_(intersection_ids))
        res = await db.execute(stmt)
        found_intersection_ids = set(res.scalars().all())
        missing_intersections = intersection_ids - found_intersection_ids
        if missing_intersections:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Intersections not found: {sorted(list(missing_intersections))}",
            )

    lane_ids = {e.lane_id for e in events if e.lane_id is not None}
    if lane_ids:
        stmt = select(Lane.id).where(Lane.id.in_(lane_ids))
        res = await db.execute(stmt)
        found_lane_ids = set(res.scalars().all())
        missing_lanes = lane_ids - found_lane_ids
        if missing_lanes:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Lanes not found: {sorted(list(missing_lanes))}",
            )

    now = datetime.now(timezone.utc)
    records = [
        {
            "intersection_id": e.intersection_id,
            "lane_id": e.lane_id,
            "event_type": e.event_type or "detection",
            "vehicle_type": e.vehicle_type or "car",
            "speed_kmh": e.speed_kmh,
            "direction": e.direction,
            "confidence": e.confidence,
            "detected_at": e.detected_at or now,
        }
        for e in events
    ]

    stmt = insert(VehicleEvent).values(records)
    await db.execute(stmt)

    client_ip = get_client_ip(request)
    await log_audit(
        db=db,
        action="vehicle_event.batch_created",
        actor_user_id=current_user.id,
        entity_type="vehicle_event",
        entity_id=None,
        details={"count": len(records)},
        ip_address=client_ip,
    )
    await db.commit()

    junction_ids = sorted(list({r["intersection_id"] for r in records if r["intersection_id"] is not None}))
    dates = [r["detected_at"] for r in records if r["detected_at"] is not None]
    window_start = min(dates).isoformat() if dates else None
    window_end = max(dates).isoformat() if dates else None

    await emit_traffic_update(
        batch_size=len(records),
        junction_ids=junction_ids,
        window_start=window_start,
        window_end=window_end,
    )

    return VehicleEventBatchResponse(
        inserted=len(records),
        message=f"Successfully ingested {len(records)} vehicle events",
    )


@router.get(
    "/{event_id}",
    response_model=VehicleEventResponse,
    status_code=status.HTTP_200_OK,
    summary="Get single vehicle event detail",
)
async def get_vehicle_event(
    event_id: int,
    db: AsyncSession = Depends(get_db),
) -> VehicleEvent:
    """Retrieve single vehicle event with eager loaded intersection and lane."""
    stmt = (
        select(VehicleEvent)
        .options(
            selectinload(VehicleEvent.intersection),
            selectinload(VehicleEvent.lane),
        )
        .where(VehicleEvent.id == event_id)
    )
    result = await db.execute(stmt)
    event = result.scalars().first()
    if not event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Vehicle event with id {event_id} not found",
        )
    return event
