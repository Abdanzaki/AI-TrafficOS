"""Incident schemas module.

Defines schemas for incident reporting, lifecycle updates, and status validation.
"""

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


VALID_INCIDENT_STATUSES = {"reported", "acknowledged", "resolved"}
VALID_INCIDENT_SEVERITIES = {"low", "medium", "high", "critical", "unknown"}


class IncidentCreate(BaseModel):
    """Schema for creating a traffic incident."""

    intersection_id: Optional[int] = Field(None, description="Optional foreign key to intersection")
    severity: str = Field("unknown", max_length=20, description="Severity (low, medium, high, critical, unknown)")
    status: str = Field("reported", max_length=30, description="Initial status (reported, acknowledged, resolved)")
    description: Optional[str] = Field(None, max_length=500, description="Incident description")
    lat: Optional[float] = Field(None, ge=-90.0, le=90.0, description="Latitude coordinate")
    lon: Optional[float] = Field(None, ge=-180.0, le=180.0, description="Longitude coordinate")
    reported_by: Optional[int] = Field(None, description="User ID of reporter (overridden by auth user)")

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str) -> str:
        if v not in VALID_INCIDENT_STATUSES:
            raise ValueError(f"Invalid status '{v}'. Allowed: {sorted(list(VALID_INCIDENT_STATUSES))}")
        return v


class IncidentUpdate(BaseModel):
    """Schema for updating a traffic incident."""

    intersection_id: Optional[int] = None
    severity: Optional[str] = Field(None, max_length=20)
    status: Optional[str] = Field(None, max_length=30)
    description: Optional[str] = Field(None, max_length=500)
    resolved_at: Optional[datetime] = None
    lat: Optional[float] = Field(None, ge=-90.0, le=90.0)
    lon: Optional[float] = Field(None, ge=-180.0, le=180.0)

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in VALID_INCIDENT_STATUSES:
            raise ValueError(f"Invalid status '{v}'. Allowed: {sorted(list(VALID_INCIDENT_STATUSES))}")
        return v


class IncidentResponse(BaseModel):
    """Schema for incident response."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    intersection_id: Optional[int] = None
    severity: str
    status: str
    description: Optional[str] = None
    reported_by: Optional[int] = None
    resolved_at: Optional[datetime] = None
    lat: Optional[float] = None
    lon: Optional[float] = None
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


class PaginatedIncidents(BaseModel):
    """Paginated incidents listing response schema."""

    items: list[IncidentResponse]
    total: int
    page: int
    per_page: int
    pages: int
