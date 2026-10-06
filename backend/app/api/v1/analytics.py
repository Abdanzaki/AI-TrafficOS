"""Traffic telemetry and perception analytics API router.

Provides aggregated SQL analytics for traffic flow, incidents distribution, and congestion hotspots.
"""

from datetime import datetime
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.event import Incident
from app.models.intersection import Intersection
from app.models.traffic import TrafficRecord
from app.schemas.analytics import (
    CongestionHotspotResponse,
    IncidentsSummaryResponse,
    TrafficSummaryBucket,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/analytics",
    tags=["analytics"],
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
    "/traffic-summary",
    response_model=list[TrafficSummaryBucket],
    status_code=status.HTTP_200_OK,
    summary="Get bucketed traffic telemetry summary",
)
async def get_traffic_summary(
    intersection_id: Optional[int] = Query(None, description="Filter by intersection ID"),
    from_date: Optional[str] = Query(None, alias="from", description="Start timestamp (inclusive, ISO 8601)"),
    to_date: Optional[str] = Query(None, alias="to", description="End timestamp (inclusive, ISO 8601)"),
    bucket: str = Query("hour", description="Aggregation bucket unit: 'hour' or 'day'"),
    db: AsyncSession = Depends(get_db),
) -> list[TrafficSummaryBucket]:
    """Calculate bucketed average vehicle counts, speeds, congestion levels, and observation counts."""
    bucket_lower = bucket.lower().strip()
    if bucket_lower not in ("hour", "day"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid bucket '{bucket}'. Allowed values: 'hour', 'day'",
        )

    dt_start = parse_query_datetime(from_date)
    dt_end = parse_query_datetime(to_date)

    bucket_col = func.date_trunc(bucket_lower, TrafficRecord.recorded_at).label("bucket")
    stmt = select(
        bucket_col,
        func.avg(TrafficRecord.vehicle_count).label("avg_vehicle_count"),
        func.avg(TrafficRecord.avg_speed_kmh).label("avg_speed"),
        func.avg(TrafficRecord.congestion_level).label("avg_congestion"),
        func.count(TrafficRecord.id).label("record_count"),
    )

    conditions = []
    if intersection_id is not None:
        conditions.append(TrafficRecord.intersection_id == intersection_id)
    if dt_start is not None:
        conditions.append(TrafficRecord.recorded_at >= dt_start)
    if dt_end is not None:
        conditions.append(TrafficRecord.recorded_at <= dt_end)

    if conditions:
        stmt = stmt.where(*conditions)

    stmt = stmt.group_by(bucket_col).order_by(bucket_col.asc())

    result = await db.execute(stmt)
    rows = result.all()

    buckets: list[TrafficSummaryBucket] = []
    for row in rows:
        avg_speed_val = round(float(row.avg_speed), 2) if row.avg_speed is not None else None
        avg_cong_val = round(float(row.avg_congestion), 2) if row.avg_congestion is not None else 0.0
        avg_vc_val = round(float(row.avg_vehicle_count), 2) if row.avg_vehicle_count is not None else 0.0

        buckets.append(
            TrafficSummaryBucket(
                bucket=row.bucket,
                avg_vehicle_count=avg_vc_val,
                avg_speed=avg_speed_val,
                avg_speed_kmh=avg_speed_val,
                avg_congestion=avg_cong_val,
                avg_congestion_level=avg_cong_val,
                record_count=int(row.record_count),
            )
        )

    return buckets


@router.get(
    "/incidents-summary",
    response_model=IncidentsSummaryResponse,
    status_code=status.HTTP_200_OK,
    summary="Get incident counts grouped by severity and status",
)
async def get_incidents_summary(
    from_date: Optional[str] = Query(None, alias="from", description="Start timestamp (inclusive, ISO 8601)"),
    to_date: Optional[str] = Query(None, alias="to", description="End timestamp (inclusive, ISO 8601)"),
    db: AsyncSession = Depends(get_db),
) -> IncidentsSummaryResponse:
    """Retrieve aggregate counts of incidents grouped by severity level and status lifecycle."""
    dt_start = parse_query_datetime(from_date)
    dt_end = parse_query_datetime(to_date)

    conditions = []
    if dt_start is not None:
        conditions.append(Incident.created_at >= dt_start)
    if dt_end is not None:
        conditions.append(Incident.created_at <= dt_end)

    # 1. Grouped by severity
    sev_stmt = select(Incident.severity, func.count(Incident.id))
    if conditions:
        sev_stmt = sev_stmt.where(*conditions)
    sev_stmt = sev_stmt.group_by(Incident.severity)
    sev_result = await db.execute(sev_stmt)
    by_severity = {row[0]: int(row[1]) for row in sev_result.all()}

    # 2. Grouped by status
    status_stmt = select(Incident.status, func.count(Incident.id))
    if conditions:
        status_stmt = status_stmt.where(*conditions)
    status_stmt = status_stmt.group_by(Incident.status)
    status_result = await db.execute(status_stmt)
    by_status = {row[0]: int(row[1]) for row in status_result.all()}

    total = sum(by_status.values())

    return IncidentsSummaryResponse(
        total=total,
        by_severity=by_severity,
        by_status=by_status,
    )


@router.get(
    "/congestion-hotspots",
    response_model=list[CongestionHotspotResponse],
    status_code=status.HTTP_200_OK,
    summary="Get top congested intersection hotspots",
)
async def get_congestion_hotspots(
    from_date: Optional[str] = Query(None, alias="from", description="Start timestamp (inclusive, ISO 8601)"),
    to_date: Optional[str] = Query(None, alias="to", description="End timestamp (inclusive, ISO 8601)"),
    limit: int = Query(10, ge=1, le=100, description="Maximum number of hotspots to return"),
    db: AsyncSession = Depends(get_db),
) -> list[CongestionHotspotResponse]:
    """Rank intersections by average congestion level descending with names and codes."""
    dt_start = parse_query_datetime(from_date)
    dt_end = parse_query_datetime(to_date)

    stmt = (
        select(
            Intersection.id.label("intersection_id"),
            Intersection.name.label("name"),
            Intersection.code.label("code"),
            func.avg(TrafficRecord.congestion_level).label("avg_congestion_level"),
            func.count(TrafficRecord.id).label("record_count"),
        )
        .join(Intersection, TrafficRecord.intersection_id == Intersection.id)
    )

    conditions = []
    if dt_start is not None:
        conditions.append(TrafficRecord.recorded_at >= dt_start)
    if dt_end is not None:
        conditions.append(TrafficRecord.recorded_at <= dt_end)

    if conditions:
        stmt = stmt.where(*conditions)

    stmt = (
        stmt.group_by(Intersection.id, Intersection.name, Intersection.code)
        .order_by(func.avg(TrafficRecord.congestion_level).desc())
        .limit(limit)
    )

    result = await db.execute(stmt)
    rows = result.all()

    hotspots: list[CongestionHotspotResponse] = []
    for row in rows:
        avg_c = round(float(row.avg_congestion_level), 2) if row.avg_congestion_level is not None else 0.0
        hotspots.append(
            CongestionHotspotResponse(
                intersection_id=row.intersection_id,
                name=row.name,
                code=row.code,
                avg_congestion_level=avg_c,
                avg_congestion=avg_c,
                record_count=int(row.record_count),
            )
        )

    return hotspots
