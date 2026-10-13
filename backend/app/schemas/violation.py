"""Traffic violation schemas module.

Defines Pydantic request and response schemas for CV-detected traffic violations.
"""

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

VALID_VIOLATION_TYPES = {"red_light", "wrong_way", "no_helmet"}
VALID_VIOLATION_STATUSES = {"recorded", "reviewed", "dismissed", "escalated"}


class ViolationCreate(BaseModel):
    """Schema for recording a new traffic violation."""

    violation_type: str = Field(
        ...,
        description="Violation category (red_light, wrong_way, no_helmet)",
    )
    detected_at: datetime = Field(
        ...,
        description="Time of detection (timezone-aware ISO 8601)",
    )
    intersection_id: Optional[int] = Field(
        None,
        description="Optional foreign key to intersections table",
    )
    camera_id: Optional[str] = Field(
        None,
        max_length=100,
        description="Identifier of originating perception camera",
    )
    confidence: float = Field(
        1.0,
        ge=0.0,
        le=1.0,
        description="Detection confidence score bounded [0.0, 1.0]",
    )
    status: str = Field(
        "recorded",
        max_length=30,
        description="Initial lifecycle status (recorded, reviewed, dismissed, escalated)",
    )
    evidence_ref: Optional[str] = Field(
        None,
        max_length=500,
        description="Evidence snapshot file path or URL",
    )
    details: Optional[dict[str, Any]] = Field(
        None,
        description="Diagnostic breakdown metadata (track_id, signal_phase, bbox, etc.)",
    )

    @field_validator("violation_type")
    @classmethod
    def validate_violation_type(cls, v: str) -> str:
        cleaned = v.strip().lower()
        if cleaned not in VALID_VIOLATION_TYPES:
            raise ValueError(
                f"Invalid violation_type '{v}'. Allowed: {sorted(list(VALID_VIOLATION_TYPES))}"
            )
        return cleaned

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str) -> str:
        cleaned = v.strip().lower()
        if cleaned not in VALID_VIOLATION_STATUSES:
            raise ValueError(
                f"Invalid status '{v}'. Allowed: {sorted(list(VALID_VIOLATION_STATUSES))}"
            )
        return cleaned


class ViolationUpdate(BaseModel):
    """Schema for updating an existing traffic violation record."""

    status: Optional[str] = Field(None, max_length=30)
    confidence: Optional[float] = Field(None, ge=0.0, le=1.0)
    evidence_ref: Optional[str] = Field(None, max_length=500)
    details: Optional[dict[str, Any]] = None

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            cleaned = v.strip().lower()
            if cleaned not in VALID_VIOLATION_STATUSES:
                raise ValueError(
                    f"Invalid status '{v}'. Allowed: {sorted(list(VALID_VIOLATION_STATUSES))}"
                )
            return cleaned
        return v


class ViolationRead(BaseModel):
    """Schema for traffic violation responses."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    violation_type: str
    detected_at: datetime
    intersection_id: Optional[int] = None
    camera_id: Optional[str] = None
    confidence: float
    status: str
    evidence_ref: Optional[str] = None
    details: Optional[dict[str, Any]] = None
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


# Response alias
ViolationResponse = ViolationRead


class PaginatedViolations(BaseModel):
    """Paginated list of traffic violations."""

    items: list[ViolationRead]
    total: int
    page: int
    per_page: int
    pages: int
