"""Backend bridge module for computer vision crash auto-detection and alerts.

Provides FastAPI dependency providers, database persistence helpers, and real-time
EventBus publishing for candidate collision anomalies detected by `CrashHeuristic`:
1. `get_crash_detector()`: FastAPI dependency provider returning a singleton `CrashHeuristic`.
2. `handle_crash_candidate()`: Persists an `Incident` row (severity 'high' for 'likely',
   'medium' for 'possible', status 'reported', explicit verdict in description, snapshot ref),
   then publishes the real-time alert envelope over `realtime/bus.py` using `INCIDENT_CREATED`.
3. `handle_crash_candidates()`: Batch processing wrapper for multiple crash candidates.

AUDIT TRAIL ARCHITECTURAL POLICY:
---------------------------------
Automated computer vision writes deliberately bypass the administrative `AuditLog`
pipeline (`log_audit()`). In production, high-frequency camera perception operates
continuously at 10 to 30 frames per second. Writing an immutable administrative audit
record for every automated perception candidate would create catastrophic write amplification
and database contention. Administrative audit logs are strictly reserved for human user
actions, triage, and manual signal overrides.
"""

from datetime import datetime, timezone
import logging
from typing import Any, Optional, Sequence
import numpy as np
from sqlalchemy.ext.asyncio import AsyncSession

from ai.cv.crash import CrashCandidate, CrashHeuristic
from app.models.event import Incident
from app.realtime import INCIDENT_CREATED, EventBus, get_bus
from app.vision.storage import save_evidence_snapshot

logger = logging.getLogger(__name__)

__all__ = [
    "CrashCandidate",
    "CrashHeuristic",
    "get_crash_detector",
    "handle_crash_candidate",
    "handle_crash_candidates",
]

_GLOBAL_CRASH_DETECTOR: Optional[CrashHeuristic] = None


def get_crash_detector() -> CrashHeuristic:
    """FastAPI dependency provider returning a configured CrashHeuristic instance.

    Returns:
        CrashHeuristic: Singleton perception heuristic detector instance.
    """
    global _GLOBAL_CRASH_DETECTOR
    if _GLOBAL_CRASH_DETECTOR is None:
        _GLOBAL_CRASH_DETECTOR = CrashHeuristic()
    return _GLOBAL_CRASH_DETECTOR


async def handle_crash_candidate(
    db: AsyncSession,
    candidate: CrashCandidate,
    intersection_id: Optional[int] = None,
    camera_id: Optional[str] = None,
    evidence_frame_bgr: Optional[np.ndarray] = None,
    evidence_ref: Optional[str] = None,
    bus: Optional[EventBus] = None,
) -> Incident:
    """Persist a candidate crash detection into `Incident` and publish real-time alert.

    Severity & Verdict Mapping:
    - Verdict 'likely'   -> severity 'high'
    - Verdict 'possible' -> severity 'medium'
    - Status is strictly initialized to 'reported'
    - Description explicitly names the verdict and confidence (e.g.
      "Possible crash detected (confidence 0.62) — unverified: tracks [1] ...")

    Real-time Fan-Out:
    Publishes an `incident.created` event onto the Redis EventBus. The envelope flows
    through `backend/app/realtime/notify.py` to produce operator control-room notifications
    (escalated to 'error' for 'high' severity, 'warning' for 'medium' severity).

    Payload Guidelines:
    - Never contains secrets or raw image frames (references only).
    - Includes incident_id, intersection_id, timestamp, confidence, verdict, evidence_ref.

    Args:
        db: Async SQLAlchemy database session.
        candidate: Evaluated `CrashCandidate` from `CrashHeuristic`.
        intersection_id: Optional intersection foreign key (overrides candidate.junction_id).
        camera_id: Optional camera identifier string.
        evidence_frame_bgr: Optional 3-channel BGR frame to persist as evidence snapshot.
        evidence_ref: Optional pre-existing evidence snapshot path or URL.
        bus: Optional EventBus instance (defaults to module-level singleton `get_bus()`).

    Returns:
        Incident: Newly persisted and flushed Incident database model instance.
    """
    # 1. Resolve evidence reference snapshot
    resolved_evidence_ref: Optional[str] = evidence_ref or candidate.evidence_ref
    if resolved_evidence_ref is None and evidence_frame_bgr is not None:
        resolved_evidence_ref = save_evidence_snapshot(
            frame_bgr=evidence_frame_bgr,
            category="crash",
            timestamp=candidate.timestamp,
        )

    # 2. Determine severity and explicit verdict description
    resolved_intersection_id = intersection_id if intersection_id is not None else candidate.junction_id
    resolved_camera_id = camera_id or candidate.camera_id

    # Severity mapping: 'high' for likely, 'medium' for possible
    severity = "high" if candidate.verdict.lower() == "likely" else "medium"

    tracks_str = f"tracks {candidate.involved_track_ids}"
    signals_str = ", ".join(candidate.signals_fired) if candidate.signals_fired else "heuristic anomaly"

    if candidate.verdict.lower() == "likely":
        desc_prefix = f"Likely crash detected (confidence {candidate.confidence:.2f}):"
    else:
        desc_prefix = f"Possible crash detected (confidence {candidate.confidence:.2f}) — unverified:"

    cam_part = f" [camera: {resolved_camera_id}]" if resolved_camera_id else ""
    evidence_part = f" [evidence: {resolved_evidence_ref}]" if resolved_evidence_ref else ""

    description = f"{desc_prefix} {tracks_str} ({signals_str}){cam_part}{evidence_part}".strip()
    if len(description) > 500:
        description = description[:497] + "..."

    # Extract location coordinates if available
    lat: Optional[float] = None
    lon: Optional[float] = None
    if candidate.location is not None:
        # Note: (cx, cy) are pixel coordinates, not geodetic lat/lon unless calibrated
        pass

    # 3. Persist Incident row in database
    incident = Incident(
        intersection_id=resolved_intersection_id,
        severity=severity,
        status="reported",
        description=description,
        reported_by=None,  # Automated perception detection
        lat=lat,
        lon=lon,
        created_at=candidate.timestamp or datetime.now(timezone.utc),
    )
    db.add(incident)
    await db.flush()

    # 4. Publish real-time event alert via realtime EventBus
    event_bus = bus if bus is not None else get_bus()
    payload: dict[str, Any] = {
        "incident_id": incident.id,
        "intersection_id": incident.intersection_id,
        "severity": incident.severity,
        "status": incident.status,
        "timestamp": incident.created_at.isoformat(),
        "confidence": candidate.confidence,
        "verdict": candidate.verdict,
        "evidence_ref": resolved_evidence_ref,
        "involved_track_ids": candidate.involved_track_ids,
        "camera_id": resolved_camera_id,
    }

    try:
        await event_bus.publish(
            event_type=INCIDENT_CREATED,
            payload=payload,
            source="crash-detector",
        )
    except Exception as exc:
        logger.warning(
            "Failed to publish real-time alert for crash incident #%d: %s",
            incident.id,
            exc,
        )

    return incident


async def handle_crash_candidates(
    db: AsyncSession,
    candidates: Sequence[CrashCandidate],
    intersection_id: Optional[int] = None,
    camera_id: Optional[str] = None,
    evidence_frame_bgr: Optional[np.ndarray] = None,
    bus: Optional[EventBus] = None,
) -> list[Incident]:
    """Persist a sequence of evaluated crash candidates and publish real-time alerts.

    Args:
        db: Async SQLAlchemy database session.
        candidates: Sequence of CrashCandidate instances.
        intersection_id: Optional intersection foreign key.
        camera_id: Optional camera identifier.
        evidence_frame_bgr: Optional BGR frame to attach as snapshot.
        bus: Optional EventBus instance.

    Returns:
        list[Incident]: Newly created Incident model instances.
    """
    records: list[Incident] = []
    for cand in candidates:
        inc = await handle_crash_candidate(
            db=db,
            candidate=cand,
            intersection_id=intersection_id,
            camera_id=camera_id,
            evidence_frame_bgr=evidence_frame_bgr,
            bus=bus,
        )
        records.append(inc)
    return records
