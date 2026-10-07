"""Forecasting schemas module.

Defines validation and serialization models for training requests, prediction execution,
and model registry version inspection.
"""

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


class TrainRequest(BaseModel):
    """Schema for initiating traffic forecasting model training."""

    intersection_ids: Optional[list[int]] = Field(
        None,
        description="Optional subset of intersection IDs to include; None trains across all intersections.",
    )
    days: int = Field(
        21,
        ge=7,
        le=90,
        description="Historical telemetry lookback window in days (must be between 7 and 90).",
    )
    notes: Optional[str] = Field(
        None,
        max_length=500,
        description="Optional descriptive notes or experiment tag for the registry.",
    )


class PredictRequest(BaseModel):
    """Schema for requesting future traffic and congestion predictions."""

    intersection_ids: list[int] = Field(
        ...,
        min_length=1,
        description="Target intersection IDs for inference execution.",
    )


class PredictionResult(BaseModel):
    """Schema representing an individual intersection prediction result."""

    model_config = ConfigDict(from_attributes=True)

    intersection_id: int
    status: str = Field("predicted", description="'predicted' or 'insufficient_data'")
    predicted_for: Optional[datetime] = None
    model_version: Optional[str] = None
    flow: Optional[dict[str, Any]] = None
    congestion: Optional[dict[str, Any]] = None
    prediction_ids: list[int] = Field(default_factory=list)
    rows_found: Optional[int] = None
    rows_required: Optional[int] = None
    message: Optional[str] = None


class PredictBatchResponse(BaseModel):
    """Schema for batch prediction endpoint response."""

    predictions: list[dict[str, Any]] = Field(
        default_factory=list,
        description="List of successfully computed and stored predictions per intersection.",
    )
    insufficient: list[dict[str, Any]] = Field(
        default_factory=list,
        description="List of intersections with insufficient telemetry rows and diagnostic counts.",
    )


class ModelVersionInfo(BaseModel):
    """Schema for model registry version details."""

    model_config = ConfigDict(from_attributes=True)

    id: Optional[int] = None
    name: str = "traffic_forecaster"
    version: str
    artifact_path: Optional[str] = None
    metrics: dict[str, Any] = Field(default_factory=dict)
    data_summary: Optional[dict[str, Any]] = None
    feature_names: Optional[list[str]] = None
    horizon_steps: Optional[int] = None
    notes: Optional[str] = None
    created_at: Optional[datetime] = None
    in_database: bool = True
    in_filesystem: bool = True
