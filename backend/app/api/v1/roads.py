"""Road network management API router."""

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
from app.models.road import Road
from app.schemas.road import (
    PaginatedRoads,
    RoadCreate,
    RoadResponse,
    RoadUpdate,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/roads",
    tags=["roads"],
    dependencies=[Depends(get_current_user)],
)


@router.get(
    "",
    response_model=PaginatedRoads,
    status_code=status.HTTP_200_OK,
    summary="List roads with pagination and filters",
)
async def list_roads(
    road_type: Optional[str] = Query(None, description="Filter by road classification"),
    search: Optional[str] = Query(None, description="Search road name (case-insensitive)"),
    page: int = Query(1, ge=1, description="Page number"),
    per_page: int = Query(20, ge=1, le=100, description="Items per page (max 100)"),
    db: AsyncSession = Depends(get_db),
) -> PaginatedRoads:
    """Retrieve paginated list of roadway segments."""
    conditions = []
    if road_type:
        conditions.append(Road.road_type == road_type)
    if search:
        conditions.append(Road.name.ilike(f"%{search}%"))

    count_stmt = select(func.count(Road.id))
    if conditions:
        count_stmt = count_stmt.where(*conditions)
    total_result = await db.execute(count_stmt)
    total = total_result.scalar() or 0

    offset = (page - 1) * per_page
    stmt = select(Road)
    if conditions:
        stmt = stmt.where(*conditions)
    stmt = stmt.order_by(Road.id.asc()).offset(offset).limit(per_page)

    result = await db.execute(stmt)
    items = list(result.scalars().all())

    pages = math.ceil(total / per_page) if total > 0 else 1

    return PaginatedRoads(
        items=items,
        total=total,
        page=page,
        per_page=per_page,
        pages=pages,
    )


@router.post(
    "",
    response_model=RoadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create road (admin and traffic officer only)",
)
async def create_road(
    payload: RoadCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles("admin", "traffic_officer")),
) -> Road:
    """Create a new roadway segment."""
    road = Road(
        name=payload.name,
        road_type=payload.road_type,
        speed_limit_kmh=payload.speed_limit_kmh,
        geometry=payload.geometry,
    )
    db.add(road)
    await db.flush()

    client_ip = get_client_ip(request)
    await log_audit(
        db=db,
        action="road.created",
        actor_user_id=current_user.id,
        entity_type="road",
        entity_id=road.id,
        details={"name": road.name, "road_type": road.road_type},
        ip_address=client_ip,
    )
    await db.commit()
    await db.refresh(road)

    return road


@router.get(
    "/{road_id}",
    response_model=RoadResponse,
    status_code=status.HTTP_200_OK,
    summary="Get road detail with eager lanes",
)
async def get_road(
    road_id: int,
    db: AsyncSession = Depends(get_db),
) -> Road:
    """Retrieve single road with eager loaded lanes."""
    stmt = (
        select(Road)
        .options(selectinload(Road.lanes))
        .where(Road.id == road_id)
    )
    result = await db.execute(stmt)
    road = result.scalars().first()
    if not road:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Road not found",
        )
    return road


@router.patch(
    "/{road_id}",
    response_model=RoadResponse,
    status_code=status.HTTP_200_OK,
    summary="Update road (admin and traffic officer only)",
)
async def update_road(
    road_id: int,
    payload: RoadUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles("admin", "traffic_officer")),
) -> Road:
    """Update fields on an existing roadway segment."""
    stmt = (
        select(Road)
        .options(selectinload(Road.lanes))
        .where(Road.id == road_id)
    )
    result = await db.execute(stmt)
    road = result.scalars().first()
    if not road:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Road not found",
        )

    update_data = payload.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(road, field, value)

    await db.flush()

    client_ip = get_client_ip(request)
    await log_audit(
        db=db,
        action="road.updated",
        actor_user_id=current_user.id,
        entity_type="road",
        entity_id=road.id,
        details=update_data,
        ip_address=client_ip,
    )
    await db.commit()
    await db.refresh(road)

    return road


@router.delete(
    "/{road_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete road (admin only)",
)
async def delete_road(
    road_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles("admin")),
) -> Response:
    """Delete an existing roadway segment."""
    stmt = select(Road).where(Road.id == road_id)
    result = await db.execute(stmt)
    road = result.scalars().first()
    if not road:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Road not found",
        )

    client_ip = get_client_ip(request)
    await log_audit(
        db=db,
        action="road.deleted",
        actor_user_id=current_user.id,
        entity_type="road",
        entity_id=road_id,
        details={"name": road.name},
        ip_address=client_ip,
    )
    await db.delete(road)
    await db.commit()

    return Response(status_code=status.HTTP_204_NO_CONTENT)
