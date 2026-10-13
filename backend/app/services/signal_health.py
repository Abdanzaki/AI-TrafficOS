"""Signal predictive-maintenance and failure risk scoring service.

Methodology Note:
    This service scores physical traffic signals on a 0-100 scale using transparent
    heuristic and statistical rules. It evaluates telemetry heartbeat freshness,
    phase-flapping rates, anomalous dwell times, and controller operating statuses.
    This is an operational heuristic/statistical indicator, NOT a physical physics-based
    wear or component-fatigue model.
    Provenance: strictly 'heuristic'.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import logging
from typing import Any, Optional, Union

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.audit import AuditLog
from app.models.signal import Signal, SignalPhase

logger = logging.getLogger(__name__)

# Transparent factor weights (summing to 1.0)
WEIGHT_CONTROLLER_STATUS: float = 0.35
WEIGHT_PHASE_FLAPPING: float = 0.25
WEIGHT_HEARTBEAT_STALENESS: float = 0.20
WEIGHT_ANOMALOUS_DWELL: float = 0.20

PROVENANCE: str = "heuristic"


@dataclass
class TelemetrySample:
    """Represents a discrete telemetry heartbeat or state observation."""

    timestamp: datetime
    state: str
    duration_seconds: Optional[int] = None
    confidence: Optional[float] = None
    status: Optional[str] = None


def _parse_telemetry_history(
    raw_history: list[Union[dict[str, Any], TelemetrySample]],
) -> list[TelemetrySample]:
    """Normalize raw telemetry history into sorted TelemetrySample list."""
    samples: list[TelemetrySample] = []
    for item in raw_history:
        if isinstance(item, TelemetrySample):
            samples.append(item)
        elif isinstance(item, dict):
            ts = item.get("timestamp") or item.get("recorded_at") or item.get("observed_at")
            if isinstance(ts, str):
                try:
                    ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                except (ValueError, TypeError):
                    ts = datetime.now(timezone.utc)
            elif ts is None:
                ts = datetime.now(timezone.utc)

            state = str(item.get("state") or item.get("observed_state") or "unknown").lower()
            dur = item.get("duration_seconds")
            conf = item.get("confidence") or item.get("observed_confidence")
            stat = item.get("status")
            samples.append(
                TelemetrySample(
                    timestamp=ts,
                    state=state,
                    duration_seconds=int(dur) if dur is not None else None,
                    confidence=float(conf) if conf is not None else None,
                    status=str(stat) if stat is not None else None,
                )
            )

    samples.sort(key=lambda s: s.timestamp)
    return samples


def compute_signal_health(
    signal: Signal,
    telemetry_history: Optional[list[Union[dict[str, Any], TelemetrySample]]] = None,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    """Compute 0-100 predictive maintenance score with human-readable factor explanation.

    Args:
        signal: SQLAlchemy Signal controller model instance.
        telemetry_history: Optional chronological observations or heartbeat records.
        now: Optional current evaluation timestamp (defaults to current UTC).

    Returns:
        Structured dictionary matching SignalHealthResponse schema.
    """
    eval_time = now or datetime.now(timezone.utc)
    samples = _parse_telemetry_history(telemetry_history or [])

    factors: list[dict[str, Any]] = []
    total_penalty = 0.0

    # ---------------------------------------------------------
    # Factor 1: Controller Hardware Operating Status (Weight 0.35)
    # ---------------------------------------------------------
    status_str = (signal.status or "active").lower().strip()
    status_penalty = 0.0
    status_status = "normal"

    if status_str == "active":
        status_penalty = 0.0
        status_desc = f"Controller hardware reports normal operating status ('{status_str}') (weight: {WEIGHT_CONTROLLER_STATUS})."
    elif status_str == "maintenance":
        status_penalty = 25.0
        status_status = "warning"
        status_desc = f"Controller is flagged in maintenance mode ('{status_str}') (weight: {WEIGHT_CONTROLLER_STATUS})."
    elif status_str == "inactive":
        status_penalty = 35.0
        status_status = "warning"
        status_desc = f"Controller is currently decommissioned or inactive ('{status_str}') (weight: {WEIGHT_CONTROLLER_STATUS})."
    elif status_str == "fault":
        status_penalty = 60.0
        status_status = "critical"
        status_desc = f"Controller reported an active hardware fault ('{status_str}') (weight: {WEIGHT_CONTROLLER_STATUS})."
    else:
        status_penalty = 20.0
        status_status = "warning"
        status_desc = f"Controller operating status is non-standard ('{status_str}') (weight: {WEIGHT_CONTROLLER_STATUS})."

    total_penalty += status_penalty
    factors.append({
        "name": "controller_status",
        "weight": WEIGHT_CONTROLLER_STATUS,
        "raw_value": status_str,
        "penalty": round(status_penalty, 1),
        "status": status_status,
        "description": status_desc,
    })

    # ---------------------------------------------------------
    # Factor 2: Phase-Flapping Rate (Weight 0.25)
    # ---------------------------------------------------------
    flapping_penalty = 0.0
    flapping_status = "normal"
    rapid_switches = 0
    total_switches = 0

    if len(samples) >= 2:
        for i in range(1, len(samples)):
            prev_s = samples[i - 1]
            curr_s = samples[i]
            if prev_s.state != curr_s.state:
                total_switches += 1
                dt_seconds = abs((curr_s.timestamp - prev_s.timestamp).total_seconds())
                if dt_seconds < 5.0:
                    rapid_switches += 1

        if rapid_switches >= 1:
            flapping_penalty = min(35.0, round(rapid_switches * 8.0, 1))
            flapping_status = "critical" if rapid_switches >= 3 else "warning"
            flapping_desc = (
                f"Phase-flapping detected: {rapid_switches} rapid transitions (<5s interval) "
                f"across {total_switches} state switches (weight: {WEIGHT_PHASE_FLAPPING})."
            )
        else:
            flapping_penalty = 0.0
            flapping_desc = (
                f"Phase switching cadence is stable ({total_switches} standard transitions; "
                f"no rapid flapping; weight: {WEIGHT_PHASE_FLAPPING})."
            )
    else:
        # Check if current observed state vs active phase shows conflict
        flapping_desc = f"Insufficient telemetry transitions to evaluate phase-flapping (weight: {WEIGHT_PHASE_FLAPPING})."

    total_penalty += flapping_penalty
    factors.append({
        "name": "phase_flapping",
        "weight": WEIGHT_PHASE_FLAPPING,
        "raw_value": {"rapid_switches": rapid_switches, "total_switches": total_switches},
        "penalty": round(flapping_penalty, 1),
        "status": flapping_status,
        "description": flapping_desc,
    })

    # ---------------------------------------------------------
    # Factor 3: Missed-Heartbeat & Telemetry Staleness (Weight 0.20)
    # ---------------------------------------------------------
    staleness_penalty = 0.0
    staleness_status = "normal"

    latest_ts: Optional[datetime] = None
    if samples:
        latest_ts = samples[-1].timestamp
    elif signal.observed_at is not None:
        latest_ts = signal.observed_at
    elif signal.updated_at is not None:
        latest_ts = signal.updated_at

    age_seconds: Optional[float] = None
    if latest_ts is not None:
        if latest_ts.tzinfo is None:
            latest_ts = latest_ts.replace(tzinfo=timezone.utc)
        age_seconds = max(0.0, (eval_time - latest_ts).total_seconds())

    if age_seconds is None:
        staleness_penalty = 25.0
        staleness_status = "warning"
        staleness_desc = f"No telemetry updates or observations on record for this controller (weight: {WEIGHT_HEARTBEAT_STALENESS})."
    elif age_seconds <= 60.0:
        staleness_penalty = 0.0
        staleness_desc = f"Telemetry heartbeat is fresh ({int(age_seconds)}s ago; weight: {WEIGHT_HEARTBEAT_STALENESS})."
    elif age_seconds <= 300.0:
        staleness_penalty = 10.0
        staleness_status = "warning"
        staleness_desc = f"Telemetry update delayed: last heartbeat was {int(age_seconds)}s ago (weight: {WEIGHT_HEARTBEAT_STALENESS})."
    elif age_seconds <= 1800.0:
        staleness_penalty = 20.0
        staleness_status = "warning"
        staleness_desc = f"Stale telemetry: last update was {int(age_seconds // 60)} minutes ago (weight: {WEIGHT_HEARTBEAT_STALENESS})."
    else:
        staleness_penalty = 30.0
        staleness_status = "critical"
        staleness_desc = (
            f"Missed-heartbeat timeout: telemetry has been stale for {int(age_seconds // 60)} minutes "
            f"(weight: {WEIGHT_HEARTBEAT_STALENESS})."
        )

    total_penalty += staleness_penalty
    factors.append({
        "name": "heartbeat_staleness",
        "weight": WEIGHT_HEARTBEAT_STALENESS,
        "raw_value": round(age_seconds, 1) if age_seconds is not None else None,
        "penalty": round(staleness_penalty, 1),
        "status": staleness_status,
        "description": staleness_desc,
    })

    # ---------------------------------------------------------
    # Factor 4: Anomalous Dwell Times (Weight 0.20)
    # ---------------------------------------------------------
    dwell_penalty = 0.0
    dwell_status = "normal"
    anomalous_dwells = 0

    configured_durations = [p.duration_seconds for p in signal.phases if p.duration_seconds > 0]
    expected_duration = (
        sum(configured_durations) / len(configured_durations) if configured_durations else 30.0
    )

    if samples:
        for s in samples:
            if s.duration_seconds is not None:
                if s.duration_seconds < 3 or s.duration_seconds > (expected_duration * 3.0):
                    anomalous_dwells += 1

    if anomalous_dwells >= 1:
        dwell_penalty = min(25.0, round(10.0 + anomalous_dwells * 5.0, 1))
        dwell_status = "critical" if anomalous_dwells >= 3 else "warning"
        dwell_desc = (
            f"Anomalous dwell time detected: {anomalous_dwells} observations had aberrant durations "
            f"(deviating >3x from expected {int(expected_duration)}s cycle plan; weight: {WEIGHT_ANOMALOUS_DWELL})."
        )
    else:
        dwell_penalty = 0.0
        dwell_desc = (
            f"Dwell times are consistent with planned phase timing intervals "
            f"(expected ~{int(expected_duration)}s; weight: {WEIGHT_ANOMALOUS_DWELL})."
        )

    total_penalty += dwell_penalty
    factors.append({
        "name": "anomalous_dwell",
        "weight": WEIGHT_ANOMALOUS_DWELL,
        "raw_value": {"anomalous_count": anomalous_dwells, "expected_dwell_s": expected_duration},
        "penalty": round(dwell_penalty, 1),
        "status": dwell_status,
        "description": dwell_desc,
    })

    # Compute final score clamped to 0-100
    raw_score = 100.0 - total_penalty
    final_score = int(max(0, min(100, round(raw_score))))

    if final_score >= 80:
        band = "healthy"
    elif final_score >= 50:
        band = "degraded"
    else:
        band = "at-risk"

    # Human-readable comprehensive explanation summary
    penalties_summary = [
        f"{f['description']} (penalty: -{f['penalty']})"
        for f in factors
        if f["penalty"] > 0
    ]
    if penalties_summary:
        summary_text = (
            f"Signal {signal.code} evaluated as '{band}' with predictive-maintenance score {final_score}/100. "
            f"Deductions: {'; '.join(penalties_summary)}. "
            f"Scored via transparent heuristic/statistical rule model (not a physics model)."
        )
    else:
        summary_text = (
            f"Signal {signal.code} evaluated as 'healthy' with optimal score {final_score}/100. "
            f"All operational indicators (heartbeat freshness, phase transition stability, dwell adherence, "
            f"controller active status) are in nominal range. "
            f"Scored via transparent heuristic/statistical rule model (not a physics model)."
        )

    return {
        "signal_id": signal.id,
        "signal_code": signal.code,
        "intersection_id": signal.intersection_id,
        "score": final_score,
        "status_band": band,
        "explanation": summary_text,
        "factors": factors,
        "provenance": PROVENANCE,
        "evaluated_at": eval_time.isoformat(),
        "metrics": {
            "total_penalty": round(total_penalty, 1),
            "rapid_flapping_switches": rapid_switches,
            "telemetry_age_seconds": round(age_seconds, 1) if age_seconds is not None else None,
            "anomalous_dwell_count": anomalous_dwells,
            "operating_status": status_str,
        },
    }


async def get_signal_health(
    db: AsyncSession,
    signal_id: int,
    telemetry_history: Optional[list[Union[dict[str, Any], TelemetrySample]]] = None,
    now: Optional[datetime] = None,
) -> Optional[dict[str, Any]]:
    """Query signal controller and compute predictive health evaluation."""
    stmt = (
        select(Signal)
        .options(selectinload(Signal.phases))
        .where(Signal.id == signal_id)
    )
    res = await db.execute(stmt)
    signal = res.scalar_one_or_none()
    if signal is None:
        return None

    # If telemetry_history was not provided, look for recent audit log overrides/updates
    samples = telemetry_history
    if samples is None:
        audit_stmt = (
            select(AuditLog)
            .where(
                AuditLog.entity_type == "signal",
                AuditLog.entity_id == signal_id,
            )
            .order_by(AuditLog.created_at.asc())
            .limit(50)
        )
        audit_res = await db.execute(audit_stmt)
        audits = audit_res.scalars().all()
        if audits:
            samples = [
                TelemetrySample(
                    timestamp=a.created_at,
                    state=str((a.details or {}).get("state") or signal.observed_state or "unknown"),
                    duration_seconds=30,
                    status=str((a.details or {}).get("status") or signal.status),
                )
                for a in audits
            ]

    return compute_signal_health(signal, samples, now=now)


async def get_all_signals_health(
    db: AsyncSession,
    intersection_id: Optional[int] = None,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    """Retrieve predictive health evaluation across all signals (or for an intersection)."""
    stmt = (
        select(Signal)
        .options(selectinload(Signal.phases))
        .order_by(Signal.id.asc())
    )
    if intersection_id is not None:
        stmt = stmt.where(Signal.intersection_id == intersection_id)

    res = await db.execute(stmt)
    signals = res.scalars().all()

    items: list[dict[str, Any]] = []
    healthy_cnt = 0
    degraded_cnt = 0
    at_risk_cnt = 0

    for s in signals:
        health = compute_signal_health(s, telemetry_history=None, now=now)
        items.append(health)
        band = health["status_band"]
        if band == "healthy":
            healthy_cnt += 1
        elif band == "degraded":
            degraded_cnt += 1
        else:
            at_risk_cnt += 1

    return {
        "items": items,
        "total": len(items),
        "healthy_count": healthy_cnt,
        "degraded_count": degraded_cnt,
        "at_risk_count": at_risk_cnt,
        "provenance": PROVENANCE,
    }
