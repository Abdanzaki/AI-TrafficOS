"""Integration tests for real-time event publishing hooks (Phase 9 Stage 6).

Covers:
1. Incident creation emits 'incident.created'; identical-status PATCH emits no 'incident.updated';
   status transition emits 'incident.updated'.
2. Signal state change emits 'signal.change'; identical state update emits nothing.
3. Emergency transit creation emits 'emergency.created'; resolution emits 'emergency.updated'.
4. Control recommendation generation emits 'control.decision'.
5. Vehicle event batch ingest emits exactly ONE 'traffic.update' event per batch.
"""

import asyncio
from datetime import datetime, timezone
from typing import Optional
import uuid

from httpx import AsyncClient
import pytest
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.intersection import Intersection
from app.models.traffic import TrafficRecord
from app.realtime import (
    CONTROL_DECISION,
    EMERGENCY_CREATED,
    EMERGENCY_UPDATED,
    EventEnvelope,
    INCIDENT_CREATED,
    INCIDENT_UPDATED,
    SIGNAL_CHANGE,
    TRAFFIC_UPDATE,
    get_bus,
)


@pytest.fixture
def anyio_backend():
    return "asyncio"


class EventCollector:
    """Hermetic Redis pub/sub event capture helper for integration tests."""

    def __init__(self, bus):
        self.bus = bus
        self.events: list[EventEnvelope] = []
        self._task: Optional[asyncio.Task] = None

    async def __aenter__(self):
        async def _run():
            async for env in self.bus.subscribe():
                self.events.append(env)

        self._task = asyncio.create_task(_run())
        await asyncio.sleep(0.05)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    def matching(self, event_type: str) -> list[EventEnvelope]:
        return [e for e in self.events if e.type == event_type]


@pytest.fixture
async def collector():
    """Fixture providing an active EventCollector listening on Redis pub/sub."""
    bus = get_bus()
    await bus.connect()
    async with EventCollector(bus) as coll:
        yield coll
    await bus.close()


@pytest.mark.anyio
async def test_incident_create_and_update_hooks(
    async_client: AsyncClient,
    test_users: dict,
    collector: EventCollector,
):
    """Incident creation emits incident.created; identical PATCH emits nothing; transition emits incident.updated."""
    token = test_users["officer"]["token"]
    headers = {"Authorization": f"Bearer {token}"}

    # 1. Create incident -> incident.created
    tag = uuid.uuid4().hex[:6]
    create_resp = await async_client.post(
        "/api/v1/incidents",
        headers=headers,
        json={
            "severity": "medium",
            "status": "reported",
            "description": f"Hook test incident {tag}",
        },
    )
    assert create_resp.status_code == 201, create_resp.text
    incident_id = create_resp.json()["id"]

    await asyncio.sleep(0.2)
    created_events = [
        e for e in collector.matching(INCIDENT_CREATED)
        if e.payload.get("incident_id") == incident_id
    ]
    assert len(created_events) == 1
    assert created_events[0].payload["severity"] == "medium"
    assert created_events[0].payload["status"] == "reported"

    # 2. PATCH with identical status -> no incident.updated emitted
    count_before = len(collector.matching(INCIDENT_UPDATED))
    patch_same = await async_client.patch(
        f"/api/v1/incidents/{incident_id}",
        headers=headers,
        json={"status": "reported", "description": f"Updated desc {tag}"},
    )
    assert patch_same.status_code == 200

    await asyncio.sleep(0.2)
    count_after_same = len(collector.matching(INCIDENT_UPDATED))
    assert count_after_same == count_before

    # 3. PATCH with changed status -> incident.updated emitted
    patch_diff = await async_client.patch(
        f"/api/v1/incidents/{incident_id}",
        headers=headers,
        json={"status": "acknowledged"},
    )
    assert patch_diff.status_code == 200

    await asyncio.sleep(0.2)
    updated_events = [
        e for e in collector.matching(INCIDENT_UPDATED)
        if e.payload.get("incident_id") == incident_id
    ]
    assert len(updated_events) == 1
    assert updated_events[0].payload["old_status"] == "reported"
    assert updated_events[0].payload["new_status"] == "acknowledged"


@pytest.mark.anyio
async def test_signal_state_change_hooks(
    async_client: AsyncClient,
    test_users: dict,
    collector: EventCollector,
):
    """Signal status change emits signal.change; update with identical status emits nothing."""
    admin_token = test_users["admin"]["token"]
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    # Ensure intersection exists
    async with AsyncSessionLocal() as session:
        j = await session.get(Intersection, 1)
        if not j:
            inter = Intersection(id=1, name="Signal Test Junction", code="INT-SIG-01", status="active")
            session.add(inter)
            await session.commit()

    # Create signal
    code = f"SIG_{uuid.uuid4().hex[:6]}"
    create_resp = await async_client.post(
        "/api/v1/signals",
        headers=admin_headers,
        json={"intersection_id": 1, "code": code, "status": "active"},
    )
    assert create_resp.status_code == 201, create_resp.text
    signal_id = create_resp.json()["id"]

    await asyncio.sleep(0.1)

    # 1. Update with different status (active -> maintenance) -> emits signal.change
    patch_resp = await async_client.patch(
        f"/api/v1/signals/{signal_id}",
        headers=admin_headers,
        json={"status": "maintenance"},
    )
    assert patch_resp.status_code == 200, patch_resp.text

    await asyncio.sleep(0.2)
    sig_changes = [
        e for e in collector.matching(SIGNAL_CHANGE)
        if e.payload.get("signal_id") == signal_id
    ]
    assert len(sig_changes) >= 1
    latest_change = sig_changes[-1]
    assert latest_change.payload["previous_state"] == "active"
    assert latest_change.payload["new_state"] == "maintenance"

    # 2. Update with identical status ("maintenance") -> emits nothing
    count_before = len(sig_changes)
    patch_same = await async_client.patch(
        f"/api/v1/signals/{signal_id}",
        headers=admin_headers,
        json={"status": "maintenance"},
    )
    assert patch_same.status_code == 200

    await asyncio.sleep(0.2)
    sig_changes_after = [
        e for e in collector.matching(SIGNAL_CHANGE)
        if e.payload.get("signal_id") == signal_id
    ]
    assert len(sig_changes_after) == count_before


@pytest.mark.anyio
async def test_emergency_create_and_resolve_hooks(
    async_client: AsyncClient,
    test_users: dict,
    collector: EventCollector,
):
    """Emergency creation emits emergency.created; status update emits emergency.updated."""
    token = test_users["officer"]["token"]
    headers = {"Authorization": f"Bearer {token}"}

    # 1. Create emergency event -> emergency.created
    em_resp = await async_client.post(
        "/api/v1/emergency-events",
        headers=headers,
        json={
            "vehicle_type": "police",
            "priority": 2,
            "status": "dispatched",
        },
    )
    assert em_resp.status_code == 201, em_resp.text
    em_id = em_resp.json()["id"]

    await asyncio.sleep(0.2)
    em_created = [
        e for e in collector.matching(EMERGENCY_CREATED)
        if e.payload.get("event_id") == em_id
    ]
    assert len(em_created) == 1
    assert em_created[0].payload["status"] == "dispatched"
    assert em_created[0].payload["priority"] == 2

    # 2. Resolve emergency event -> emergency.updated
    em_patch = await async_client.patch(
        f"/api/v1/emergency-events/{em_id}",
        headers=headers,
        json={"status": "resolved"},
    )
    assert em_patch.status_code == 200, em_patch.text

    await asyncio.sleep(0.2)
    em_updated = [
        e for e in collector.matching(EMERGENCY_UPDATED)
        if e.payload.get("event_id") == em_id
    ]
    assert len(em_updated) == 1
    assert em_updated[0].payload["old_status"] == "dispatched"
    assert em_updated[0].payload["new_status"] == "resolved"


@pytest.mark.anyio
async def test_control_recommendation_hook(
    async_client: AsyncClient,
    test_users: dict,
    collector: EventCollector,
):
    """Generating supervisory control recommendation emits control.decision."""
    admin_token = test_users["admin"]["token"]
    headers = {"Authorization": f"Bearer {admin_token}"}

    # Ensure intersection 1 exists and has fresh telemetry (< 300s old)
    async with AsyncSessionLocal() as session:
        j = await session.get(Intersection, 1)
        if not j:
            inter = Intersection(id=1, name="Control Test Junction", code="INT-CTL-01", status="active")
            session.add(inter)
            await session.commit()

        # Ingest fresh traffic record
        rec = TrafficRecord(
            intersection_id=1,
            vehicle_count=50,
            avg_speed_kmh=25.0,
            congestion_level=60,
            recorded_at=datetime.now(timezone.utc),
            source="sensor",
        )
        session.add(rec)
        await session.commit()

    # Call POST /api/v1/control/recommendations
    rec_resp = await async_client.post(
        "/api/v1/control/recommendations",
        headers=headers,
        json={"intersection_id": 1},
    )
    assert rec_resp.status_code == 201, rec_resp.text
    dec_id = rec_resp.json()["id"]

    await asyncio.sleep(0.2)
    dec_events = [
        e for e in collector.matching(CONTROL_DECISION)
        if e.payload.get("decision_id") == dec_id
    ]
    assert len(dec_events) == 1
    assert dec_events[0].payload["junction_id"] == 1
    assert "decision_type" in dec_events[0].payload


@pytest.mark.anyio
async def test_vehicle_batch_ingest_single_traffic_update(
    async_client: AsyncClient,
    test_users: dict,
    collector: EventCollector,
):
    """Vehicle event batch ingest emits exactly ONE traffic.update event with total count."""
    token = test_users["officer"]["token"]
    headers = {"Authorization": f"Bearer {token}"}

    events = [
        {"intersection_id": 1, "event_type": "detection", "vehicle_type": "car", "confidence": 0.95},
        {"intersection_id": 1, "event_type": "detection", "vehicle_type": "bus", "confidence": 0.90},
        {"intersection_id": 1, "event_type": "detection", "vehicle_type": "truck", "confidence": 0.88},
    ]

    before_count = len(collector.matching(TRAFFIC_UPDATE))

    batch_resp = await async_client.post(
        "/api/v1/vehicle-events/batch",
        headers=headers,
        json={"events": events},
    )
    assert batch_resp.status_code == 201, batch_resp.text
    assert batch_resp.json()["inserted"] == 3

    await asyncio.sleep(0.2)
    traffic_updates = collector.matching(TRAFFIC_UPDATE)[before_count:]

    # Exactly ONE event per batch
    assert len(traffic_updates) == 1
    assert traffic_updates[0].payload["batch_size"] == 3
    assert 1 in traffic_updates[0].payload["junction_ids"]
