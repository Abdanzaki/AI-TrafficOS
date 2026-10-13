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
    observed_state: Optional[str] = Field(None, min_length=1, max_length=20)
    observed_confidence: Optional[float] = Field(None, ge=0.0, le=1.0)
    observed_at: Optional[datetime] = None


class SignalObservationUpdate(BaseModel):
    """Schema for ingesting a computer vision signal state observation."""

    observed_state: str = Field(..., min_length=1, max_length=20, description="Observed state (red, yellow, green, unknown)")
    observed_confidence: float = Field(..., ge=0.0, le=1.0, description="Heuristic / model confidence score")
    observed_at: Optional[datetime] = Field(None, description="Timestamp of CV frame capture")


class SignalResponse(BaseModel):
    """Schema for signal controller response."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    intersection_id: int
    code: str
    status: str
    observed_state: Optional[str] = None
    observed_confidence: Optional[float] = None
    observed_at: Optional[datetime] = None
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


class SignalHealthFactor(BaseModel):
    """Contributing factor in the heuristic predictive-maintenance health score."""

    name: str = Field(..., description="Factor identifier (e.g. controller_status, phase_flapping, heartbeat_staleness, anomalous_dwell)")
    weight: float = Field(..., ge=0.0, le=1.0, description="Relative weight in overall scoring")
    raw_value: Any = Field(..., description="Observed metric value (e.g. flapping rate, staleness seconds)")
    penalty: float = Field(..., ge=0.0, description="Deduction points subtracted from 100")
    status: str = Field("normal", description="'normal', 'warning', or 'critical'")
    description: str = Field(..., description="Human-readable explanation of this factor's impact")


class SignalHealthResponse(BaseModel):
    """Predictive-maintenance health score response for an individual traffic signal."""

    model_config = ConfigDict(from_attributes=True)

    signal_id: int
    signal_code: str
    intersection_id: int
    score: int = Field(..., ge=0, le=100, description="Predictive maintenance score (0-100)")
    status_band: str = Field(..., description="'healthy' (>=80), 'degraded' (50-79), or 'at-risk' (<50)")
    explanation: str = Field(..., description="Transparent explanation listing factors and weights")
    factors: list[SignalHealthFactor] = Field(default_factory=list, description="Breakdown of contributing factors")
    provenance: str = Field("heuristic", description="Method provenance (strictly 'heuristic' / statistical)")
    evaluated_at: datetime = Field(..., description="Timestamp when score was evaluated")
    metrics: dict[str, Any] = Field(default_factory=dict, description="Raw statistical metrics")


class SignalHealthListResponse(BaseModel):
    """Collection response of signal health evaluations across intersections."""

    items: list[SignalHealthResponse] = Field(default_factory=list)
    total: int = 0
    healthy_count: int = 0
    degraded_count: int = 0
    at_risk_count: int = 0
    provenance: str = Field("heuristic", description="Method provenance (strictly 'heuristic')")

