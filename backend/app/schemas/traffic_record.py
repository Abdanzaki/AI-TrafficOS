"""TrafficRecord schemas module.

Defines schemas for aggregated telemetry observations, bulk ingest, and queries.
"""

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


class TrafficRecordCreate(BaseModel):
    """Schema for creating a traffic record observation."""

    intersection_id: int = Field(..., description="Foreign key to intersection")
    lane_id: Optional[int] = Field(None, description="Optional foreign key to lane")
    recorded_at: Optional[datetime] = Field(None, description="Record timestamp")
    vehicle_count: int = Field(0, ge=0, description="Vehicular count")
    avg_speed_kmh: Optional[float] = Field(None, ge=0.0, le=500.0, description="Average speed in km/h")
    congestion_level: int = Field(0, ge=0, le=100, description="Congestion percentage (0-100)")
    source: str = Field("sensor", min_length=1, max_length=50, description="Observation source (sensor, camera, manual, ai)")


class TrafficRecordBatchCreate(BaseModel):
    """Schema for batch ingesting up to 500 traffic records."""

    records: list[TrafficRecordCreate] = Field(
        ...,
        min_length=1,
        max_length=500,
        description="List of traffic records to ingest (max 500)",
    )


class TrafficRecordBatchResponse(BaseModel):
    """Schema for batch traffic records ingestion response."""

    inserted: int = Field(..., description="Number of records inserted")
    message: str = Field("Batch traffic records ingested successfully", description="Status message")


class TrafficRecordResponse(BaseModel):
    """Schema for traffic record response."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    intersection_id: int
    lane_id: Optional[int] = None
    recorded_at: datetime
    vehicle_count: int
    avg_speed_kmh: Optional[float] = None
    congestion_level: int
    source: str
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


class PaginatedTrafficRecords(BaseModel):
    """Paginated traffic records listing response schema."""

    items: list[TrafficRecordResponse]
    total: int
    page: int
    per_page: int
    pages: int
