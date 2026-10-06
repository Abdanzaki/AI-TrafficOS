"""AI TrafficOS perception and predictive analytics package.

Phase 1 Foundation:
This package provides interfaces, schemas, and abstract classes defining the
architectural contracts for future AI workloads. No live model inference or
fake predictions are implemented in Phase 1.

Phase Roadmap:
- Phase 1: Abstract contracts, schemas (Detection, TrafficSnapshot), and stubs.
- Phase 4: Computer Vision perception engine (ai.cv):
    * Concrete YOLO/detection models for vehicle classification.
    * Traffic light signal-state classifiers.
    * Emergency vehicle audio/visual detector.
- Phase 5: Predictive Analytics engine (ai.prediction):
    * Graph neural network (GNN) and time-series traffic flow forecasting.
    * Congestion and bottleneck prediction models.
"""

from ai.common.schemas import Detection, TrafficSnapshot
from ai.cv.detectors import BaseDetector
from ai.prediction.base import BasePredictor

__all__ = [
    "BaseDetector",
    "BasePredictor",
    "Detection",
    "TrafficSnapshot",
]
