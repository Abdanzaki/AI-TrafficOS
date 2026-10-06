"""EmergencyEvent schemas module.

Defines schemas for emergency transit/dispatch event lifecycle and routing.
"""

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


VALID_EMERGENCY_STATUSES = {"active", "dispatched", "on_scene", "resolved"}


class EmergencyEventCreate(BaseModel):
    """Schema for creating an emergency dispatch/transit event."""

    incident_id: Optional[int] = Field(None, description="Optional foreign key to incident")
    intersection_id: Optional[int] = Field(None, description="Optional intersection ID (auto-suggested from incident if omitted)")
    vehicle_type: str = Field(..., min_length=1, max_length=50, description="Emergency vehicle type (e.g. ambulance, fire, police)")
    priority: int = Field(1, ge=1, le=5, description="Priority level (1=highest)")
    status: str = Field("active", max_length=30, description="Status (active, dispatched, on_scene, resolved)")
    detected_at: Optional[datetime] = Field(None, description="Detection timestamp")
    cleared_at: Optional[datetime] = Field(None, description="Clearance timestamp")

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str) -> str:
        if v not in VALID_EMERGENCY_STATUSES:
            raise ValueError(f"Invalid status '{v}'. Allowed: {sorted(list(VALID_EMERGENCY_STATUSES))}")
        return v


class EmergencyEventUpdate(BaseModel):
    """Schema for updating an emergency dispatch/transit event."""

    priority: Optional[int] = Field(None, ge=1, le=5, description="Updated priority level")
    status: Optional[str] = Field(None, max_length=30, description="Updated status")
    cleared_at: Optional[datetime] = Field(None, description="Clearance timestamp")

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in VALID_EMERGENCY_STATUSES:
            raise ValueError(f"Invalid status '{v}'. Allowed: {sorted(list(VALID_EMERGENCY_STATUSES))}")
        return v


class EmergencyEventResponse(BaseModel):
    """Schema for emergency event response."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    incident_id: Optional[int] = None
    intersection_id: Optional[int] = None
    vehicle_type: str
    priority: int
    status: str
    detected_at: datetime
    cleared_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="before")
    @classmethod
    def handle_unloaded_relationships(cls, data: Any) -> Any:
        """Prevent lazy loading missing greenlet error and auto-populate intersection_id from incident if present."""
        if hasattr(data, "__dict__"):
            d = dict(data.__dict__)
            d.pop("_sa_instance_state", None)
            if d.get("intersection_id") is None:
                incident = getattr(data, "incident", None)
                if incident and hasattr(incident, "intersection_id"):
                    d["intersection_id"] = incident.intersection_id
            return d
        return data


class PaginatedEmergencyEvents(BaseModel):
    """Paginated emergency events listing response schema."""

    items: list[EmergencyEventResponse]
    total: int
    page: int
    per_page: int
    pages: int
