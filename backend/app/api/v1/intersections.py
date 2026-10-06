"""Intersection / Junction management API router."""

import logging
import math
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_current_user, require_roles
from app.api.v1.auth import get_client_ip
from app.core.audit import log_audit
from app.core.database import get_db
from app.models.auth import User
from app.models.intersection import Intersection
from app.schemas.intersection import (
    IntersectionCreate,
    IntersectionResponse,
    IntersectionUpdate,
    PaginatedIntersections,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/junctions",
    tags=["junctions"],
    dependencies=[Depends(get_current_user)],
)


@router.get(
    "",
    response_model=PaginatedIntersections,
    status_code=status.HTTP_200_OK,
    summary="List junctions with pagination and filters",
)
async def list_junctions(
    status_filter: Optional[str] = Query(None, alias="status", description="Filter by status"),
    city: Optional[str] = Query(None, description="Filter by city"),
    zone: Optional[str] = Query(None, description="Filter by zone"),
    search: Optional[str] = Query(None, description="Search name or code (case-insensitive)"),
    page: int = Query(1, ge=1, description="Page number"),
    per_page: int = Query(20, ge=1, le=100, description="Items per page (max 100)"),
    db: AsyncSession = Depends(get_db),
) -> PaginatedIntersections:
    """Retrieve paginated list of physical junctions / intersections."""
    conditions = []
    if status_filter:
        conditions.append(Intersection.status == status_filter)
    if city:
        conditions.append(Intersection.city.ilike(f"%{city}%"))
    if zone:
        conditions.append(Intersection.zone.ilike(f"%{zone}%"))
    if search:
        search_pattern = f"%{search}%"
        conditions.append(
            or_(
                Intersection.name.ilike(search_pattern),
                Intersection.code.ilike(search_pattern),
            )
        )

    count_stmt = select(func.count(Intersection.id))
    if conditions:
        count_stmt = count_stmt.where(*conditions)
    total_result = await db.execute(count_stmt)
    total = total_result.scalar() or 0

    offset = (page - 1) * per_page
    stmt = select(Intersection)
    if conditions:
        stmt = stmt.where(*conditions)
    stmt = stmt.order_by(Intersection.id.asc()).offset(offset).limit(per_page)

    result = await db.execute(stmt)
    items = list(result.scalars().all())

    pages = math.ceil(total / per_page) if total > 0 else 1

    return PaginatedIntersections(
        items=items,
        total=total,
        page=page,
        per_page=per_page,
        pages=pages,
    )


@router.post(
    "",
    response_model=IntersectionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create junction (admin and traffic officer only)",
)
async def create_junction(
    payload: IntersectionCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles("admin", "traffic_officer")),
) -> Intersection:
    """Create a new physical intersection."""
    existing_stmt = select(Intersection).where(Intersection.code == payload.code)
    existing = (await db.execute(existing_stmt)).scalars().first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Intersection with code '{payload.code}' already exists",
        )

    junction = Intersection(
        name=payload.name,
        code=payload.code,
        status=payload.status,
        city=payload.city,
        zone=payload.zone,
        lat=payload.lat,
        lon=payload.lon,
    )
    db.add(junction)
    await db.flush()

    client_ip = get_client_ip(request)
    await log_audit(
        db=db,
        action="junction.created",
        actor_user_id=current_user.id,
        entity_type="junction",
        entity_id=junction.id,
        details={"name": junction.name, "code": junction.code},
        ip_address=client_ip,
    )
    await db.commit()
    await db.refresh(junction)

    return junction


@router.get(
    "/{junction_id}",
    response_model=IntersectionResponse,
    status_code=status.HTTP_200_OK,
    summary="Get junction detail with eager signals and lanes",
)
async def get_junction(
    junction_id: int,
    db: AsyncSession = Depends(get_db),
) -> Intersection:
    """Retrieve single junction with eager loaded signals and lanes."""
    stmt = (
        select(Intersection)
        .options(
            selectinload(Intersection.signals),
            selectinload(Intersection.lanes),
        )
        .where(Intersection.id == junction_id)
    )
    result = await db.execute(stmt)
    junction = result.scalars().first()
    if not junction:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Junction not found",
        )
    return junction


@router.patch(
    "/{junction_id}",
    response_model=IntersectionResponse,
    status_code=status.HTTP_200_OK,
    summary="Update junction (admin and traffic officer only)",
)
async def update_junction(
    junction_id: int,
    payload: IntersectionUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles("admin", "traffic_officer")),
) -> Intersection:
    """Update fields on an existing physical junction."""
    stmt = (
        select(Intersection)
        .options(
            selectinload(Intersection.signals),
            selectinload(Intersection.lanes),
        )
        .where(Intersection.id == junction_id)
    )
    result = await db.execute(stmt)
    junction = result.scalars().first()
    if not junction:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Junction not found",
        )

    update_data = payload.model_dump(exclude_unset=True)
    if "code" in update_data and update_data["code"] != junction.code:
        code_check = await db.execute(
            select(Intersection).where(
                Intersection.code == update_data["code"],
                Intersection.id != junction_id,
            )
        )
        if code_check.scalars().first():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Intersection with code '{update_data['code']}' already exists",
            )

    for field, value in update_data.items():
        setattr(junction, field, value)

    await db.flush()

    client_ip = get_client_ip(request)
    await log_audit(
        db=db,
        action="junction.updated",
        actor_user_id=current_user.id,
        entity_type="junction",
        entity_id=junction.id,
        details=update_data,
        ip_address=client_ip,
    )
    await db.commit()
    await db.refresh(junction)

    return junction


@router.delete(
    "/{junction_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete junction (admin only)",
)
async def delete_junction(
    junction_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles("admin")),
) -> Response:
    """Delete an existing junction."""
    stmt = select(Intersection).where(Intersection.id == junction_id)
    result = await db.execute(stmt)
    junction = result.scalars().first()
    if not junction:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Junction not found",
        )

    client_ip = get_client_ip(request)
    await log_audit(
        db=db,
        action="junction.deleted",
        actor_user_id=current_user.id,
        entity_type="junction",
        entity_id=junction_id,
        details={"name": junction.name, "code": junction.code},
        ip_address=client_ip,
    )
    await db.delete(junction)
    await db.commit()

    return Response(status_code=status.HTTP_204_NO_CONTENT)
