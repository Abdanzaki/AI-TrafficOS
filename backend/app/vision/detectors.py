"""FastAPI backend integration module for computer vision vehicle perception.

Layout & Architecture Note:
---------------------------
Core vision models and heuristics are implemented in `ai/cv/yolo_detector.py` and
`ai/cv/emergency_heuristic.py` to keep the perception algorithms decoupled from the web
framework. This module (`app.vision.detectors`) provides the FastAPI backend bridge:
1. Re-exports the concrete `YoloVehicleDetector` and `EmergencyVehicleHeuristic`.
2. Provides dependency injection singleton management (`get_vehicle_detector`).
3. Adapts raw `Detection` dataclasses into database-ready `VehicleEventCreate` schemas
   for ingestion by `/api/v1/vehicle-events`.

This layout ensures that streaming pipelines, asynchronous workers, and Phase 5/6
forecasting/control engines can run vision perception headlessly, while FastAPI services
benefit from structured dependency injection.
"""

from functools import lru_cache
from typing import Optional
from pathlib import Path

from ai.common.schemas import Detection
from ai.cv.emergency_heuristic import EmergencyVehicleHeuristic
from ai.cv.exceptions import (
    CorruptFrameError,
    InvalidInputFrameError,
    ModelLoadError,
    UnsupportedInputFormatError,
    VisionDetectorError,
)
from ai.common.schemas import SignalDetection
from ai.cv.signal_detector import DEFAULT_COCO_TRAFFIC_LIGHT_ID, TrafficSignalDetector
from ai.cv.signal_state_heuristic import SignalStateHeuristic, SignalStateResult
from ai.cv.yolo_detector import (
    DEFAULT_COCO_VEHICLE_MAP,
    YoloVehicleDetector,
    resolve_default_model_path,
    select_optimal_device,
)
from app.models.signal import Signal
from app.schemas.vehicle_event import VehicleEventCreate
from datetime import datetime, timezone
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

__all__ = [
    "CorruptFrameError",
    "DEFAULT_COCO_TRAFFIC_LIGHT_ID",
    "DEFAULT_COCO_VEHICLE_MAP",
    "EmergencyVehicleHeuristic",
    "InvalidInputFrameError",
    "ModelLoadError",
    "SignalDetection",
    "SignalStateHeuristic",
    "SignalStateResult",
    "TrafficSignalDetector",
    "UnsupportedInputFormatError",
    "VisionDetectorError",
    "YoloVehicleDetector",
    "detection_to_vehicle_event_create",
    "get_signal_detector",
    "get_vehicle_detector",
    "record_signal_observation",
    "resolve_default_model_path",
    "select_optimal_device",
]

# Singleton cache for FastAPI dependency injection
_GLOBAL_DETECTOR: Optional[YoloVehicleDetector] = None
_GLOBAL_SIGNAL_DETECTOR: Optional[TrafficSignalDetector] = None



def get_vehicle_detector(
    model_path: str | Path | None = None,
    conf_threshold: float = 0.25,
    iou_threshold: float = 0.45,
    imgsz: int = 640,
    device: str | None = None,
    enable_emergency_heuristic: bool = True,
) -> YoloVehicleDetector:
    """FastAPI dependency provider returning a shared YoloVehicleDetector instance.

    Lazy-initializes on first invocation to preserve fast application startup.

    Args:
        model_path: Optional custom weights path.
        conf_threshold: Confidence threshold (default: 0.25).
        iou_threshold: NMS IoU threshold (default: 0.45).
        imgsz: Inference resolution (default: 640).
        device: Device target ('cpu', 'cuda', or None for auto).
        enable_emergency_heuristic: Whether to activate emergency vehicle heuristic.

    Returns:
        YoloVehicleDetector: Configured detector instance.
    """
    global _GLOBAL_DETECTOR
    if _GLOBAL_DETECTOR is None:
        _GLOBAL_DETECTOR = YoloVehicleDetector(
            model_path=model_path,
            conf_threshold=conf_threshold,
            iou_threshold=iou_threshold,
            imgsz=imgsz,
            device=device,
            enable_emergency_heuristic=enable_emergency_heuristic,
        )
    return _GLOBAL_DETECTOR


def detection_to_vehicle_event_create(
    detection: Detection,
    intersection_id: Optional[int] = None,
    lane_id: Optional[int] = None,
    speed_kmh: Optional[float] = None,
    direction: Optional[str] = None,
) -> VehicleEventCreate:
    """Adapt a computer vision Detection dataclass to a VehicleEventCreate schema.

    Maps vision detection attributes to the database model fields:
    - Normal vehicle detection -> event_type='detection', vehicle_type=label ('car', 'truck', etc.)
    - Emergency heuristic detection -> event_type='emergency_preemption', vehicle_type='emergency_vehicle_heuristic'

    Args:
        detection: Computer vision Detection instance.
        intersection_id: Optional intersection foreign key.
        lane_id: Optional lane foreign key.
        speed_kmh: Optional estimated speed.
        direction: Optional heading direction.

    Returns:
        VehicleEventCreate: Validated Pydantic schema ready for ingestion.
    """
    is_emergency = detection.label == "emergency_vehicle_heuristic"
    event_type = "emergency_preemption" if is_emergency else "detection"

    return VehicleEventCreate(
        intersection_id=intersection_id,
        lane_id=lane_id,
        event_type=event_type,
        vehicle_type=detection.label,
        speed_kmh=speed_kmh,
        direction=direction,
        confidence=detection.confidence,
        detected_at=detection.timestamp,
    )


def get_signal_detector(
    model_path: str | Path | None = None,
    conf_threshold: float = 0.20,
    iou_threshold: float = 0.45,
    imgsz: int = 640,
    device: str | None = None,
    signal_class_id: int = DEFAULT_COCO_TRAFFIC_LIGHT_ID,
    heuristic: Optional[SignalStateHeuristic] = None,
) -> TrafficSignalDetector:
    """FastAPI dependency provider returning a shared TrafficSignalDetector instance.

    Lazy-initializes on first invocation to preserve fast application startup.

    Args:
        model_path: Optional custom weights path.
        conf_threshold: Confidence threshold for signal head detection (default: 0.20).
        iou_threshold: NMS IoU threshold (default: 0.45).
        imgsz: Inference resolution (default: 640).
        device: Device target ('cpu', 'cuda', or None for auto).
        signal_class_id: COCO class ID for traffic lights (default: 9).
        heuristic: Custom SignalStateHeuristic instance.

    Returns:
        TrafficSignalDetector: Configured detector instance.
    """
    global _GLOBAL_SIGNAL_DETECTOR
    if _GLOBAL_SIGNAL_DETECTOR is None:
        _GLOBAL_SIGNAL_DETECTOR = TrafficSignalDetector(
            model_path=model_path,
            conf_threshold=conf_threshold,
            iou_threshold=iou_threshold,
            imgsz=imgsz,
            device=device,
            signal_class_id=signal_class_id,
            heuristic=heuristic,
        )
    return _GLOBAL_SIGNAL_DETECTOR


async def record_signal_observation(
    db: AsyncSession,
    signal_id: int,
    observed_state: str,
    confidence: float,
    observed_at: Optional[datetime] = None,
) -> Optional[Signal]:
    """Persist a CV optical signal state observation to the database Signal model.

    Updates the physical signal's observed_state, observed_confidence, and observed_at fields.

    Args:
        db: Async SQLAlchemy database session.
        signal_id: ID of the physical Signal controller in the database.
        observed_state: Detected lamp state ('red', 'yellow', 'green', 'unknown').
        confidence: Dominance margin confidence score [0.0, 1.0].
        observed_at: Observation timestamp (defaults to current UTC time if None).

    Returns:
        Optional[Signal]: Updated Signal instance, or None if signal not found.
    """
    stmt = select(Signal).where(Signal.id == signal_id)
    res = await db.execute(stmt)
    sig = res.scalar_one_or_none()
    if sig is None:
        return None

    sig.observed_state = observed_state
    sig.observed_confidence = float(confidence)
    sig.observed_at = observed_at or datetime.now(timezone.utc)
    await db.flush()
    return sig

