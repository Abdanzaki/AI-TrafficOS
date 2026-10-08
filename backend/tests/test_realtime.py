"""Unit and integration tests for Phase 9 Real-Time EventBus and EventEnvelope.

Covers:
- EventEnvelope validation, default factories, and serialization.
- Canonical event type constants and typing.
- EventBus lifecycle (connect, close, degraded mode).
- Real-time publish, stream retention, and fan-out pub/sub.
- Stream replay with read_since (complete replay, partial delta, stale flag).
- Deduplication guard via SETNX.
- Safe publish error handling.
- Module accessor get_bus().
"""

import asyncio
from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from app.realtime import (
    ALL_EVENT_TYPES,
    CONGESTION_CHANGE,
    CONTROL_DECISION,
    EMERGENCY_CREATED,
    EMERGENCY_UPDATED,
    EventBus,
    EventEnvelope,
    INCIDENT_CREATED,
    INCIDENT_UPDATED,
    NOTIFICATION_CREATED,
    PREDICTION_PUBLISHED,
    SIGNAL_CHANGE,
    SYSTEM_STATUS,
    TRAFFIC_UPDATE,
    get_bus,
)


def test_event_constants_specification() -> None:
    """Verify all 11 required event type constants are correctly defined."""
    expected = {
        "traffic.update",
        "congestion.change",
        "signal.change",
        "incident.created",
        "incident.updated",
        "emergency.created",
        "emergency.updated",
        "prediction.published",
        "control.decision",
        "notification.created",
        "system.status",
    }
    actual = {
        TRAFFIC_UPDATE,
        CONGESTION_CHANGE,
        SIGNAL_CHANGE,
        INCIDENT_CREATED,
        INCIDENT_UPDATED,
        EMERGENCY_CREATED,
        EMERGENCY_UPDATED,
        PREDICTION_PUBLISHED,
        CONTROL_DECISION,
        NOTIFICATION_CREATED,
        SYSTEM_STATUS,
    }
    assert actual == expected
    assert set(ALL_EVENT_TYPES) == expected


def test_event_envelope_defaults_and_validation() -> None:
    """Verify EventEnvelope generates defaults and validates event types."""
    envelope = EventEnvelope(
        type=TRAFFIC_UPDATE,
        payload={"flow": 120},
        source="signals-api",
    )
    assert isinstance(envelope.event_id, UUID)
    assert isinstance(envelope.timestamp, datetime)
    assert envelope.timestamp.tzinfo is not None
    assert envelope.payload == {"flow": 120}
    assert envelope.source == "signals-api"

    # JSON round-trip
    serialized = envelope.model_dump_json()
    reconstructed = EventEnvelope.model_validate_json(serialized)
    assert reconstructed.event_id == envelope.event_id
    assert reconstructed.type == envelope.type
    assert reconstructed.payload == envelope.payload
    assert reconstructed.source == envelope.source


def test_event_envelope_invalid_type_rejected() -> None:
    """Verify invalid event type raises a validation error."""
    with pytest.raises(ValidationError):
        EventEnvelope(
            type="invalid.event.type",  # type: ignore[arg-type]
            payload={},
            source="test",
        )


def test_get_bus_singleton() -> None:
    """Verify get_bus returns the singleton EventBus instance."""
    bus1 = get_bus()
    bus2 = get_bus()
    assert bus1 is bus2
    assert isinstance(bus1, EventBus)


def test_event_bus_degraded_mode() -> None:
    """Verify bus connects gracefully in DEGRADED mode on invalid host/port without raising."""

    async def _run():
        bad_bus = EventBus(redis_url="redis://localhost:9999/0")
        await bad_bus.connect()

        assert not bad_bus.is_connected
        assert bad_bus.is_degraded

        # publish in degraded mode returns envelope
        pub = await bad_bus.publish(TRAFFIC_UPDATE, {"delta": 1}, "test")
        assert isinstance(pub, EventEnvelope)

        # safe_publish in degraded mode returns None
        safe_pub = await bad_bus.safe_publish(TRAFFIC_UPDATE, {"delta": 1}, "test")
        assert safe_pub is None

        # read_since in degraded mode returns ([], True)
        events, stale = await bad_bus.read_since(None)
        assert events == []
        assert stale is True

        # subscribe in degraded mode yields nothing
        sub_count = 0
        async for _ in bad_bus.subscribe():
            sub_count += 1
        assert sub_count == 0

        await bad_bus.close()

    asyncio.run(_run())


def test_event_bus_live_redis_roundtrip() -> None:
    """Verify EventBus publish, dedupe, read_since, and pub/sub against local Redis."""

    async def _run():
        test_id = uuid4().hex[:8]
        stream_key = f"trafficos:events:pytest_{test_id}"
        channel_key = f"trafficos:events:pubsub:pytest_{test_id}"

        bus = EventBus(
            redis_url="redis://localhost:6379/0",
            stream_key=stream_key,
            pubsub_channel=channel_key,
        )
        await bus.connect()
        assert bus.is_connected
        assert not bus.is_degraded

        try:
            # Publish two events
            e1 = await bus.publish(TRAFFIC_UPDATE, {"count": 10}, "test-sensor")
            e2 = await bus.publish(SIGNAL_CHANGE, {"phase": "green"}, "signals-api")

            assert isinstance(e1, EventEnvelope)
            assert isinstance(e2, EventEnvelope)

            # Replay all events
            all_events, stale = await bus.read_since(None)
            assert not stale
            assert len(all_events) == 2
            assert all_events[0].event_id == e1.event_id
            assert all_events[1].event_id == e2.event_id

            # Replay since e1
            since_e1, stale_e1 = await bus.read_since(e1.event_id)
            assert not stale_e1
            assert len(since_e1) == 1
            assert since_e1[0].event_id == e2.event_id

            # Replay since e2
            since_e2, stale_e2 = await bus.read_since(e2.event_id)
            assert not stale_e2
            assert len(since_e2) == 0

            # Replay since unknown id -> stale=True
            unknown_events, stale_unknown = await bus.read_since(uuid4())
            assert stale_unknown is True
            assert unknown_events == []

            # Deduplication test: re-publishing e1 should not add entry to stream
            dup = await bus.publish(
                TRAFFIC_UPDATE,
                {"count": 999},
                "test-sensor",
                event_id=e1.event_id,
            )
            assert dup.event_id == e1.event_id
            stream_len = await bus._redis.xlen(stream_key)
            assert stream_len == 2

            # safe_publish test
            safe_result = await bus.safe_publish(INCIDENT_CREATED, {"desc": "stall"}, "patrol")
            assert safe_result is not None
            assert safe_result.type == INCIDENT_CREATED

        finally:
            if bus._redis is not None:
                await bus._redis.delete(stream_key)
                await bus._redis.delete(f"{bus.DEDUPE_KEY_PREFIX}{e1.event_id}")
                await bus._redis.delete(f"{bus.DEDUPE_KEY_PREFIX}{e2.event_id}")
                if "safe_result" in locals() and safe_result:
                    await bus._redis.delete(f"{bus.DEDUPE_KEY_PREFIX}{safe_result.event_id}")
                await bus.close()

    asyncio.run(_run())


def test_event_bus_pubsub_fanout() -> None:
    """Verify live fan-out message delivery via subscribe() on Pub/Sub."""

    async def _run():
        test_id = uuid4().hex[:8]
        stream_key = f"trafficos:events:pubsub_stream_{test_id}"
        channel_key = f"trafficos:events:pubsub_chan_{test_id}"

        bus_sub = EventBus(redis_url="redis://localhost:6379/0", stream_key=stream_key, pubsub_channel=channel_key)
        bus_pub = EventBus(redis_url="redis://localhost:6379/0", stream_key=stream_key, pubsub_channel=channel_key)

        await bus_sub.connect()
        await bus_pub.connect()

        received: list[EventEnvelope] = []

        async def listener() -> None:
            async for envelope in bus_sub.subscribe():
                received.append(envelope)
                if len(received) >= 1:
                    break

        listen_task = asyncio.create_task(listener())
        # Give the subscriber a brief moment to connect to Redis
        await asyncio.sleep(0.1)

        published = await bus_pub.publish(SYSTEM_STATUS, {"status": "operational"}, "health-check")
        await asyncio.wait_for(listen_task, timeout=3.0)

        assert len(received) == 1
        assert received[0].event_id == published.event_id
        assert received[0].payload == {"status": "operational"}

        if bus_pub._redis is not None:
            await bus_pub._redis.delete(stream_key)
            await bus_pub._redis.delete(f"{bus_pub.DEDUPE_KEY_PREFIX}{published.event_id}")

        await bus_sub.close()
        await bus_pub.close()

    asyncio.run(_run())
