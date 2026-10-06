"""AI decisions and recommendations REST API router.

Provides endpoints for autonomous and advisory decision management, lifecycle state transitions, and auditing.
"""

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
from app.models.ai import AIDecision, AIPrediction
from app.models.auth import User
from app.models.intersection import Intersection
from app.schemas.ai import (
    ALLOWED_TRANSITIONS,
    AIDecisionCreate,
    AIDecisionResponse,
    AIDecisionUpdate,
    PaginatedAIDecisions,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/ai-decisions",
    tags=["ai-decisions"],
    dependencies=[Depends(get_current_user)],
)


@router.post(
    "",
    response_model=AIDecisionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create AI decision recommendation (officer and admin only)",
)
async def create_decision(
    payload: AIDecisionCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles("admin", "traffic_officer")),
) -> AIDecision:
    """Propose an autonomous or advisory control action."""
    if payload.intersection_id is not None:
        intersection = await db.get(Intersection, payload.intersection_id)
        if not intersection:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Intersection with id {payload.intersection_id} not found",
            )

    if payload.prediction_id is not None:
        prediction = await db.get(AIPrediction, payload.prediction_id)
        if not prediction:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"AI prediction with id {payload.prediction_id} not found",
            )

    decision = AIDecision(
        prediction_id=payload.prediction_id,
        intersection_id=payload.intersection_id,
        decision_type=payload.decision_type,
        payload=payload.payload,
        status="proposed",
        rationale=payload.rationale,
    )
    db.add(decision)
    await db.flush()

    client_ip = get_client_ip(request)
    await log_audit(
        db=db,
        action="ai_decision.created",
        actor_user_id=current_user.id,
        entity_type="ai_decision",
        entity_id=decision.id,
        details={
            "decision_type": decision.decision_type,
            "status": decision.status,
            "intersection_id": decision.intersection_id,
            "prediction_id": decision.prediction_id,
        },
        ip_address=client_ip,
    )
    await db.commit()
    await db.refresh(decision)

    return decision


@router.get(
    "",
    response_model=PaginatedAIDecisions,
    status_code=status.HTTP_200_OK,
    summary="List AI decisions with pagination and filters",
)
async def list_decisions(
    decision_type: Optional[str] = Query(None, description="Filter by decision type"),
    status_filter: Optional[str] = Query(None, alias="status", description="Filter by status (proposed, applied, reverted)"),
    intersection_id: Optional[int] = Query(None, description="Filter by intersection ID"),
    page: int = Query(1, ge=1, description="Page number"),
    per_page: int = Query(20, ge=1, le=100, description="Items per page (max 100)"),
    db: AsyncSession = Depends(get_db),
) -> PaginatedAIDecisions:
    """Retrieve paginated decision records matching filter criteria."""
    conditions = []
    if decision_type:
        conditions.append(AIDecision.decision_type == decision_type)
    if status_filter:
        conditions.append(AIDecision.status == status_filter)
    if intersection_id is not None:
        conditions.append(AIDecision.intersection_id == intersection_id)

    count_stmt = select(func.count(AIDecision.id))
    if conditions:
        count_stmt = count_stmt.where(*conditions)
    total_result = await db.execute(count_stmt)
    total = total_result.scalar() or 0

    offset = (page - 1) * per_page
    stmt = (
        select(AIDecision)
        .options(
            selectinload(AIDecision.prediction),
            selectinload(AIDecision.intersection),
            selectinload(AIDecision.applier),
        )
    )
    if conditions:
        stmt = stmt.where(*conditions)
    stmt = stmt.order_by(AIDecision.created_at.desc(), AIDecision.id.desc()).offset(offset).limit(per_page)

    result = await db.execute(stmt)
    items = list(result.scalars().all())

    pages = math.ceil(total / per_page) if total > 0 else 1

    return PaginatedAIDecisions(
        items=items,
        total=total,
        page=page,
        per_page=per_page,
        pages=pages,
    )


@router.get(
    "/{decision_id}",
    response_model=AIDecisionResponse,
    status_code=status.HTTP_200_OK,
    summary="Get AI decision detail",
)
async def get_decision(
    decision_id: int,
    db: AsyncSession = Depends(get_db),
) -> AIDecision:
    """Retrieve detailed information for a single decision record."""
    stmt = (
        select(AIDecision)
        .options(
            selectinload(AIDecision.prediction),
            selectinload(AIDecision.intersection),
            selectinload(AIDecision.applier),
        )
        .where(AIDecision.id == decision_id)
    )
    result = await db.execute(stmt)
    decision = result.scalars().first()
    if not decision:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"AI decision with id {decision_id} not found",
        )
    return decision


@router.patch(
    "/{decision_id}",
    response_model=AIDecisionResponse,
    status_code=status.HTTP_200_OK,
    summary="Update decision lifecycle status (officer and admin only)",
)
async def update_decision(
    decision_id: int,
    payload: AIDecisionUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles("admin", "traffic_officer")),
) -> AIDecision:
    """Transition decision lifecycle state (proposed->applied, proposed->reverted, applied->reverted)."""
    stmt = (
        select(AIDecision)
        .options(
            selectinload(AIDecision.prediction),
            selectinload(AIDecision.intersection),
            selectinload(AIDecision.applier),
        )
        .where(AIDecision.id == decision_id)
    )
    result = await db.execute(stmt)
    decision = result.scalars().first()
    if not decision:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"AI decision with id {decision_id} not found",
        )

    current_status = decision.status
    target_status = payload.status

    valid_targets = ALLOWED_TRANSITIONS.get(current_status, set())
    if target_status not in valid_targets:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid status transition from '{current_status}' to '{target_status}'. Allowed transitions: proposed->applied, proposed->reverted, applied->reverted",
        )

    audit_details = {
        "old_status": current_status,
        "new_status": target_status,
    }

    decision.status = target_status
    if payload.rationale is not None:
        decision.rationale = payload.rationale

    if target_status == "applied":
        applied_time = datetime.now(timezone.utc)
        decision.applied_by = current_user.id
        decision.applied_at = applied_time
        # Store in payload dictionary as well
        existing_payload = dict(decision.payload or {})
        existing_payload["applied_at"] = applied_time.isoformat()
        decision.payload = existing_payload

        audit_details["applied_by"] = current_user.id
        audit_details["applied_at"] = applied_time.isoformat()

    client_ip = get_client_ip(request)
    await log_audit(
        db=db,
        action="ai_decision.updated",
        actor_user_id=current_user.id,
        entity_type="ai_decision",
        entity_id=decision.id,
        details=audit_details,
        ip_address=client_ip,
    )
    await db.commit()
    await db.refresh(decision)

    return decision
