"""Video processing pipeline for AI TrafficOS perception subsystems.

Implements `VideoProcessor` which ingests video streams and files, samples frames
at a configurable stride for CPU efficiency, coordinates detection, tracking,
and metric calculation, and yields timestamped per-frame results.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator, Sequence
import numpy as np
import cv2

from ai.common.schemas import Detection
from ai.cv.detectors import BaseDetector
from ai.cv.exceptions import (
    CorruptVideoError,
    EmptyVideoError,
    UnsupportedVideoFormatError,
    VideoOpenError,
    VideoProcessingError,
)
from ai.cv.metrics import FrameMetrics, PolygonROI, compute_frame_metrics
from ai.cv.tracking import MultiObjectTracker, TrackedVehicle
from ai.cv.yolo_detector import YoloVehicleDetector


@dataclass(frozen=True)
class VideoFrameResult:
    """Per-frame output record yielded by the video processing pipeline.

    Attributes:
        frame_index: Sequential zero-based frame index from source video.
        timestamp_seconds: Playback time offset in seconds from video start.
        timestamp: Datetime timestamp associated with this frame.
        detections: Raw Detection objects emitted by the detector.
        tracks: Actively tracked vehicles with assigned IDs and estimated speeds.
        metrics: Computed traffic metrics (counts, density, lane occupancy, queue length).
    """

    frame_index: int
    timestamp_seconds: float
    timestamp: datetime
    detections: list[Detection]
    tracks: list[TrackedVehicle]
    metrics: FrameMetrics


class VideoProcessor:
    """End-to-end video stream processor for traffic detection, tracking, and metrics.

    Features:
    - Frame Stride Sampling: Configurable `frame_stride` reduces CPU burden by skipping
      frames (e.g., stride=2 or 5) while maintaining stable tracking via timestamp adjustments.
    - Robust Video Validation: Verifies file existence, decodability, stream emptiness,
      and frame integrity with typed exceptions.
    - Integrated Perception: Glues together BaseDetector, MultiObjectTracker, and
      FrameMetrics into a clean streaming generator.
    """

    SUPPORTED_EXTENSIONS: tuple[str, ...] = (
        ".mp4",
        ".avi",
        ".mkv",
        ".mov",
        ".wmv",
        ".m4v",
        ".webm",
    )

    def __init__(
        self,
        detector: BaseDetector | None = None,
        tracker: MultiObjectTracker | None = None,
        frame_stride: int = 1,
        rois: dict[str, PolygonROI | Sequence[tuple[float, float]]] | None = None,
        queue_rois: dict[str, PolygonROI | Sequence[tuple[float, float]]] | None = None,
        pixels_per_meter: float | None = None,
        speed_threshold_px_s: float = 5.0,
    ) -> None:
        """Initialize VideoProcessor.

        Args:
            detector: Concrete BaseDetector instance (defaults to YoloVehicleDetector).
            tracker: MultiObjectTracker instance (defaults to new instance).
            frame_stride: Stride interval for frame sampling (1 = every frame, 2 = every 2nd, etc.).
            rois: Dictionary of named polygon ROIs for lane occupancy calculation.
            queue_rois: Dictionary of named polygon ROIs for queue length calculation.
            pixels_per_meter: Calibration parameter for physical speed estimation in km/h.
            speed_threshold_px_s: Speed threshold in pixels/sec to qualify as queued low-movement.

        Raises:
            ValueError: If frame_stride < 1.
        """
        if frame_stride < 1:
            raise ValueError(f"frame_stride must be an integer >= 1, got {frame_stride}.")

        self.detector = detector if detector is not None else YoloVehicleDetector()
        self.tracker = (
            tracker
            if tracker is not None
            else MultiObjectTracker(pixels_per_meter=pixels_per_meter)
        )
        self.frame_stride = int(frame_stride)
        self.rois = rois or {}
        self.queue_rois = queue_rois or {}
        self.pixels_per_meter = pixels_per_meter
        self.speed_threshold_px_s = float(speed_threshold_px_s)

    def _validate_video_path(self, path: Path) -> None:
        """Validate input video file path and container extension."""
        if not path.exists():
            raise VideoOpenError(f"Video file does not exist: {path}")
        if not path.is_file():
            raise VideoOpenError(f"Specified video path is not a regular file: {path}")
        if path.stat().st_size == 0:
            raise EmptyVideoError(f"Video file is 0 bytes (empty file): {path}")

        # Check extension
        ext = path.suffix.lower()
        if ext and ext not in self.SUPPORTED_EXTENSIONS:
            raise UnsupportedVideoFormatError(
                f"Unsupported video container extension '{ext}'. "
                f"Supported extensions: {self.SUPPORTED_EXTENSIONS}"
            )

    def process_video(
        self,
        video_source: str | Path | cv2.VideoCapture,
        max_frames: int | None = None,
        start_time: datetime | None = None,
    ) -> Iterator[VideoFrameResult]:
        """Process video frames on configured stride, yielding per-frame perception results.

        Args:
            video_source: File path to video or pre-opened cv2.VideoCapture instance.
            max_frames: Optional upper limit on the total number of source frames to read.
            start_time: Starting UTC datetime for video recording (defaults to current UTC).

        Yields:
            VideoFrameResult: Per-sampled-frame perception results.

        Raises:
            VideoOpenError: If file cannot be found or opened.
            UnsupportedVideoFormatError: If video format or codec is unsupported.
            EmptyVideoError: If video source contains 0 frames.
            CorruptVideoError: If frame data is corrupted or cannot be decoded.
        """
        is_external_cap = isinstance(video_source, cv2.VideoCapture)
        if is_external_cap:
            cap = video_source
        else:
            path = Path(video_source)
            self._validate_video_path(path)
            cap = cv2.VideoCapture(str(path))

        if not cap.isOpened():
            raise VideoOpenError(f"OpenCV failed to open video source: {video_source}")

        fps = cap.get(cv2.CAP_PROP_FPS)
        if fps <= 0.0 or np.isnan(fps):
            fps = 30.0

        base_dt = start_time or datetime.now(timezone.utc)

        # Read the first frame to verify decodability and detect empty streams
        ret, first_frame = cap.read()
        if not ret or first_frame is None or first_frame.size == 0:
            if not is_external_cap:
                cap.release()
            raise EmptyVideoError(f"Video stream yielded 0 readable frames: {video_source}")

        try:
            raw_frame_idx = 0
            frames_processed = 0

            # Process first frame (index 0 is always sampled since 0 % stride == 0)
            yield self._process_single_frame(
                frame=first_frame,
                frame_idx=raw_frame_idx,
                fps=fps,
                base_dt=base_dt,
            )
            frames_processed += 1

            # Process subsequent frames
            while True:
                if max_frames is not None and (raw_frame_idx + 1) >= max_frames:
                    break

                ret, frame = cap.read()
                if not ret:
                    # Reached end of stream normally
                    break

                raw_frame_idx += 1

                if frame is None or frame.size == 0:
                    raise CorruptVideoError(f"Decoded empty/corrupt frame at index {raw_frame_idx}")

                # Stride check
                if raw_frame_idx % self.frame_stride != 0:
                    continue

                yield self._process_single_frame(
                    frame=frame,
                    frame_idx=raw_frame_idx,
                    fps=fps,
                    base_dt=base_dt,
                )
                frames_processed += 1

        finally:
            if not is_external_cap:
                cap.release()

    def _process_single_frame(
        self,
        frame: np.ndarray,
        frame_idx: int,
        fps: float,
        base_dt: datetime,
    ) -> VideoFrameResult:
        """Internal helper to execute detection, tracking, and metrics on a single frame."""
        t_sec = float(frame_idx) / fps
        frame_dt = base_dt + timedelta(seconds=t_sec)

        # 1. Detection
        detections = self.detector.detect(frame, timestamp=frame_dt)

        # 2. Multi-Object Tracking
        tracks = self.tracker.update(
            detections=detections,
            timestamp_seconds=t_sec,
            timestamp=frame_dt,
        )

        # 3. Traffic Metrics
        metrics = compute_frame_metrics(
            detections=detections,
            tracks=tracks,
            frame_shape=frame.shape,
            rois=self.rois,
            queue_rois=self.queue_rois,
            speed_threshold_px_s=self.speed_threshold_px_s,
            timestamp=frame_dt,
        )

        return VideoFrameResult(
            frame_index=frame_idx,
            timestamp_seconds=round(t_sec, 3),
            timestamp=frame_dt,
            detections=detections,
            tracks=tracks,
            metrics=metrics,
        )
