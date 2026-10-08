"""Verification script for Stage 3 Real-time Publishing Hooks.

Boots a test runner that connects to the live FastAPI server via WebSocket,
executes the required domain mutations, and verifies that exact real-time
events are emitted (or NOT emitted on identical updates) according to the
specification.
"""

import asyncio
from datetime import datetime, timezone
import json
import sys
import time
from typing import Any, Optional
import httpx
import websockets

from app.core.database import AsyncSessionLocal
from app.core.security import create_access_token
from app.models.traffic import TrafficRecord


BASE_URL = "http://127.0.0.1:8000"
WS_URL = "ws://127.0.0.1:8000/ws/v1/stream"


async def drain_events(ws, timeout: float = 1.0) -> list[dict[str, Any]]:
    """Read any pending events from the websocket within timeout."""
    events = []
    while True:
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
            data = json.loads(raw)
            events.append(data)
        except asyncio.TimeoutError:
            break
    return events


async def wait_for_event(ws, expected_type: str, timeout: float = 5.0) -> dict[str, Any]:
    """Wait for an event of expected_type within timeout, skipping connection or heartbeats."""
    start = time.time()
    while time.time() - start < timeout:
        remaining = timeout - (time.time() - start)
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=max(0.1, remaining))
            data = json.loads(raw)
            if data.get("type") == expected_type:
                return data
            print(f"  [ws recv other] type={data.get('type')}")
        except asyncio.TimeoutError:
            break
    raise TimeoutError(f"Timed out waiting for event type '{expected_type}' after {timeout}s")


async def expect_no_event(ws, unexpected_type: str, timeout: float = 1.0) -> None:
    """Ensure no event of unexpected_type is received within timeout."""
    start = time.time()
    while time.time() - start < timeout:
        remaining = timeout - (time.time() - start)
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=max(0.1, remaining))
            data = json.loads(raw)
            if data.get("type") == unexpected_type:
                raise AssertionError(f"Unexpected event '{unexpected_type}' was received! payload={data}")
        except asyncio.TimeoutError:
            break


async def run_verification():
    print("=" * 70)
    print("STAGE 3 VERIFICATION: Real-Time Event Publishing Hooks")
    print("=" * 70)

    # 1. Generate Admin JWT
    token = create_access_token(user_id=1, role="admin")
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    client = httpx.AsyncClient(base_url=BASE_URL, headers=headers, timeout=10.0)

    ws_uri = f"{WS_URL}?token={token}"
    print(f"[1/8] Connecting admin WebSocket to {ws_uri} ...")

    async with websockets.connect(ws_uri) as ws:
        # Handshake
        handshake_raw = await asyncio.wait_for(ws.recv(), timeout=5.0)
        handshake = json.loads(handshake_raw)
        print(f"  Handshake received: type={handshake.get('type')}, role={handshake.get('role')}")
        assert handshake.get("type") == "connection.established", f"Expected connection.established, got {handshake}"

        # Drain any initial messages (e.g. system.status on boot)
        initial_events = await drain_events(ws, timeout=0.5)
        print(f"  Drained {len(initial_events)} initial event(s)")

        # ----------------------------------------------------------------------
        # Verification 1: POST /api/v1/incidents -> expect incident.created
        # ----------------------------------------------------------------------
        print("\n[2/8] Testing POST /api/v1/incidents (admin) -> expect incident.created ...")
        inc_resp = await client.post(
            "/api/v1/incidents",
            json={
                "severity": "high",
                "status": "reported",
                "description": "Test verification stalled vehicle",
                "lat": 12.9716,
                "lon": 77.5946,
            },
        )
        assert inc_resp.status_code == 201, f"Failed to create incident: {inc_resp.text}"
        inc_data = inc_resp.json()
        incident_id = inc_data["id"]
        print(f"  Incident created with id={incident_id}")

        event = await wait_for_event(ws, "incident.created", timeout=5.0)
        print(f"  Received incident.created: payload={event.get('payload')}")
        assert event["payload"]["incident_id"] == incident_id
        assert event["payload"]["severity"] == "high"
        assert event["payload"]["status"] == "reported"

        # ----------------------------------------------------------------------
        # Verification 2: PATCH incident with IDENTICAL status -> expect NO incident.updated
        # ----------------------------------------------------------------------
        print("\n[3/8] Testing PATCH /api/v1/incidents with IDENTICAL status -> expect NO incident.updated ...")
        patch_identical = await client.patch(
            f"/api/v1/incidents/{incident_id}",
            json={"status": "reported"},
        )
        assert patch_identical.status_code == 200, f"Failed identical patch: {patch_identical.text}"
        await expect_no_event(ws, "incident.updated", timeout=1.5)
        print("  Confirmed: NO incident.updated was emitted on identical status update.")

        # ----------------------------------------------------------------------
        # Verification 3: PATCH incident with NEW status -> expect incident.updated
        # ----------------------------------------------------------------------
        print("\n[4/8] Testing PATCH /api/v1/incidents with NEW status -> expect incident.updated ...")
        patch_new = await client.patch(
            f"/api/v1/incidents/{incident_id}",
            json={"status": "acknowledged"},
        )
        assert patch_new.status_code == 200, f"Failed new patch: {patch_new.text}"
        event_updated = await wait_for_event(ws, "incident.updated", timeout=5.0)
        print(f"  Received incident.updated: payload={event_updated.get('payload')}")
        assert event_updated["payload"]["incident_id"] == incident_id
        assert event_updated["payload"]["old_status"] == "reported"
        assert event_updated["payload"]["new_status"] == "acknowledged"

        # ----------------------------------------------------------------------
        # Verification 4: Create + resolve emergency event -> expect emergency.created then emergency.updated
        # ----------------------------------------------------------------------
        print("\n[5/8] Testing emergency event: create then resolve -> expect emergency.created then emergency.updated ...")
        em_create_resp = await client.post(
            "/api/v1/emergency-events",
            json={
                "vehicle_type": "ambulance",
                "priority": 1,
                "status": "active",
                "incident_id": incident_id,
            },
        )
        assert em_create_resp.status_code == 201, f"Failed to create emergency event: {em_create_resp.text}"
        em_data = em_create_resp.json()
        emergency_id = em_data["id"]
        print(f"  Emergency event created with id={emergency_id}")

        em_created_event = await wait_for_event(ws, "emergency.created", timeout=5.0)
        print(f"  Received emergency.created: payload={em_created_event.get('payload')}")
        assert em_created_event["payload"]["event_id"] == emergency_id
        assert em_created_event["payload"]["status"] == "active"

        # Resolve emergency event
        em_resolve_resp = await client.patch(
            f"/api/v1/emergency-events/{emergency_id}",
            json={"status": "resolved"},
        )
        assert em_resolve_resp.status_code == 200, f"Failed to resolve emergency event: {em_resolve_resp.text}"
        em_updated_event = await wait_for_event(ws, "emergency.updated", timeout=5.0)
        print(f"  Received emergency.updated: payload={em_updated_event.get('payload')}")
        assert em_updated_event["payload"]["event_id"] == emergency_id
        assert em_updated_event["payload"]["old_status"] == "active"
        assert em_updated_event["payload"]["new_status"] == "resolved"

        # ----------------------------------------------------------------------
        # Verification 5: Change signal state -> expect signal.change. Update with identical state -> expect nothing
        # ----------------------------------------------------------------------
        print("\n[6/8] Testing signal state changes -> expect signal.change on change, nothing on identical update ...")
        test_code = f"SIG-VERIFY-{int(time.time() * 1000) % 100000}"
        sig_create_resp = await client.post(
            "/api/v1/signals",
            json={
                "intersection_id": 1,
                "code": test_code,
                "status": "active",
            },
        )
        assert sig_create_resp.status_code == 201, f"Failed to create signal: {sig_create_resp.text}"
        sig_data = sig_create_resp.json()
        signal_id = sig_data["id"]
        print(f"  Signal created with id={signal_id}, code={test_code}")

        sig_create_event = await wait_for_event(ws, "signal.change", timeout=5.0)
        print(f"  Received signal.change (create): payload={sig_create_event.get('payload')}")
        assert sig_create_event["payload"]["signal_id"] == signal_id
        assert sig_create_event["payload"]["change_kind"] == "create"

        # Update signal state to 'maintenance'
        sig_patch_resp = await client.patch(
            f"/api/v1/signals/{signal_id}",
            json={"status": "maintenance"},
        )
        assert sig_patch_resp.status_code == 200, f"Failed to patch signal: {sig_patch_resp.text}"
        sig_update_event = await wait_for_event(ws, "signal.change", timeout=5.0)
        print(f"  Received signal.change (update): payload={sig_update_event.get('payload')}")
        assert sig_update_event["payload"]["signal_id"] == signal_id
        assert sig_update_event["payload"]["previous_state"] == "active"
        assert sig_update_event["payload"]["new_state"] == "maintenance"
        assert sig_update_event["payload"]["change_kind"] == "update"

        # Update signal with identical status 'maintenance'
        sig_patch_identical = await client.patch(
            f"/api/v1/signals/{signal_id}",
            json={"status": "maintenance"},
        )
        assert sig_patch_identical.status_code == 200, f"Failed identical patch: {sig_patch_identical.text}"
        await expect_no_event(ws, "signal.change", timeout=1.5)
        print("  Confirmed: NO signal.change was emitted on identical signal state update.")

        # ----------------------------------------------------------------------
        # Verification 6: Control recommendation (create_recommendation) -> expect control.decision
        # ----------------------------------------------------------------------
        print("\n[7/8] Testing control recommendation (POST /api/v1/control/recommendations) -> expect control.decision ...")
        # Ensure fresh TrafficRecord exists for intersection 1 so telemetry is not stale
        async with AsyncSessionLocal() as session:
            now_utc = datetime.now(timezone.utc)
            fresh_rec = TrafficRecord(
                intersection_id=1,
                recorded_at=now_utc,
                vehicle_count=45,
                avg_speed_kmh=35.0,
                congestion_level=40,
                source="sensor",
            )
            session.add(fresh_rec)
            await session.commit()
            print("  Seeded fresh TrafficRecord for intersection 1")

        rec_resp = await client.post(
            "/api/v1/control/recommendations",
            json={"intersection_id": 1},
        )
        assert rec_resp.status_code == 201, f"Failed create_recommendation: {rec_resp.text}"
        rec_data = rec_resp.json()
        print(f"  Recommendation formulated: decision_id={rec_data['id']}, action={rec_data['action']}")

        ctrl_event = await wait_for_event(ws, "control.decision", timeout=5.0)
        print(f"  Received control.decision: payload={ctrl_event.get('payload')}")
        assert ctrl_event["payload"]["decision_id"] == rec_data["id"]
        assert ctrl_event["payload"]["junction_id"] == 1
        assert ctrl_event["payload"]["decision_type"] == rec_data["action"]
        assert "summary" in ctrl_event["payload"]

        # ----------------------------------------------------------------------
        # Verification 7: POST broadcast notification -> expect notification.created + REST list confirmation
        # ----------------------------------------------------------------------
        print("\n[8/8] Testing POST /api/v1/notifications/broadcast -> expect notification.created & REST list row ...")
        broadcast_title = f"Emergency Alert Test {int(time.time())}"
        notif_resp = await client.post(
            "/api/v1/notifications/broadcast",
            json={
                "title": broadcast_title,
                "message": "Major congestion on Arterial North",
                "severity": "critical",
            },
        )
        assert notif_resp.status_code == 201, f"Failed broadcast notification: {notif_resp.text}"
        notif_data = notif_resp.json()
        notif_id = notif_data["id"]
        print(f"  Broadcast notification created with id={notif_id}")

        notif_event = await wait_for_event(ws, "notification.created", timeout=5.0)
        print(f"  Received notification.created: payload={notif_event.get('payload')}")
        assert notif_event["payload"]["notification_id"] == notif_id
        assert notif_event["payload"]["severity"] == "critical"
        assert notif_event["payload"]["title"] == broadcast_title

        # Confirm notifications REST list shows the row
        list_resp = await client.get("/api/v1/notifications/me")
        assert list_resp.status_code == 200, f"Failed listing notifications: {list_resp.text}"
        list_data = list_resp.json()
        found = any(item["id"] == notif_id for item in list_data.get("items", []))
        assert found, f"Notification id {notif_id} not found in REST list /api/v1/notifications/me"
        print("  Confirmed: notification row successfully found in /api/v1/notifications/me REST list.")

    await client.aclose()
    print("\n" + "=" * 70)
    print("ALL 7 END-TO-END VERIFICATION CHECKS PASSED PERFECTLY!")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(run_verification())
