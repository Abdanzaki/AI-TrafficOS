"""Comprehensive unit and integration test suite for Phase 9 Real-Time WebSocket Streaming API.

Covers:
- Query-parameter JWT authentication (?token=...)
- Immediate rejection (close code 4401) on missing, garbage, or expired tokens
- Near-expiry rejection (<60s remaining lifetime) with JSON close reason
- Mid-connection token expiry watchdog (auth.expired message and close 4401)
- Handshake payload (connection.established, allowed event types, heartbeat interval, role)
- Deprecated aliases (/api/v1/ws and /ws) with deprecation notes
- Client control messages: ping/pong, subscribe, unsubscribe, and error handling
- Role-based event filtering (ROLE_EVENT_ALLOWLIST) and payload sanitization for analysts
- Deduplication suppression (BoundedDedupeSet)
- Backpressure queue overflow and stale notification
- Reconnect resync with valid and trimmed/bogus last_event_id
- Connection registry and leak-free lifecycle cleanup
"""

import asyncio
from datetime import datetime, timedelta, timezone
import json
import time
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.core.security import create_access_token, create_refresh_token
from app.main import create_app
from app.realtime import (
    ALL_EVENT_TYPES,
    CONGESTION_CHANGE,
    CONTROL_DECISION,
    EMERGENCY_CREATED,
    EventBus,
    EventEnvelope,
    INCIDENT_CREATED,
    NOTIFICATION_CREATED,
    ROLE_EVENT_ALLOWLIST,
    TRAFFIC_UPDATE,
    BoundedDedupeSet,
    StreamConnection,
    StreamConnectionManager,
    get_bus,
    sanitize_payload_for_analyst,
    stream_manager,
)


def _make_token(user_id: int = 1, role: str = "admin", delta_seconds: float = 3600) -> str:
    """Helper to generate JWT access token with custom expiry."""
    return create_access_token(
        user_id=user_id,
        role=role,
        expires_delta=timedelta(seconds=delta_seconds),
    )


def test_auth_missing_token_rejected() -> None:
    """Connecting to /ws/v1/stream without a token must close with code 4401."""
    app = create_app()
    client = TestClient(app)
    with pytest.raises(WebSocketDisconnect) as excinfo:
        with client.websocket_connect("/ws/v1/stream"):
            pass
    assert excinfo.value.code == 4401


def test_auth_garbage_token_rejected() -> None:
    """Connecting with an invalid / garbage token must close with code 4401."""
    app = create_app()
    client = TestClient(app)
    with pytest.raises(WebSocketDisconnect) as excinfo:
        with client.websocket_connect("/ws/v1/stream?token=invalid.garbage.token"):
            pass
    assert excinfo.value.code == 4401


def test_auth_expired_token_rejected() -> None:
    """Connecting with an already expired token must close with code 4401."""
    token = _make_token(user_id=1, role="admin", delta_seconds=-10)
    app = create_app()
    client = TestClient(app)
    with pytest.raises(WebSocketDisconnect) as excinfo:
        with client.websocket_connect(f"/ws/v1/stream?token={token}"):
            pass
    assert excinfo.value.code == 4401


def test_auth_refresh_token_rejected() -> None:
    """Connecting with a refresh token instead of access token must close with code 4401."""
    refresh_token = create_refresh_token(user_id=1)
    app = create_app()
    client = TestClient(app)
    with pytest.raises(WebSocketDisconnect) as excinfo:
        with client.websocket_connect(f"/ws/v1/stream?token={refresh_token}"):
            pass
    assert excinfo.value.code == 4401


def test_auth_short_lived_token_rejected_under_60s() -> None:
    """Tokens with <60s remaining lifetime must be rejected with code 4401."""
    token = _make_token(user_id=1, role="admin", delta_seconds=30)
    app = create_app()
    client = TestClient(app)
    with pytest.raises(WebSocketDisconnect) as excinfo:
        with client.websocket_connect(f"/ws/v1/stream?token={token}"):
            pass
    assert excinfo.value.code == 4401


def test_handshake_admin_role() -> None:
    """Valid admin connection receives connection.established with all event types."""
    token = _make_token(user_id=1, role="admin", delta_seconds=3600)
    app = create_app()
    client = TestClient(app)
    with client.websocket_connect(f"/ws/v1/stream?token={token}") as ws:
        msg = ws.receive_json()
        assert msg["type"] == "connection.established"
        assert msg["role"] == "admin"
        assert msg["heartbeat_interval_ms"] == 25000
        assert set(msg["event_types"]) == set(ALL_EVENT_TYPES)
        assert "server_time" in msg


def test_handshake_analyst_role_filtered() -> None:
    """Analyst handshake receives restricted event types list (no PII or emergency events)."""
    token = _make_token(user_id=2, role="analyst", delta_seconds=3600)
    app = create_app()
    client = TestClient(app)
    with client.websocket_connect(f"/ws/v1/stream?token={token}") as ws:
        msg = ws.receive_json()
        assert msg["type"] == "connection.established"
        assert msg["role"] == "analyst"
        assert set(msg["event_types"]) == ROLE_EVENT_ALLOWLIST["analyst"]
        assert NOTIFICATION_CREATED not in msg["event_types"]
        assert EMERGENCY_CREATED not in msg["event_types"]


def test_deprecated_v1_alias_with_token() -> None:
    """Connecting to /api/v1/ws with token returns deprecated note and full stream capability."""
    token = _make_token(user_id=1, role="admin", delta_seconds=3600)
    app = create_app()
    client = TestClient(app)
    with client.websocket_connect(f"/api/v1/ws?token={token}") as ws:
        msg = ws.receive_json()
        assert msg["type"] == "connection.established"
        assert msg.get("deprecated") is True
        assert "Use /ws/v1/stream" in msg.get("note", "")


def test_client_ping_pong_control_message() -> None:
    """Client sending {'type': 'ping'} receives {'type': 'pong', 'server_time': ...}."""
    token = _make_token(user_id=1, role="admin", delta_seconds=3600)
    app = create_app()
    client = TestClient(app)
    with client.websocket_connect(f"/ws/v1/stream?token={token}") as ws:
        ws.receive_json()  # Handshake
        ws.send_json({"type": "ping"})
        reply = ws.receive_json()
        assert reply["type"] == "pong"
        assert "server_time" in reply


def test_client_subscribe_and_unsubscribe() -> None:
    """Client can dynamically subscribe and unsubscribe to allowed event types."""
    token = _make_token(user_id=1, role="admin", delta_seconds=3600)
    app = create_app()
    client = TestClient(app)
    with client.websocket_connect(f"/ws/v1/stream?token={token}") as ws:
        ws.receive_json()  # Handshake

        # Unsubscribe from congestion.change
        ws.send_json({"type": "unsubscribe", "event_types": [CONGESTION_CHANGE]})
        resp = ws.receive_json()
        assert resp["type"] == "subscription.updated"
        assert CONGESTION_CHANGE not in resp["event_types"]

        # Resubscribe
        ws.send_json({"type": "subscribe", "event_types": [CONGESTION_CHANGE]})
        resp2 = ws.receive_json()
        assert resp2["type"] == "subscription.updated"
        assert CONGESTION_CHANGE in resp2["event_types"]


def test_client_subscribe_unknown_and_forbidden_type() -> None:
    """Subscribing to unknown or role-forbidden event type returns error message."""
    token_analyst = _make_token(user_id=2, role="analyst", delta_seconds=3600)
    app = create_app()
    client = TestClient(app)
    with client.websocket_connect(f"/ws/v1/stream?token={token_analyst}") as ws:
        ws.receive_json()  # Handshake

        # Unknown type
        ws.send_json({"type": "subscribe", "event_types": ["bogus.event.type"]})
        err1 = ws.receive_json()
        assert err1["type"] == "error"
        assert "Unknown event type" in err1["detail"]

        # Forbidden type for analyst (notification.created)
        ws.send_json({"type": "subscribe", "event_types": [NOTIFICATION_CREATED]})
        err2 = ws.receive_json()
        assert err2["type"] == "error"
        assert "not permitted for role 'analyst'" in err2["detail"]


def test_sanitize_payload_for_analyst() -> None:
    """Sensitive operator PII keys are recursively stripped for analysts."""
    raw = {
        "decision_id": "dec-123",
        "action": "extend_green",
        "operator": "officer_bob",
        "operator_email": "bob@trafficos.io",
        "user_id": 42,
        "nested": {
            "internal_notes": "tactical plan",
            "score": 0.95,
        },
    }
    sanitized = sanitize_payload_for_analyst(raw)
    assert sanitized["decision_id"] == "dec-123"
    assert sanitized["action"] == "extend_green"
    assert "operator" not in sanitized
    assert "operator_email" not in sanitized
    assert "user_id" not in sanitized
    assert sanitized["nested"] == {"score": 0.95}


def test_bounded_dedupe_set() -> None:
    """BoundedDedupeSet evicts oldest elements when exceeding maxsize."""
    dedupe = BoundedDedupeSet(maxsize=3)
    id1, id2, id3, id4 = str(uuid4()), str(uuid4()), str(uuid4()), str(uuid4())

    assert dedupe.add(id1) is True
    assert dedupe.add(id1) is False  # Already seen
    assert dedupe.is_seen(id1) is True

    assert dedupe.add(id2) is True
    assert dedupe.add(id3) is True
    # Cache now holds id1, id2, id3

    assert dedupe.add(id4) is True
    # id1 should be evicted (FIFO)
    assert dedupe.is_seen(id1) is False
    assert dedupe.is_seen(id2) is True
    assert dedupe.is_seen(id3) is True
    assert dedupe.is_seen(id4) is True


def test_fanout_broadcast_and_role_filtering() -> None:
    """Verify live broadcast dispatch to active connections with role-based filtering."""
    token_admin = _make_token(user_id=1, role="admin", delta_seconds=3600)
    token_analyst = _make_token(user_id=2, role="analyst", delta_seconds=3600)

    app = create_app()
    client = TestClient(app)

    with client.websocket_connect(f"/ws/v1/stream?token={token_admin}") as ws_admin:
        ws_admin.receive_json()  # Handshake

        with client.websocket_connect(f"/ws/v1/stream?token={token_analyst}") as ws_analyst:
            ws_analyst.receive_json()  # Handshake

            # Broadcast traffic.update (allowed for both)
            env_traffic = EventEnvelope(
                type=TRAFFIC_UPDATE,
                payload={"flow": 55},
                source="test-detector",
            )
            stream_manager.broadcast_envelope(env_traffic)

            admin_traffic = ws_admin.receive_json()
            assert admin_traffic["type"] == TRAFFIC_UPDATE
            assert admin_traffic["payload"]["flow"] == 55

            analyst_traffic = ws_analyst.receive_json()
            assert analyst_traffic["type"] == TRAFFIC_UPDATE
            assert analyst_traffic["payload"]["flow"] == 55

            # Broadcast notification.created (forbidden for analyst, allowed for admin)
            env_notif = EventEnvelope(
                type=NOTIFICATION_CREATED,
                payload={"operator_email": "admin@trafficos.io", "alert": "critical"},
                source="test-alerts",
            )
            stream_manager.broadcast_envelope(env_notif)

            admin_notif = ws_admin.receive_json()
            assert admin_notif["type"] == NOTIFICATION_CREATED

            # Broadcast control.decision with PII
            env_decision = EventEnvelope(
                type=CONTROL_DECISION,
                payload={"action": "hold", "operator_email": "secret@trafficos.io"},
                source="control-engine",
            )
            stream_manager.broadcast_envelope(env_decision)

            admin_dec = ws_admin.receive_json()
            assert admin_dec["payload"]["operator_email"] == "secret@trafficos.io"

            # Analyst receives decision WITHOUT operator_email
            analyst_dec = ws_analyst.receive_json()
            assert analyst_dec["type"] == CONTROL_DECISION
            assert analyst_dec["payload"]["action"] == "hold"
            assert "operator_email" not in analyst_dec["payload"]


def test_watchdog_triggers_auth_expired() -> None:
    """Watchdog task monitors token expiry and terminates connection with 4401."""

    async def _run() -> None:
        mock_ws = AsyncMock()
        conn = StreamConnection("test_watchdog", mock_ws, "1", "admin", datetime.now(timezone.utc).timestamp())
        # Run watchdog with short 0.05s delay
        await conn.run_watchdog(0.05)
        assert conn.closed is True
        mock_ws.send_json.assert_awaited_once_with({
            "type": "auth.expired",
            "message": "Access token has expired; refresh credentials and reconnect",
        })
        mock_ws.close.assert_awaited_once_with(code=4401, reason="Token expired")

    asyncio.run(_run())


def test_backpressure_queue_overflow_and_stale() -> None:
    """When client queue overflows past dropped threshold, sends stale notice and resets."""

    async def _run() -> None:
        mock_ws = AsyncMock()
        conn = StreamConnection("test_backpressure", mock_ws, "1", "admin", datetime.now(timezone.utc).timestamp() + 3600)
        conn.dropped_threshold = 5  # Lower threshold for fast test

        # Fill queue to maxsize (100)
        for i in range(100):
            conn.enqueue(EventEnvelope(type=TRAFFIC_UPDATE, payload={"i": i}, source="test"))

        # Push 5 more items to exceed dropped_threshold
        for i in range(5):
            conn.enqueue(EventEnvelope(type=TRAFFIC_UPDATE, payload={"overflow": i}, source="test"))

        # Launch sender task briefly
        conn.sender_task = asyncio.create_task(conn.run_sender())
        await asyncio.sleep(0.05)
        conn.close()
        try:
            await conn.sender_task
        except asyncio.CancelledError:
            pass

        # Verify stale message was sent
        mock_ws.send_json.assert_awaited_with({
            "type": "stale",
            "message": "client fell behind; refetch via REST",
        })

    asyncio.run(_run())


def test_reconnect_resync_stream_replay() -> None:
    """Verify handle_resync replays missed envelopes and handles stale / bogus event IDs."""

    async def _run() -> None:
        test_id = uuid4().hex[:8]
        stream_key = f"trafficos:events:ws_resync_{test_id}"
        bus = EventBus(redis_url="redis://localhost:6379/0", stream_key=stream_key)
        await bus.connect()

        try:
            e1 = await bus.publish(TRAFFIC_UPDATE, {"flow": 10}, "test")
            e2 = await bus.publish(CONGESTION_CHANGE, {"level": "med"}, "test")

            mock_ws = AsyncMock()
            conn = StreamConnection("test_resync", mock_ws, "1", "admin", datetime.now(timezone.utc).timestamp() + 3600)

            # Replay since e1 -> should yield e2 + resync.complete
            await stream_manager.handle_resync(conn, str(e1.event_id), bus)

            sent_calls = [c.args[0] for c in mock_ws.send_json.call_args_list]
            assert len(sent_calls) == 2
            assert sent_calls[0]["event_id"] == str(e2.event_id)
            assert sent_calls[0]["type"] == CONGESTION_CHANGE
            assert sent_calls[1]["type"] == "resync.complete"
            assert sent_calls[1]["replayed"] == 1

            # Bogus / trimmed event ID -> stale message
            mock_ws.reset_mock()
            await stream_manager.handle_resync(conn, str(uuid4()), bus)
            stale_call = mock_ws.send_json.call_args[0][0]
            assert stale_call["type"] == "stale"
            assert "event history unavailable" in stale_call["message"]

        finally:
            if bus._redis is not None:
                await bus._redis.delete(stream_key)
                await bus._redis.delete(f"{bus.DEDUPE_KEY_PREFIX}{e1.event_id}")
                await bus._redis.delete(f"{bus.DEDUPE_KEY_PREFIX}{e2.event_id}")
            await bus.close()

    asyncio.run(_run())


def test_connection_registry_lifecycle() -> None:
    """Verify register and unregister cleanly track active counts without leaking."""

    async def _run() -> None:
        mgr = StreamConnectionManager()
        assert mgr.active_connections_count == 0

        mock_ws = AsyncMock()
        conn = StreamConnection("c1", mock_ws, "1", "admin", time.time() + 3600)
        await mgr.register(conn)
        assert mgr.active_connections_count == 1

        await mgr.unregister("c1")
        assert mgr.active_connections_count == 0
        assert conn.closed is True

    asyncio.run(_run())
