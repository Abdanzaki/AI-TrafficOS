"""Real-time event to notification system wiring for AI TrafficOS.

Provides policy-driven evaluation of domain events emitted over the real-time EventBus,
mapping operationally significant events into system notifications with severity gating,
Redis-backed rate limiting, and database-level unread entity deduplication.

Architectural Design:
1. Delivery Target:
   Operational traffic alerts (incidents, emergency transits, severe congestion, supervisory
   actions, and emergency signal overrides) are delivered as system-wide broadcasts (`user_id=None`).
   This follows the existing Notification model and API pattern where `user_id=None` targets all
   active platform operators and dispatchers monitoring the central traffic network, whereas
   targeted notifications (`user_id=<int>`) are reserved for private operator communications.

2. Severity Gating:
   Mapped via `EVENT_NOTIFICATION_CONFIG`:
   - `incident.created`      -> warning (escalated to error for high/critical incidents)
   - `incident.updated`      -> info (deduped if unread notification exists for that incident)
   - `emergency.created`     -> critical
   - `emergency.updated`     -> info ONLY when resolved or closed
   - `congestion.change`     -> warning ONLY for severe congestion (>75%) with 15-min Redis gate
   - `control.decision`      -> info ONLY for operationally significant decision types
   - `signal.change`         -> NO notification by default; warning for emergency manual overrides
   - `prediction.published`  -> NO notification (dashboards pull forecast batches on demand)
   - `notification.created`  -> NEVER triggers another notification (explicit recursion guard)

3. Deduplication Guards:
   - Redis Key Gate: `trafficos:notify:congestion:{junction_id}` with 15-minute TTL prevents
     severe congestion alert flooding for the same junction.
   - Single Indexed DB Query: `is_duplicate_unread_notification` performs a single indexed query
     on `(entity_type, entity_id, is_read, created_at)` within the dedupe window (15 minutes).
     If an unread alert already exists for the entity, subsequent inserts are skipped (no N+1).

4. Exactly-Once Delivery & Integration:
   The `maybe_notify_for_event` helper integrates with the shared `create_notification` helper
   used by the REST API, ensuring that persistence, audit logging, and the `notification.created`
   real-time WebSocket broadcast occur exactly once per triggered alert.
"""

from datetime import datetime, timedelta, timezone
import logging
from typing import Any, Optional, Union

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.models.notification import Notification
from app.realtime.bus import EventBus
from app.realtime.events import (
    CONGESTION_CHANGE,
    CONTROL_DECISION,
    EMERGENCY_CREATED,
    EMERGENCY_UPDATED,
    EventEnvelope,
    INCIDENT_CREATED,
    INCIDENT_UPDATED,
    NOTIFICATION_CREATED,
    PREDICTION_PUBLISHED,
    SIGNAL_CHANGE,
    SYSTEM_STATUS,
    TRAFFIC_UPDATE,
)

logger = logging.getLogger(__name__)

# Operational limits and deduplication windows
DEFAULT_DEDUPE_WINDOW_SECONDS = 900  # 15 minutes
CONGESTION_NOTIFY_TTL_SECONDS = 900  # 15 minutes
CONGESTION_SEVERE_THRESHOLD = 75  # Congestion percentage > 75% is Band 3 (severe)
CONGESTION_REDIS_KEY_PREFIX = "trafficos:notify:congestion:"

# Documented filter list for operationally significant supervisory control decisions
OPERATIONALLY_SIGNIFICANT_DECISION_TYPES: set[str] = {
    # Emergency preemption and priority routing
    "PRIORITIZE_EMERGENCY",
    "prioritize_emergency",
    "emergency_priority",
    # Coordinated green corridor activation
    "ACTIVATE_GREEN_CORRIDOR",
    "activate_green_corridor",
    "green_corridor",
    # Dynamic traffic rerouting
    "REROUTE_TRAFFIC",
    "reroute_traffic",
    # Approved / applied supervisory actions
    "applied",
    "decision_applied",
}

# Signal change change_kind classifications triggering emergency override notifications
EMERGENCY_OVERRIDE_CHANGE_KINDS: set[str] = {
    "override",
    "emergency_override",
    "manual_override",
    "signal_override",
}

# Documented severity gating configuration dictionary
EVENT_NOTIFICATION_CONFIG: dict[str, dict[str, Any]] = {
    INCIDENT_CREATED: {
        "enabled": True,
        "default_severity": "warning",
        "critical_payload_severities": {"high", "critical"},
        "escalated_severity": "error",
        "entity_type": "incident",
        "match_severity_on_dedupe": False,
        "description": "Traffic incident reported; error for high/critical, warning otherwise.",
    },
    INCIDENT_UPDATED: {
        "enabled": True,
        "default_severity": "info",
        "entity_type": "incident",
        "match_severity_on_dedupe": False,
        "description": "Incident status transition; deduped if unread incident alert exists.",
    },
    EMERGENCY_CREATED: {
        "enabled": True,
        "default_severity": "critical",
        "entity_type": "emergency_event",
        "match_severity_on_dedupe": True,
        "description": "Emergency vehicle transit dispatched across the network.",
    },
    EMERGENCY_UPDATED: {
        "enabled": True,
        "default_severity": "info",
        "allowed_statuses": {"resolved", "closed"},
        "entity_type": "emergency_event",
        "match_severity_on_dedupe": True,
        "description": "Emergency event resolved or closed.",
    },
    CONGESTION_CHANGE: {
        "enabled": True,
        "default_severity": "warning",
        "min_severe_level": 76,  # >75%
        "entity_type": "junction",
        "match_severity_on_dedupe": True,
        "description": "Severe congestion alert; gated to 1 per junction per 15 min via Redis.",
    },
    CONTROL_DECISION: {
        "enabled": True,
        "default_severity": "info",
        "entity_type": "control_decision",
        "match_severity_on_dedupe": True,
        "description": "Operationally significant supervisory control recommendations or applied decisions.",
    },
    SIGNAL_CHANGE: {
        "enabled": True,
        "default_severity": "warning",
        "allowed_change_kinds": EMERGENCY_OVERRIDE_CHANGE_KINDS,
        "entity_type": "signal",
        "match_severity_on_dedupe": True,
        "description": "Routine phase changes ignored; emergency manual overrides generate warnings.",
    },
    PREDICTION_PUBLISHED: {
        "enabled": False,
        "description": "High-frequency forecast batch; dashboards pull on demand without push alert.",
    },
    NOTIFICATION_CREATED: {
        "enabled": False,
        "description": "Hard recursion guard; notification creation events NEVER trigger notifications.",
    },
    TRAFFIC_UPDATE: {
        "enabled": False,
        "description": "Raw telemetry batch ingest; no operator notification.",
    },
    SYSTEM_STATUS: {
        "enabled": False,
        "description": "Service heartbeat and lifecycle status; no operator alert.",
    },
}


def _get_bus() -> EventBus:
    """Retrieve the global EventBus singleton."""
    from app.realtime import get_bus

    return get_bus()


async def is_duplicate_unread_notification(
    db: AsyncSession,
    *,
    entity_type: Optional[str],
    entity_id: Optional[int],
    severity: Optional[str] = None,
    window_seconds: int = DEFAULT_DEDUPE_WINDOW_SECONDS,
    match_severity: bool = False,
) -> bool:
    """Check for an existing unread notification for the same entity within the dedupe window.

    Guarantees:
    - Single indexed query utilizing composite index `ix_notifications_entity_dedupe`.
    - No N+1 queries.
    - Timezone-aware timestamp comparison.
    """
    if not entity_type or entity_id is None:
        return False

    cutoff = datetime.now(timezone.utc) - timedelta(seconds=window_seconds)

    stmt = select(Notification.id).where(
        Notification.entity_type == entity_type,
        Notification.entity_id == entity_id,
        Notification.is_read.is_(False),
        Notification.created_at >= cutoff,
    )
    if match_severity and severity is not None:
        stmt = stmt.where(Notification.severity == severity)

    stmt = stmt.limit(1)
    result = await db.execute(stmt)
    return result.scalar_one_or_none() is not None


def evaluate_event_policy(
    envelope: EventEnvelope,
) -> Optional[dict[str, Any]]:
    """Evaluate event against notification policy rules without performing database or Redis I/O.

    Returns:
        dict with keys:
            - title: str
            - message: str
            - severity: str
            - entity_type: str
            - entity_id: int
            - match_severity_on_dedupe: bool
            - is_congestion: bool
        or None if no notification should be generated.
    """
    event_type = envelope.type

    # 1. Hard recursion guard against infinite loops
    if event_type == NOTIFICATION_CREATED:
        return None

    config = EVENT_NOTIFICATION_CONFIG.get(event_type)
    if not config or not config.get("enabled", False):
        return None

    payload = envelope.payload or {}

    # 2. Incident Created
    if event_type == INCIDENT_CREATED:
        incident_id = payload.get("incident_id")
        if incident_id is None:
            return None

        inc_sev = str(payload.get("severity", "medium")).lower()
        if inc_sev in config.get("critical_payload_severities", {"high", "critical"}):
            severity = config.get("escalated_severity", "error")
        else:
            severity = config.get("default_severity", "warning")

        intersection_id = payload.get("intersection_id")
        status_val = payload.get("status", "reported")
        loc_str = f" at intersection {intersection_id}" if intersection_id is not None else ""

        return {
            "title": f"Traffic Incident #{incident_id} ({inc_sev.upper()})",
            "message": f"Incident #{incident_id} reported{loc_str} (status: {status_val}, severity: {inc_sev}).",
            "severity": severity,
            "entity_type": "incident",
            "entity_id": int(incident_id),
            "match_severity_on_dedupe": config.get("match_severity_on_dedupe", False),
            "is_congestion": False,
        }

    # 3. Incident Updated
    if event_type == INCIDENT_UPDATED:
        incident_id = payload.get("incident_id")
        if incident_id is None:
            return None

        old_status = payload.get("old_status", "unknown")
        new_status = payload.get("new_status", "unknown")

        return {
            "title": f"Incident #{incident_id} Status: {new_status}",
            "message": f"Incident #{incident_id} status changed from '{old_status}' to '{new_status}'.",
            "severity": config.get("default_severity", "info"),
            "entity_type": "incident",
            "entity_id": int(incident_id),
            "match_severity_on_dedupe": config.get("match_severity_on_dedupe", False),
            "is_congestion": False,
        }

    # 4. Emergency Created
    if event_type == EMERGENCY_CREATED:
        event_id = payload.get("event_id")
        if event_id is None:
            return None

        priority = payload.get("priority", 1)
        vehicle_type = payload.get("vehicle_type", "emergency")
        status_val = payload.get("status", "dispatched")

        return {
            "title": f"Emergency Transit #{event_id}",
            "message": f"Emergency vehicle transit #{event_id} ({vehicle_type}, priority {priority}) active (status: {status_val}).",
            "severity": "critical",
            "entity_type": "emergency_event",
            "entity_id": int(event_id),
            "match_severity_on_dedupe": True,
            "is_congestion": False,
        }

    # 5. Emergency Updated (resolved/closed only)
    if event_type == EMERGENCY_UPDATED:
        event_id = payload.get("event_id")
        if event_id is None:
            return None

        new_status = str(payload.get("new_status") or payload.get("status") or "").lower()
        allowed_statuses = config.get("allowed_statuses", {"resolved", "closed"})
        if new_status not in allowed_statuses:
            return None

        return {
            "title": f"Emergency #{event_id} Resolved",
            "message": f"Emergency vehicle transit #{event_id} has been {new_status}.",
            "severity": "info",
            "entity_type": "emergency_event",
            "entity_id": int(event_id),
            "match_severity_on_dedupe": True,
            "is_congestion": False,
        }

    # 6. Congestion Change (severe band only)
    if event_type == CONGESTION_CHANGE:
        junction_id = payload.get("junction_id")
        if junction_id is None:
            return None

        congestion_level = payload.get("congestion_level")
        if congestion_level is None:
            return None

        try:
            c_int = int(congestion_level)
        except (ValueError, TypeError):
            return None

        # Check severe band (>75%)
        if c_int <= CONGESTION_SEVERE_THRESHOLD:
            return None

        return {
            "title": f"Severe Congestion: Junction {junction_id}",
            "message": f"Severe congestion detected at junction {junction_id} ({c_int}%).",
            "severity": "warning",
            "entity_type": "junction",
            "entity_id": int(junction_id),
            "match_severity_on_dedupe": True,
            "is_congestion": True,
        }

    # 7. Control Decision (operationally significant only)
    if event_type == CONTROL_DECISION:
        decision_id = payload.get("decision_id")
        decision_type = str(payload.get("decision_type", ""))
        summary = str(payload.get("summary", ""))
        junction_id = payload.get("junction_id")

        is_significant = (
            decision_type in OPERATIONALLY_SIGNIFICANT_DECISION_TYPES
            or decision_type.upper() in OPERATIONALLY_SIGNIFICANT_DECISION_TYPES
            or "applied" in decision_type.lower()
            or "applied" in summary.lower()
            or "emergency" in decision_type.lower()
            or "corridor" in decision_type.lower()
            or "reroute" in decision_type.lower()
        )
        if not is_significant:
            return None

        entity_id = int(decision_id) if decision_id is not None else (int(junction_id) if junction_id is not None else 0)
        loc_str = f" at junction {junction_id}" if junction_id is not None else ""

        return {
            "title": f"Control Decision: {decision_type}",
            "message": summary or f"Operational supervisory control decision '{decision_type}' issued{loc_str}.",
            "severity": "info",
            "entity_type": "control_decision",
            "entity_id": entity_id,
            "match_severity_on_dedupe": True,
            "is_congestion": False,
        }

    # 8. Signal Change (emergency overrides only)
    if event_type == SIGNAL_CHANGE:
        signal_id = payload.get("signal_id")
        if signal_id is None:
            return None

        change_kind = str(payload.get("change_kind", "")).lower()
        is_override = (
            change_kind in EMERGENCY_OVERRIDE_CHANGE_KINDS
            or "override" in change_kind
            or "emergency" in change_kind
        )
        if not is_override:
            # Routine signal changes are filtered out to prevent alert fatigue
            return None

        intersection_id = payload.get("intersection_id")
        loc_str = f" at intersection {intersection_id}" if intersection_id is not None else ""

        return {
            "title": f"Signal #{signal_id} Emergency Override",
            "message": f"Manual emergency override executed for signal #{signal_id}{loc_str}.",
            "severity": "warning",
            "entity_type": "signal",
            "entity_id": int(signal_id),
            "match_severity_on_dedupe": True,
            "is_congestion": False,
        }

    return None


async def _check_congestion_redis_gate(junction_id: int) -> bool:
    """Check and set Redis 15-min dedupe key for severe congestion alert.

    Returns:
        True if this is a NEW alert within the window (allowed to proceed).
        False if an alert was already triggered within the last 15 minutes (suppressed).
    """
    bus = _get_bus()
    if bus.is_degraded or not bus.is_connected or bus._redis is None:
        # Fall back gracefully to database-level deduplication
        return True

    redis_key = f"{CONGESTION_REDIS_KEY_PREFIX}{junction_id}"
    try:
        is_new = await bus._redis.set(
            redis_key,
            "1",
            nx=True,
            ex=CONGESTION_NOTIFY_TTL_SECONDS,
        )
        return bool(is_new)
    except Exception as exc:
        logger.warning("Error checking Redis congestion dedupe key %s: %s", redis_key, exc)
        return True


async def maybe_notify_for_event(
    envelope: EventEnvelope,
    db: Optional[AsyncSession] = None,
) -> Optional[Notification]:
    """Evaluate an EventEnvelope against notification policies and create a Notification if warranted.

    Guarantees:
    - Never raises exceptions; logs errors fail-safely without interrupting event production.
    - Emits system-wide broadcast (user_id=None) across operators.
    - Dedupes against unread notifications for the same entity within 15 minutes.
    - Enforces 15-minute Redis key gate for severe congestion.
    - Delegates to `create_notification` to guarantee exactly-once persistence and
      exactly-once real-time `notification.created` emission over WebSocket.
    - Explicit infinite loop guard against `notification.created` recursion.

    Args:
        envelope: Canonical EventEnvelope describing the domain event.
        db: Optional active SQLAlchemy AsyncSession. If omitted, opens and manages
            a dedicated session via AsyncSessionLocal.

    Returns:
        The created Notification instance, or None if skipped by policy or dedupe.
    """
    try:
        policy = evaluate_event_policy(envelope)
        if policy is None:
            return None

        # Congestion 15-minute Redis TTL gate
        if policy.get("is_congestion"):
            is_new = await _check_congestion_redis_gate(policy["entity_id"])
            if not is_new:
                logger.info(
                    "Severe congestion alert for junction %d suppressed by 15-min Redis gate",
                    policy["entity_id"],
                )
                return None

        # Database deduplication check & notification creation
        if db is not None:
            return await _create_notification_if_unique(db, policy)

        async with AsyncSessionLocal() as session:
            return await _create_notification_if_unique(session, policy)

    except Exception as exc:
        logger.error(
            "Unexpected error in maybe_notify_for_event for event %s (id: %s): %s",
            envelope.type,
            envelope.event_id,
            exc,
            exc_info=True,
        )
        return None


async def _create_notification_if_unique(
    db: AsyncSession,
    policy: dict[str, Any],
) -> Optional[Notification]:
    """Execute deduplication check and invoke create_notification."""
    from app.api.v1.notifications import create_notification

    is_duplicate = await is_duplicate_unread_notification(
        db,
        entity_type=policy["entity_type"],
        entity_id=policy["entity_id"],
        severity=policy["severity"],
        match_severity=policy["match_severity_on_dedupe"],
    )
    if is_duplicate:
        logger.info(
            "Notification for %s #%d (%s) suppressed by DB unread dedupe query",
            policy["entity_type"],
            policy["entity_id"],
            policy["severity"],
        )
        return None

    notification = await create_notification(
        db=db,
        user_id=None,  # System-wide operational broadcast
        title=policy["title"],
        message=policy["message"],
        severity=policy["severity"],
        entity_type=policy["entity_type"],
        entity_id=policy["entity_id"],
        audit_action="notification.system_alert",
        audit_details={
            "source_entity": policy["entity_type"],
            "source_id": policy["entity_id"],
            "severity": policy["severity"],
        },
    )

    logger.info(
        "Created operational notification #%d (%s) for %s #%d",
        notification.id,
        notification.severity,
        policy["entity_type"],
        policy["entity_id"],
    )
    return notification
