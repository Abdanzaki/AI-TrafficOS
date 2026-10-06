"""Computer Vision detector interfaces and abstractions.

Future detector implementations (Phase 4):
- Vehicle detector (cars, buses, trucks, motorcycles, bicycles)
- Signal-state classifier (red, amber, green, arrows)
- Emergency-vehicle detector (ambulances, fire engines, law enforcement)
"""

from abc import ABC, abstractmethod
from typing import Any

from ai.common.schemas import Detection


class BaseDetector(ABC):
    """Abstract base class for vision detectors."""

    @abstractmethod
    def detect(self, frame: Any) -> list[Detection]:
        """Execute detection inference over an input video frame.

        Args:
            frame: Raw image or numpy frame buffer.

        Returns:
            list[Detection]: List of bounding-box detections with confidence scores.

        Raises:
            NotImplementedError: Raised in Phase 1 stubs.
        """
        raise NotImplementedError("Not implemented: Phase 4 will provide concrete detectors")
