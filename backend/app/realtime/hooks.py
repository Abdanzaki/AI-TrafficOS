"""Real-time event publishing hooks for AI TrafficOS domain state changes.

Provides lightweight, fire-and-forget, non-raising emit_* functions taking
already-loaded scalar values (no internal DB queries) to broadcast domain
mutations across the real-time EventBus after successful database commits.
"""

from datetime import datetime, timezone
import logging
from typing import Any, Optional, Sequence

from app.realtime.bus import EventBus
from app.realtime.events import (
    CONGESTION_CHANGE,
    CONTROL_DECISION,
    EMERGENCY_CREATED,
    EMERGENCY_UPDATED,
    INCIDENT_CREATED,
    INCIDENT_UPDATED,
    NOTIFICATION_CREATED,
    PREDICTION_PUBLISHED,
    SIGNAL_CHANGE,
    SYSTEM_STATUS,
    TRAFFIC_UPDATE,
)

logger = logging.getLogger(__name__)


def _get_bus() -> EventBus:
    """Retrieve global EventBus singleton."""
    from app.realtime import get_bus

    return get_bus()


async def emit_signal_change(
    signal_id: int,
    intersection_id: int,
    previous_state: Optional[str],
    new_state: Optional[str],
    change_kind: str,
) -> None:
    """Emit signal.change when a signal or phase state changes."""
    bus = _get_bus()
    if bus.is_degraded:
        logger.debug("EventBus degraded; skipping signal.change for signal %d", signal_id)
        return
    payload = {
        "signal_id": signal_id,
        "intersection_id": intersection_id,
        "previous_state": previous_state,
        "new_state": new_state,
        "change_kind": change_kind,
    }
    await bus.safe_publish(SIGNAL_CHANGE, payload, source="signals-api")


async def emit_incident_created(
    incident_id: int,
    severity: str,
    intersection_id: Optional[int],
    status: str,
) -> None:
    """Emit incident.created on new traffic incident reporting."""
    bus = _get_bus()
    if bus.is_degraded:
        logger.debug("EventBus degraded; skipping incident.created for incident %d", incident_id)
        return
    payload = {
        "incident_id": incident_id,
        "severity": severity,
        "intersection_id": intersection_id,
        "status": status,
    }
    await bus.safe_publish(INCIDENT_CREATED, payload, source="incident-service")


async def emit_incident_updated(
    incident_id: int,
    old_status: str,
    new_status: str,
) -> None:
    """Emit incident.updated when incident status transitions."""
    bus = _get_bus()
    if bus.is_degraded:
        logger.debug("EventBus degraded; skipping incident.updated for incident %d", incident_id)
        return
    payload = {
        "incident_id": incident_id,
        "old_status": old_status,
        "new_status": new_status,
    }
    await bus.safe_publish(INCIDENT_UPDATED, payload, source="incident-service")


async def emit_emergency_created(
    event_id: int,
    status: str,
    priority: int,
    vehicle_type: str,
    intersection_id: Optional[int] = None,
    incident_id: Optional[int] = None,
) -> None:
    """Emit emergency.created on emergency vehicle transit event dispatch."""
    bus = _get_bus()
    if bus.is_degraded:
        logger.debug("EventBus degraded; skipping emergency.created for event %d", event_id)
        return
    payload = {
        "event_id": event_id,
        "status": status,
        "priority": priority,
        "vehicle_type": vehicle_type,
        "intersection_id": intersection_id,
        "incident_id": incident_id,
    }
    await bus.safe_publish(EMERGENCY_CREATED, payload, source="emergency-service")


async def emit_emergency_updated(
    event_id: int,
    old_status: str,
    new_status: str,
) -> None:
    """Emit emergency.updated on emergency lifecycle transition."""
    bus = _get_bus()
    if bus.is_degraded:
        logger.debug("EventBus degraded; skipping emergency.updated for event %d", event_id)
        return
    payload = {
        "event_id": event_id,
        "old_status": old_status,
        "new_status": new_status,
    }
    await bus.safe_publish(EMERGENCY_UPDATED, payload, source="emergency-service")


async def emit_control_decision(
    decision_id: Optional[int],
    decision_type: str,
    junction_id: Optional[int],
    summary: str,
) -> None:
    """Emit control.decision on supervisory AI control recommendation or actuation."""
    bus = _get_bus()
    if bus.is_degraded:
        logger.debug("EventBus degraded; skipping control.decision")
        return
    payload = {
        "decision_id": decision_id,
        "decision_type": decision_type,
        "junction_id": junction_id,
        "summary": summary[:200] if summary else "",
    }
    await bus.safe_publish(CONTROL_DECISION, payload, source="control-engine")


async def emit_prediction_published(
    model_version: str,
    horizon_minutes: int,
    junction_ids: Sequence[int],
    generated_at: Optional[str] = None,
) -> None:
    """Emit prediction.published when a new forecast batch is stored."""
    bus = _get_bus()
    if bus.is_degraded:
        logger.debug("EventBus degraded; skipping prediction.published")
        return
    payload = {
        "model_version": model_version,
        "horizon_minutes": horizon_minutes,
        "junction_ids": list(junction_ids),
        "generated_at": generated_at or datetime.now(timezone.utc).isoformat(),
    }
    await bus.safe_publish(PREDICTION_PUBLISHED, payload, source="forecasting-service")


async def emit_traffic_update(
    batch_size: int,
    junction_ids: Sequence[int],
    window_start: Optional[str],
    window_end: Optional[str],
) -> None:
    """Emit aggregated traffic.update per ingested batch of vehicle events."""
    bus = _get_bus()
    if bus.is_degraded:
        logger.debug("EventBus degraded; skipping traffic.update")
        return
    payload = {
        "batch_size": batch_size,
        "junction_ids": list(junction_ids),
        "window_start": window_start,
        "window_end": window_end,
    }
    await bus.safe_publish(TRAFFIC_UPDATE, payload, source="traffic-ingest")


def _congestion_band(level: int) -> int:
    """Map integer congestion percentage [0, 100] to threshold band index (0-3)."""
    if level <= 25:
        return 0
    if level <= 50:
        return 1
    if level <= 75:
        return 2
    return 3


async def emit_congestion_change(
    junction_id: int,
    congestion_level: int,
) -> None:
    """Emit congestion.change only when congestion level crosses a threshold band.

    State Tracking:
        Tracks last-emitted level in Redis key `trafficos:congestion:last:{junction_id}`.
        No database writes are performed for this state.
    """
    bus = _get_bus()
    if bus.is_degraded or bus._redis is None:
        logger.debug("EventBus degraded; skipping congestion threshold check for junction %d", junction_id)
        return

    redis_key = f"trafficos:congestion:last:{junction_id}"
    try:
        raw_last = await bus._redis.get(redis_key)
        last_level = int(raw_last) if raw_last is not None else None
        if last_level is not None and _congestion_band(congestion_level) == _congestion_band(last_level):
            return
        await bus._redis.set(redis_key, str(congestion_level))
        payload = {
            "junction_id": junction_id,
            "congestion_level": congestion_level,
            "previous_level": last_level,
        }
        await bus.safe_publish(CONGESTION_CHANGE, payload, source="traffic-analysis")
    except Exception as exc:
        logger.debug("Failed evaluating congestion.change threshold: %s", exc)


async def emit_notification_created(
    notification_id: int,
    severity: str,
    title: str,
) -> None:
    """Emit notification.created on newly created notification."""
    bus = _get_bus()
    if bus.is_degraded:
        logger.debug("EventBus degraded; skipping notification.created for %d", notification_id)
        return
    payload = {
        "notification_id": notification_id,
        "severity": severity,
        "title": title,
    }
    await bus.safe_publish(NOTIFICATION_CREATED, payload, source="notifications-service")


async def emit_system_status(
    status: str = "online",
    service: str = "ai-trafficos",
) -> None:
    """Emit system.status event on application startup lifespan."""
    bus = _get_bus()
    if bus.is_degraded:
        logger.debug("EventBus degraded; skipping system.status")
        return
    payload = {
        "status": status,
        "service": service,
    }
    await bus.safe_publish(SYSTEM_STATUS, payload, source="system")
