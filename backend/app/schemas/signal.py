"""Signal and SignalPhase schemas module."""

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


class SignalPhaseCreate(BaseModel):
    """Schema for creating a signal phase."""

    name: str = Field(..., min_length=1, max_length=80, description="Phase interval name")
    phase_order: int = Field(1, ge=1, description="Sequence order within cycle")
    duration_seconds: int = Field(30, ge=1, description="Timing duration in seconds")
    state: str = Field("red", min_length=1, max_length=20, description="Interval state (red, yellow, green)")
    is_active: bool = Field(True, description="Whether this phase is currently active")
    intersection_id: Optional[int] = Field(None, description="Optional foreign key to intersection")


class SignalPhaseUpdate(BaseModel):
    """Schema for updating a signal phase."""

    name: Optional[str] = Field(None, min_length=1, max_length=80)
    phase_order: Optional[int] = Field(None, ge=1)
    duration_seconds: Optional[int] = Field(None, ge=1)
    state: Optional[str] = Field(None, min_length=1, max_length=20)
    is_active: Optional[bool] = None
    intersection_id: Optional[int] = None


class SignalPhaseResponse(BaseModel):
    """Schema for signal phase response."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    signal_id: int
    intersection_id: Optional[int] = None
    name: str
    phase_order: int
    duration_seconds: int
    state: str
    is_active: bool
    created_at: datetime
    updated_at: datetime


class SignalCreate(BaseModel):
    """Schema for creating a signal controller."""

    intersection_id: int = Field(..., description="Foreign key to intersection")
    code: str = Field(..., min_length=1, max_length=50, description="Unique operational hardware code")
    status: str = Field("active", min_length=1, max_length=30, description="Operating status")


class SignalUpdate(BaseModel):
    """Schema for updating a signal controller."""

    intersection_id: Optional[int] = None
    code: Optional[str] = Field(None, min_length=1, max_length=50)
    status: Optional[str] = Field(None, min_length=1, max_length=30)


class SignalResponse(BaseModel):
    """Schema for signal controller response."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    intersection_id: int
    code: str
    status: str
    created_at: datetime
    updated_at: datetime
    phases: Optional[list[SignalPhaseResponse]] = None

    @model_validator(mode="before")
    @classmethod
    def handle_unloaded_phases(cls, data: Any) -> Any:
        """Prevent lazy loading missing greenlet error on phases relation."""
        if hasattr(data, "__dict__"):
            d = dict(data.__dict__)
            d.pop("_sa_instance_state", None)
            if "phases" not in data.__dict__:
                d["phases"] = None
            return d
        return data


class PaginatedSignals(BaseModel):
    """Paginated signal listing response schema."""

    items: list[SignalResponse]
    total: int
    page: int
    per_page: int
    pages: int


class SignalOverrideRequest(BaseModel):
    """Schema for manual signal state override by traffic officers."""

    phase_id: Optional[int] = Field(None, description="Specific phase ID to activate")
    state: Optional[str] = Field(None, min_length=1, max_length=20, description="Target signal state (e.g. red, yellow, green)")
    is_active: Optional[bool] = Field(None, description="Explicit active state")
    reason: Optional[str] = Field(None, description="Operational justification for override")

    @model_validator(mode="after")
    def validate_payload(self) -> "SignalOverrideRequest":
        """Ensure at least phase_id or state is provided."""
        if self.phase_id is None and self.state is None and self.is_active is None:
            raise ValueError("At least one of phase_id, state, or is_active must be provided for override")
        return self
