"""Lane schemas module."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class LaneCreate(BaseModel):
    """Schema for creating a lane."""

    road_id: int = Field(..., description="Foreign key to road")
    intersection_id: Optional[int] = Field(None, description="Optional foreign key to intersection")
    lane_number: int = Field(..., ge=1, description="Sequential lane number")
    direction: str = Field(..., min_length=1, max_length=50, description="Heading direction (e.g. northbound)")
    lane_type: str = Field(..., min_length=1, max_length=50, description="Functional type (e.g. through, left_turn, bus)")


class LaneUpdate(BaseModel):
    """Schema for updating a lane."""

    road_id: Optional[int] = Field(None, description="Foreign key to road")
    intersection_id: Optional[int] = Field(None, description="Optional foreign key to intersection")
    lane_number: Optional[int] = Field(None, ge=1, description="Sequential lane number")
    direction: Optional[str] = Field(None, min_length=1, max_length=50, description="Heading direction")
    lane_type: Optional[str] = Field(None, min_length=1, max_length=50, description="Functional type")


class LaneResponse(BaseModel):
    """Schema for lane response."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    road_id: int
    intersection_id: Optional[int] = None
    lane_number: int
    direction: str
    lane_type: str
    created_at: datetime
    updated_at: datetime


class PaginatedLanes(BaseModel):
    """Paginated lane listing response schema."""

    items: list[LaneResponse]
    total: int
    page: int
    per_page: int
    pages: int
