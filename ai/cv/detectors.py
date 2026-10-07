"""Computer Vision detector interfaces and abstractions.

Phase 4 concrete implementations:
- YoloVehicleDetector: Real YOLOv8 vehicle detection (cars, buses, trucks, motorcycles)
- EmergencyVehicleHeuristic: Honest rule-based visual heuristic layer for emergency vehicles
"""

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

from ai.common.schemas import Detection

if TYPE_CHECKING:
    from ai.cv.yolo_detector import YoloVehicleDetector


class BaseDetector(ABC):
    """Abstract base class for vision detectors."""

    @abstractmethod
    def detect(self, frame: Any) -> list[Detection]:
        """Execute detection inference over an input video frame.

        Args:
            frame: Raw image or numpy frame buffer.

        Returns:
            list[Detection]: List of bounding-box detections with confidence scores.
        """
        raise NotImplementedError("Not implemented: Phase 4 will provide concrete detectors")


def __getattr__(name: str) -> Any:
    """Lazy-load concrete detectors to prevent circular imports."""
    if name == "YoloVehicleDetector":
        from ai.cv.yolo_detector import YoloVehicleDetector

        return YoloVehicleDetector
    if name == "TrafficSignalDetector":
        from ai.cv.signal_detector import TrafficSignalDetector

        return TrafficSignalDetector
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")


__all__ = ["BaseDetector", "YoloVehicleDetector", "TrafficSignalDetector"]

