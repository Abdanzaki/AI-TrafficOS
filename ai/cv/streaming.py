"""Abstract StreamConsumer interface and specification for live camera feed perception.

ARCHITECTURE & FUTURE INTEGRATION CONTRACT:
--------------------------------------------
This module defines the formal abstract contract for real-time video stream ingestion
in AI TrafficOS (planned for Phase 5 / live hardware deployment).

Live Intersection Camera Architecture:
1. Physical Cameras:
   RTSP, WebRTC, HLS, or NDI edge streams mounted at municipal intersections
   (e.g. 1080p @ 15-30 FPS).
2. FrameSource / Ingestion:
   Decodes raw network video packets asynchronously with hardware acceleration (e.g. NVDEC / VAAPI)
   into normalized NumPy BGR frame arrays wrapped in `FramePacket`.
3. Backpressure & Stride Management:
   To prevent memory exhaustion and inference lag when GPU/CPU load spikes,
   a bounded ring buffer (e.g. queue size 2-5) drops oldest frames (drop-oldest strategy)
   or samples with a fixed frame stride (e.g. every 3rd or 5th frame).
4. Vision Pipeline Execution:
   - Vehicle Detection & Tracking: `YoloVehicleDetector` + `MultiObjectTracker`
   - Traffic Metrics: `compute_frame_metrics` (occupancy, queue, density)
   - Congestion Scoring: `compute_congestion_score`
   - Incident Anomaly Heuristics: `IncidentDetector` (wrong-way, stopped vehicles)
   - Traffic Signal State: `TrafficSignalDetector`
5. Aggregated Persistence:
   Rather than emitting database transactions per frame (which would flood PostgreSQL at 30 Hz),
   observations are aggregated into rolling temporal windows (e.g. 30-60 seconds) and
   persisted as `TrafficRecord` with `source='camera'`. Detected safety incidents are immediately
   persisted as `Incident` with `status='reported'`.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, AsyncIterator, Callable, Optional, Sequence
import numpy as np

from ai.common.schemas import Detection, SignalDetection
from ai.cv.congestion import CongestionResult
from ai.cv.incidents import IncidentCandidate
from ai.cv.metrics import FrameMetrics
from ai.cv.tracking import TrackedVehicle


class StreamStatus(str, Enum):
    """Lifecycle status of a camera stream consumer."""

    IDLE = "idle"
    CONNECTING = "connecting"
    STREAMING = "streaming"
    RECONNECTING = "reconnecting"
    STOPPED = "stopped"
    ERROR = "error"


class FrameDropPolicy(str, Enum):
    """Backpressure mitigation strategies for live camera feeds."""

    DROP_OLDEST = "drop_oldest"  # Discard stale frames when consumer lags (preferred for real-time)
    DROP_NEWEST = "drop_newest"  # Reject incoming frames until buffer clears
    BLOCK = "block"              # Backpressure up to video decoder (may cause latency drift)


@dataclass(frozen=True)
class StreamConfig:
    """Configuration contract for live camera stream ingestion.

    Attributes:
        camera_id: Unique hardware identifier for the intersection camera.
        stream_url: RTSP / RTMP / WebRTC endpoint URL.
        intersection_id: Optional foreign key ID of associated intersection.
        lane_id: Optional foreign key ID of monitored lane corridor.
        target_fps: Desired sampling rate (e.g. 5 to 15 FPS).
        frame_stride: Stride interval to skip frames during high load (1 = process all).
        buffer_size: Maximum frames retained in the in-memory ring buffer.
        drop_policy: Frame dropping strategy under backpressure.
        reconnect_interval_s: Seconds to wait before attempting socket reconnection.
        max_reconnect_attempts: Maximum consecutive reconnection retries before failing.
        window_duration_seconds: Temporal window for rolling TrafficRecord aggregations.
    """

    camera_id: str
    stream_url: str
    intersection_id: Optional[int] = None
    lane_id: Optional[int] = None
    target_fps: float = 10.0
    frame_stride: int = 2
    buffer_size: int = 5
    drop_policy: FrameDropPolicy = FrameDropPolicy.DROP_OLDEST
    reconnect_interval_s: float = 5.0
    max_reconnect_attempts: int = 10
    window_duration_seconds: float = 30.0


@dataclass(frozen=True)
class FramePacket:
    """Atomic frame payload emitted from an asynchronous live video source.

    Attributes:
        camera_id: Source camera identifier.
        frame_index: Monotonically increasing frame index from connection start.
        timestamp: Precision UTC capture timestamp.
        frame: 3-channel BGR numpy ndarray (height, width, 3) with uint8 pixels.
        metadata: Optional transport metadata (e.g. bitrate, PTS, packet loss).
    """

    camera_id: str
    frame_index: int
    timestamp: datetime
    frame: np.ndarray
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class StreamPerceptionResult:
    """Per-frame computer vision perception result produced by the live stream worker.

    Attributes:
        camera_id: Originating camera identifier.
        frame_index: Source frame index.
        timestamp: Measurement timestamp.
        vehicle_detections: Detected vehicles with bounding boxes and classes.
        tracks: Actively tracked vehicle identities and velocity estimations.
        metrics: Spatial frame metrics (occupancy, queue lengths, density).
        congestion: Evaluated congestion score and factors.
        signal_detections: Detected traffic lights and observed optical states.
        incident_candidates: Anomaly heuristic detections (stopped vehicle, wrong way).
    """

    camera_id: str
    frame_index: int
    timestamp: datetime
    vehicle_detections: list[Detection]
    tracks: list[TrackedVehicle]
    metrics: FrameMetrics
    congestion: CongestionResult
    signal_detections: list[SignalDetection]
    incident_candidates: list[IncidentCandidate]


class AbstractFrameSource(ABC):
    """Abstract interface for high-performance frame capture and decoding."""

    @abstractmethod
    async def open(self) -> None:
        """Establish network connection and initialize hardware/software video decoders."""
        pass

    @abstractmethod
    async def close(self) -> None:
        """Gracefully release network sockets, buffers, and decoder handles."""
        pass

    @abstractmethod
    async def get_frames(self) -> AsyncIterator[FramePacket]:
        """Asynchronously yield sequential decoded frames with backpressure management."""
        pass

    @property
    @abstractmethod
    def is_connected(self) -> bool:
        """Whether the underlying video transport is actively connected."""
        pass


class AbstractStreamConsumer(ABC):
    """Abstract architecture interface for an AI TrafficOS live camera stream processor.

    This interface defines the complete contract required to run uninterrupted,
    fault-tolerant computer vision perception on physical intersection cameras.
    """

    def __init__(self, config: StreamConfig) -> None:
        """Initialize consumer with configuration."""
        self.config = config
        self._status = StreamStatus.IDLE

    @property
    def status(self) -> StreamStatus:
        """Current operational lifecycle status."""
        return self._status

    @abstractmethod
    async def start(self) -> None:
        """Start the live streaming ingestion worker task."""
        pass

    @abstractmethod
    async def stop(self) -> None:
        """Stop streaming, release decoders, and flush trailing aggregated records."""
        pass

    @abstractmethod
    async def process_frame(self, packet: FramePacket) -> StreamPerceptionResult:
        """Execute the perception pipeline on a single decoded frame.

        Steps:
        1. BaseDetector vehicle inference.
        2. MultiObjectTracker association and speed calculation.
        3. FrameMetrics lane occupancy and queue calculation.
        4. Congestion scoring.
        5. Heuristic incident detection.
        6. Traffic signal head state classification.
        """
        pass

    @abstractmethod
    async def flush_window_telemetry(
        self,
        window_results: Sequence[StreamPerceptionResult],
    ) -> None:
        """Persist aggregated perception results to the database.

        Contract:
        - Aggregates rolling window results into a single `TrafficRecord` with `source='camera'`.
        - Persists any candidate anomalies into `Incident` with `status='reported'`.
        - Updates physical `Signal` records with current `observed_state` and confidence.
        """
        pass
