"""FastAPI backend integration module for multi-object tracking.

Provides dependency injection providers and re-exports for MultiObjectTracker
and TrackedVehicle from the pure `ai.cv.tracking` package.
"""

from typing import Optional

from ai.cv.exceptions import SingleFrameSpeedError
from ai.cv.tracking import (
    MultiObjectTracker,
    TrackedVehicle,
    compute_bbox_iou,
    compute_centroid,
    estimate_speed_from_history,
)

__all__ = [
    "MultiObjectTracker",
    "SingleFrameSpeedError",
    "TrackedVehicle",
    "compute_bbox_iou",
    "compute_centroid",
    "estimate_speed_from_history",
    "get_vehicle_tracker",
]


def get_vehicle_tracker(
    iou_threshold: float = 0.3,
    max_centroid_distance: float = 90.0,
    max_lost_frames: int = 5,
    pixels_per_meter: Optional[float] = None,
) -> MultiObjectTracker:
    """FastAPI dependency provider creating a MultiObjectTracker instance.

    Args:
        iou_threshold: Minimum IoU overlap to associate tracks across frames.
        max_centroid_distance: Maximum distance for centroid proximity matching.
        max_lost_frames: Frames before dead tracks are dropped.
        pixels_per_meter: Calibration factor for speed estimation.

    Returns:
        MultiObjectTracker: Configured tracker instance.
    """
    return MultiObjectTracker(
        iou_threshold=iou_threshold,
        max_centroid_distance=max_centroid_distance,
        max_lost_frames=max_lost_frames,
        pixels_per_meter=pixels_per_meter,
    )
