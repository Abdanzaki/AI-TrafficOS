"""AI predictions REST API router.

Provides endpoints for storing temporal forecasting inferences and retrieving paginated prediction records.
"""

from datetime import datetime
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
from app.models.ai import AIPrediction
from app.models.auth import User
from app.models.intersection import Intersection
from app.schemas.ai import (
    AIPredictionCreate,
    AIPredictionResponse,
    PaginatedAIPredictions,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/ai-predictions",
    tags=["ai-predictions"],
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


@router.post(
    "",
    response_model=AIPredictionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create AI prediction record (officer and admin only)",
)
async def create_prediction(
    payload: AIPredictionCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles("admin", "traffic_officer")),
) -> AIPrediction:
    """Record an inference output from the predictive engine or authorized system actors."""
    if payload.intersection_id is not None:
        intersection = await db.get(Intersection, payload.intersection_id)
        if not intersection:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Intersection with id {payload.intersection_id} not found",
            )

    prediction = AIPrediction(
        intersection_id=payload.intersection_id,
        prediction_type=payload.prediction_type,
        predicted_for=payload.predicted_for,
        payload=payload.payload,
        confidence=payload.confidence,
        model_version=payload.model_version,
    )
    db.add(prediction)
    await db.flush()

    client_ip = get_client_ip(request)
    await log_audit(
        db=db,
        action="ai_prediction.created",
        actor_user_id=current_user.id,
        entity_type="ai_prediction",
        entity_id=prediction.id,
        details={
            "prediction_type": prediction.prediction_type,
            "intersection_id": prediction.intersection_id,
            "model_version": prediction.model_version,
            "confidence": prediction.confidence,
        },
        ip_address=client_ip,
    )
    await db.commit()
    await db.refresh(prediction)

    return prediction


@router.get(
    "",
    response_model=PaginatedAIPredictions,
    status_code=status.HTTP_200_OK,
    summary="List AI predictions with pagination and filters",
)
async def list_predictions(
    prediction_type: Optional[str] = Query(None, description="Filter by prediction type (e.g. congestion, flow, incident_risk)"),
    intersection_id: Optional[int] = Query(None, description="Filter by intersection ID"),
    predicted_from: Optional[str] = Query(None, description="Predicted for start timestamp (ISO 8601)"),
    predicted_to: Optional[str] = Query(None, description="Predicted for end timestamp (ISO 8601)"),
    from_date: Optional[str] = Query(None, alias="from", description="Predicted for start timestamp (alias)"),
    to_date: Optional[str] = Query(None, alias="to", description="Predicted for end timestamp (alias)"),
    page: int = Query(1, ge=1, description="Page number"),
    per_page: int = Query(20, ge=1, le=100, description="Items per page (max 100)"),
    db: AsyncSession = Depends(get_db),
) -> PaginatedAIPredictions:
    """Retrieve paginated prediction records matching filter criteria."""
    conditions = []
    if prediction_type:
        conditions.append(AIPrediction.prediction_type == prediction_type)
    if intersection_id is not None:
        conditions.append(AIPrediction.intersection_id == intersection_id)

    raw_start = predicted_from or from_date
    raw_end = predicted_to or to_date
    dt_start = parse_query_datetime(raw_start)
    dt_end = parse_query_datetime(raw_end)

    if dt_start is not None:
        conditions.append(AIPrediction.predicted_for >= dt_start)
    if dt_end is not None:
        conditions.append(AIPrediction.predicted_for <= dt_end)

    count_stmt = select(func.count(AIPrediction.id))
    if conditions:
        count_stmt = count_stmt.where(*conditions)
    total_result = await db.execute(count_stmt)
    total = total_result.scalar() or 0

    offset = (page - 1) * per_page
    stmt = (
        select(AIPrediction)
        .options(
            selectinload(AIPrediction.intersection),
            selectinload(AIPrediction.decisions),
        )
    )
    if conditions:
        stmt = stmt.where(*conditions)
    stmt = stmt.order_by(AIPrediction.predicted_for.desc(), AIPrediction.id.desc()).offset(offset).limit(per_page)

    result = await db.execute(stmt)
    items = list(result.scalars().all())

    pages = math.ceil(total / per_page) if total > 0 else 1

    return PaginatedAIPredictions(
        items=items,
        total=total,
        page=page,
        per_page=per_page,
        pages=pages,
    )


@router.get(
    "/{prediction_id}",
    response_model=AIPredictionResponse,
    status_code=status.HTTP_200_OK,
    summary="Get AI prediction detail",
)
async def get_prediction(
    prediction_id: int,
    db: AsyncSession = Depends(get_db),
) -> AIPrediction:
    """Retrieve detailed information for a single prediction record."""
    stmt = (
        select(AIPrediction)
        .options(
            selectinload(AIPrediction.intersection),
            selectinload(AIPrediction.decisions),
        )
        .where(AIPrediction.id == prediction_id)
    )
    result = await db.execute(stmt)
    prediction = result.scalars().first()
    if not prediction:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"AI prediction with id {prediction_id} not found",
        )
    return prediction
