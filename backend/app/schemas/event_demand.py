"""Event demand forecasting schemas module.

Defines request validation and transparent response structures for
parametric heuristic event demand uplift modeling across junctions.
"""

from datetime import datetime, timezone
from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator


class EventDemandRequest(BaseModel):
    """Event demand forecasting request payload."""

    name: str = Field(
        ...,
        min_length=1,
        max_length=150,
        description="Event name (e.g. 'City Marathon', 'Stadium Concert')",
    )
    junction_id: Optional[int] = Field(
        None,
        description="Host junction ID (optional if lat and lng coordinates are provided)",
    )
    lat: Optional[float] = Field(
        None,
        ge=-90.0,
        le=90.0,
        description="Latitude of event venue",
    )
    lng: Optional[float] = Field(
        None,
        ge=-180.0,
        le=180.0,
        description="Longitude of event venue",
    )
    starts_at: datetime = Field(
        ...,
        description="Event start timestamp (must be strictly in the future)",
    )
    expected_attendance: int = Field(
        ...,
        gt=0,
        description="Anticipated attendee count (must be strictly greater than 0)",
    )
    k_nearest: int = Field(
        3,
        ge=1,
        le=10,
        description="Number of neighboring junctions to distribute demand across (default: 3)",
    )

    @model_validator(mode="after")
    def validate_request(self) -> "EventDemandRequest":
        # Ensure starts_at is in the future
        now = datetime.now(timezone.utc)
        target_time = self.starts_at
        if target_time.tzinfo is None:
            target_time = target_time.replace(tzinfo=timezone.utc)
        if target_time <= now:
            raise ValueError(
                f"starts_at must be strictly in the future. Received {self.starts_at.isoformat()} which is in the past."
            )

        # Ensure either junction_id or (lat, lng) is supplied
        if self.junction_id is None and (self.lat is None or self.lng is None):
            raise ValueError(
                "Either junction_id or both lat and lng coordinates must be specified."
            )

        return self


class AssumptionItem(BaseModel):
    """Documented assumption parameter and transparent range."""

    parameter: str = Field(..., description="Parameter key name")
    description: str = Field(..., description="Operational explanation of parameter")
    range_or_value: str = Field(..., description="Human-readable summary of assumption range")
    low: Optional[float] = Field(None, description="Conservative / low scenario value")
    base: Optional[float] = Field(None, description="Baseline / expected scenario value")
    high: Optional[float] = Field(None, description="Upper bound / high surge scenario value")
    formula: Optional[str] = Field(None, description="Mathematical equation or heuristic definition")


class ScenarioUplift(BaseModel):
    """Demand uplift figures for a specific assumption scenario."""

    uplift_vehicles: int = Field(..., description="Additional peak vehicles projected for junction")
    projected_total_flow: Optional[float] = Field(
        None,
        description="Combined baseline + uplift flow (None if baseline is missing)",
    )
    uplift_percentage: Optional[float] = Field(
        None,
        description="Percentage surge relative to baseline (None if baseline is missing)",
    )


class JunctionUpliftResult(BaseModel):
    """Per-junction demand uplift forecast with confidence interval."""

    junction_id: int = Field(..., description="Target junction ID")
    junction_name: str = Field(..., description="Junction name")
    junction_code: Optional[str] = Field(None, description="Operational junction code")
    distance_km: float = Field(..., description="Distance in kilometers from event venue")
    spatial_weight: float = Field(..., description="Normalized gravity distribution share (0.0 - 1.0)")
    baseline_flow: Optional[float] = Field(
        None,
        description="Recent average vehicle flow from real DB telemetry (None if no data)",
    )
    baseline_status: Literal["observed", "no_baseline_data"] = Field(
        ...,
        description="Status of baseline telemetry: 'observed' or 'no_baseline_data'",
    )
    baseline_note: Optional[str] = Field(
        None,
        description="Explicit note when baseline flow is unavailable",
    )
    scenarios: dict[str, ScenarioUplift] = Field(
        ...,
        description="Uplift projections under 'low', 'base', and 'high' scenarios",
    )
    confidence_interval: list[int] = Field(
        ...,
        description="Lower and upper bounds of additional peak vehicles [low, high]",
    )


class EventDemandResponse(BaseModel):
    """Structured response for event demand uplift forecasting."""

    event_name: str = Field(..., description="Name of the scheduled event")
    starts_at: datetime = Field(..., description="Scheduled event start time")
    expected_attendance: int = Field(..., description="Expected attendee count")
    provenance: Literal["parametric-heuristic"] = Field(
        "parametric-heuristic",
        description="Strictly labeled as parametric heuristic, NOT ML",
    )
    model_type: str = Field(
        "parametric-heuristic",
        description="Model architecture classifier",
    )
    documentation: str = Field(
        ...,
        description="Explanation of the transparent parametric gravity model formula",
    )
    total_peak_vehicles: dict[str, int] = Field(
        ...,
        description="Total network-wide peak arrival vehicles across scenarios (low, base, high)",
    )
    assumptions: list[AssumptionItem] = Field(
        ...,
        description="Comprehensive list of model parameters and assumption ranges",
    )
    junctions: list[JunctionUpliftResult] = Field(
        ...,
        description="Per-junction demand uplift forecasts ranked by proximity",
    )
