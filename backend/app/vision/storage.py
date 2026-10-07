"""Database storage integration for computer vision congestion and incident perception.

Provides async SQLAlchemy persistence functions mapping CV perception outputs
to database models:
1. `record_congestion_observation`: Persists evaluated congestion metrics into `TrafficRecord`.
2. `record_incident_candidate`: Persists candidate heuristic anomalies into `Incident`.
3. `map_confidence_to_severity`: Deterministic, documented mapping from candidate confidence
   and event type to valid database `Incident.severity` levels.

AUDIT TRAIL ARCHITECTURAL POLICY:
---------------------------------
Automated computer vision writes deliberately BYPASS the administrative `AuditLog`
pipeline (`log_audit()`). In production, high-frequency camera perception operates
continuously at 10 to 30 frames per second (or minute-level rolling windows across
dozens of intersection cameras). Writing an immutable administrative audit record for
every automated perception write would create catastrophic write amplification,
database contention, and storage exhaustion.
In accordance with AI TrafficOS Phase 2 patterns, `AuditLog` is reserved for human
user actions, manual signal overrides, role permissions changes, and administrative triage.
"""

from datetime import datetime, timezone
from typing import Optional, Sequence
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ai.cv.congestion import CongestionResult
from ai.cv.incidents import IncidentCandidate
from app.models.event import Incident
from app.models.traffic import TrafficRecord


# Documented severity mapping thresholds
VALID_SEVERITIES = {"low", "medium", "high", "critical", "unknown"}


def map_confidence_to_severity(event_type: str, confidence: float) -> str:
    """Map heuristic candidate confidence and event type to Incident severity.

    SEVERITY MAPPING SPECIFICATION:
    -------------------------------
    - 'wrong_way': Immediate active collision hazard on public roadways.
        - confidence >= 0.85  -> 'critical' (strong opposing trajectory > 150° deviation)
        - 0.65 <= conf < 0.85 -> 'high' (moderate opposing trajectory 120°-150°)
        - conf < 0.65         -> 'medium' (early opposing heading deviation)

    - 'stopped_vehicle': Stationary vehicle outside queue zones (potential stall/hazard).
        - confidence >= 0.85  -> 'high' (persistent stationary > 20+ frames outside queue)
        - 0.60 <= conf < 0.85 -> 'medium' (stationary 12-20 frames)
        - conf < 0.60         -> 'low' (early candidate, at threshold 10 frames)

    - Other / Ambiguous / Negative:
        - confidence < 0.0 or outside domain -> 'unknown'

    Args:
        event_type: Incident category ('wrong_way', 'stopped_vehicle', etc.).
        confidence: Normalized confidence score [0.0, 1.0].

    Returns:
        str: Valid Incident severity string ('low', 'medium', 'high', 'critical', 'unknown').
    """
    if confidence < 0.0 or confidence > 1.0:
        return "unknown"

    if event_type == "wrong_way":
        if confidence >= 0.85:
            return "critical"
        if confidence >= 0.65:
            return "high"
        return "medium"

    if event_type == "stopped_vehicle":
        if confidence >= 0.85:
            return "high"
        if confidence >= 0.60:
            return "medium"
        return "low"

    # Default fallback for unknown event categories
    if confidence >= 0.80:
        return "high"
    if confidence >= 0.50:
        return "medium"
    return "low"


async def record_congestion_observation(
    db: AsyncSession,
    intersection_id: int,
    congestion_result: CongestionResult | int,
    vehicle_count: Optional[int] = None,
    avg_speed_kmh: Optional[float] = None,
    lane_id: Optional[int] = None,
    recorded_at: Optional[datetime] = None,
) -> TrafficRecord:
    """Persist a computer vision congestion observation into `TrafficRecord`.

    Honest Data Contract:
    - `source` is explicitly set to 'camera'.
    - `avg_speed_kmh` is strictly populated ONLY when calibrated km/h speeds exist;
      if uncalibrated or speed estimation is absent, it is stored as None.
    - `congestion_level` is bounded to integer percentage [0, 100].

    Args:
        db: Async SQLAlchemy database session.
        intersection_id: Foreign key to `intersections.id`.
        congestion_result: Evaluated `CongestionResult` dataclass or integer congestion level.
        vehicle_count: Explicit vehicle count (if congestion_result is an integer).
        avg_speed_kmh: Explicit calibrated speed in km/h (if congestion_result is an integer).
        lane_id: Optional foreign key to `lanes.id`.
        recorded_at: Measurement capture timestamp (defaults to current UTC if None).

    Returns:
        TrafficRecord: Newly persisted and flushed TrafficRecord database model instance.
    """
    rec_time = recorded_at or datetime.now(timezone.utc)

    if isinstance(congestion_result, CongestionResult):
        c_level = congestion_result.congestion_level
        v_count = congestion_result.vehicle_count if vehicle_count is None else vehicle_count
        # Honest limit: only report avg_speed_kmh if physically calibrated
        s_kmh = congestion_result.avg_speed_kmh if congestion_result.is_calibrated else None
        if avg_speed_kmh is not None:
            s_kmh = avg_speed_kmh
    else:
        c_level = int(max(0, min(100, congestion_result)))
        v_count = int(vehicle_count) if vehicle_count is not None else 0
        s_kmh = float(avg_speed_kmh) if avg_speed_kmh is not None else None

    record = TrafficRecord(
        intersection_id=intersection_id,
        lane_id=lane_id,
        recorded_at=rec_time,
        vehicle_count=v_count,
        avg_speed_kmh=s_kmh,
        congestion_level=c_level,
        source="camera",
    )
    db.add(record)
    await db.flush()
    return record


async def record_incident_candidate(
    db: AsyncSession,
    candidate: IncidentCandidate,
    intersection_id: Optional[int] = None,
    lat: Optional[float] = None,
    lon: Optional[float] = None,
) -> Incident:
    """Persist a candidate anomaly heuristic observation into `Incident`.

    Honest Data Contract:
    - `severity` is computed via `map_confidence_to_severity(candidate.event_type, candidate.confidence)`.
    - `status` is initialized to 'reported'.
    - `description` MUST explicitly identify the underlying heuristic method and details.
    - `reported_by` is None (reflecting automated perception, not an authenticated human).

    Args:
        db: Async SQLAlchemy database session.
        candidate: `IncidentCandidate` dataclass from perception heuristic.
        intersection_id: Optional foreign key to `intersections.id`.
        lat: Optional geographic latitude.
        lon: Optional geographic longitude.

    Returns:
        Incident: Newly persisted and flushed Incident database model instance.
    """
    severity = map_confidence_to_severity(candidate.event_type, candidate.confidence)
    summary_text = candidate.details.get("summary", "")
    method_name = candidate.method

    # Format description explicitly stating the heuristic method
    description = (
        f"[Heuristic: {method_name}] Candidate {candidate.event_type} anomaly detected for "
        f"vehicle track #{candidate.track_id} (confidence: {candidate.confidence:.2f}). "
        f"{summary_text}"
    ).strip()

    # Clamp description to model max_length 500
    if len(description) > 500:
        description = description[:497] + "..."

    incident = Incident(
        intersection_id=intersection_id,
        severity=severity,
        status="reported",
        description=description,
        reported_by=None,
        lat=lat,
        lon=lon,
        created_at=candidate.timestamp or datetime.now(timezone.utc),
    )
    db.add(incident)
    await db.flush()
    return incident


async def record_incident_candidates(
    db: AsyncSession,
    candidates: Sequence[IncidentCandidate],
    intersection_id: Optional[int] = None,
    lat: Optional[float] = None,
    lon: Optional[float] = None,
) -> list[Incident]:
    """Persist a batch of candidate anomaly heuristic observations into `Incident`.

    Args:
        db: Async SQLAlchemy database session.
        candidates: Sequence of IncidentCandidate dataclasses.
        intersection_id: Optional foreign key to intersections.id.
        lat: Optional latitude coordinate.
        lon: Optional longitude coordinate.

    Returns:
        list[Incident]: List of persisted Incident model instances.
    """
    persisted: list[Incident] = []
    for cand in candidates:
        inc = await record_incident_candidate(
            db=db,
            candidate=cand,
            intersection_id=intersection_id,
            lat=lat,
            lon=lon,
        )
        persisted.append(inc)
    return persisted
