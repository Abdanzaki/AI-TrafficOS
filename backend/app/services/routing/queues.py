"""High-performance queue and streaming buffer primitives for vehicle telemetry ingest.

Provides bounded double-ended queues for ingestion pipelines and moving-window
statistical aggregators for lane-level congestion metrics.
"""

from collections import deque
from typing import Any, Optional


class EventBuffer:
    """Bounded double-ended staging buffer for real-time perception and telemetry event ingest.

    Traffic-engineering and computer-systems rationale:
        Roadside computer vision camera nodes, inductive loops, and radar sensors generate
        dense bursts of vehicle detections during peak flow intervals (thousands of events/sec).
        Using standard Python lists (`list`) for FIFO queue buffering introduces severe performance
        bottlenecks: `list.pop(0)` exhibits O(n) algorithmic complexity because the entire memory
        block must be shifted left upon every item removal.

        In contrast, `collections.deque` is implemented in C as a doubly linked list of fixed-size
        contiguous memory chunks. Both `append()` (push to right) and `popleft()` (drain from left)
        operate in guaranteed amortized O(1) time without array-shifting memory overhead.
        Furthermore, `maxlen` provides a bounded ring-buffer memory guarantee: when arrival rate
        exceeds processing throughput, the oldest unserviced telemetry records are gracefully
        evicted via drop-tail backpressure, protecting the backend from Out-Of-Memory (OOM) failures.
    """

    def __init__(self, capacity: int = 10000) -> None:
        """Initialize bounded EventBuffer with designated capacity.

        Raises:
            ValueError: If capacity is non-positive.
        """
        if capacity <= 0:
            raise ValueError(f"EventBuffer capacity must be positive, got {capacity}")
        self.capacity: int = capacity
        self._deque: deque[Any] = deque(maxlen=capacity)
        self._dropped_count: int = 0
        self._total_appended: int = 0

    def append(self, item: Any) -> bool:
        """Enqueue an item into the buffer.

        Returns:
            bool: True if the item was added without evicting previous elements;
                  False if the buffer was full and the oldest item was dropped.
        """
        was_full = len(self._deque) == self.capacity
        self._deque.append(item)
        self._total_appended += 1
        if was_full:
            self._dropped_count += 1
            return False
        return True

    def drain(self, max_items: int) -> list[Any]:
        """Drain up to max_items from the head of the buffer in FIFO order (O(1) per item).

        Raises:
            ValueError: If max_items is negative.
        """
        if max_items < 0:
            raise ValueError(f"max_items cannot be negative, got {max_items}")
        items: list[Any] = []
        count = min(max_items, len(self._deque))
        for _ in range(count):
            items.append(self._deque.popleft())
        return items

    def __len__(self) -> int:
        """Return the current number of queued items."""
        return len(self._deque)

    def stats(self) -> dict[str, int]:
        """Return operational telemetry metrics for the buffer."""
        return {
            "capacity": self.capacity,
            "size": len(self._deque),
            "dropped": self._dropped_count,
            "total_appended": self._total_appended,
        }


class SlidingWindow:
    """Deque-based rolling statistical aggregator over the last N floating-point samples.

    Traffic-engineering rationale:
        Raw traffic sensor feeds (instantaneous vehicle speeds, lane occupancy percentages,
        and camera detection confidence scores) exhibit high-frequency stochastic noise
        caused by individual vehicle platooning, stop-and-go headway gaps, and sensor jitter.
        A bounded sliding window smooths high-frequency perturbations into robust rolling
        macroscopic averages and extrema, providing stabilized inputs for adaptive signal
        timing plans and corridor congestion factors.
    """

    def __init__(self, size: int = 100) -> None:
        """Initialize sliding window with sample window size.

        Raises:
            ValueError: If size is non-positive.
        """
        if size <= 0:
            raise ValueError(f"SlidingWindow size must be positive, got {size}")
        self.size: int = size
        self._deque: deque[float] = deque(maxlen=size)

    def add(self, value: float) -> None:
        """Insert a new floating-point observation into the sliding window."""
        self._deque.append(float(value))

    def mean(self) -> float:
        """Return arithmetic mean of samples, or 0.0 if empty."""
        if not self._deque:
            return 0.0
        return sum(self._deque) / len(self._deque)

    def minimum(self) -> float:
        """Return minimum observed value within the window, or 0.0 if empty."""
        if not self._deque:
            return 0.0
        return min(self._deque)

    def maximum(self) -> float:
        """Return maximum observed value within the window, or 0.0 if empty."""
        if not self._deque:
            return 0.0
        return max(self._deque)

    def count(self) -> int:
        """Return current number of observations in the sliding window."""
        return len(self._deque)


_BUFFER: Optional[EventBuffer] = None


def get_ingest_buffer(capacity: int = 10000) -> EventBuffer:
    """Retrieve or lazily initialize the singleton EventBuffer instance.

    Parameters:
        capacity: Default capacity used if singleton instance has not yet been initialized.

    Returns:
        EventBuffer: Active singleton staging buffer.
    """
    global _BUFFER
    if _BUFFER is None:
        _BUFFER = EventBuffer(capacity=capacity)
    return _BUFFER
