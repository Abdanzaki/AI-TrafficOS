"""FastAPI backend integration module for traffic congestion perception.

Layout & Architecture Note:
---------------------------
Core congestion and traffic-ahead algorithms reside in `ai/cv/congestion.py` to keep
perception logic decoupled from HTTP/FastAPI dependencies. This backend module provides:
1. Re-exports of `CongestionResult`, `CongestionWeights`, `TrafficAheadResult`, and calculation functions.
2. Provider function for FastAPI dependency injection (`get_congestion_calculator`).
"""

from typing import Callable
from ai.cv.congestion import (
    CongestionResult,
    CongestionWeights,
    TrafficAheadResult,
    compute_congestion_score,
    detect_traffic_ahead,
)

__all__ = [
    "CongestionResult",
    "CongestionWeights",
    "TrafficAheadResult",
    "compute_congestion_score",
    "detect_traffic_ahead",
    "get_congestion_calculator",
]


def get_congestion_calculator() -> Callable[..., CongestionResult]:
    """FastAPI dependency provider returning the primary congestion scoring callable.

    Returns:
        Callable: compute_congestion_score function reference.
    """
    return compute_congestion_score
