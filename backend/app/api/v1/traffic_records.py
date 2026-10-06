"""Traffic records and telemetry aggregation API router."""

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
from app.models.intersection import Intersection
from app.models.road import Lane
from app.models.traffic import TrafficRecord
from app.schemas.traffic_record import (
    PaginatedTrafficRecords,
    TrafficRecordBatchCreate,
    TrafficRecordBatchResponse,
    TrafficRecordCreate,
    TrafficRecordResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/traffic-records",
    tags=["traffic-records"],
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
    response_model=PaginatedTrafficRecords,
    status_code=status.HTTP_200_OK,
    summary="List traffic records with pagination and filters",
)
async def list_traffic_records(
    intersection_id: Optional[int] = Query(None, description="Filter by intersection ID"),
    lane_id: Optional[int] = Query(None, description="Filter by lane ID"),
    recorded_from: Optional[str] = Query(None, description="Recorded from timestamp (inclusive, ISO 8601)"),
    recorded_to: Optional[str] = Query(None, description="Recorded to timestamp (inclusive, ISO 8601)"),
    source: Optional[str] = Query(None, description="Filter by observation source (sensor, camera, manual, ai)"),
    page: int = Query(1, ge=1, description="Page number"),
    per_page: int = Query(20, ge=1, le=100, description="Items per page (max 100)"),
    db: AsyncSession = Depends(get_db),
) -> PaginatedTrafficRecords:
    """Retrieve paginated traffic records matching filter criteria."""
    conditions = []
    if intersection_id is not None:
        conditions.append(TrafficRecord.intersection_id == intersection_id)
    if lane_id is not None:
        conditions.append(TrafficRecord.lane_id == lane_id)

    dt_from = parse_query_datetime(recorded_from)
    dt_to = parse_query_datetime(recorded_to)
    if dt_from is not None:
        conditions.append(TrafficRecord.recorded_at >= dt_from)
    if dt_to is not None:
        conditions.append(TrafficRecord.recorded_at <= dt_to)
    if source is not None:
        conditions.append(TrafficRecord.source == source)

    count_stmt = select(func.count(TrafficRecord.id))
    if conditions:
        count_stmt = count_stmt.where(*conditions)
    total_result = await db.execute(count_stmt)
    total = total_result.scalar() or 0

    offset = (page - 1) * per_page
    stmt = (
        select(TrafficRecord)
        .options(
            selectinload(TrafficRecord.intersection),
            selectinload(TrafficRecord.lane),
        )
    )
    if conditions:
        stmt = stmt.where(*conditions)
    stmt = stmt.order_by(TrafficRecord.recorded_at.desc(), TrafficRecord.id.desc()).offset(offset).limit(per_page)

    result = await db.execute(stmt)
    items = list(result.scalars().all())

    pages = math.ceil(total / per_page) if total > 0 else 1

    return PaginatedTrafficRecords(
        items=items,
        total=total,
        page=page,
        per_page=per_page,
        pages=pages,
    )


@router.post(
    "",
    response_model=TrafficRecordResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create traffic record (officer and admin only)",
)
async def create_traffic_record(
    payload: TrafficRecordCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles("admin", "traffic_officer")),
) -> TrafficRecord:
    """Ingest a single aggregated traffic record."""
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

    record = TrafficRecord(
        intersection_id=payload.intersection_id,
        lane_id=payload.lane_id,
        recorded_at=payload.recorded_at or datetime.now(timezone.utc),
        vehicle_count=payload.vehicle_count,
        avg_speed_kmh=payload.avg_speed_kmh,
        congestion_level=payload.congestion_level,
        source=payload.source or "sensor",
    )
    db.add(record)
    await db.flush()

    client_ip = get_client_ip(request)
    await log_audit(
        db=db,
        action="traffic_record.created",
        actor_user_id=current_user.id,
        entity_type="traffic_record",
        entity_id=record.id,
        details={
            "intersection_id": record.intersection_id,
            "vehicle_count": record.vehicle_count,
            "congestion_level": record.congestion_level,
        },
        ip_address=client_ip,
    )
    await db.commit()
    await db.refresh(record)

    return record


@router.post(
    "/batch",
    response_model=TrafficRecordBatchResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Batch ingest traffic records (officer and admin only)",
)
async def batch_ingest_traffic_records(
    request: Request,
    payload: Union[TrafficRecordBatchCreate, list[TrafficRecordCreate]] = Body(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles("admin", "traffic_officer")),
) -> TrafficRecordBatchResponse:
    """Bulk ingest up to 500 traffic records in a single executemany/insert query."""
    records_list = payload.records if isinstance(payload, TrafficRecordBatchCreate) else payload

    if not records_list:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Batch cannot be empty",
        )
    if len(records_list) > 500:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Batch size exceeds maximum limit of 500 records (received {len(records_list)})",
        )

    # Validate foreign keys
    intersection_ids = {r.intersection_id for r in records_list}
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

    lane_ids = {r.lane_id for r in records_list if r.lane_id is not None}
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
            "intersection_id": r.intersection_id,
            "lane_id": r.lane_id,
            "recorded_at": r.recorded_at or now,
            "vehicle_count": r.vehicle_count,
            "avg_speed_kmh": r.avg_speed_kmh,
            "congestion_level": r.congestion_level,
            "source": r.source or "sensor",
        }
        for r in records_list
    ]

    stmt = insert(TrafficRecord).values(records)
    await db.execute(stmt)

    client_ip = get_client_ip(request)
    await log_audit(
        db=db,
        action="traffic_record.batch_created",
        actor_user_id=current_user.id,
        entity_type="traffic_record",
        entity_id=None,
        details={"count": len(records)},
        ip_address=client_ip,
    )
    await db.commit()

    return TrafficRecordBatchResponse(
        inserted=len(records),
        message=f"Successfully ingested {len(records)} traffic records",
    )


@router.get(
    "/{record_id}",
    response_model=TrafficRecordResponse,
    status_code=status.HTTP_200_OK,
    summary="Get single traffic record detail",
)
async def get_traffic_record(
    record_id: int,
    db: AsyncSession = Depends(get_db),
) -> TrafficRecord:
    """Retrieve single traffic record with eager loaded intersection and lane."""
    stmt = (
        select(TrafficRecord)
        .options(
            selectinload(TrafficRecord.intersection),
            selectinload(TrafficRecord.lane),
        )
        .where(TrafficRecord.id == record_id)
    )
    result = await db.execute(stmt)
    record = result.scalars().first()
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Traffic record with id {record_id} not found",
        )
    return record
