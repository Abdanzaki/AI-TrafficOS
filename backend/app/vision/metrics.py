"""FastAPI backend integration module for traffic perception metrics.

Layout & Architecture Note:
---------------------------
Core metric algorithms are implemented in `ai/cv/metrics.py` to keep perception
pure and decoupled from HTTP/FastAPI dependencies. This backend module provides:
1. Re-exports of `FrameMetrics`, `PolygonROI`, and calculation functions.
2. Provider function for FastAPI dependency injection (`get_frame_metrics_calculator`).
3. Serialization / schema adapters for ingestion by downstream analytics services.
"""

from typing import Any, Callable, Sequence
from datetime import datetime

from ai.common.schemas import Detection
from ai.cv.metrics import (
    FrameMetrics,
    PolygonROI,
    calculate_lane_occupancy,
    calculate_queue_length,
    calculate_traffic_density,
    compute_frame_metrics,
    compute_vehicle_counts,
)

__all__ = [
    "FrameMetrics",
    "PolygonROI",
    "calculate_lane_occupancy",
    "calculate_queue_length",
    "calculate_traffic_density",
    "compute_frame_metrics",
    "compute_vehicle_counts",
    "get_metrics_calculator",
]


def get_metrics_calculator() -> Callable[..., FrameMetrics]:
    """FastAPI dependency provider returning the primary metrics computation callable.

    Returns:
        Callable: compute_frame_metrics function reference.
    """
    return compute_frame_metrics
