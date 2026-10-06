"""Analytics and telemetry aggregation schemas module."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class TrafficSummaryBucket(BaseModel):
    """Bucketed aggregation of traffic sensor and telemetry observations."""

    bucket: datetime = Field(..., description="Truncated time bucket (hour or day)")
    avg_vehicle_count: float = Field(..., description="Average vehicle count in bucket")
    avg_speed: Optional[float] = Field(None, description="Average speed in km/h")
    avg_speed_kmh: Optional[float] = Field(None, description="Average speed in km/h (alias)")
    avg_congestion: float = Field(..., description="Average congestion percentage (0-100)")
    avg_congestion_level: float = Field(..., description="Average congestion percentage (alias)")
    record_count: int = Field(..., description="Number of observations in bucket")


class IncidentsSummaryResponse(BaseModel):
    """Traffic incident counts grouped by severity and lifecycle status."""

    total: int = Field(..., description="Total incident count in time range")
    by_severity: dict[str, int] = Field(..., description="Counts grouped by severity")
    by_status: dict[str, int] = Field(..., description="Counts grouped by status")


class CongestionHotspotResponse(BaseModel):
    """Intersection hotspot ranked by average congestion level."""

    intersection_id: int = Field(..., description="Foreign key of intersection")
    name: str = Field(..., description="Intersection name")
    code: str = Field(..., description="Intersection operational code")
    avg_congestion_level: float = Field(..., description="Average congestion level percentage")
    avg_congestion: float = Field(..., description="Average congestion level (alias)")
    record_count: int = Field(..., description="Number of sensor records aggregated")
