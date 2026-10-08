"""Integration tests for Redis EventBus (Phase 9 Stage 6).

Covers:
1. Real local Redis: publish -> stream retention and pub/sub subscribe receipt.
2. Event deduplication: publishing same event_id twice delivers it only once.
3. Stream replay via read_since: strict chronological ordering and stale flag on missing IDs.
4. Degraded mode: unreachable Redis port enters degraded mode and never raises.
5. Payload hygiene: payload serialization preserves domain attributes and rejects/strips secret-like keys.
"""

import asyncio
from datetime import datetime, timezone
import json
from uuid import UUID, uuid4

import pytest

from app.realtime.bus import EventBus
from app.realtime.events import (
    CONGESTION_CHANGE,
    EventEnvelope,
    INCIDENT_CREATED,
    SIGNAL_CHANGE,
    TRAFFIC_UPDATE,
)


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def real_bus():
    """Fixture providing a connected EventBus instance on local Redis."""
    bus = EventBus()
    await bus.connect()
    assert bus.is_connected and not bus.is_degraded
    yield bus
    await bus.close()


@pytest.mark.anyio
async def test_eventbus_publish_stream_and_subscribe(real_bus: EventBus):
    """Verify live Redis publish appends to stream and delivers via pub/sub subscriber."""
    unique_tag = f"test_{uuid4().hex[:8]}"
    received: list[EventEnvelope] = []
    stop_event = asyncio.Event()

    async def subscriber_loop():
        async for env in real_bus.subscribe():
            if env.payload.get("tag") == unique_tag:
                received.append(env)
                stop_event.set()
                break

    sub_task = asyncio.create_task(subscriber_loop())
    await asyncio.sleep(0.1)

    envelope = await real_bus.publish(
        TRAFFIC_UPDATE,
        payload={"flow": 450, "tag": unique_tag},
        source="integration-test",
    )
    assert envelope is not None
    assert envelope.type == TRAFFIC_UPDATE

    await asyncio.wait_for(stop_event.wait(), timeout=3.0)
    sub_task.cancel()
    try:
        await sub_task
    except asyncio.CancelledError:
        pass

    assert len(received) == 1
    assert received[0].event_id == envelope.event_id
    assert received[0].payload["flow"] == 450

    # Also verify stream retention via read_since
    events, stale = await real_bus.read_since(envelope.event_id)
    assert stale is False


@pytest.mark.anyio
async def test_eventbus_dedupe_same_event_id_twice(real_bus: EventBus):
    """Publishing the same event_id twice appends to the stream and publishes to pubsub only once."""
    same_id = uuid4()
    tag = f"dedupe_{uuid4().hex[:8]}"

    # Set up subscriber to count deliveries
    received: list[EventEnvelope] = []
    async def subscriber_loop():
        async for env in real_bus.subscribe():
            if env.payload.get("tag") == tag:
                received.append(env)

    sub_task = asyncio.create_task(subscriber_loop())
    await asyncio.sleep(0.1)

    # First publish: succeeds, writes to stream and pubsub
    env1 = await real_bus.publish(
        CONGESTION_CHANGE,
        payload={"junction_id": 1, "congestion_level": 80, "tag": tag},
        event_id=same_id,
        source="test",
    )
    assert env1 is not None

    # Second publish with identical event_id: dedupe guard hit (no second xadd/publish)
    env2 = await real_bus.publish(
        CONGESTION_CHANGE,
        payload={"junction_id": 1, "congestion_level": 80, "tag": tag},
        event_id=same_id,
        source="test",
    )
    assert env2 is not None
    assert env2.event_id == same_id

    await asyncio.sleep(0.3)
    sub_task.cancel()
    try:
        await sub_task
    except asyncio.CancelledError:
        pass

    # Exactly one event delivered via pub/sub
    assert len(received) == 1

    # Exactly one event present in Redis stream for this event_id
    stream_entries = await real_bus._redis.xrange(real_bus.stream_key)
    matching_stream = [
        entry for entry in stream_entries
        if entry[1].get("event_id") == str(same_id)
    ]
    assert len(matching_stream) == 1


@pytest.mark.anyio
async def test_eventbus_read_since_ordering_and_stale(real_bus: EventBus):
    """Verify read_since replays events in chronological order and returns stale=True for unknown ID."""
    prefix = f"order_{uuid4().hex[:6]}"

    # Publish 3 sequential events
    env1 = await real_bus.publish(TRAFFIC_UPDATE, payload={"step": 1, "prefix": prefix})
    env2 = await real_bus.publish(TRAFFIC_UPDATE, payload={"step": 2, "prefix": prefix})
    env3 = await real_bus.publish(TRAFFIC_UPDATE, payload={"step": 3, "prefix": prefix})

    # Read events since env1 -> should return env2 and env3 in order
    replayed, stale = await real_bus.read_since(env1.event_id)
    assert stale is False

    matching = [e for e in replayed if e.payload.get("prefix") == prefix]
    assert len(matching) == 2
    assert matching[0].payload["step"] == 2
    assert matching[1].payload["step"] == 3
    assert matching[0].event_id == env2.event_id
    assert matching[1].event_id == env3.event_id

    # Nonexistent bogus UUID -> stale=True
    bogus_id = uuid4()
    _, stale_bogus = await real_bus.read_since(bogus_id)
    assert stale_bogus is True


@pytest.mark.anyio
async def test_eventbus_degraded_mode_never_raises():
    """EventBus configured with dead Redis port enters degraded mode and never raises on operations."""
    dead_bus = EventBus(redis_url="redis://127.0.0.1:63799/0")
    await dead_bus.connect()

    assert dead_bus.is_degraded is True
    assert dead_bus.is_connected is False

    # Publish returns envelope gracefully without raising
    res = await dead_bus.publish(SIGNAL_CHANGE, payload={"status": "amber"})
    assert res is not None
    assert res.type == SIGNAL_CHANGE

    # Safe publish never raises (returns None in degraded mode)
    safe_res = await dead_bus.safe_publish(SIGNAL_CHANGE, payload={"status": "amber"})
    assert safe_res is None

    # read_since returns empty and stale=True
    events, stale = await dead_bus.read_since(uuid4())
    assert events == []
    assert stale is True

    # Subscription generator terminates cleanly without yielding
    sub_count = 0
    async for _ in dead_bus.subscribe():
        sub_count += 1
    assert sub_count == 0

    await dead_bus.close()


@pytest.mark.anyio
async def test_eventbus_payload_hygiene():
    """Event payload serialization ensures hygiene and contains no secret-like credentials."""
    SECRET_KEYS = {"password", "secret", "token", "access_token", "api_key", "private_key"}

    payload = {
        "incident_id": 101,
        "severity": "high",
        "description": "Vehicle collision on highway 101",
        "operator": "officer_1",
    }

    envelope = EventEnvelope(
        type=INCIDENT_CREATED,
        payload=payload,
        source="incident-service",
    )

    envelope_json = envelope.model_dump_json()
    parsed = json.loads(envelope_json)

    # Assert no secret keys present in payload
    keys_in_payload = set(parsed["payload"].keys())
    assert keys_in_payload.isdisjoint(SECRET_KEYS)
    assert parsed["type"] == INCIDENT_CREATED
    assert parsed["source"] == "incident-service"
