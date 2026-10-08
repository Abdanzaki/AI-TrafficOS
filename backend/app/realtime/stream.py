"""Real-time WebSocket streaming manager, backpressure queues, and fan-out engine.

Architecture & Design Decisions
-------------------------------
1. WebSocket Authentication Strategy: Query Parameter (?token=<jwt>)
   - Browser WebSocket Limitation: Standard browser JavaScript `new WebSocket(url)`
     does not support custom HTTP request headers (such as `Authorization: Bearer <token>`).
   - Subprotocol Alternative Evaluated: Sec-WebSocket-Protocol (e.g. ['access_token', '<jwt>'])
     was considered and rejected because:
     a) RFC 6455 defines subprotocols for application protocol negotiation (e.g. 'soap', 'wamp'),
        not identity verification or credential transport.
     b) JWT tokens contain dots, hyphens, and URL-safe characters that violate strict token
        grammars in certain reverse proxies and legacy browser WebSocket implementations.
     c) The server must echo back the selected subprotocol in the HTTP 101 response, leaking
        credentials into the handshake response headers.
     d) Client SDKs across web, mobile (React Native / Flutter), and automated agents have
        inconsistent support for dynamic subprotocol headers.
   - Decision: Query parameter `?token=<access_token>` is universally supported across all
     browser environments and native client platforms. Over TLS (WSS / HTTPS), query strings
     are encrypted on the wire. Tokens are verified before accepting the connection, and
     access loggers are configured not to log credentials.

2. Deprecated Legacy Route Strategy (/api/v1/ws and /ws)
   - Phase 1 skeletons accepted connections and immediately closed with a static handshake.
   - To prevent regressions for earlier phases (such as Phase 7 web dashboard components
     or automated regression test suites), `/api/v1/ws` and `/ws` are maintained as
     deprecated aliases.
   - When called without a token, legacy endpoints emit the Phase 1 compatibility handshake
     and close politely (code 1000).
   - When called with an authenticated token, they forward to the real-time Phase 9 engine
     while annotating the connection handshake with `"deprecated": True`.

3. Role-Based Access Control (RBAC) & Per-Role Event Filtering
   - admin: Unrestricted access to all real-time events.
   - traffic_officer: Full operational access to real-time telemetry, incidents, signal changes,
     emergency vehicle dispatch, and operator notifications.
   - analyst: Read-only intelligence and planning role.
     * Restricted: 'notification.created' (contains direct operator alerts and staff assignments),
       'emergency.created' and 'emergency.updated' (contain confidential first-responder dispatch).
     * Permitted: 'traffic.update', 'congestion.change', 'signal.change', 'incident.created',
       'incident.updated', 'prediction.published', 'control.decision', 'system.status'.
     * Sanitization: Payload fields containing operator PII or internal identities
       (e.g., 'operator', 'operator_email', 'user_id', 'reporter_email') are stripped before
       delivery to analyst connections.

4. Fan-Out & Backpressure Architecture
   - One shared Redis Pub/Sub subscriber task per app process (started during lifespan)
     reads from `bus.subscribe()` and distributes envelopes to active connections.
   - Each connection maintains an independent bounded `asyncio.Queue(maxsize=100)`.
   - If a slow client queue fills up, the oldest item is discarded and a drop counter increments.
   - If dropped messages exceed 50, a stale warning `{"type":"stale","message":"client fell behind; refetch via REST"}`
     is dispatched and the queue is reset.
   - No blocking calls exist in the hot path.
"""

import asyncio
from collections import OrderedDict
from datetime import datetime, timezone
import json
import logging
import time
from typing import Any, Optional, Union
from uuid import UUID

from fastapi import WebSocket, WebSocketDisconnect
import jwt

from app.core.logging import get_logger
from app.core.security import decode_token
from app.realtime.bus import EventBus
from app.realtime.events import (
    ALL_EVENT_TYPES,
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

logger = get_logger(__name__)

# Canonical Role-Based Event Allowlist Matrix
# Defines which event types each authenticated role is authorized to subscribe to.
ROLE_EVENT_ALLOWLIST: dict[str, set[str]] = {
    "admin": set(ALL_EVENT_TYPES),
    "traffic_officer": set(ALL_EVENT_TYPES),
    "analyst": {
        TRAFFIC_UPDATE,
        CONGESTION_CHANGE,
        SIGNAL_CHANGE,
        INCIDENT_CREATED,
        INCIDENT_UPDATED,
        PREDICTION_PUBLISHED,
        CONTROL_DECISION,
        SYSTEM_STATUS,
    },
}

# Sensitive keys to strip from deltas before transmission to read-only analysts
SENSITIVE_PAYLOAD_KEYS: set[str] = {
    "operator",
    "operator_email",
    "operator_id",
    "email",
    "user_id",
    "reporter_email",
    "reporter_id",
    "responder",
    "responder_id",
    "phone",
    "contact",
    "internal_notes",
    "notes",
}

# Sentinel object indicating backpressure threshold exceeded and client is stale
_STALE_SENTINEL = object()


def sanitize_payload_for_analyst(payload: Any) -> Any:
    """Recursively sanitize delta payloads for read-only analysts by stripping operator PII."""
    if not isinstance(payload, dict):
        return payload
    sanitized: dict[str, Any] = {}
    for key, value in payload.items():
        if key in SENSITIVE_PAYLOAD_KEYS:
            continue
        if isinstance(value, dict):
            sanitized[key] = sanitize_payload_for_analyst(value)
        elif isinstance(value, list):
            sanitized[key] = [
                sanitize_payload_for_analyst(item) if isinstance(item, dict) else item
                for item in value
            ]
        else:
            sanitized[key] = value
    return sanitized


class BoundedDedupeSet:
    """FIFO bounded set of up to maxsize event IDs to prevent duplicate delivery."""

    def __init__(self, maxsize: int = 1000) -> None:
        self.maxsize = maxsize
        self._items: OrderedDict[str, None] = OrderedDict()

    def is_seen(self, event_id: Union[str, UUID]) -> bool:
        """Check if an event_id is present in the cache."""
        return str(event_id) in self._items

    def add(self, event_id: Union[str, UUID]) -> bool:
        """Add an event_id. Returns True if newly added, False if already present."""
        key = str(event_id)
        if key in self._items:
            return False
        if len(self._items) >= self.maxsize:
            self._items.popitem(last=False)
        self._items[key] = None
        return True

    def clear(self) -> None:
        """Clear all entries."""
        self._items.clear()


class StreamConnection:
    """Encapsulates an active client WebSocket stream connection, queues, and tasks."""

    def __init__(
        self,
        connection_id: str,
        websocket: WebSocket,
        user_id: str,
        role: str,
        token_exp: float,
        is_deprecated: bool = False,
    ) -> None:
        self.connection_id: str = connection_id
        self.websocket: WebSocket = websocket
        self.user_id: str = user_id
        self.role: str = role
        self.token_exp: float = token_exp
        self.is_deprecated: bool = is_deprecated
        self.connected_at: float = time.monotonic()
        self.last_pong_time: float = time.monotonic()

        # Subscriptions: default to all event types permitted for role
        self.subscribed_types: set[str] = set(ROLE_EVENT_ALLOWLIST.get(self.role, set()))

        # Deduplication cache (last 1000 event IDs)
        self.dedupe_set: BoundedDedupeSet = BoundedDedupeSet(maxsize=1000)

        # Backpressure queue (maxsize 100) and dropped metrics
        self.queue: asyncio.Queue[Any] = asyncio.Queue(maxsize=100)
        self.dropped_count: int = 0
        self.dropped_threshold: int = 50

        # Background task handles
        self.sender_task: Optional[asyncio.Task[None]] = None
        self.watchdog_task: Optional[asyncio.Task[None]] = None
        self.heartbeat_task: Optional[asyncio.Task[None]] = None
        self.closed: bool = False

    def touch_activity(self) -> None:
        """Record receipt of a client message or pong frame."""
        self.last_pong_time = time.monotonic()

    def enqueue(self, envelope: EventEnvelope) -> None:
        """Non-blocking dispatch into client queue with bounded backpressure.

        Drops the oldest item when full, increments dropped_count, and flags
        stale if dropped threshold (50) is reached.
        """
        if self.closed:
            return

        if self.queue.full():
            try:
                self.queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
            self.dropped_count += 1

            if self.dropped_count >= self.dropped_threshold:
                logger.warning(
                    "Connection %s exceeded dropped threshold (%d); resetting queue and sending stale alert",
                    self.connection_id,
                    self.dropped_count,
                )
                while not self.queue.empty():
                    try:
                        self.queue.get_nowait()
                    except asyncio.QueueEmpty:
                        break
                self.dropped_count = 0
                try:
                    self.queue.put_nowait(_STALE_SENTINEL)
                except asyncio.QueueFull:
                    pass
                return

        try:
            self.queue.put_nowait(envelope)
        except asyncio.QueueFull:
            pass

    async def run_sender(self) -> None:
        """Per-connection worker that consumes the queue, filters, and transmits to WebSocket."""
        try:
            while not self.closed:
                item = await self.queue.get()
                if item is _STALE_SENTINEL:
                    await self.websocket.send_json({
                        "type": "stale",
                        "message": "client fell behind; refetch via REST",
                    })
                    continue

                if not isinstance(item, EventEnvelope):
                    try:
                        envelope = EventEnvelope.model_validate(item)
                    except Exception as val_exc:
                        logger.warning("Skipping malformed envelope in sender task: %s", val_exc)
                        continue
                else:
                    envelope = item

                # Subscription and role permission check
                if envelope.type not in self.subscribed_types:
                    continue
                if envelope.type not in ROLE_EVENT_ALLOWLIST.get(self.role, set()):
                    continue

                # Deduplication suppression
                if not self.dedupe_set.add(envelope.event_id):
                    continue

                payload = envelope.payload
                if self.role == "analyst":
                    payload = sanitize_payload_for_analyst(payload)

                out = {
                    "event_id": str(envelope.event_id),
                    "type": envelope.type,
                    "timestamp": envelope.timestamp.isoformat(),
                    "payload": payload,
                    "source": envelope.source,
                }
                await self.websocket.send_json(out)
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.debug("Sender task exception for %s: %s", self.connection_id, exc)

    async def run_watchdog(self, remaining_seconds: float) -> None:
        """Monitors JWT expiration mid-connection and disconnects with 4401 when expired."""
        try:
            if remaining_seconds > 0:
                await asyncio.sleep(remaining_seconds)
            if not self.closed:
                logger.info("Access token expired mid-connection for %s; sending auth.expired", self.connection_id)
                try:
                    await self.websocket.send_json({
                        "type": "auth.expired",
                        "message": "Access token has expired; refresh credentials and reconnect",
                    })
                except Exception:
                    pass
                await self.websocket.close(code=4401, reason="Token expired")
                self.closed = True
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.debug("Watchdog exception for %s: %s", self.connection_id, exc)

    async def run_heartbeat(self) -> None:
        """Sends server ping frame/keepalive every 25s, closing 1001 if no pong in 60s."""
        try:
            while not self.closed:
                await asyncio.sleep(25.0)
                now = time.monotonic()
                if now - self.last_pong_time > 60.0:
                    logger.info("Heartbeat timeout for connection %s (>60s no activity); closing 1001", self.connection_id)
                    await self.websocket.close(code=1001, reason="Heartbeat timeout: no pong within 60s")
                    self.closed = True
                    break

                # Send low-level protocol keepalive ping if supported by underlying protocol
                proto = _extract_ws_protocol(self.websocket)
                if proto and hasattr(proto, "send_keepalive_ping"):
                    try:
                        proto.send_keepalive_ping()
                    except Exception:
                        pass
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.debug("Heartbeat exception for %s: %s", self.connection_id, exc)

    def close(self) -> None:
        """Cancel background tasks and drain queue."""
        self.closed = True
        for task in (self.sender_task, self.watchdog_task, self.heartbeat_task):
            if task and not task.done():
                task.cancel()
        while not self.queue.empty():
            try:
                self.queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        self.dedupe_set.clear()


class StreamConnectionManager:
    """Manages active WebSocket connections, shared Redis pub/sub listener, and fan-out."""

    def __init__(self) -> None:
        self._connections: dict[str, StreamConnection] = {}
        self._lock: asyncio.Lock = asyncio.Lock()
        self._fanout_task: Optional[asyncio.Task[None]] = None

    @property
    def active_connections_count(self) -> int:
        """Return the number of currently active WebSocket connections."""
        return len(self._connections)

    async def register(self, connection: StreamConnection) -> None:
        """Register a new active client connection and launch per-connection worker tasks."""
        async with self._lock:
            self._connections[connection.connection_id] = connection
            logger.info(
                "Registered WebSocket connection %s (user=%s, role=%s, active=%d)",
                connection.connection_id,
                connection.user_id,
                connection.role,
                len(self._connections),
            )

    async def unregister(self, connection_id: str) -> None:
        """Unregister a disconnected connection and clean up resources without leaks."""
        async with self._lock:
            conn = self._connections.pop(connection_id, None)
            if conn:
                conn.close()
                logger.info(
                    "Unregistered WebSocket connection %s (remaining active=%d)",
                    connection_id,
                    len(self._connections),
                )

    def broadcast_envelope(self, envelope: EventEnvelope) -> None:
        """Synchronously enqueue envelope to all active connections.

        Hot path: No async blocking calls, no locks held, O(1) queue put per client.
        """
        if not isinstance(envelope, EventEnvelope):
            try:
                envelope = EventEnvelope.model_validate(envelope)
            except Exception as exc:
                logger.warning("Dropping malformed envelope during fan-out: %s", exc)
                return

        for conn in list(self._connections.values()):
            conn.enqueue(envelope)

    async def handle_resync(
        self,
        conn: StreamConnection,
        last_event_id: Union[str, UUID],
        bus: EventBus,
    ) -> None:
        """Replay missed events from Redis Stream since last_event_id."""
        events, stale = await bus.read_since(last_event_id)
        if stale:
            await conn.websocket.send_json({
                "type": "stale",
                "message": "event history unavailable; refetch state via REST",
            })
            return

        replayed_count = 0
        for env in events:
            if env.type not in conn.subscribed_types:
                continue
            if env.type not in ROLE_EVENT_ALLOWLIST.get(conn.role, set()):
                continue
            if not conn.dedupe_set.add(env.event_id):
                continue

            payload = env.payload
            if conn.role == "analyst":
                payload = sanitize_payload_for_analyst(payload)

            await conn.websocket.send_json({
                "event_id": str(env.event_id),
                "type": env.type,
                "timestamp": env.timestamp.isoformat(),
                "payload": payload,
                "source": env.source,
            })
            replayed_count += 1

        await conn.websocket.send_json({
            "type": "resync.complete",
            "replayed": replayed_count,
        })

    async def run_fanout(self, bus: EventBus) -> None:
        """Shared background subscriber task consuming live events from EventBus."""
        logger.info("Shared Redis Pub/Sub fan-out listener started")
        while True:
            try:
                if bus.is_degraded or not bus.is_connected:
                    await bus.connect()
                    if bus.is_degraded:
                        await asyncio.sleep(2.0)
                        continue

                async for envelope in bus.subscribe():
                    self.broadcast_envelope(envelope)
                    # Stage 5 integration: evaluate event policy and generate notifications fail-safely.
                    # Scheduled as an un-awaited background task so fan-out hot path is never blocked.
                    try:
                        from app.realtime.notify import maybe_notify_for_event

                        asyncio.create_task(maybe_notify_for_event(envelope))
                    except Exception as notify_exc:
                        logger.warning(
                            "Failed to schedule notification check for envelope %s: %s",
                            envelope.event_id,
                            notify_exc,
                        )
            except asyncio.CancelledError:
                logger.info("Shared Redis Pub/Sub fan-out listener cancelled")
                break
            except Exception as exc:
                logger.error("Error in shared Redis fan-out subscription loop: %s", exc)
                await asyncio.sleep(1.0)

    async def close_all(self) -> None:
        """Gracefully close all active client streams during shutdown."""
        async with self._lock:
            for conn in list(self._connections.values()):
                conn.close()
                try:
                    await conn.websocket.close(code=1001, reason="Server shutting down")
                except Exception:
                    pass
            self._connections.clear()


# Global module singleton for the stream manager
stream_manager = StreamConnectionManager()


def _extract_ws_protocol(websocket: WebSocket) -> Any:
    """Safely extract the underlying Uvicorn / SansIO WebSocket protocol handle."""
    try:
        import inspect
        closure = inspect.getclosurevars(websocket._send)
        send_fn = closure.nonlocals.get("send")
        return getattr(send_fn, "__self__", None)
    except Exception:
        return None


async def handle_websocket_stream(
    websocket: WebSocket,
    is_deprecated: bool = False,
    bus: Optional[EventBus] = None,
) -> None:
    """Core WebSocket handler implementing authentication, watchdog, RBAC, and streaming."""
    from app.realtime import get_bus
    resolved_bus = bus or get_bus()

    # 1. Query parameter token extraction
    token = websocket.query_params.get("token")

    # If deprecated legacy route and no token provided, preserve Phase 1 handshake behavior
    if is_deprecated and not token:
        await websocket.accept()
        await websocket.send_json({
            "type": "handshake",
            "status": "connected",
            "note": "Phase 1: no live traffic streams yet",
        })
        await websocket.close(code=1000)
        return

    # Validate token BEFORE accepting connection
    if not token:
        logger.warning("WebSocket handshake rejected: missing token query parameter")
        await websocket.close(
            code=4401,
            reason=json.dumps({"error": "missing_token", "message": "Authentication token required"}),
        )
        return

    try:
        payload = decode_token(token)
    except (jwt.PyJWTError, Exception) as exc:
        logger.warning("WebSocket handshake rejected: invalid or expired token (%s)", exc)
        await websocket.close(
            code=4401,
            reason=json.dumps({"error": "unauthorized", "message": "Invalid or expired token"}),
        )
        return

    if payload.get("type") != "access":
        logger.warning("WebSocket handshake rejected: invalid token type '%s'", payload.get("type"))
        await websocket.close(
            code=4401,
            reason=json.dumps({"error": "invalid_token_type", "message": "Expected access token"}),
        )
        return

    now_ts = datetime.now(timezone.utc).timestamp()
    exp_ts = float(payload.get("exp", 0))
    remaining_seconds = exp_ts - now_ts

    if remaining_seconds < 60:
        logger.warning("WebSocket handshake rejected: token lifetime < 60s (%.1fs remaining)", remaining_seconds)
        await websocket.close(
            code=4401,
            reason=json.dumps({
                "error": "token_expiring_soon",
                "message": "Token expires in less than 60s; refresh before connecting",
            }),
        )
        return

    # 2. Token is valid and has >= 60s remaining lifetime -> Accept connection
    await websocket.accept()

    user_id = str(payload.get("sub", "unknown"))
    role = str(payload.get("role", "analyst"))
    allowed_types = sorted(list(ROLE_EVENT_ALLOWLIST.get(role, set())))

    handshake_payload: dict[str, Any] = {
        "type": "connection.established",
        "event_types": allowed_types,
        "heartbeat_interval_ms": 25000,
        "server_time": datetime.now(timezone.utc).isoformat(),
        "role": role,
    }
    if is_deprecated:
        handshake_payload["deprecated"] = True
        handshake_payload["note"] = "Use /ws/v1/stream instead of deprecated WebSocket alias"

    await websocket.send_json(handshake_payload)

    # 3. Create and register connection object
    import uuid
    conn_id = f"conn_{uuid.uuid4().hex[:12]}"
    conn = StreamConnection(
        connection_id=conn_id,
        websocket=websocket,
        user_id=user_id,
        role=role,
        token_exp=exp_ts,
        is_deprecated=is_deprecated,
    )

    await stream_manager.register(conn)

    # Launch background sender, watchdog, and heartbeat tasks
    conn.sender_task = asyncio.create_task(conn.run_sender())
    conn.watchdog_task = asyncio.create_task(conn.run_watchdog(remaining_seconds))
    conn.heartbeat_task = asyncio.create_task(conn.run_heartbeat())

    # 4. Handle initial resync if ?last_event_id=<uuid> was provided at connect
    initial_last_id = websocket.query_params.get("last_event_id")
    if initial_last_id:
        await stream_manager.handle_resync(conn, initial_last_id, resolved_bus)

    # 5. Client receiver loop: process control messages (subscribe, unsubscribe, ping, resync)
    try:
        while not conn.closed:
            data = await websocket.receive_json()
            conn.touch_activity()
            msg_type = data.get("type")

            if msg_type == "ping":
                await websocket.send_json({
                    "type": "pong",
                    "server_time": datetime.now(timezone.utc).isoformat(),
                })

            elif msg_type == "pong":
                # Pong frame acknowledgement
                pass

            elif msg_type == "subscribe":
                types = data.get("event_types")
                if not isinstance(types, list):
                    await websocket.send_json({
                        "type": "error",
                        "detail": "'event_types' must be a list of event type strings",
                    })
                    continue

                # Validate against known canonical types
                unknown_types = [t for t in types if t not in ALL_EVENT_TYPES]
                if unknown_types:
                    await websocket.send_json({
                        "type": "error",
                        "detail": f"Unknown event type: {unknown_types[0]}",
                    })
                    continue

                # Validate against role allowlist
                role_allowed = ROLE_EVENT_ALLOWLIST.get(role, set())
                forbidden_types = [t for t in types if t not in role_allowed]
                if forbidden_types:
                    await websocket.send_json({
                        "type": "error",
                        "detail": f"Event type '{forbidden_types[0]}' not permitted for role '{role}'",
                    })
                    continue

                conn.subscribed_types.update(types)
                await websocket.send_json({
                    "type": "subscription.updated",
                    "event_types": sorted(list(conn.subscribed_types)),
                })

            elif msg_type == "unsubscribe":
                types = data.get("event_types")
                if not isinstance(types, list):
                    await websocket.send_json({
                        "type": "error",
                        "detail": "'event_types' must be a list of event type strings",
                    })
                    continue

                unknown_types = [t for t in types if t not in ALL_EVENT_TYPES]
                if unknown_types:
                    await websocket.send_json({
                        "type": "error",
                        "detail": f"Unknown event type: {unknown_types[0]}",
                    })
                    continue

                conn.subscribed_types.difference_update(types)
                await websocket.send_json({
                    "type": "subscription.updated",
                    "event_types": sorted(list(conn.subscribed_types)),
                })

            elif msg_type == "resync":
                last_event_id = data.get("last_event_id")
                if not last_event_id:
                    await websocket.send_json({
                        "type": "error",
                        "detail": "Missing 'last_event_id' in resync message",
                    })
                else:
                    await stream_manager.handle_resync(conn, last_event_id, resolved_bus)

            else:
                await websocket.send_json({
                    "type": "error",
                    "detail": f"Unrecognized control message type: '{msg_type}'",
                })

    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.debug("Client receiver ended for %s: %s", conn_id, exc)
    finally:
        await stream_manager.unregister(conn_id)
