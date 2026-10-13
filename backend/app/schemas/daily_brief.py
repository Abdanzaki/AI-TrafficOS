"""Daily traffic operations brief schemas module.

Defines response structures for deterministic traffic morning briefs,
including observed telemetry counts, predicted hotspots, day-over-day trends,
and per-section data provenance.
"""

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field


class IncidentBriefSection(BaseModel):
    """Yesterday's observed incidents breakdown and counts."""

    provenance: Literal["observed"] = "observed"
    has_data: bool = Field(..., description="True if incident records exist for yesterday")
    count: Optional[int] = Field(None, description="Observed incident count, or None if no data")
    total: Optional[int] = Field(None, description="Alias for count, or None if no data")
    by_severity: dict[str, int] = Field(default_factory=dict, description="Breakdown of incidents by severity")
    by_type: dict[str, int] = Field(default_factory=dict, description="Breakdown of incidents by type/severity")
    note: Optional[str] = Field(None, description="Explanatory provenance or empty-state note")


class ViolationBriefSection(BaseModel):
    """Yesterday's observed violations breakdown by type."""

    provenance: Literal["observed"] = "observed"
    has_data: bool = Field(..., description="True if violation records exist for yesterday")
    count: Optional[int] = Field(None, description="Observed violation count, or None if no data")
    total: Optional[int] = Field(None, description="Alias for count, or None if no data")
    by_type: dict[str, int] = Field(default_factory=dict, description="Breakdown of violations by violation_type")
    note: Optional[str] = Field(None, description="Explanatory provenance or empty-state note")


class HotspotItem(BaseModel):
    """Forecasted hotspot intersection entity."""

    intersection_id: int = Field(..., description="Intersection database identifier")
    intersection_name: str = Field(..., description="Intersection name")
    intersection_code: Optional[str] = Field(None, description="Operational junction code")
    predicted_congestion: Optional[float] = Field(None, description="Predicted congestion level percentage")
    predicted_flow: Optional[float] = Field(None, description="Predicted vehicle volume")
    confidence: Optional[float] = Field(None, description="Model prediction confidence score")
    predicted_for: Optional[datetime] = Field(None, description="Target timestamp of forecast")


class HotspotBriefSection(BaseModel):
    """Today's forecasted congestion and volume hotspots."""

    provenance: Literal["predicted"] = "predicted"
    has_data: bool = Field(..., description="True if real model predictions exist for today")
    items: list[HotspotItem] = Field(default_factory=list, description="Ranked predicted hotspots")
    note: Optional[str] = Field(None, description="Explanatory note when no predictions exist")


class TrendBriefSection(BaseModel):
    """Day-over-day operational trends and historical deltas."""

    provenance: Literal["observed"] = "observed"
    has_sufficient_history: bool = Field(..., description="True if >= 2 days of real data exist")
    incident_delta: Optional[int] = Field(None, description="Day-over-day incident delta, or None if insufficient history")
    violation_delta: Optional[int] = Field(None, description="Day-over-day violation delta, or None if insufficient history")
    direction: Optional[str] = Field(None, description="Trend trajectory: 'increased', 'decreased', 'stable', or None")
    note: Optional[str] = Field(None, description="Explanatory note detailing changes or insufficient history")


class DailyBriefResponse(BaseModel):
    """Consolidated daily morning traffic brief payload."""

    generated_at: datetime = Field(..., description="Timestamp when brief was generated")
    date: str = Field(..., description="Target date for the brief (YYYY-MM-DD)")
    summary_text: str = Field(..., description="Human-readable brief narrative (deterministic or rephrased)")
    rephrased: bool = Field(False, description="Whether summary_text was rephrased via GeminiProvider")
    incidents: IncidentBriefSection
    violations: ViolationBriefSection
    hotspots: HotspotBriefSection
    trends: TrendBriefSection
