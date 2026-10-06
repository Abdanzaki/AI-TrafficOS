"""AI predictions and autonomous decisions schemas module.

Defines validation and serialization models for predictive inference and control actions.
"""

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


VALID_DECISION_STATUSES = {"proposed", "applied", "reverted"}
ALLOWED_TRANSITIONS = {
    "proposed": {"applied", "reverted"},
    "applied": {"reverted"},
    "reverted": set(),
}


class AIPredictionCreate(BaseModel):
    """Schema for creating a predictive inference record."""

    intersection_id: Optional[int] = Field(None, description="Optional foreign key to intersection")
    prediction_type: str = Field(..., min_length=1, max_length=50, description="Prediction type (e.g. congestion, flow, incident_risk)")
    predicted_for: datetime = Field(..., description="Target future timestamp predicted for")
    payload: dict[str, Any] = Field(..., description="Prediction payload containing inference metrics")
    confidence: Optional[float] = Field(None, ge=0.0, le=1.0, description="Model prediction confidence score")
    model_version: str = Field(..., min_length=1, max_length=50, description="Model version tag or identifier")


class AIPredictionResponse(BaseModel):
    """Schema for returning AI prediction details."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    intersection_id: Optional[int] = None
    prediction_type: str
    predicted_for: datetime
    payload: dict[str, Any]
    confidence: Optional[float] = None
    model_version: str
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


class PaginatedAIPredictions(BaseModel):
    """Paginated AI predictions response schema."""

    items: list[AIPredictionResponse]
    total: int
    page: int
    per_page: int
    pages: int


class AIDecisionCreate(BaseModel):
    """Schema for creating an autonomous or advisory decision recommendation."""

    prediction_id: Optional[int] = Field(None, description="Optional foreign key to source AI prediction")
    intersection_id: Optional[int] = Field(None, description="Optional foreign key to target intersection")
    decision_type: str = Field(..., min_length=1, max_length=50, description="Decision type (e.g. signal_timing, route_advisory, alert)")
    payload: dict[str, Any] = Field(..., description="Actionable decision parameters")
    rationale: Optional[str] = Field(None, description="Human-readable or algorithmic explanation")


class AIDecisionUpdate(BaseModel):
    """Schema for updating decision status lifecycle."""

    status: str = Field(..., min_length=1, max_length=30, description="Target lifecycle status (applied, reverted)")
    rationale: Optional[str] = Field(None, description="Optional explanation for transition")

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str) -> str:
        if v not in VALID_DECISION_STATUSES:
            raise ValueError(f"Invalid status '{v}'. Allowed: {sorted(list(VALID_DECISION_STATUSES))}")
        return v


class AIDecisionResponse(BaseModel):
    """Schema for returning AI decision details."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    prediction_id: Optional[int] = None
    intersection_id: Optional[int] = None
    decision_type: str
    payload: dict[str, Any]
    status: str
    applied_by: Optional[int] = None
    applied_at: Optional[datetime] = None
    rationale: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="before")
    @classmethod
    def handle_unloaded_relationships(cls, data: Any) -> Any:
        """Prevent lazy loading missing greenlet error on relationships."""
        if hasattr(data, "__dict__"):
            d = dict(data.__dict__)
            d.pop("_sa_instance_state", None)
            if "applied_at" not in d or d["applied_at"] is None:
                if getattr(data, "applied_at", None) is not None:
                    d["applied_at"] = data.applied_at
                elif isinstance(d.get("payload"), dict) and "applied_at" in d["payload"]:
                    try:
                        d["applied_at"] = datetime.fromisoformat(d["payload"]["applied_at"])
                    except Exception:
                        pass
                elif d.get("status") == "applied":
                    d["applied_at"] = d.get("updated_at")
            return d
        elif isinstance(data, dict):
            if data.get("applied_at") is None and data.get("status") == "applied":
                if isinstance(data.get("payload"), dict) and "applied_at" in data["payload"]:
                    try:
                        data["applied_at"] = datetime.fromisoformat(data["payload"]["applied_at"])
                    except Exception:
                        pass
                elif data.get("updated_at"):
                    data["applied_at"] = data.get("updated_at")
        return data


class PaginatedAIDecisions(BaseModel):
    """Paginated AI decisions response schema."""

    items: list[AIDecisionResponse]
    total: int
    page: int
    per_page: int
    pages: int
