"""Intersection schemas module."""

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.lane import LaneResponse
from app.schemas.signal import SignalResponse


class IntersectionCreate(BaseModel):
    """Schema for creating an intersection / junction."""

    name: str = Field(..., min_length=1, max_length=120, description="Intersection name")
    code: str = Field(..., min_length=1, max_length=50, description="Unique operational code")
    status: str = Field("active", min_length=1, max_length=30, description="Status (e.g. active, inactive, maintenance)")
    city: Optional[str] = Field(None, max_length=100, description="Municipality / City")
    zone: Optional[str] = Field(None, max_length=100, description="Zoning / District")
    lat: Optional[float] = Field(None, ge=-90.0, le=90.0, description="Latitude coordinate")
    lon: Optional[float] = Field(None, ge=-180.0, le=180.0, description="Longitude coordinate")


class IntersectionUpdate(BaseModel):
    """Schema for updating an intersection / junction."""

    name: Optional[str] = Field(None, min_length=1, max_length=120)
    code: Optional[str] = Field(None, min_length=1, max_length=50)
    status: Optional[str] = Field(None, min_length=1, max_length=30)
    city: Optional[str] = Field(None, max_length=100)
    zone: Optional[str] = Field(None, max_length=100)
    lat: Optional[float] = Field(None, ge=-90.0, le=90.0)
    lon: Optional[float] = Field(None, ge=-180.0, le=180.0)


class IntersectionResponse(BaseModel):
    """Schema for intersection / junction response."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    code: str
    status: str
    city: Optional[str] = None
    zone: Optional[str] = None
    lat: Optional[float] = None
    lon: Optional[float] = None
    created_at: datetime
    updated_at: datetime
    lanes: Optional[list[LaneResponse]] = None
    signals: Optional[list[SignalResponse]] = None

    @model_validator(mode="before")
    @classmethod
    def handle_unloaded_relationships(cls, data: Any) -> Any:
        """Prevent lazy loading missing greenlet error on lanes and signals relations."""
        if hasattr(data, "__dict__"):
            d = dict(data.__dict__)
            d.pop("_sa_instance_state", None)
            if "lanes" not in data.__dict__:
                d["lanes"] = None
            if "signals" not in data.__dict__:
                d["signals"] = None
            return d
        return data


class PaginatedIntersections(BaseModel):
    """Paginated intersection listing response schema."""

    items: list[IntersectionResponse]
    total: int
    page: int
    per_page: int
    pages: int
