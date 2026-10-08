#!/usr/bin/env python3
"""Smoke verification script for Phase 9 Real-Time WebSocket Streaming API.

Runs end-to-end verification against live uvicorn server at http://127.0.0.1:8000:
(a) login as admin@trafficos.io via POST /api/v1/auth/login to get a JWT,
    connect to ws://127.0.0.1:8000/ws/v1/stream?token=... -> expect connection.established;
(b) connect with garbage token -> expect close code 4401 or pre-accept rejection;
(c) publish an event through the EventBus (import backend.app.realtime) -> expect delivered on socket;
(d) login as an analyst-role user, connect, publish a role-restricted event type ->
    expect it NOT delivered (and an allowed type delivered);
(e) disconnect, publish 2 events, reconnect with ?last_event_id=<id of earlier event> ->
    expect replay of exactly the missed ones + resync.complete;
(f) reconnect with a bogus last_event_id -> expect {"type":"stale"};
(g) send {"type":"ping"} -> expect pong.
"""

import asyncio
import json
from pathlib import Path
import sys
import uuid

import httpx
import websockets

# Add backend to sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = REPO_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.realtime import (
    CONGESTION_CHANGE,
    NOTIFICATION_CREATED,
    SIGNAL_CHANGE,
    TRAFFIC_UPDATE,
    get_bus,
)

BASE_HTTP = "http://127.0.0.1:8000"
BASE_WS = "ws://127.0.0.1:8000"


async def main() -> None:
    print("=" * 70)
    print("PHASE 9 REAL-TIME WEBSOCKET STREAMING VERIFICATION")
    print("=" * 70)

    async with httpx.AsyncClient(base_url=BASE_HTTP, timeout=10.0, trust_env=False) as http_client:
        # Check /health
        print("\n[Step 0] Checking server health...")
        health_resp = await http_client.get("/health")
        assert health_resp.status_code == 200, f"Health check failed: {health_resp.status_code}"
        print(f"  [PASS] /health response: {health_resp.json()}")

        # (a) Login as admin@trafficos.io
        print("\n[Step (a)] Logging in as admin@trafficos.io...")
        admin_login = await http_client.post(
            "/api/v1/auth/login",
            json={"email": "admin@trafficos.io", "password": "adminpassword123"},
        )
        assert admin_login.status_code == 200, f"Admin login failed: {admin_login.text}"
        admin_token = admin_login.json()["access_token"]
        print("  [PASS] Logged in as admin, got JWT access token.")

        # Connect to ws://127.0.0.1:8000/ws/v1/stream?token=...
        print("  Connecting to ws://127.0.0.1:8000/ws/v1/stream?token=...")
        async with websockets.connect(f"{BASE_WS}/ws/v1/stream?token={admin_token}") as ws:
            handshake = json.loads(await ws.recv())
            assert handshake.get("type") == "connection.established", f"Unexpected handshake: {handshake}"
            assert handshake.get("role") == "admin", f"Expected admin role: {handshake}"
            assert handshake.get("heartbeat_interval_ms") == 25000
            print(f"  [PASS] Received connection.established: role={handshake['role']}, events={len(handshake['event_types'])}")

        # (b) Connect with garbage token
        print("\n[Step (b)] Connecting with garbage token...")
        try:
            async with websockets.connect(f"{BASE_WS}/ws/v1/stream?token=garbage.token.here") as ws:
                msg = await ws.recv()
                print(f"  [FAIL] Unexpectedly received message: {msg}")
                sys.exit(1)
        except websockets.exceptions.ConnectionClosed as exc:
            assert exc.code == 4401, f"Expected 4401, got {exc.code}"
            print(f"  [PASS] WebSocket connection closed with code {exc.code}")
        except websockets.exceptions.InvalidStatus as exc:
            print(f"  [PASS] Handshake rejected before accept with HTTP {exc.response.status_code} (ASGI 403 on pre-accept close)")

        # (c) Publish an event through EventBus and verify socket delivery
        print("\n[Step (c)] Connecting admin socket and publishing event via EventBus...")
        bus = get_bus()
        await bus.connect()

        async with websockets.connect(f"{BASE_WS}/ws/v1/stream?token={admin_token}") as ws:
            hs = json.loads(await ws.recv())
            assert hs["type"] == "connection.established"

            # Publish event
            test_tag = uuid.uuid4().hex[:6]
            published = await bus.publish(
                TRAFFIC_UPDATE,
                payload={"flow": 42, "tag": test_tag},
                source="smoke-test",
            )
            print(f"  Published event {published.event_id} ({published.type}) to EventBus.")

            # Receive on socket
            delivered = json.loads(await asyncio.wait_for(ws.recv(), timeout=5.0))
            assert delivered["type"] == TRAFFIC_UPDATE
            assert delivered["payload"]["tag"] == test_tag
            assert delivered["event_id"] == str(published.event_id)
            print(f"  [PASS] Event received on WebSocket: {delivered['type']} (id={delivered['event_id']})")

        # (d) Login as analyst-role user, connect, publish role-restricted event type
        print("\n[Step (d)] Testing analyst role filtering...")
        analyst_email = f"analyst_verify_{uuid.uuid4().hex[:6]}@trafficos.io"
        reg_resp = await http_client.post(
            "/api/v1/auth/register",
            json={"email": analyst_email, "password": "Password123!", "full_name": "Test Analyst"},
        )
        assert reg_resp.status_code == 201, f"Analyst registration failed: {reg_resp.text}"
        login_resp = await http_client.post(
            "/api/v1/auth/login",
            json={"email": analyst_email, "password": "Password123!"},
        )
        assert login_resp.status_code == 200
        analyst_token = login_resp.json()["access_token"]
        print(f"  Created and logged in analyst account: {analyst_email}")

        async with websockets.connect(f"{BASE_WS}/ws/v1/stream?token={analyst_token}") as ws_analyst:
            hs = json.loads(await ws_analyst.recv())
            assert hs["type"] == "connection.established"
            assert hs["role"] == "analyst"
            print("  Analyst connection established.")

            # Publish restricted event (notification.created)
            notif_tag = uuid.uuid4().hex[:6]
            await bus.publish(
                NOTIFICATION_CREATED,
                payload={"operator_email": "admin@trafficos.io", "notif_tag": notif_tag},
                source="operator-dispatch",
            )
            print("  Published restricted event: notification.created.")

            # Publish allowed event (signal.change)
            sig_tag = uuid.uuid4().hex[:6]
            await bus.publish(
                SIGNAL_CHANGE,
                payload={"state": "green", "sig_tag": sig_tag},
                source="signal-controller",
            )
            print("  Published allowed event: signal.change.")

            # Read from socket: first message received MUST be signal.change, NOT notification.created
            received_msg = json.loads(await asyncio.wait_for(ws_analyst.recv(), timeout=5.0))
            assert received_msg["type"] == SIGNAL_CHANGE, f"Expected signal.change, got {received_msg['type']}"
            assert received_msg["payload"]["sig_tag"] == sig_tag
            print(f"  [PASS] Role filtering verified! Restricted event NOT delivered; allowed event '{received_msg['type']}' delivered.")

        # (e) Disconnect, publish 2 events, reconnect with ?last_event_id=<earlier>
        print("\n[Step (e)] Testing reconnect resync with ?last_event_id=...")
        # Publish event 1
        e1 = await bus.publish(
            TRAFFIC_UPDATE,
            payload={"resync_seq": 1, "nonce": uuid.uuid4().hex[:6]},
            source="resync-test",
        )
        # Publish event 2
        e2 = await bus.publish(
            CONGESTION_CHANGE,
            payload={"resync_seq": 2, "nonce": uuid.uuid4().hex[:6]},
            source="resync-test",
        )
        print(f"  Published e1 ({e1.event_id}) and e2 ({e2.event_id}).")

        # Reconnect with last_event_id = e1.event_id -> should replay exactly e2
        resync_url = f"{BASE_WS}/ws/v1/stream?token={admin_token}&last_event_id={e1.event_id}"
        async with websockets.connect(resync_url) as ws_resync:
            hs = json.loads(await ws_resync.recv())
            assert hs["type"] == "connection.established"

            # Expect e2 replayed
            replayed = json.loads(await asyncio.wait_for(ws_resync.recv(), timeout=5.0))
            assert replayed["event_id"] == str(e2.event_id)
            assert replayed["type"] == CONGESTION_CHANGE
            print(f"  [PASS] Received replayed event: {replayed['type']} (id={replayed['event_id']})")

            # Expect resync.complete
            complete_msg = json.loads(await asyncio.wait_for(ws_resync.recv(), timeout=5.0))
            assert complete_msg["type"] == "resync.complete"
            assert complete_msg["replayed"] >= 1
            print(f"  [PASS] Received resync.complete (replayed={complete_msg['replayed']})")

        # (f) Reconnect with bogus last_event_id -> expect {"type": "stale"}
        print("\n[Step (f)] Reconnecting with bogus last_event_id...")
        bogus_id = str(uuid.uuid4())
        bogus_url = f"{BASE_WS}/ws/v1/stream?token={admin_token}&last_event_id={bogus_id}"
        async with websockets.connect(bogus_url) as ws_bogus:
            hs = json.loads(await ws_bogus.recv())
            assert hs["type"] == "connection.established"

            stale_msg = json.loads(await asyncio.wait_for(ws_bogus.recv(), timeout=5.0))
            assert stale_msg["type"] == "stale", f"Expected stale, got {stale_msg}"
            assert "event history unavailable" in stale_msg["message"]
            print(f"  [PASS] Received expected stale notice: {stale_msg['message']}")

        # (g) Send {"type": "ping"} -> expect pong
        print("\n[Step (g)] Testing control message ping -> pong...")
        async with websockets.connect(f"{BASE_WS}/ws/v1/stream?token={admin_token}") as ws_ping:
            hs = json.loads(await ws_ping.recv())
            assert hs["type"] == "connection.established"

            await ws_ping.send(json.dumps({"type": "ping"}))
            pong_msg = json.loads(await asyncio.wait_for(ws_ping.recv(), timeout=5.0))
            assert pong_msg["type"] == "pong"
            assert "server_time" in pong_msg
            print(f"  [PASS] Sent ping, received pong: {pong_msg}")

    print("\n" + "=" * 70)
    print("ALL 7 VERIFICATION SCENARIOS (a)-(g) PASSED COMPLETELY!")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
