"""FastAPI backend integration module for video stream and file processing.

Provides dependency injection providers and re-exports for VideoProcessor,
VideoFrameResult, and video processing exceptions from `ai.cv`.
"""

from pathlib import Path
from typing import Optional, Sequence

from ai.cv.detectors import BaseDetector
from ai.cv.exceptions import (
    CorruptVideoError,
    EmptyVideoError,
    UnsupportedVideoFormatError,
    VideoOpenError,
    VideoProcessingError,
)
from ai.cv.metrics import PolygonROI
from ai.cv.tracking import MultiObjectTracker
from ai.cv.video_processor import VideoFrameResult, VideoProcessor
from .detectors import get_vehicle_detector

__all__ = [
    "CorruptVideoError",
    "EmptyVideoError",
    "UnsupportedVideoFormatError",
    "VideoFrameResult",
    "VideoOpenError",
    "VideoProcessingError",
    "VideoProcessor",
    "get_video_processor",
]


def get_video_processor(
    detector: Optional[BaseDetector] = None,
    tracker: Optional[MultiObjectTracker] = None,
    frame_stride: int = 1,
    rois: Optional[dict[str, PolygonROI | Sequence[tuple[float, float]]]] = None,
    queue_rois: Optional[dict[str, PolygonROI | Sequence[tuple[float, float]]]] = None,
    pixels_per_meter: Optional[float] = None,
    speed_threshold_px_s: float = 5.0,
) -> VideoProcessor:
    """FastAPI dependency provider creating a VideoProcessor instance.

    Args:
        detector: Custom detector (or default shared YoloVehicleDetector).
        tracker: Custom tracker (or default MultiObjectTracker).
        frame_stride: Frame sampling stride (default: 1).
        rois: Polygon ROIs for lane occupancy.
        queue_rois: Polygon ROIs for queue detection.
        pixels_per_meter: Calibration factor for speed estimation in km/h.
        speed_threshold_px_s: Low movement speed threshold for queue counting.

    Returns:
        VideoProcessor: Configured video processor instance.
    """
    resolved_detector = detector or get_vehicle_detector()
    return VideoProcessor(
        detector=resolved_detector,
        tracker=tracker,
        frame_stride=frame_stride,
        rois=rois,
        queue_rois=queue_rois,
        pixels_per_meter=pixels_per_meter,
        speed_threshold_px_s=speed_threshold_px_s,
    )
