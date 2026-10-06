"""VehicleEvent schemas module.

Defines schemas for vehicle detection ingest, batch ingest, and queries.
"""

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


class VehicleEventCreate(BaseModel):
    """Schema for creating a vehicle detection event."""

    intersection_id: Optional[int] = Field(None, description="Optional foreign key to intersection")
    lane_id: Optional[int] = Field(None, description="Optional foreign key to lane")
    event_type: str = Field("detection", max_length=60, description="Detection event type")
    vehicle_type: str = Field("car", max_length=50, description="Vehicle classification (car, truck, bus, motorcycle, bicycle)")
    speed_kmh: Optional[float] = Field(None, ge=0.0, le=500.0, description="Estimated vehicle speed in km/h")
    direction: Optional[str] = Field(None, max_length=50, description="Heading direction (e.g. northbound)")
    confidence: Optional[float] = Field(None, ge=0.0, le=1.0, description="Computer vision detection confidence score")
    detected_at: Optional[datetime] = Field(None, description="Detection timestamp (defaults to current time)")


class VehicleEventBatchCreate(BaseModel):
    """Schema for batch ingesting up to 500 vehicle events."""

    events: list[VehicleEventCreate] = Field(
        ...,
        min_length=1,
        max_length=500,
        description="List of vehicle events to ingest (max 500)",
    )


class VehicleEventBatchResponse(BaseModel):
    """Schema for batch ingestion response."""

    inserted: int = Field(..., description="Number of events inserted")
    message: str = Field("Batch vehicle events ingested successfully", description="Status message")


class VehicleEventResponse(BaseModel):
    """Schema for vehicle event response."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    intersection_id: Optional[int] = None
    lane_id: Optional[int] = None
    event_type: str
    vehicle_type: str
    speed_kmh: Optional[float] = None
    direction: Optional[str] = None
    confidence: Optional[float] = None
    detected_at: datetime
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="before")
    @classmethod
    def handle_unloaded_relationships(cls, data: Any) -> Any:
        """Prevent lazy loading missing greenlet error on relationships."""
        if hasattr(data, "__dict__"):
            d = dict(data.__dict__)
            d.pop("_sa_instance_state", None)
            return d
        return data


class PaginatedVehicleEvents(BaseModel):
    """Paginated vehicle events listing response schema."""

    items: list[VehicleEventResponse]
    total: int
    page: int
    per_page: int
    pages: int
