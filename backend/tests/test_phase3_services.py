"""Pure unit tests for Phase 3 routing services and queue primitives.

Tests in-memory data structures without database access:
- DispatchQueue: Multi-attribute priority queue ordering (severity-descending, emergency priority tie-breaking,
  FIFO timestamp resolution), peek idempotence, and IndexError on empty queue.
- EventBuffer: Bounded double-ended ring buffer capacity adherence, drop-tail eviction tracking,
  FIFO drain ordering, and operational stats dictionary keys.
- SlidingWindow: Rolling statistical aggregation (mean, min, max, count) and sliding window sample eviction.
- RoadGraph: Topological operations, bidirectional expansion, unidirectional arc handling, edge lookups,
  and neighbor traversals.
"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import pytest

from app.models.emergency import EmergencyEvent
from app.models.event import Incident
from app.services.routing.dispatch import (
    SEVERITY_RANK,
    DispatchItem,
    DispatchQueue,
)
from app.services.routing.graph import Edge, RoadGraph
from app.services.routing.queues import EventBuffer, SlidingWindow


# ==============================================================================
# 1. DispatchQueue Tests
# ==============================================================================

def test_dispatch_queue_severity_and_fifo_ordering():
    """Verify pop order is severity-descending, and ties are broken by oldest-first."""
    queue = DispatchQueue()
    base_time = datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc)

    # Push incidents with varying severities and created_at timestamps
    # Severities: critical (4), high (3), medium (2), low (1), unknown (0)
    incidents = [
        Incident(id=1, severity="low", created_at=base_time + timedelta(minutes=10), description="Minor debris"),
        Incident(id=2, severity="critical", created_at=base_time + timedelta(minutes=20), description="Major pileup"),
        Incident(id=3, severity="critical", created_at=base_time + timedelta(minutes=5), description="Bridge collapse"),
        Incident(id=4, severity="medium", created_at=base_time + timedelta(minutes=15), description="Stalled vehicle"),
        Incident(id=5, severity="high", created_at=base_time + timedelta(minutes=30), description="Overturned lorry"),
        Incident(id=6, severity="unknown", created_at=base_time + timedelta(minutes=2), description="Unverified report"),
    ]

    for inc in incidents:
        queue.push_incident(inc)

    assert len(queue) == 6
    assert bool(queue) is True

    # Expected order:
    # 1. Critical (oldest): #3 (5 min)
    # 2. Critical (newer): #2 (20 min)
    # 3. High: #5 (30 min)
    # 4. Medium: #4 (15 min)
    # 5. Low: #1 (10 min)
    # 6. Unknown: #6 (2 min)
    expected_ids = [3, 2, 5, 4, 1, 6]
    popped_ids = []

    while queue:
        item = queue.pop()
        assert isinstance(item, DispatchItem)
        assert item.kind == "incident"
        popped_ids.append(item.ref_id)

    assert popped_ids == expected_ids
    assert len(queue) == 0


def test_dispatch_queue_emergency_priority_tie_breaking():
    """Verify higher vehicle priority breaks ties among emergencies with the same severity."""
    queue = DispatchQueue()
    base_time = datetime(2026, 10, 1, 14, 0, 0, tzinfo=timezone.utc)

    # Two emergency events with identical severity 'critical' and identical timestamp
    # Priority 5 (trauma ambulance) vs Priority 2 (patrol escort)
    em_high_prio = EmergencyEvent(
        id=101,
        vehicle_type="ambulance",
        priority=5,
        created_at=base_time,
    )
    em_low_prio = EmergencyEvent(
        id=102,
        vehicle_type="police_escort",
        priority=2,
        created_at=base_time,
    )

    # Push low priority first, then high priority
    queue.push_emergency(em_low_prio, severity="critical")
    queue.push_emergency(em_high_prio, severity="critical")

    first = queue.pop()
    second = queue.pop()

    assert first.ref_id == 101
    assert first.priority == 5
    assert second.ref_id == 102
    assert second.priority == 2


def test_dispatch_queue_peek_and_empty_errors():
    """Verify peek inspects without removal, and operations on empty queue raise IndexError."""
    queue = DispatchQueue()

    with pytest.raises(IndexError, match="pop from empty"):
        queue.pop()

    with pytest.raises(IndexError, match="peek into empty"):
        queue.peek()

    inc = Incident(id=99, severity="high", created_at=datetime.now(timezone.utc), description="Fire")
    queue.push_incident(inc)

    # Peek does not remove
    assert len(queue) == 1
    peeked = queue.peek()
    assert peeked.ref_id == 99
    assert len(queue) == 1

    # Pop removes
    popped = queue.pop()
    assert popped.ref_id == 99
    assert len(queue) == 0

    with pytest.raises(IndexError):
        queue.pop()


# ==============================================================================
# 2. EventBuffer Tests
# ==============================================================================

def test_event_buffer_capacity_overflow_and_stats():
    """Verify EventBuffer respects capacity bound, evicts oldest on overflow, and updates stats."""
    capacity = 5
    buf = EventBuffer(capacity=capacity)

    assert len(buf) == 0
    stats = buf.stats()
    assert stats == {"capacity": 5, "size": 0, "dropped": 0, "total_appended": 0}

    # Add 5 items (fill to capacity)
    for i in range(5):
        ok = buf.append(f"item_{i}")
        assert ok is True

    assert len(buf) == 5
    assert buf.stats()["dropped"] == 0
    assert buf.stats()["total_appended"] == 5

    # Append 3 additional items causing drop-tail overflow of oldest 3
    for i in range(5, 8):
        ok = buf.append(f"item_{i}")
        assert ok is False  # Evicted oldest element

    assert len(buf) == 5
    stats_overflow = buf.stats()
    assert stats_overflow["size"] == 5
    assert stats_overflow["dropped"] == 3
    assert stats_overflow["total_appended"] == 8

    # Drain remaining items in FIFO order (should be items 3, 4, 5, 6, 7)
    drained = buf.drain(10)
    assert drained == ["item_3", "item_4", "item_5", "item_6", "item_7"]
    assert len(buf) == 0


def test_event_buffer_drain_and_validation():
    """Verify drain respects max_items and negative parameters raise ValueError."""
    with pytest.raises(ValueError, match="capacity must be positive"):
        EventBuffer(capacity=0)

    with pytest.raises(ValueError, match="capacity must be positive"):
        EventBuffer(capacity=-10)

    buf = EventBuffer(capacity=10)
    for i in range(5):
        buf.append(i)

    # Partial drain
    chunk1 = buf.drain(2)
    assert chunk1 == [0, 1]
    assert len(buf) == 3

    # Negative drain raises ValueError
    with pytest.raises(ValueError, match="cannot be negative"):
        buf.drain(-1)


# ==============================================================================
# 3. SlidingWindow Tests
# ==============================================================================

def test_sliding_window_aggregation_and_sliding():
    """Verify rolling mean, min, max, count over last N samples as window slides."""
    window = SlidingWindow(size=4)

    # Empty window
    assert window.count() == 0
    assert window.mean() == 0.0
    assert window.minimum() == 0.0
    assert window.maximum() == 0.0

    # Add 3 samples: [10.0, 20.0, 30.0]
    window.add(10.0)
    window.add(20.0)
    window.add(30.0)

    assert window.count() == 3
    assert window.minimum() == 10.0
    assert window.maximum() == 30.0
    assert window.mean() == 20.0

    # Add 4th sample: [10.0, 20.0, 30.0, 40.0]
    window.add(40.0)
    assert window.count() == 4
    assert window.mean() == 25.0

    # Add 5th sample (exceeds size 4, 10.0 is evicted): [20.0, 30.0, 40.0, 100.0]
    window.add(100.0)
    assert window.count() == 4
    assert window.minimum() == 20.0
    assert window.maximum() == 100.0
    assert window.mean() == (20.0 + 30.0 + 40.0 + 100.0) / 4.0

    # Invalid window size
    with pytest.raises(ValueError, match="size must be positive"):
        SlidingWindow(size=0)


# ==============================================================================
# 4. RoadGraph Topology Tests
# ==============================================================================

def test_road_graph_bidirectional_and_unidirectional_arcs():
    """Verify bidirectional edges add opposing arcs and unidirectional edges add single arc."""
    graph = RoadGraph()

    # Bidirectional edge between node 1 and 2
    bidi_edge = Edge(
        road_id=10,
        from_id=1,
        to_id=2,
        length_km=1.5,
        speed_limit_kmh=50.0,
        bidirectional=True,
    )
    graph.add_edge(bidi_edge)

    assert graph.edge_count() == 2
    assert set(graph.node_ids()) == {1, 2}

    fwd = graph.get_edge(1, 2)
    assert fwd is not None
    assert fwd.road_id == 10
    assert fwd.length_km == 1.5

    rev = graph.get_edge(2, 1)
    assert rev is not None
    assert rev.road_id == 10
    assert rev.from_id == 2
    assert rev.to_id == 1

    # Unidirectional edge from node 2 to 3
    one_way_edge = Edge(
        road_id=20,
        from_id=2,
        to_id=3,
        length_km=2.0,
        bidirectional=False,
    )
    graph.add_edge(one_way_edge)

    assert graph.edge_count() == 3
    assert set(graph.node_ids()) == {1, 2, 3}

    assert graph.get_edge(2, 3) is not None
    assert graph.get_edge(3, 2) is None  # Reverse should not exist

    # Neighbors check
    n1 = graph.neighbors(1)
    assert len(n1) == 1
    assert n1[0].to_id == 2

    n2 = graph.neighbors(2)
    assert len(n2) == 2
    assert {e.to_id for e in n2} == {1, 3}

    # Non-existent edge lookup
    assert graph.get_edge(1, 99) is None
    assert graph.get_edge(99, 1) is None
    assert graph.neighbors(99) == []
