"""FastAPI backend integration module for incident perception heuristics.

Layout & Architecture Note:
---------------------------
Core heuristic logic resides in `ai/cv/incidents.py` to keep perception decoupled
from web frameworks. This backend module provides:
1. Re-exports of `IncidentCandidate`, `IncidentDetector`, `LaneDirectionConfig`,
   `StoppedVehicleHeuristic`, and `WrongWayHeuristic`.
2. Provider function for FastAPI dependency injection (`get_incident_detector`).
"""

from typing import Optional
from ai.cv.incidents import (
    IncidentCandidate,
    IncidentDetector,
    LaneDirectionConfig,
    StoppedVehicleHeuristic,
    WrongWayHeuristic,
)

__all__ = [
    "IncidentCandidate",
    "IncidentDetector",
    "LaneDirectionConfig",
    "StoppedVehicleHeuristic",
    "WrongWayHeuristic",
    "get_incident_detector",
]

_GLOBAL_INCIDENT_DETECTOR: Optional[IncidentDetector] = None


def get_incident_detector(
    min_stopped_frames: int = 10,
    stopped_speed_threshold_px_s: float = 3.0,
    min_alignment_confidence: float = 0.50,
) -> IncidentDetector:
    """FastAPI dependency provider returning an IncidentDetector instance.

    Args:
        min_stopped_frames: Frames at ~zero speed required to flag stopped vehicle.
        stopped_speed_threshold_px_s: Speed threshold in px/s to consider stationary.
        min_alignment_confidence: Base confidence for wrong-way detection.

    Returns:
        IncidentDetector: Configured heuristic detector instance.
    """
    global _GLOBAL_INCIDENT_DETECTOR
    if _GLOBAL_INCIDENT_DETECTOR is None:
        stopped_h = StoppedVehicleHeuristic(
            min_stopped_frames=min_stopped_frames,
            stopped_speed_threshold_px_s=stopped_speed_threshold_px_s,
        )
        wrong_way_h = WrongWayHeuristic(
            min_alignment_confidence=min_alignment_confidence,
        )
        _GLOBAL_INCIDENT_DETECTOR = IncidentDetector(
            stopped_heuristic=stopped_h,
            wrong_way_heuristic=wrong_way_h,
        )
    return _GLOBAL_INCIDENT_DETECTOR
