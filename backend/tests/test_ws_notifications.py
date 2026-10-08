"""Integration tests for WebSocket notification delivery and deduplication (Phase 9 Stage 6).

Covers:
1. Authenticated WebSocket client receives 'notification.created' when a broadcast notification
   is created via the REST API (/api/v1/notifications/broadcast).
2. Authenticated WebSocket client receives 'notification.created' when a targeted notification
   is created via the REST API (/api/v1/notifications).
3. Per-connection deduplication cache suppression:
   Broadcasting an envelope with the identical event_id twice delivers the event exactly ONCE to
   the WebSocket connection.
4. Role permission gating:
   'notification.created' is delivered to operators/admins, but filtered out for analysts
   per ROLE_EVENT_ALLOWLIST.
"""

from datetime import timedelta
import time
import uuid

import pytest
from starlette.testclient import TestClient

from app.core.database import engine
from app.core.security import create_access_token
from app.main import create_app
from app.realtime import (
    EventEnvelope,
    NOTIFICATION_CREATED,
    stream_manager,
)


@pytest.fixture(autouse=True)
def cleanup_resources():
    """Ensure database connection pool is disposed cleanly."""
    yield
    import asyncio
    asyncio.run(engine.dispose())


def _make_token(user_id: int = 1, role: str = "admin", delta_seconds: float = 3600) -> str:
    """Helper to generate JWT access token with custom expiry."""
    return create_access_token(
        user_id=user_id,
        role=role,
        expires_delta=timedelta(seconds=delta_seconds),
    )


def test_ws_client_receives_notification_created_on_rest_broadcast():
    """Connected admin WS client receives notification.created upon POST /api/v1/notifications/broadcast."""
    app = create_app()
    admin_token = _make_token(user_id=1, role="admin")

    with TestClient(app) as client:
        with client.websocket_connect(f"/ws/v1/stream?token={admin_token}") as ws:
            # Consume handshake
            handshake = ws.receive_json()
            assert handshake["type"] == "connection.established"

            # Create broadcast notification via REST
            tag = uuid.uuid4().hex[:6]
            post_resp = client.post(
                "/api/v1/notifications/broadcast",
                headers={"Authorization": f"Bearer {admin_token}"},
                json={
                    "title": f"Grid Alert {tag}",
                    "message": "Congestion advisory across corridor A",
                    "severity": "warning",
                },
            )
            assert post_resp.status_code == 201, post_resp.text
            notif_id = post_resp.json()["id"]

            # Read broadcast event over WebSocket
            event = ws.receive_json()
            assert event["type"] == NOTIFICATION_CREATED
            assert event["payload"]["notification_id"] == notif_id
            assert event["payload"]["title"] == f"Grid Alert {tag}"
            assert event["payload"]["severity"] == "warning"


def test_ws_client_receives_targeted_notification_on_rest_create():
    """Connected WS client receives notification.created when targeted notification is posted."""
    app = create_app()
    admin_token = _make_token(user_id=1, role="admin")

    with TestClient(app) as client:
        with client.websocket_connect(f"/ws/v1/stream?token={admin_token}") as ws:
            ws.receive_json()  # Handshake

            tag = uuid.uuid4().hex[:6]
            post_resp = client.post(
                "/api/v1/notifications",
                headers={"Authorization": f"Bearer {admin_token}"},
                json={
                    "user_id": 1,
                    "title": f"Direct Alert {tag}",
                    "message": "Shift change briefing",
                    "severity": "info",
                },
            )
            assert post_resp.status_code == 201, post_resp.text
            notif_id = post_resp.json()["id"]

            event = ws.receive_json()
            assert event["type"] == NOTIFICATION_CREATED
            assert event["payload"]["notification_id"] == notif_id
            assert event["payload"]["title"] == f"Direct Alert {tag}"


def test_duplicate_event_id_delivered_once_per_connection():
    """An event with the same event_id broadcast twice is delivered only once to the client."""
    app = create_app()
    admin_token = _make_token(user_id=1, role="admin")

    with TestClient(app) as client:
        with client.websocket_connect(f"/ws/v1/stream?token={admin_token}") as ws:
            ws.receive_json()  # Handshake

            shared_event_id = uuid.uuid4()
            env1 = EventEnvelope(
                event_id=shared_event_id,
                type=NOTIFICATION_CREATED,
                source="test-alerts",
                payload={"notification_id": 1001, "title": "First Arrival", "severity": "info"},
            )
            env2 = EventEnvelope(
                event_id=shared_event_id,
                type=NOTIFICATION_CREATED,
                source="test-alerts",
                payload={"notification_id": 1001, "title": "Duplicate Arrival", "severity": "info"},
            )
            env3 = EventEnvelope(
                event_id=uuid.uuid4(),
                type=NOTIFICATION_CREATED,
                source="test-alerts",
                payload={"notification_id": 1002, "title": "Distinct Alert", "severity": "info"},
            )

            # Broadcast env1 and then duplicate env2
            stream_manager.broadcast_envelope(env1)
            stream_manager.broadcast_envelope(env2)
            # Broadcast distinct env3 as a marker
            stream_manager.broadcast_envelope(env3)

            # First message received is env1
            msg1 = ws.receive_json()
            assert msg1["event_id"] == str(shared_event_id)
            assert msg1["payload"]["title"] == "First Arrival"

            # Second message received MUST be env3 (env2 was suppressed by dedupe cache)
            msg2 = ws.receive_json()
            assert msg2["event_id"] == str(env3.event_id)
            assert msg2["payload"]["title"] == "Distinct Alert"


def test_role_filtering_analyst_cannot_receive_notification_created():
    """Analyst connection does not receive notification.created events due to role restrictions."""
    app = create_app()
    admin_token = _make_token(user_id=1, role="admin")
    analyst_token = _make_token(user_id=2, role="analyst")

    with TestClient(app) as client:
        with client.websocket_connect(f"/ws/v1/stream?token={analyst_token}") as ws_analyst:
            handshake = ws_analyst.receive_json()
            assert NOTIFICATION_CREATED not in handshake["event_types"]

            # Broadcast notification.created directly
            env_notif = EventEnvelope(
                type=NOTIFICATION_CREATED,
                source="test-alerts",
                payload={"notification_id": 2001, "title": "Classified Operational Alert", "severity": "critical"},
            )
            stream_manager.broadcast_envelope(env_notif)

            # Ping/pong to verify connection is alive and hasn't received the notification
            ws_analyst.send_json({"type": "ping"})
            reply = ws_analyst.receive_json()
            assert reply["type"] == "pong", "Expected ping response; notification.created should have been filtered"
