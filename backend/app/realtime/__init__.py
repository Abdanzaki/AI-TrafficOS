"""Real-time event streaming and fan-out package for AI TrafficOS.

Architectural Design: Redis Streams vs. Redis Pub/Sub
------------------------------------------------------
AI TrafficOS pairs Redis Streams and Redis Pub/Sub in a dual-channel design:

1. Redis Streams (`trafficos:events`): Durable Replay for Reconnect Resync
   - Redis Streams act as an append-only, sequentially-ordered log with a bounded
     retention policy (~10,000 entries maxlen approximate trim).
   - When a WebSocket client, dashboard, or downstream worker drops connection
     due to network flutter, it can reconnect and call `read_since(last_event_id)`.
   - The bus searches the stream for `last_event_id` and replays all subsequent
     events in strict chronological order.
   - If the client has been disconnected too long and the ID has been trimmed
     from the stream, `read_since` flags `stale=True`, instructing the client
     to perform a full state snapshot refresh from REST endpoints.

2. Redis Pub/Sub (`trafficos:events:pubsub`): Live, Low-Latency Fan-Out
   - Ephemeral broadcast channel that fans out events instantaneously to all
     connected WebSocket workers and processes.
   - Avoids individual consumers having to poll Redis Streams or maintain
     high-overhead consumer groups for connected end-user WebSockets.
   - Memory footprint is near zero on Redis because messages are dispatched
     immediately to subscribed sockets without persistent buffering.

3. Deduplication Guards
   - Every event published has a server-generated UUID4 `event_id`.
   - Redis `SET key val NX EX 3600` ensures duplicate publishes (e.g. from
     retried API requests or worker failover) are idempotent no-ops.

4. Graceful Degradation
   - If Redis is unreachable at startup or crashes during runtime, the EventBus
     enters DEGRADED mode. Publishing becomes a logged no-op and subscriptions
     yield nothing, allowing REST and core API endpoints to remain fully operational.
"""

from typing import Optional

from app.realtime.bus import EventBus
from app.realtime.events import (
    ALL_EVENT_TYPES,
    CONGESTION_CHANGE,
    CONTROL_DECISION,
    EMERGENCY_CREATED,
    EMERGENCY_UPDATED,
    EventEnvelope,
    EventType,
    INCIDENT_CREATED,
    INCIDENT_UPDATED,
    NOTIFICATION_CREATED,
    PREDICTION_PUBLISHED,
    SIGNAL_CHANGE,
    SYSTEM_STATUS,
    TRAFFIC_UPDATE,
)

from app.realtime.stream import (
    ROLE_EVENT_ALLOWLIST,
    BoundedDedupeSet,
    StreamConnection,
    StreamConnectionManager,
    handle_websocket_stream,
    sanitize_payload_for_analyst,
    stream_manager,
)

from app.realtime.hooks import (
    emit_congestion_change,
    emit_control_decision,
    emit_emergency_created,
    emit_emergency_updated,
    emit_incident_created,
    emit_incident_updated,
    emit_notification_created,
    emit_prediction_published,
    emit_signal_change,
    emit_system_status,
    emit_traffic_update,
)

from app.realtime.notify import (
    evaluate_event_policy,
    maybe_notify_for_event,
)

_bus: Optional[EventBus] = None


def get_bus() -> EventBus:
    """Retrieve the global module-level EventBus singleton."""
    global _bus
    if _bus is None:
        _bus = EventBus()
    return _bus


def set_bus(bus: Optional[EventBus]) -> None:
    """Set or reset the global EventBus singleton (useful in test suites)."""
    global _bus
    _bus = bus


__all__ = [
    "EventBus",
    "EventEnvelope",
    "EventType",
    "get_bus",
    "set_bus",
    "TRAFFIC_UPDATE",
    "CONGESTION_CHANGE",
    "SIGNAL_CHANGE",
    "INCIDENT_CREATED",
    "INCIDENT_UPDATED",
    "EMERGENCY_CREATED",
    "EMERGENCY_UPDATED",
    "PREDICTION_PUBLISHED",
    "CONTROL_DECISION",
    "NOTIFICATION_CREATED",
    "SYSTEM_STATUS",
    "ALL_EVENT_TYPES",
    "ROLE_EVENT_ALLOWLIST",
    "BoundedDedupeSet",
    "StreamConnection",
    "StreamConnectionManager",
    "handle_websocket_stream",
    "sanitize_payload_for_analyst",
    "stream_manager",
    "emit_congestion_change",
    "emit_control_decision",
    "emit_emergency_created",
    "emit_emergency_updated",
    "emit_incident_created",
    "emit_incident_updated",
    "emit_notification_created",
    "emit_prediction_published",
    "emit_signal_change",
    "emit_system_status",
    "emit_traffic_update",
    "evaluate_event_policy",
    "maybe_notify_for_event",
]
