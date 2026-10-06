"""Computer Vision module for AI TrafficOS.

Provides detector base abstractions and interfaces. Concrete computer vision
models and inference pipelines will be implemented in Phase 4.
"""

from ai.cv.detectors import BaseDetector

__all__ = ["BaseDetector"]
