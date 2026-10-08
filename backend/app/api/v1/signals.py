"""Signal controller hardware and phase timing management API router."""

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
from app.models.intersection import Intersection
from app.models.signal import Signal, SignalPhase
from app.realtime import emit_signal_change
from app.schemas.signal import (
    PaginatedSignals,
    SignalCreate,
    SignalOverrideRequest,
    SignalPhaseCreate,
    SignalPhaseResponse,
    SignalPhaseUpdate,
    SignalResponse,
    SignalUpdate,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/signals",
    tags=["signals"],
    dependencies=[Depends(get_current_user)],
)

phases_router = APIRouter(
    prefix="/phases",
    tags=["phases"],
    dependencies=[Depends(get_current_user)],
)


@router.get(
    "",
    response_model=PaginatedSignals,
    status_code=status.HTTP_200_OK,
    summary="List signals with pagination and filters",
)
async def list_signals(
    intersection_id: Optional[int] = Query(None, description="Filter by intersection ID"),
    status_filter: Optional[str] = Query(None, alias="status", description="Filter by status"),
    page: int = Query(1, ge=1, description="Page number"),
    per_page: int = Query(20, ge=1, le=100, description="Items per page (max 100)"),
    db: AsyncSession = Depends(get_db),
) -> PaginatedSignals:
    """Retrieve paginated list of traffic signals."""
    conditions = []
    if intersection_id is not None:
        conditions.append(Signal.intersection_id == intersection_id)
    if status_filter:
        conditions.append(Signal.status == status_filter)

    count_stmt = select(func.count(Signal.id))
    if conditions:
        count_stmt = count_stmt.where(*conditions)
    total_result = await db.execute(count_stmt)
    total = total_result.scalar() or 0

    offset = (page - 1) * per_page
    stmt = select(Signal)
    if conditions:
        stmt = stmt.where(*conditions)
    stmt = stmt.order_by(Signal.id.asc()).offset(offset).limit(per_page)

    result = await db.execute(stmt)
    items = list(result.scalars().all())

    pages = math.ceil(total / per_page) if total > 0 else 1

    return PaginatedSignals(
        items=items,
        total=total,
        page=page,
        per_page=per_page,
        pages=pages,
    )


@router.post(
    "",
    response_model=SignalResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create signal (admin and traffic officer only)",
)
async def create_signal(
    payload: SignalCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles("admin", "traffic_officer")),
) -> Signal:
    """Create a new signal controller unit."""
    # Validate intersection FK exists
    inter_stmt = select(Intersection).where(Intersection.id == payload.intersection_id)
    intersection = (await db.execute(inter_stmt)).scalars().first()
    if not intersection:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Intersection with id {payload.intersection_id} not found",
        )

    # Validate signal code uniqueness
    code_stmt = select(Signal).where(Signal.code == payload.code)
    existing_code = (await db.execute(code_stmt)).scalars().first()
    if existing_code:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Signal with code '{payload.code}' already exists",
        )

    signal = Signal(
        intersection_id=payload.intersection_id,
        code=payload.code,
        status=payload.status,
    )
    db.add(signal)
    await db.flush()

    client_ip = get_client_ip(request)
    await log_audit(
        db=db,
        action="signal.created",
        actor_user_id=current_user.id,
        entity_type="signal",
        entity_id=signal.id,
        details={"code": signal.code, "intersection_id": signal.intersection_id},
        ip_address=client_ip,
    )
    await db.commit()
    await db.refresh(signal)

    await emit_signal_change(
        signal_id=signal.id,
        intersection_id=signal.intersection_id,
        previous_state=None,
        new_state=signal.status,
        change_kind="create",
    )

    return signal


@router.get(
    "/{signal_id}",
    response_model=SignalResponse,
    status_code=status.HTTP_200_OK,
    summary="Get signal detail with ordered phases",
)
async def get_signal(
    signal_id: int,
    db: AsyncSession = Depends(get_db),
) -> Signal:
    """Retrieve single signal with phases ordered by phase_order."""
    stmt = (
        select(Signal)
        .options(selectinload(Signal.phases))
        .where(Signal.id == signal_id)
    )
    result = await db.execute(stmt)
    signal = result.scalars().first()
    if not signal:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Signal not found",
        )
    signal.phases.sort(key=lambda p: (p.phase_order, p.id))
    return signal


@router.patch(
    "/{signal_id}",
    response_model=SignalResponse,
    status_code=status.HTTP_200_OK,
    summary="Update signal (admin and traffic officer only)",
)
async def update_signal(
    signal_id: int,
    payload: SignalUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles("admin", "traffic_officer")),
) -> Signal:
    """Update fields on an existing signal controller."""
    stmt = (
        select(Signal)
        .options(selectinload(Signal.phases))
        .where(Signal.id == signal_id)
    )
    result = await db.execute(stmt)
    signal = result.scalars().first()
    if not signal:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Signal not found",
        )

    update_data = payload.model_dump(exclude_unset=True)
    old_status = signal.status
    old_observed_state = signal.observed_state

    # Validate updated intersection if present
    if "intersection_id" in update_data and update_data["intersection_id"] != signal.intersection_id:
        inter_stmt = select(Intersection).where(Intersection.id == update_data["intersection_id"])
        intersection = (await db.execute(inter_stmt)).scalars().first()
        if not intersection:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Intersection with id {update_data['intersection_id']} not found",
            )

    # Validate updated code if present
    if "code" in update_data and update_data["code"] != signal.code:
        code_stmt = select(Signal).where(
            Signal.code == update_data["code"],
            Signal.id != signal_id,
        )
        existing_code = (await db.execute(code_stmt)).scalars().first()
        if existing_code:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Signal with code '{update_data['code']}' already exists",
            )

    for field, value in update_data.items():
        setattr(signal, field, value)

    await db.flush()

    client_ip = get_client_ip(request)
    await log_audit(
        db=db,
        action="signal.updated",
        actor_user_id=current_user.id,
        entity_type="signal",
        entity_id=signal.id,
        details=update_data,
        ip_address=client_ip,
    )
    await db.commit()
    await db.refresh(signal)
    signal.phases.sort(key=lambda p: (p.phase_order, p.id))

    # Real-time event publishing hook: emit only if state actually changed
    if signal.status != old_status:
        await emit_signal_change(
            signal_id=signal.id,
            intersection_id=signal.intersection_id,
            previous_state=old_status,
            new_state=signal.status,
            change_kind="update",
        )
    elif signal.observed_state != old_observed_state:
        await emit_signal_change(
            signal_id=signal.id,
            intersection_id=signal.intersection_id,
            previous_state=old_observed_state,
            new_state=signal.observed_state,
            change_kind="update",
        )

    return signal


@router.delete(
    "/{signal_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete signal (admin only)",
)
async def delete_signal(
    signal_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles("admin")),
) -> Response:
    """Delete an existing signal controller."""
    stmt = select(Signal).where(Signal.id == signal_id)
    result = await db.execute(stmt)
    signal = result.scalars().first()
    if not signal:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Signal not found",
        )

    deleted_signal_id = signal.id
    deleted_intersection_id = signal.intersection_id
    old_status = signal.status

    client_ip = get_client_ip(request)
    await log_audit(
        db=db,
        action="signal.deleted",
        actor_user_id=current_user.id,
        entity_type="signal",
        entity_id=signal_id,
        details={"code": signal.code},
        ip_address=client_ip,
    )
    await db.delete(signal)
    await db.commit()

    await emit_signal_change(
        signal_id=deleted_signal_id,
        intersection_id=deleted_intersection_id,
        previous_state=old_status,
        new_state="deleted",
        change_kind="delete",
    )

    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{signal_id}/override",
    response_model=SignalResponse,
    status_code=status.HTTP_200_OK,
    summary="Manual signal override (admin and traffic officer only)",
)
async def override_signal(
    signal_id: int,
    payload: SignalOverrideRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles("admin", "traffic_officer")),
) -> Signal:
    """Manual signal override for traffic officers: sets is_active appropriately and logs audit trail."""
    stmt = (
        select(Signal)
        .options(selectinload(Signal.phases))
        .where(Signal.id == signal_id)
    )
    result = await db.execute(stmt)
    signal = result.scalars().first()
    if not signal:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Signal not found",
        )

    active_before = next((p for p in signal.phases if p.is_active), None)
    active_state_before = active_before.state if active_before else None
    active_id_before = active_before.id if active_before else None

    if payload.phase_id is not None:
        target_phase = next((p for p in signal.phases if p.id == payload.phase_id), None)
        if not target_phase:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"SignalPhase with id {payload.phase_id} not found on signal {signal_id}",
            )
        target_phase.is_active = payload.is_active if payload.is_active is not None else True
        if payload.state:
            target_phase.state = payload.state
        for p in signal.phases:
            if p.id != target_phase.id:
                p.is_active = False
    elif payload.state is not None:
        matched = False
        for p in signal.phases:
            if p.state == payload.state:
                p.is_active = True
                matched = True
            else:
                p.is_active = False
        if not matched and signal.phases:
            signal.phases[0].state = payload.state
            signal.phases[0].is_active = True
            for p in signal.phases[1:]:
                p.is_active = False

    await db.flush()

    client_ip = get_client_ip(request)
    await log_audit(
        db=db,
        action="signal.override",
        actor_user_id=current_user.id,
        entity_type="signal",
        entity_id=signal.id,
        details={
            "phase_id": payload.phase_id,
            "state": payload.state,
            "is_active": payload.is_active,
            "reason": payload.reason,
        },
        ip_address=client_ip,
    )
    await db.commit()
    await db.refresh(signal)
    signal.phases.sort(key=lambda p: (p.phase_order, p.id))

    active_after = next((p for p in signal.phases if p.is_active), None)
    active_state_after = active_after.state if active_after else None
    active_id_after = active_after.id if active_after else None

    if active_id_before != active_id_after or active_state_before != active_state_after:
        await emit_signal_change(
            signal_id=signal.id,
            intersection_id=signal.intersection_id,
            previous_state=active_state_before,
            new_state=active_state_after,
            change_kind="override",
        )

    return signal


@router.post(
    "/{signal_id}/phases",
    response_model=SignalPhaseResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add phase to signal (admin and traffic officer only)",
)
async def create_signal_phase(
    signal_id: int,
    payload: SignalPhaseCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles("admin", "traffic_officer")),
) -> SignalPhase:
    """Create a new phase interval associated with a signal controller."""
    signal_stmt = select(Signal).where(Signal.id == signal_id)
    signal = (await db.execute(signal_stmt)).scalars().first()
    if not signal:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Signal with id {signal_id} not found",
        )

    intersection_id = payload.intersection_id or signal.intersection_id
    if payload.intersection_id is not None:
        inter_stmt = select(Intersection).where(Intersection.id == payload.intersection_id)
        if not (await db.execute(inter_stmt)).scalars().first():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Intersection with id {payload.intersection_id} not found",
            )

    phase = SignalPhase(
        signal_id=signal_id,
        intersection_id=intersection_id,
        name=payload.name,
        phase_order=payload.phase_order,
        duration_seconds=payload.duration_seconds,
        state=payload.state,
        is_active=payload.is_active,
    )
    db.add(phase)
    await db.flush()

    client_ip = get_client_ip(request)
    await log_audit(
        db=db,
        action="signal_phase.created",
        actor_user_id=current_user.id,
        entity_type="signal_phase",
        entity_id=phase.id,
        details={
            "signal_id": signal_id,
            "name": phase.name,
            "phase_order": phase.phase_order,
        },
        ip_address=client_ip,
    )
    await db.commit()
    await db.refresh(phase)

    await emit_signal_change(
        signal_id=phase.signal_id,
        intersection_id=phase.intersection_id or intersection_id,
        previous_state=None,
        new_state=phase.state,
        change_kind="phase_create",
    )

    return phase


# Phase direct handlers mounted under /phases


@phases_router.get(
    "/{phase_id}",
    response_model=SignalPhaseResponse,
    status_code=status.HTTP_200_OK,
    summary="Get phase detail",
)
async def get_phase(
    phase_id: int,
    db: AsyncSession = Depends(get_db),
) -> SignalPhase:
    """Retrieve details of a single signal phase interval."""
    stmt = select(SignalPhase).where(SignalPhase.id == phase_id)
    phase = (await db.execute(stmt)).scalars().first()
    if not phase:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Signal phase not found",
        )
    return phase


@phases_router.patch(
    "/{phase_id}",
    response_model=SignalPhaseResponse,
    status_code=status.HTTP_200_OK,
    summary="Update phase (admin and traffic officer only)",
)
async def update_phase(
    phase_id: int,
    payload: SignalPhaseUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles("admin", "traffic_officer")),
) -> SignalPhase:
    """Update fields of an existing signal phase interval."""
    stmt = select(SignalPhase).where(SignalPhase.id == phase_id)
    phase = (await db.execute(stmt)).scalars().first()
    if not phase:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Signal phase not found",
        )

    update_data = payload.model_dump(exclude_unset=True)
    old_state = phase.state
    old_active = phase.is_active

    if "intersection_id" in update_data and update_data["intersection_id"] is not None:
        if update_data["intersection_id"] != phase.intersection_id:
            inter_stmt = select(Intersection).where(Intersection.id == update_data["intersection_id"])
            if not (await db.execute(inter_stmt)).scalars().first():
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Intersection with id {update_data['intersection_id']} not found",
                )

    for field, value in update_data.items():
        setattr(phase, field, value)

    await db.flush()

    client_ip = get_client_ip(request)
    await log_audit(
        db=db,
        action="signal_phase.updated",
        actor_user_id=current_user.id,
        entity_type="signal_phase",
        entity_id=phase.id,
        details=update_data,
        ip_address=client_ip,
    )
    await db.commit()
    await db.refresh(phase)

    if phase.state != old_state or phase.is_active != old_active:
        await emit_signal_change(
            signal_id=phase.signal_id,
            intersection_id=phase.intersection_id or 0,
            previous_state=old_state,
            new_state=phase.state,
            change_kind="phase_update",
        )

    return phase


@phases_router.delete(
    "/{phase_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete phase (admin only)",
)
async def delete_phase(
    phase_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles("admin")),
) -> Response:
    """Delete an existing signal phase interval."""
    stmt = select(SignalPhase).where(SignalPhase.id == phase_id)
    phase = (await db.execute(stmt)).scalars().first()
    if not phase:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Signal phase not found",
        )

    phase_signal_id = phase.signal_id
    phase_intersection_id = phase.intersection_id or 0
    phase_old_state = phase.state

    client_ip = get_client_ip(request)
    await log_audit(
        db=db,
        action="signal_phase.deleted",
        actor_user_id=current_user.id,
        entity_type="signal_phase",
        entity_id=phase_id,
        details={"name": phase.name, "signal_id": phase.signal_id},
        ip_address=client_ip,
    )
    await db.delete(phase)
    await db.commit()

    await emit_signal_change(
        signal_id=phase_signal_id,
        intersection_id=phase_intersection_id,
        previous_state=phase_old_state,
        new_state="deleted",
        change_kind="phase_delete",
    )

    return Response(status_code=status.HTTP_204_NO_CONTENT)


# Also provide /signals/{signal_id}/phases/{phase_id} aliases for convenience
@router.patch(
    "/{signal_id}/phases/{phase_id}",
    response_model=SignalPhaseResponse,
    status_code=status.HTTP_200_OK,
    summary="Update phase via signal path (admin and traffic officer only)",
)
async def update_signal_phase_alias(
    signal_id: int,
    phase_id: int,
    payload: SignalPhaseUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles("admin", "traffic_officer")),
) -> SignalPhase:
    """Alias for updating a signal phase interval."""
    return await update_phase(
        phase_id=phase_id,
        payload=payload,
        request=request,
        db=db,
        current_user=current_user,
    )


@router.delete(
    "/{signal_id}/phases/{phase_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete phase via signal path (admin only)",
)
async def delete_signal_phase_alias(
    signal_id: int,
    phase_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles("admin")),
) -> Response:
    """Alias for deleting a signal phase interval."""
    return await delete_phase(
        phase_id=phase_id,
        request=request,
        db=db,
        current_user=current_user,
    )
