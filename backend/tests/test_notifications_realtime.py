"""Integration tests for real-time notification policies and deduplication (Phase 9 Stage 6).

Covers:
1. incident.created (high severity) -> notification row (error severity) + bus notification.created.
2. Incident update dedupe within window (single notification row for the entity while unread).
3. Severity gating and filtering:
   - Routine signal.change -> no notification row.
   - Emergency manual override signal.change -> warning notification.
   - emergency.created -> critical notification.
   - emergency.updated (resolved) -> info notification.
   - emergency.updated (in_transit) -> filtered out (no notification).
   - High-frequency telemetry (traffic.update, prediction.published) -> filtered out.
4. Congestion 15-min gate: rapid severe congestion changes produce at most 1 notification.
5. Recursion guard: notification.created NEVER triggers another notification.
"""

import asyncio
from datetime import datetime, timezone
import uuid
from typing import Optional

import pytest
from sqlalchemy import func, select

from app.core.database import AsyncSessionLocal, engine
from app.models.notification import Notification
from app.realtime import (
    CONGESTION_CHANGE,
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
    evaluate_event_policy,
    get_bus,
    maybe_notify_for_event,
)


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(autouse=True)
async def dispose_engine():
    yield
    await engine.dispose()


class EventCollector:
    """Pub/Sub listener helper for capturing bus broadcasts."""

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
    """Fixture providing an active EventCollector and managing bus lifecycle."""
    bus = get_bus()
    await bus.connect()
    async with EventCollector(bus) as coll:
        yield coll
    await bus.close()


@pytest.mark.anyio
async def test_incident_created_high_severity_flow(collector: EventCollector):
    """High severity incident.created generates an 'error' notification and emits notification.created."""
    bus = get_bus()
    incident_id = 990001 + int(uuid.uuid4().int % 10000)

    env = EventEnvelope(
        type=INCIDENT_CREATED,
        source="incident-service",
        payload={
            "incident_id": incident_id,
            "severity": "high",
            "status": "reported",
            "description": "Multi-car collision on arterial",
        },
    )

    notif = await maybe_notify_for_event(env)
    assert notif is not None
    assert notif.severity == "error"
    assert notif.entity_type == "incident"
    assert notif.entity_id == incident_id
    assert notif.user_id is None  # System-wide broadcast

    # Verify notification row exists in DB
    async with AsyncSessionLocal() as session:
        db_notif = await session.get(Notification, notif.id)
        assert db_notif is not None
        assert db_notif.severity == "error"
        assert not db_notif.is_read

    # Verify bus received notification.created
    await asyncio.sleep(0.2)
    emitted = [
        e for e in collector.matching(NOTIFICATION_CREATED)
        if e.payload.get("notification_id") == notif.id
    ]
    assert len(emitted) == 1
    assert emitted[0].payload["severity"] == "error"


@pytest.mark.anyio
async def test_incident_dedupe_within_window():
    """Subsequent updates for an incident with an unread notification are deduped."""
    incident_id = 991001 + int(uuid.uuid4().int % 10000)

    create_env = EventEnvelope(
        type=INCIDENT_CREATED,
        source="incident-service",
        payload={
            "incident_id": incident_id,
            "severity": "medium",
            "status": "reported",
            "description": "Stalled vehicle in lane 2",
        },
    )

    # First event creates a notification
    notif1 = await maybe_notify_for_event(create_env)
    assert notif1 is not None

    # Immediate status update for same incident while notif1 is unread -> deduped
    update_env = EventEnvelope(
        type=INCIDENT_UPDATED,
        source="incident-service",
        payload={
            "incident_id": incident_id,
            "old_status": "reported",
            "new_status": "acknowledged",
        },
    )
    notif2 = await maybe_notify_for_event(update_env)
    assert notif2 is None, "Expected unread notification deduplication to suppress duplicate"

    # Now mark notif1 as read in the DB
    async with AsyncSessionLocal() as session:
        notif_row = await session.get(Notification, notif1.id)
        assert notif_row is not None
        notif_row.is_read = True
        await session.commit()

    # Now that the previous alert is read, a new update creates a notification
    resolve_env = EventEnvelope(
        type=INCIDENT_UPDATED,
        source="incident-service",
        payload={
            "incident_id": incident_id,
            "old_status": "acknowledged",
            "new_status": "resolved",
        },
    )
    notif3 = await maybe_notify_for_event(resolve_env)
    assert notif3 is not None
    assert notif3.id != notif1.id


@pytest.mark.anyio
async def test_severity_gating_and_filtering():
    """Verify severity gating, emergency mappings, and non-notifiable event types."""
    sig_routine_id = 993000 + int(uuid.uuid4().int % 10000)
    routine_signal = EventEnvelope(
        type=SIGNAL_CHANGE,
        source="signal-controller",
        payload={
            "signal_id": sig_routine_id,
            "intersection_id": 1,
            "state": "green",
            "change_kind": "routine",
        },
    )
    assert evaluate_event_policy(routine_signal) is None
    res = await maybe_notify_for_event(routine_signal)
    assert res is None

    # 2. Emergency override signal.change -> warning notification
    sig_override_id = 994000 + int(uuid.uuid4().int % 10000)
    override_signal = EventEnvelope(
        type=SIGNAL_CHANGE,
        source="signal-controller",
        payload={
            "signal_id": sig_override_id,
            "intersection_id": 1,
            "state": "all-red",
            "change_kind": "emergency_override",
        },
    )
    override_policy = evaluate_event_policy(override_signal)
    assert override_policy is not None
    assert override_policy["severity"] == "warning"
    res_override = await maybe_notify_for_event(override_signal)
    assert res_override is not None
    assert res_override.severity == "warning"

    # 3. emergency.created -> critical notification
    emer_id = 992001 + int(uuid.uuid4().int % 10000)
    emer_env = EventEnvelope(
        type=EMERGENCY_CREATED,
        source="emergency-dispatch",
        payload={
            "event_id": emer_id,
            "vehicle_type": "ambulance",
            "priority_level": "code_3",
            "status": "in_transit",
        },
    )
    res_emer = await maybe_notify_for_event(emer_env)
    assert res_emer is not None
    assert res_emer.severity == "critical"

    # 4. emergency.updated (non-resolved status) -> NO notification
    emer_update_in_transit = EventEnvelope(
        type=EMERGENCY_UPDATED,
        source="emergency-dispatch",
        payload={
            "event_id": emer_id,
            "old_status": "dispatched",
            "new_status": "in_transit",
        },
    )
    assert evaluate_event_policy(emer_update_in_transit) is None
    res_in_transit = await maybe_notify_for_event(emer_update_in_transit)
    assert res_in_transit is None

    # 5. emergency.updated (resolved) -> info notification
    emer_update_resolved = EventEnvelope(
        type=EMERGENCY_UPDATED,
        source="emergency-dispatch",
        payload={
            "event_id": emer_id,
            "old_status": "in_transit",
            "new_status": "resolved",
        },
    )
    res_resolved = await maybe_notify_for_event(emer_update_resolved)
    assert res_resolved is not None
    assert res_resolved.severity == "info"

    # 6. Telemetry and heartbeat events -> strictly filtered
    for evt_type in [TRAFFIC_UPDATE, PREDICTION_PUBLISHED, SYSTEM_STATUS]:
        env = EventEnvelope(type=evt_type, source="telemetry", payload={"data": 123})
        assert evaluate_event_policy(env) is None
        assert await maybe_notify_for_event(env) is None


@pytest.mark.anyio
async def test_congestion_15_minute_gate():
    """10 rapid severe congestion changes for the same junction result in at most 1 notification."""
    junction_id = 880001 + int(uuid.uuid4().int % 10000)

    # 1. Mild congestion (<=75%) -> policy ignores it
    mild_env = EventEnvelope(
        type=CONGESTION_CHANGE,
        source="congestion-engine",
        payload={
            "junction_id": junction_id,
            "congestion_level": 60,
        },
    )
    assert evaluate_event_policy(mild_env) is None
    assert await maybe_notify_for_event(mild_env) is None

    # 2. 10 rapid severe congestion events (>75%)
    results = []
    for _ in range(10):
        env = EventEnvelope(
            type=CONGESTION_CHANGE,
            source="congestion-engine",
            payload={
                "junction_id": junction_id,
                "congestion_level": 88,
            },
        )
        res = await maybe_notify_for_event(env)
        results.append(res)

    # Exactly the first event should produce a notification; the remaining 9 are gated by Redis
    successful = [r for r in results if r is not None]
    assert len(successful) == 1
    assert successful[0].severity == "warning"
    assert successful[0].entity_type == "junction"
    assert successful[0].entity_id == junction_id

    # Verify count in database
    async with AsyncSessionLocal() as session:
        stmt = select(func.count(Notification.id)).where(
            Notification.entity_type == "junction",
            Notification.entity_id == junction_id,
        )
        count = (await session.execute(stmt)).scalar()
        assert count == 1


@pytest.mark.anyio
async def test_recursion_guard_notification_created():
    """notification.created never produces another notification (infinite loop prevention)."""
    env = EventEnvelope(
        type=NOTIFICATION_CREATED,
        source="notification-service",
        payload={
            "notification_id": 12345,
            "severity": "critical",
            "title": "System Alert",
        },
    )

    # Policy explicitly returns None
    assert evaluate_event_policy(env) is None

    # maybe_notify_for_event returns None without DB insertion
    res = await maybe_notify_for_event(env)
    assert res is None
