"""Data containers and type definitions for AI perception and forecasting.

Pure data containers with no processing logic (Phase 1 foundation).
"""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Detection:
    """Bounding box detection payload from vision models.

    Concrete detector implementations arrive in Phase 4.
    """

    label: str
    confidence: float
    bbox: tuple[float, float, float, float] | None = None
    timestamp: datetime | None = None


@dataclass(frozen=True)
class TrafficSnapshot:
    """Aggregated traffic state snapshot for a given intersection.

    State evaluation and predictive ingestion arrive in Phase 5.
    """

    intersection_id: int
    vehicle_count: int = 0
    timestamp: datetime | None = None
    raw: dict | None = None
