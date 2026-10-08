"""Smoke verification script for AI TrafficOS Phase 9 Real-Time EventBus.

Tests against REAL local Redis (localhost:6379):
1. Connects to Redis and confirms connection state.
2. Publishes 2 distinct events (traffic.update, congestion.change).
3. Reads them back via read_since (chronological ordering, partial replay).
4. Verifies deduplication guard (same event_id published twice -> stream contains it once).
5. Verifies stale=True when querying an unknown last_event_id.
6. Verifies degraded mode tolerance against a non-existent port (no exceptions raised).
"""

import asyncio
import sys
from pathlib import Path
from uuid import uuid4

# Ensure backend directory is in sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = REPO_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.realtime.bus import EventBus
from app.realtime.events import (
    CONGESTION_CHANGE,
    TRAFFIC_UPDATE,
    EventEnvelope,
)


async def run_smoke_verification() -> bool:
    print("=" * 70)
    print("AI TrafficOS Phase 9: Real-time EventBus Smoke Verification")
    print("=" * 70)

    smoke_run_id = uuid4().hex[:8]
    stream_key = f"trafficos:events:smoke_{smoke_run_id}"
    pubsub_channel = f"trafficos:events:pubsub:smoke_{smoke_run_id}"

    bus = EventBus(
        redis_url="redis://localhost:6379/0",
        stream_key=stream_key,
        pubsub_channel=pubsub_channel,
    )

    try:
        # 1. Connect
        print("\n[Step 1] Connecting to local Redis at localhost:6379...")
        await bus.connect()
        assert bus.is_connected, "Expected bus.is_connected to be True"
        assert not bus.is_degraded, "Expected bus.is_degraded to be False"
        print("  ✓ Connected successfully (is_connected=True, is_degraded=False)")

        # 2. Publish 2 events
        print("\n[Step 2] Publishing 2 real-time events...")
        event1 = await bus.publish(
            event_type=TRAFFIC_UPDATE,
            payload={"intersection_id": 42, "vehicle_count": 17, "avg_speed_mph": 34.5},
            source="signals-api",
        )
        assert isinstance(event1, EventEnvelope)
        assert event1.type == TRAFFIC_UPDATE
        assert event1.source == "signals-api"
        print(f"  ✓ Published Event 1: ID={event1.event_id}, type={event1.type}")

        event2 = await bus.publish(
            event_type=CONGESTION_CHANGE,
            payload={"intersection_id": 42, "level": "heavy", "delay_seconds": 65},
            source="control-engine",
        )
        assert isinstance(event2, EventEnvelope)
        assert event2.type == CONGESTION_CHANGE
        assert event2.source == "control-engine"
        print(f"  ✓ Published Event 2: ID={event2.event_id}, type={event2.type}")

        # 3. Read back via read_since
        print("\n[Step 3] Replaying stream via read_since...")
        # 3a. Replay from beginning (last_event_id=None)
        all_events, stale = await bus.read_since(None)
        assert not stale, "Expected stale=False when reading from start"
        assert len(all_events) == 2, f"Expected 2 events, got {len(all_events)}"
        assert all_events[0].event_id == event1.event_id
        assert all_events[1].event_id == event2.event_id
        print("  ✓ read_since(None): returned both events in order, stale=False")

        # 3b. Replay since event1
        since_e1, stale_e1 = await bus.read_since(event1.event_id)
        assert not stale_e1, "Expected stale=False for known event1"
        assert len(since_e1) == 1, f"Expected 1 event since e1, got {len(since_e1)}"
        assert since_e1[0].event_id == event2.event_id
        print("  ✓ read_since(event1.id): returned [event2], stale=False")

        # 3c. Replay since event2
        since_e2, stale_e2 = await bus.read_since(event2.event_id)
        assert not stale_e2, "Expected stale=False for known event2"
        assert len(since_e2) == 0, f"Expected 0 new events since e2, got {len(since_e2)}"
        print("  ✓ read_since(event2.id): returned empty list, stale=False")

        # 4. Verify deduplication guard
        print("\n[Step 4] Verifying deduplication guard...")
        dup_event = await bus.publish(
            event_type=TRAFFIC_UPDATE,
            payload={"intersection_id": 42, "vehicle_count": 999},  # Changed payload
            source="signals-api",
            event_id=event1.event_id,  # SAME event_id
        )
        assert dup_event.event_id == event1.event_id
        # Verify Redis stream still contains only 2 entries (event1 was not re-appended)
        stream_len = await bus._redis.xlen(stream_key)
        assert stream_len == 2, f"Expected stream length to remain 2, but got {stream_len}"
        print(f"  ✓ Deduplication confirmed: stream length remains {stream_len} after duplicate publish")

        # 5. Verify stale=True for unknown last_event_id
        print("\n[Step 5] Verifying stale=True for unknown last_event_id...")
        unknown_id = uuid4()
        events_unknown, stale_unknown = await bus.read_since(unknown_id)
        assert stale_unknown is True, "Expected stale=True for unknown event_id"
        assert events_unknown == [], f"Expected empty list, got {events_unknown}"
        print(f"  ✓ read_since({unknown_id}): returned ([], stale=True)")

        # 6. Verify degraded mode against bad port
        print("\n[Step 6] Verifying DEGRADED mode tolerance against bad port (localhost:9999)...")
        degraded_bus = EventBus(redis_url="redis://localhost:9999/0")
        await degraded_bus.connect()  # Must not raise
        assert not degraded_bus.is_connected, "Expected degraded_bus.is_connected to be False"
        assert degraded_bus.is_degraded, "Expected degraded_bus.is_degraded to be True"
        print("  ✓ connect() failed gracefully: is_degraded=True, no exception raised")

        # Publish in degraded mode (must be logged no-op)
        deg_pub = await degraded_bus.publish(TRAFFIC_UPDATE, {"k": "v"}, "test")
        assert isinstance(deg_pub, EventEnvelope), "Expected envelope returned from degraded publish"
        print("  ✓ publish() in degraded mode: completed as no-op without raising")

        # safe_publish in degraded mode
        safe_res = await degraded_bus.safe_publish(TRAFFIC_UPDATE, {"k": "v"}, "test")
        assert safe_res is None, "Expected None from safe_publish in degraded mode"
        print("  ✓ safe_publish() in degraded mode: returned None without raising")

        # read_since in degraded mode
        deg_events, deg_stale = await degraded_bus.read_since(None)
        assert deg_stale is True, "Expected stale=True in degraded mode"
        assert deg_events == [], "Expected empty events list in degraded mode"
        print("  ✓ read_since() in degraded mode: returned ([], stale=True) without raising")

        # subscribe in degraded mode
        yielded_items = []
        async for item in degraded_bus.subscribe():
            yielded_items.append(item)
        assert len(yielded_items) == 0, "Expected degraded subscribe to yield nothing"
        print("  ✓ subscribe() in degraded mode: yielded 0 items and completed")

        await degraded_bus.close()
        print("  ✓ close() on degraded bus: cleanly completed without raising")

    finally:
        # Cleanup Redis test keys
        if bus._redis is not None:
            await bus._redis.delete(stream_key)
            await bus._redis.delete(f"{bus.DEDUPE_KEY_PREFIX}{event1.event_id}")
            await bus._redis.delete(f"{bus.DEDUPE_KEY_PREFIX}{event2.event_id}")
            await bus.close()
            print("\n[Cleanup] Test Redis stream and dedupe keys removed.")

    print("\n" + "=" * 70)
    print("ALL SMOKE VERIFICATIONS PASSED SUCCESSFULLY!")
    print("=" * 70)
    return True


if __name__ == "__main__":
    success = asyncio.run(run_smoke_verification())
    sys.exit(0 if success else 1)
