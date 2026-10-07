"""Computer Vision REST API request and response schemas.

Provides strict Pydantic schemas validating all inputs and structured
perception outputs for image/video analysis and optical signal observations.
"""

from datetime import datetime
from typing import Any, Optional
from pydantic import BaseModel, ConfigDict, Field, model_validator


class DetectionSummaryItem(BaseModel):
    """Bounding box detection summary returned from YOLO inference."""

    model_config = ConfigDict(from_attributes=True)

    label: str = Field(..., description="Detected vehicle or object class label")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Detection confidence score")
    bbox: Optional[list[float]] = Field(
        None,
        description="Bounding box coordinates [x1, y1, x2, y2]",
    )
    vehicle_type: Optional[str] = Field(
        None,
        description="Normalized database vehicle category (car, truck, bus, motorcycle, emergency)",
    )


class SignalObservationResult(BaseModel):
    """Detected traffic signal head and classified illuminated state."""

    model_config = ConfigDict(from_attributes=True)

    signal_id: Optional[int] = Field(None, description="Matched database Signal controller ID if known")
    state: str = Field(..., description="Classified optical lamp state ('red', 'yellow', 'green', 'unknown')")
    confidence: float = Field(..., ge=0.0, le=1.0, description="State classification confidence score")
    bbox: Optional[list[float]] = Field(None, description="Signal head bounding box [x1, y1, x2, y2]")


class ImageAnalysisResponse(BaseModel):
    """Structured response schema returned by POST /vision/analyze-image."""

    model_config = ConfigDict(from_attributes=True)

    vehicle_count: int = Field(..., ge=0, description="Total vehicles detected in frame")
    vehicle_counts_by_type: dict[str, int] = Field(
        default_factory=dict,
        description="Vehicles counted per class (car, truck, bus, motorcycle, emergency)",
    )
    traffic_density: float = Field(..., ge=0.0, description="Vehicle count normalized by frame area")
    density_per_100k_px: float = Field(..., ge=0.0, description="Vehicles per 100,000 screen pixels")
    lane_occupancy: dict[str, float] = Field(
        default_factory=dict,
        description="Fractional lane occupancy [0.0, 1.0] per defined lane ROI",
    )
    queue_lengths: dict[str, int] = Field(
        default_factory=dict,
        description="Vehicles stationary in queue zones per defined lane ROI",
    )
    congestion_level: int = Field(..., ge=0, le=100, description="Operational congestion percentage [0, 100]")
    congestion_status: str = Field(
        ...,
        description="Descriptive congestion category (free_flow, moderate, heavy, severe)",
    )
    detections: list[DetectionSummaryItem] = Field(
        default_factory=list,
        description="List of vehicle detections in the frame",
    )
    signal_observations: list[SignalObservationResult] = Field(
        default_factory=list,
        description="Detected signal heads and observed states",
    )
    traffic_record_id: Optional[int] = Field(
        None,
        description="Persisted TrafficRecord ID if intersection_id was provided",
    )
    events_persisted: int = Field(
        0,
        ge=0,
        description="Count of individual VehicleEvent rows created (if persist_events was enabled)",
    )
    processed_at: datetime = Field(..., description="UTC timestamp of completion")


class VideoAnalysisResponse(BaseModel):
    """Structured response schema returned by POST /vision/analyze-video."""

    model_config = ConfigDict(from_attributes=True)

    frames_processed: int = Field(..., ge=0, description="Total video frames processed on stride")
    total_frames_sampled: int = Field(..., ge=0, description="Number of sampled frame evaluation cycles")
    duration_seconds: float = Field(..., ge=0.0, description="Video duration in seconds")
    fps: float = Field(..., ge=0.0, description="Video framerate")
    average_vehicle_count: float = Field(..., ge=0.0, description="Mean vehicle count across evaluated windows")
    average_congestion_level: float = Field(
        ...,
        ge=0.0,
        le=100.0,
        description="Mean congestion score across evaluated windows",
    )
    traffic_records_created: int = Field(
        ...,
        ge=0,
        description="Number of aggregated TrafficRecord rows persisted",
    )
    incidents_created: int = Field(
        ...,
        ge=0,
        description="Number of candidate Incident rows persisted",
    )
    incident_details: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Summary of generated incidents (severity, type, track ID)",
    )
    processed_at: datetime = Field(..., description="UTC timestamp of completion")


class SignalObservationItem(BaseModel):
    """Signal controller entity with optical observation details."""

    model_config = ConfigDict(from_attributes=True)

    signal_id: int = Field(..., description="Signal hardware ID")
    intersection_id: int = Field(..., description="Associated intersection ID")
    intersection_name: Optional[str] = Field(None, description="Intersection name")
    intersection_code: Optional[str] = Field(None, description="Intersection code")
    signal_code: str = Field(..., description="Operational signal identifier")
    status: str = Field(..., description="Signal operational status")
    observed_state: str = Field(..., description="Detected lamp state ('red', 'yellow', 'green', 'unknown')")
    observed_confidence: float = Field(..., ge=0.0, le=1.0, description="Observation confidence score")
    observed_at: Optional[datetime] = Field(None, description="Timestamp of observation")
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="before")
    @classmethod
    def handle_signal_model(cls, data: Any) -> Any:
        """Extract fields from Signal model instance."""
        if hasattr(data, "__dict__"):
            d = dict(data.__dict__)
            d.pop("_sa_instance_state", None)
            d["signal_id"] = d.get("id")
            d["signal_code"] = d.get("code")
            # Pull intersection relation if loaded
            intersection = getattr(data, "intersection", None)
            if intersection:
                d["intersection_name"] = getattr(intersection, "name", None)
                d["intersection_code"] = getattr(intersection, "code", None)
            return d
        return data


class PaginatedSignalObservations(BaseModel):
    """Paginated listing response for signal observations."""

    items: list[SignalObservationItem]
    total: int = Field(..., ge=0)
    page: int = Field(..., ge=1)
    per_page: int = Field(..., ge=1)
    pages: int = Field(..., ge=0)
