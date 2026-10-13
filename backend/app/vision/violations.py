"""FastAPI backend bridge module for traffic violation detection.

Layout & Architecture Note:
---------------------------
Pure computer vision heuristics reside in `ai/cv/violations.py` to keep perception
decoupled from web frameworks. This backend module provides:
1. Re-exports of `ViolationCandidate`, `StopLineConfig`, `RedLightViolationHeuristic`,
   `WrongWayViolationHeuristic`, `NoHelmetViolationHeuristic`, `ViolationDetector`,
   `HelmetClassifier`, `PyTorchHelmetClassifier`.
2. FastAPI dependency provider function (`get_violation_detector`).
3. Database persistence function (`persist_violation`) writing `Violation` rows.
4. Optional evidence snapshot persistence helper (`save_violation_evidence_snapshot`).
"""

from datetime import datetime, timezone
import os
from pathlib import Path
from typing import Optional, Sequence
import uuid
import numpy as np
import cv2
from sqlalchemy.ext.asyncio import AsyncSession

from ai.cv.violations import (
    HelmetClassifier,
    NoHelmetViolationHeuristic,
    PyTorchHelmetClassifier,
    RedLightViolationHeuristic,
    StopLineConfig,
    ViolationCandidate,
    ViolationDetector,
    WrongWayViolationHeuristic,
)
from app.models.violation import Violation

__all__ = [
    "HelmetClassifier",
    "NoHelmetViolationHeuristic",
    "PyTorchHelmetClassifier",
    "RedLightViolationHeuristic",
    "StopLineConfig",
    "ViolationCandidate",
    "ViolationDetector",
    "WrongWayViolationHeuristic",
    "get_violation_detector",
    "persist_violation",
    "persist_violations",
    "save_violation_evidence_snapshot",
]

_GLOBAL_VIOLATION_DETECTOR: Optional[ViolationDetector] = None


def get_violation_detector() -> ViolationDetector:
    """FastAPI dependency provider returning a configured ViolationDetector instance.

    Returns:
        ViolationDetector: Unified heuristic detector instance.
    """
    global _GLOBAL_VIOLATION_DETECTOR
    if _GLOBAL_VIOLATION_DETECTOR is None:
        helmet_weights = os.getenv("HELMET_MODEL_PATH")
        classifier = PyTorchHelmetClassifier(weights_path=helmet_weights) if helmet_weights else None
        _GLOBAL_VIOLATION_DETECTOR = ViolationDetector(
            red_light_heuristic=RedLightViolationHeuristic(),
            wrong_way_heuristic=WrongWayViolationHeuristic(),
            no_helmet_heuristic=NoHelmetViolationHeuristic(classifier=classifier),
        )
    return _GLOBAL_VIOLATION_DETECTOR


def save_violation_evidence_snapshot(
    frame_bgr: np.ndarray,
    violation_type: str,
    timestamp: Optional[datetime] = None,
    output_dir: Optional[str | Path] = None,
) -> Optional[str]:
    """Save an evidence frame snapshot to disk and return the evidence reference path.

    Args:
        frame_bgr: 3-channel BGR numpy image frame.
        violation_type: Violation category for path indexing.
        timestamp: Measurement capture timestamp.
        output_dir: Storage directory path. Defaults to 'storage/evidence/violations'.

    Returns:
        Optional[str]: Relative snapshot path or URL string if written, None if frame is empty.
    """
    if frame_bgr is None or not isinstance(frame_bgr, np.ndarray) or frame_bgr.size == 0:
        return None

    dt = timestamp or datetime.now(timezone.utc)
    ts_str = dt.strftime("%Y%m%d_%H%M%S")
    uid = uuid.uuid4().hex[:6]

    base_dir = Path(output_dir) if output_dir else Path("storage/evidence/violations")
    base_dir.mkdir(parents=True, exist_ok=True)

    filename = f"{violation_type}_{ts_str}_{uid}.jpg"
    filepath = base_dir / filename

    try:
        cv2.imwrite(str(filepath), frame_bgr)
        return str(filepath)
    except Exception:
        return None


async def persist_violation(
    db: AsyncSession,
    candidate: ViolationCandidate,
    intersection_id: Optional[int] = None,
    camera_id: Optional[str] = None,
    evidence_ref: Optional[str] = None,
) -> Violation:
    """Persist a candidate computer vision violation into the database.

    AUDIT TRAIL ARCHITECTURAL POLICY:
    Automated computer vision writes deliberately bypass administrative `AuditLog`
    to prevent write amplification under continuous multi-camera perception streams.
    Audit logs remain reserved for human administrative actions and overrides.

    Args:
        db: Async SQLAlchemy database session.
        candidate: ViolationCandidate emitted by perception heuristic.
        intersection_id: Optional foreign key to intersections.id.
        camera_id: Optional camera identifier.
        evidence_ref: Optional evidence snapshot reference URL or file path.

    Returns:
        Violation: Newly persisted and flushed Violation model instance.
    """
    cam_id = camera_id or candidate.camera_id
    ev_ref = evidence_ref or candidate.evidence_ref

    violation = Violation(
        violation_type=candidate.violation_type,
        detected_at=candidate.detected_at,
        intersection_id=intersection_id,
        camera_id=cam_id,
        confidence=candidate.confidence,
        status="recorded",
        evidence_ref=ev_ref,
        details=candidate.details,
    )
    db.add(violation)
    await db.flush()
    return violation


async def persist_violations(
    db: AsyncSession,
    candidates: Sequence[ViolationCandidate],
    intersection_id: Optional[int] = None,
    camera_id: Optional[str] = None,
) -> list[Violation]:
    """Persist a batch of candidate violations into the database.

    Args:
        db: Async SQLAlchemy database session.
        candidates: Sequence of ViolationCandidate instances.
        intersection_id: Optional foreign key to intersections.id.
        camera_id: Optional camera identifier.

    Returns:
        list[Violation]: List of newly persisted Violation model instances.
    """
    records: list[Violation] = []
    for cand in candidates:
        v = await persist_violation(
            db=db,
            candidate=cand,
            intersection_id=intersection_id,
            camera_id=camera_id,
        )
        records.append(v)
    return records
