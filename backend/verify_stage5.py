#!/usr/bin/env python3
"""Stage 5 live integration verification script for AI TrafficOS.

Verifies live uvicorn server (:8000) with real PostgreSQL and Redis:
1. POST /api/v1/incidents (severity high) -> notification row in GET /api/v1/notifications AND notification.created on WS.
2. Update the same incident twice -> dedupe: single notification row for the entity in the window.
3. Create + resolve an emergency event -> critical on create, info 'resolved' on resolve.
4. Routine signal.change published via bus -> NO notification row.
5. 10 rapid severe congestion.change for one junction -> at most 1 notification (15-min gate).
6. Create a notification via REST -> exactly one notification.created on the bus (no double emission, no loop).
"""

import asyncio
import json
import logging
from pathlib import Path
import sys
import uuid

import httpx
import websockets

BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.realtime import (
    CONGESTION_CHANGE,
    SIGNAL_CHANGE,
    get_bus,
)

BASE_HTTP = "http://127.0.0.1:8000"
BASE_WS = "ws://127.0.0.1:8000"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("verify_stage5")


async def main() -> None:
    logger.info("=" * 70)
    logger.info("STAGE 5 REAL-TIME NOTIFICATIONS LIVE VERIFICATION")
    logger.info("=" * 70)

    async with httpx.AsyncClient(base_url=BASE_HTTP, timeout=15.0, trust_env=False) as client:
        # Check /health
        health = await client.get("/health")
        assert health.status_code == 200, f"/health failed: {health.text}"
        logger.info("[Pass] Server healthy on %s", BASE_HTTP)

        # Login as admin
        login_resp = await client.post(
            "/api/v1/auth/login",
            json={"email": "admin@trafficos.io", "password": "adminpassword123"},
        )
        assert login_resp.status_code == 200, f"Admin login failed: {login_resp.text}"
        admin_token = login_resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {admin_token}"}
        logger.info("[Pass] Admin authenticated successfully")

        # Connect WebSocket
        ws_url = f"{BASE_WS}/ws/v1/stream?token={admin_token}"
        async with websockets.connect(ws_url) as ws:
            hs = json.loads(await ws.recv())
            assert hs.get("type") == "connection.established", f"Bad handshake: {hs}"
            logger.info("[Pass] WebSocket connection established as %s", hs.get("role"))

            # Background message collector
            received_events: list[dict] = []
            ws_stop = asyncio.Event()

            async def ws_reader():
                try:
                    while not ws_stop.is_set():
                        raw = await ws.recv()
                        msg = json.loads(raw)
                        received_events.append(msg)
                except Exception:
                    pass

            reader_task = asyncio.create_task(ws_reader())

            try:
                # -------------------------------------------------------------
                # 1. POST /api/v1/incidents (severity high) -> notification row + WS
                # -------------------------------------------------------------
                logger.info("\n--- 1. Testing Incident High Severity -> Notification ---")
                inc_resp = await client.post(
                    "/api/v1/incidents",
                    headers=headers,
                    json={
                        "intersection_id": 1,
                        "severity": "high",
                        "status": "reported",
                        "description": f"Stage5 Test Incident {uuid.uuid4().hex[:6]}",
                    },
                )
                assert inc_resp.status_code == 201, f"Failed to create incident: {inc_resp.text}"
                incident_id = inc_resp.json()["id"]
                logger.info("Created incident #%d with severity=high", incident_id)

                # Wait for WS and background notification task
                await asyncio.sleep(1.5)

                # Check WS received notification.created
                notif_ws = [
                    e for e in received_events
                    if e.get("type") == "notification.created"
                    and f"#{incident_id}" in e.get("payload", {}).get("title", "")
                ]
                assert len(notif_ws) >= 1, f"Expected notification.created on WS for incident #{incident_id}, received: {received_events}"
                logger.info("[Pass] WebSocket received notification.created for incident #%d (severity: %s)", incident_id, notif_ws[0]["payload"]["severity"])

                # Check GET /api/v1/notifications has notification row
                notifs_resp = await client.get("/api/v1/notifications/me", headers=headers)
                assert notifs_resp.status_code == 200
                rows = [
                    n for n in notifs_resp.json()["items"]
                    if n.get("entity_type") == "incident" and n.get("entity_id") == incident_id
                ]
                assert len(rows) == 1, f"Expected exactly 1 notification row for incident #{incident_id}, found: {len(rows)}"
                assert rows[0]["severity"] == "error", f"High incident should map to error, got: {rows[0]['severity']}"
                logger.info("[Pass] GET /notifications contains unread error row for incident #%d", incident_id)

                # -------------------------------------------------------------
                # 2. Update same incident twice -> dedupe: single notification row
                # -------------------------------------------------------------
                logger.info("\n--- 2. Testing Incident Update Deduplication ---")
                patch1 = await client.patch(
                    f"/api/v1/incidents/{incident_id}",
                    headers=headers,
                    json={"status": "acknowledged"},
                )
                assert patch1.status_code == 200, f"Failed patch1: {patch1.text}"
                patch2 = await client.patch(
                    f"/api/v1/incidents/{incident_id}",
                    headers=headers,
                    json={"description": "Updated description twice"},
                )
                assert patch2.status_code == 200, f"Failed patch2: {patch2.text}"
                await asyncio.sleep(1.5)

                notifs_after = await client.get("/api/v1/notifications/me", headers=headers)
                rows_after = [
                    n for n in notifs_after.json()["items"]
                    if n.get("entity_type") == "incident" and n.get("entity_id") == incident_id
                ]
                assert len(rows_after) == 1, f"Dedupe failed! Expected 1 notification row for incident #{incident_id}, found: {len(rows_after)}"
                logger.info("[Pass] Incident updated twice; exactly 1 notification row exists (dedupe preserved)")

                # -------------------------------------------------------------
                # 3. Create + resolve emergency event -> critical on create, info on resolve
                # -------------------------------------------------------------
                logger.info("\n--- 3. Testing Emergency Create + Resolve Gating ---")
                em_resp = await client.post(
                    "/api/v1/emergency-events",
                    headers=headers,
                    json={
                        "vehicle_type": "ambulance",
                        "priority": 1,
                        "status": "dispatched",
                    },
                )
                assert em_resp.status_code == 201, f"Failed to create emergency event: {em_resp.text}"
                em_id = em_resp.json()["id"]
                logger.info("Created emergency event #%d", em_id)
                await asyncio.sleep(1.5)

                # Check critical notification row created
                n_em = await client.get("/api/v1/notifications/me", headers=headers)
                em_rows = [
                    n for n in n_em.json()["items"]
                    if n.get("entity_type") == "emergency_event" and n.get("entity_id") == em_id
                ]
                assert len(em_rows) == 1, f"Expected 1 emergency notification row, got {len(em_rows)}"
                assert em_rows[0]["severity"] == "critical"
                logger.info("[Pass] Emergency #%d has critical notification row", em_id)

                # Resolve emergency event
                em_resolve = await client.patch(
                    f"/api/v1/emergency-events/{em_id}",
                    headers=headers,
                    json={"status": "resolved"},
                )
                assert em_resolve.status_code == 200
                await asyncio.sleep(1.5)

                n_em_res = await client.get("/api/v1/notifications/me", headers=headers)
                em_resolved_rows = [
                    n for n in n_em_res.json()["items"]
                    if n.get("entity_type") == "emergency_event" and n.get("entity_id") == em_id
                ]
                severities = {r["severity"] for r in em_resolved_rows}
                assert "critical" in severities and "info" in severities, f"Expected critical and info rows for emergency #{em_id}, got: {severities}"
                logger.info("[Pass] Emergency resolution created 'info' notification row alongside 'critical'")

                # -------------------------------------------------------------
                # 4. Routine signal.change published via bus -> NO notification row
                # -------------------------------------------------------------
                logger.info("\n--- 4. Testing Routine Signal Change (No Notification) ---")
                bus = get_bus()
                await bus.connect()

                initial_notifs_count = len((await client.get("/api/v1/notifications/me", headers=headers)).json()["items"])
                sig_tag = 777777
                await bus.publish(
                    SIGNAL_CHANGE,
                    payload={
                        "signal_id": sig_tag,
                        "change_kind": "routine_cycle",
                        "phase_name": "Phase 1 Green",
                        "status": "normal",
                    },
                )
                await asyncio.sleep(1.5)

                notifs_after_sig = (await client.get("/api/v1/notifications/me", headers=headers)).json()["items"]
                sig_notifs = [
                    n for n in notifs_after_sig
                    if n.get("entity_type") == "signal" and n.get("entity_id") == sig_tag
                ]
                assert len(sig_notifs) == 0, f"Routine signal change should not produce notification, got: {sig_notifs}"
                logger.info("[Pass] Routine signal.change generated 0 notification rows")

                # -------------------------------------------------------------
                # 5. 10 rapid severe congestion.change -> at most 1 notification (15-min gate)
                # -------------------------------------------------------------
                logger.info("\n--- 5. Testing 10 Rapid Severe Congestion Changes (15-min Gate) ---")
                test_junction_id = 999123
                for _ in range(10):
                    await bus.publish(
                        CONGESTION_CHANGE,
                        payload={
                            "junction_id": test_junction_id,
                            "congestion_level": 88,
                            "severity": "severe",
                        },
                    )
                await asyncio.sleep(2.0)

                cong_notifs = [
                    n for n in (await client.get("/api/v1/notifications/me", headers=headers)).json()["items"]
                    if n.get("entity_type") == "junction" and n.get("entity_id") == test_junction_id
                ]
                assert len(cong_notifs) == 1, f"Expected exactly 1 notification for junction {test_junction_id}, got {len(cong_notifs)}"
                assert cong_notifs[0]["severity"] == "warning"
                logger.info("[Pass] 10 rapid severe congestion events produced exactly 1 notification row (15-min gate active)")

                # -------------------------------------------------------------
                # 6. Create notification via REST -> exactly one notification.created on WS
                # -------------------------------------------------------------
                logger.info("\n--- 6. Testing REST Notification Creation (No Loop / Single Emission) ---")
                ws_count_before = len([
                    e for e in received_events
                    if e.get("type") == "notification.created"
                ])

                rest_title = f"Manual REST Alert {uuid.uuid4().hex[:6]}"
                create_resp = await client.post(
                    "/api/v1/notifications/broadcast",
                    headers=headers,
                    json={
                        "title": rest_title,
                        "message": "Manual dispatcher alert via REST",
                        "severity": "info",
                    },
                )
                assert create_resp.status_code == 201
                await asyncio.sleep(2.0)

                matching_events = [
                    e for e in received_events
                    if e.get("type") == "notification.created"
                    and e.get("payload", {}).get("title") == rest_title
                ]
                assert len(matching_events) == 1, f"Expected exactly 1 notification.created event on bus, got {len(matching_events)}"
                logger.info("[Pass] REST broadcast emitted exactly 1 notification.created event (no recursion, no loop)")

            finally:
                ws_stop.set()
                reader_task.cancel()

    logger.info("\n" + "=" * 70)
    logger.info("ALL 6 STAGE 5 VERIFICATION CHECKS PASSED PERFECTLY!")
    logger.info("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
