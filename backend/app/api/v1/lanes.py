"""Lane topology management API router."""

import logging
import math
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_roles
from app.api.v1.auth import get_client_ip
from app.core.audit import log_audit
from app.core.database import get_db
from app.models.auth import User
from app.models.intersection import Intersection
from app.models.road import Lane, Road
from app.schemas.lane import (
    LaneCreate,
    LaneResponse,
    LaneUpdate,
    PaginatedLanes,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/lanes",
    tags=["lanes"],
    dependencies=[Depends(get_current_user)],
)


@router.get(
    "",
    response_model=PaginatedLanes,
    status_code=status.HTTP_200_OK,
    summary="List lanes with pagination and filters",
)
async def list_lanes(
    road_id: Optional[int] = Query(None, description="Filter by road ID"),
    intersection_id: Optional[int] = Query(None, description="Filter by intersection ID"),
    page: int = Query(1, ge=1, description="Page number"),
    per_page: int = Query(20, ge=1, le=100, description="Items per page (max 100)"),
    db: AsyncSession = Depends(get_db),
) -> PaginatedLanes:
    """Retrieve paginated list of roadway lanes."""
    conditions = []
    if road_id is not None:
        conditions.append(Lane.road_id == road_id)
    if intersection_id is not None:
        conditions.append(Lane.intersection_id == intersection_id)

    count_stmt = select(func.count(Lane.id))
    if conditions:
        count_stmt = count_stmt.where(*conditions)
    total_result = await db.execute(count_stmt)
    total = total_result.scalar() or 0

    offset = (page - 1) * per_page
    stmt = select(Lane)
    if conditions:
        stmt = stmt.where(*conditions)
    stmt = stmt.order_by(Lane.id.asc()).offset(offset).limit(per_page)

    result = await db.execute(stmt)
    items = list(result.scalars().all())

    pages = math.ceil(total / per_page) if total > 0 else 1

    return PaginatedLanes(
        items=items,
        total=total,
        page=page,
        per_page=per_page,
        pages=pages,
    )


@router.post(
    "",
    response_model=LaneResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create lane (admin and traffic officer only)",
)
async def create_lane(
    payload: LaneCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles("admin", "traffic_officer")),
) -> Lane:
    """Create a new lane linked to a road and optional intersection."""
    # Validate Road FK exists
    road_stmt = select(Road).where(Road.id == payload.road_id)
    road = (await db.execute(road_stmt)).scalars().first()
    if not road:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Road with id {payload.road_id} not found",
        )

    # Validate Intersection FK exists if provided
    if payload.intersection_id is not None:
        inter_stmt = select(Intersection).where(Intersection.id == payload.intersection_id)
        intersection = (await db.execute(inter_stmt)).scalars().first()
        if not intersection:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Intersection with id {payload.intersection_id} not found",
            )

    lane = Lane(
        road_id=payload.road_id,
        intersection_id=payload.intersection_id,
        lane_number=payload.lane_number,
        direction=payload.direction,
        lane_type=payload.lane_type,
    )
    db.add(lane)
    await db.flush()

    client_ip = get_client_ip(request)
    await log_audit(
        db=db,
        action="lane.created",
        actor_user_id=current_user.id,
        entity_type="lane",
        entity_id=lane.id,
        details={
            "road_id": lane.road_id,
            "intersection_id": lane.intersection_id,
            "lane_number": lane.lane_number,
        },
        ip_address=client_ip,
    )
    await db.commit()
    await db.refresh(lane)

    return lane


@router.get(
    "/{lane_id}",
    response_model=LaneResponse,
    status_code=status.HTTP_200_OK,
    summary="Get lane detail",
)
async def get_lane(
    lane_id: int,
    db: AsyncSession = Depends(get_db),
) -> Lane:
    """Retrieve single lane details."""
    stmt = select(Lane).where(Lane.id == lane_id)
    result = await db.execute(stmt)
    lane = result.scalars().first()
    if not lane:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Lane not found",
        )
    return lane


@router.patch(
    "/{lane_id}",
    response_model=LaneResponse,
    status_code=status.HTTP_200_OK,
    summary="Update lane (admin and traffic officer only)",
)
async def update_lane(
    lane_id: int,
    payload: LaneUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles("admin", "traffic_officer")),
) -> Lane:
    """Update fields on an existing lane."""
    stmt = select(Lane).where(Lane.id == lane_id)
    result = await db.execute(stmt)
    lane = result.scalars().first()
    if not lane:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Lane not found",
        )

    update_data = payload.model_dump(exclude_unset=True)

    # Validate updated Road FK if present
    if "road_id" in update_data and update_data["road_id"] != lane.road_id:
        road_stmt = select(Road).where(Road.id == update_data["road_id"])
        road = (await db.execute(road_stmt)).scalars().first()
        if not road:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Road with id {update_data['road_id']} not found",
            )

    # Validate updated Intersection FK if present
    if "intersection_id" in update_data and update_data["intersection_id"] is not None:
        if update_data["intersection_id"] != lane.intersection_id:
            inter_stmt = select(Intersection).where(Intersection.id == update_data["intersection_id"])
            intersection = (await db.execute(inter_stmt)).scalars().first()
            if not intersection:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Intersection with id {update_data['intersection_id']} not found",
                )

    for field, value in update_data.items():
        setattr(lane, field, value)

    await db.flush()

    client_ip = get_client_ip(request)
    await log_audit(
        db=db,
        action="lane.updated",
        actor_user_id=current_user.id,
        entity_type="lane",
        entity_id=lane.id,
        details=update_data,
        ip_address=client_ip,
    )
    await db.commit()
    await db.refresh(lane)

    return lane


@router.delete(
    "/{lane_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete lane (admin only)",
)
async def delete_lane(
    lane_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles("admin")),
) -> Response:
    """Delete an existing lane."""
    stmt = select(Lane).where(Lane.id == lane_id)
    result = await db.execute(stmt)
    lane = result.scalars().first()
    if not lane:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Lane not found",
        )

    client_ip = get_client_ip(request)
    await log_audit(
        db=db,
        action="lane.deleted",
        actor_user_id=current_user.id,
        entity_type="lane",
        entity_id=lane_id,
        details={"road_id": lane.road_id, "lane_number": lane.lane_number},
        ip_address=client_ip,
    )
    await db.delete(lane)
    await db.commit()

    return Response(status_code=status.HTTP_204_NO_CONTENT)
