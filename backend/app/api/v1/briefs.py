"""Daily traffic briefs REST API router."""

from datetime import date
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.auth import User
from app.schemas.daily_brief import DailyBriefResponse
from app.services.daily_brief import generate_daily_brief

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/briefs",
    tags=["briefs"],
    dependencies=[Depends(get_current_user)],
)


@router.get(
    "/daily",
    response_model=DailyBriefResponse,
    status_code=status.HTTP_200_OK,
    summary="Get daily traffic operations brief",
)
async def get_daily_brief(
    rephrase: bool = Query(
        False,
        description="Optionally run deterministic text through grounded GeminiProvider",
    ),
    target_date: Optional[str] = Query(
        None,
        alias="date",
        description="Target reference date in YYYY-MM-DD format (defaults to yesterday)",
    ),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DailyBriefResponse:
    """Retrieve daily morning traffic operations brief.

    Aggregates yesterday's observed incidents and violations, today's predicted
    hotspots from AI forecasting models, and day-over-day operational trends.
    Each section includes explicit data provenance ('observed' or 'predicted')
    and honest empty-state notes when data is missing.
    """
    parsed_date: Optional[date] = None
    if target_date:
        try:
            parsed_date = date.fromisoformat(target_date.strip())
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid date format '{target_date}'. Expected YYYY-MM-DD format.",
            )

    brief = await generate_daily_brief(
        db=db,
        target_date=parsed_date,
        rephrase=rephrase,
    )
    return DailyBriefResponse(**brief)
