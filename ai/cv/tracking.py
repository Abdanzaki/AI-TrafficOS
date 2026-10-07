"""Multi-object tracking and speed estimation module for AI TrafficOS perception.

Implements a robust Centroid and IoU multi-object tracker (`MultiObjectTracker`)
that maintains stable vehicle identities across video frames and computes speed
strictly based on physical displacement per second.

SPEED ESTIMATION LIMITATION & CALIBRATION STORY:
- Speed in pixels/sec: Computed as Euclidean pixel displacement divided by elapsed time (dt).
- Real-world speed (km/h): STRICTLY REQUIRES a valid `pixels_per_meter` calibration factor
  (derived from ground-truth camera calibration and ground-plane homography).
- If no calibration factor is provided, the tracker reports `speed_px_s` and sets `speed_kmh = None`.
  AI TrafficOS NEVER fabricates or guesses km/h values.
- Single images cannot produce speed values. Attempting to evaluate speed on a single frame
  returns None or raises `SingleFrameSpeedError`.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import math
from typing import Any, Sequence
import numpy as np

from ai.common.schemas import Detection
from ai.cv.exceptions import SingleFrameSpeedError


def compute_bbox_iou(
    box_a: tuple[float, float, float, float],
    box_b: tuple[float, float, float, float],
) -> float:
    """Compute Intersection-over-Union (IoU) between two bounding boxes (x1, y1, x2, y2)."""
    x_a = max(box_a[0], box_b[0])
    y_a = max(box_a[1], box_b[1])
    x_b = min(box_a[2], box_b[2])
    y_b = min(box_a[3], box_b[3])

    inter_w = max(0.0, x_b - x_a)
    inter_h = max(0.0, y_b - y_a)
    inter_area = inter_w * inter_h

    if inter_area <= 0.0:
        return 0.0

    area_a = max(0.0, box_a[2] - box_a[0]) * max(0.0, box_a[3] - box_a[1])
    area_b = max(0.0, box_b[2] - box_b[0]) * max(0.0, box_b[3] - box_b[1])
    union_area = area_a + area_b - inter_area

    if union_area <= 0.0:
        return 0.0

    return float(inter_area / union_area)


def compute_centroid(bbox: tuple[float, float, float, float]) -> tuple[float, float]:
    """Calculate the (cx, cy) 2D centroid of a bounding box."""
    return ((bbox[0] + bbox[2]) / 2.0, (bbox[1] + bbox[3]) / 2.0)


@dataclass
class TrackedVehicle:
    """Representation of an actively tracked vehicle across consecutive video frames.

    Attributes:
        track_id: Stable integer identifier across frames.
        label: Vehicle class label ('car', 'truck', 'bus', 'motorcycle').
        confidence: Detection confidence of the most recent observation.
        bbox: Current bounding box (x1, y1, x2, y2).
        centroid: Current (cx, cy) pixel coordinates.
        history: Sequence of past observations: [((cx, cy), timestamp_seconds), ...].
        speed_px_s: Displacement speed in pixels/second (None for single-frame detections).
        speed_kmh: Calibrated speed in km/h (None if no pixels_per_meter calibration provided).
        displacement_px: Pixel displacement from the immediate previous frame.
        hits: Total number of consecutive frames this track has been matched.
        lost_frames: Number of consecutive frames since this track was last detected.
        first_seen_timestamp: UTC datetime when track was first detected.
        last_seen_timestamp: UTC datetime of most recent detection.
    """

    track_id: int
    label: str
    confidence: float
    bbox: tuple[float, float, float, float]
    centroid: tuple[float, float]
    history: list[tuple[tuple[float, float], float]] = field(default_factory=list)
    speed_px_s: float | None = None
    speed_kmh: float | None = None
    displacement_px: float = 0.0
    hits: int = 1
    lost_frames: int = 0
    first_seen_timestamp: datetime | None = None
    last_seen_timestamp: datetime | None = None


def estimate_speed_from_history(
    history: list[tuple[tuple[float, float], float]],
    pixels_per_meter: float | None = None,
    max_history_window: int = 5,
    strict: bool = False,
) -> tuple[float | None, float | None]:
    """Estimate speed from a temporal sequence of ((cx, cy), timestamp_seconds) points.

    Args:
        history: Sequence of past (centroid, timestamp_seconds) observations.
        pixels_per_meter: Optional camera calibration factor (pixels per physical meter).
        max_history_window: Maximum number of recent frames to smooth over.
        strict: If True, raise SingleFrameSpeedError when fewer than 2 frames are present.

    Returns:
        tuple[float | None, float | None]: (speed_px_s, speed_kmh).
        If history has < 2 points and strict=False, returns (None, None).
        If pixels_per_meter is None or <= 0, speed_kmh is strictly None.

    Raises:
        SingleFrameSpeedError: When strict=True and history has < 2 observations.
    """
    if len(history) < 2:
        if strict:
            raise SingleFrameSpeedError(
                f"Single images or unconfirmed tracks (history length {len(history)}) cannot "
                "produce speed values without multi-frame temporal displacement."
            )
        return None, None

    # Use rolling window over recent points to smooth single-frame discrete pixel quantization
    window = history[-max_history_window:]
    (c_start, t_start) = window[0]
    (c_end, t_end) = window[-1]

    dt = t_end - t_start
    if dt <= 0.0:
        return 0.0, (0.0 if (pixels_per_meter and pixels_per_meter > 0) else None)

    dist_px = math.hypot(c_end[0] - c_start[0], c_end[1] - c_start[1])
    speed_px_s = round(dist_px / dt, 2)

    speed_kmh: float | None = None
    if pixels_per_meter is not None and pixels_per_meter > 0.0:
        speed_m_s = (dist_px / pixels_per_meter) / dt
        speed_kmh = round(speed_m_s * 3.6, 2)

    return speed_px_s, speed_kmh


class MultiObjectTracker:
    """Centroid and IoU multi-object tracker for vehicle trajectories and speed estimation.

    Features:
    - Stable integer track IDs across video frames.
    - Dual matching pipeline: primary Non-Maximum IoU matching with fallback to Centroid
      Euclidean proximity matching.
    - Honest speed estimation: reports displacement in pixels/sec and only computes km/h
      when a non-zero `pixels_per_meter` calibration parameter is provided.
    - Explicit rejection of single-frame speed estimation.
    """

    def __init__(
        self,
        iou_threshold: float = 0.3,
        max_centroid_distance: float = 90.0,
        max_lost_frames: int = 5,
        pixels_per_meter: float | None = None,
        min_hits_to_confirm: int = 1,
    ) -> None:
        """Initialize MultiObjectTracker.

        Args:
            iou_threshold: Minimum IoU to associate existing track with new detection.
            max_centroid_distance: Fallback maximum Euclidean distance (pixels) for centroid match.
            max_lost_frames: Maximum frames to retain a track without updates before deletion.
            pixels_per_meter: Ground-plane camera calibration factor. If None, speed in km/h is None.
            min_hits_to_confirm: Minimum detections required to consider track confirmed.
        """
        self.iou_threshold = float(iou_threshold)
        self.max_centroid_distance = float(max_centroid_distance)
        self.max_lost_frames = int(max_lost_frames)
        self.pixels_per_meter = float(pixels_per_meter) if pixels_per_meter is not None else None
        self.min_hits_to_confirm = int(min_hits_to_confirm)

        self._next_track_id: int = 1
        self._tracks: dict[int, TrackedVehicle] = {}
        self._current_frame_index: int = 0

    @property
    def active_tracks(self) -> list[TrackedVehicle]:
        """List of active confirmed tracks (returned as snapshot copies)."""
        return [
            TrackedVehicle(
                track_id=t.track_id,
                label=t.label,
                confidence=t.confidence,
                bbox=t.bbox,
                centroid=t.centroid,
                history=list(t.history),
                speed_px_s=t.speed_px_s,
                speed_kmh=t.speed_kmh,
                displacement_px=t.displacement_px,
                hits=t.hits,
                lost_frames=t.lost_frames,
                first_seen_timestamp=t.first_seen_timestamp,
                last_seen_timestamp=t.last_seen_timestamp,
            )
            for t in self._tracks.values()
            if t.lost_frames == 0 and t.hits >= self.min_hits_to_confirm
        ]

    def reset(self) -> None:
        """Reset all tracking states."""
        self._next_track_id = 1
        self._tracks.clear()
        self._current_frame_index = 0

    def update(
        self,
        detections: Sequence[Detection],
        timestamp_seconds: float | None = None,
        timestamp: datetime | None = None,
    ) -> list[TrackedVehicle]:
        """Update tracker with detections from the current frame.

        Args:
            detections: List of Detection objects for the current frame.
            timestamp_seconds: Elapsed video playback time in seconds. If None,
                synthesized from frame index assuming 30 FPS.
            timestamp: Actual datetime timestamp of the frame.

        Returns:
            list[TrackedVehicle]: List of currently active tracks.
        """
        self._current_frame_index += 1

        if timestamp_seconds is not None:
            curr_t = float(timestamp_seconds)
        else:
            curr_t = float(self._current_frame_index) / 30.0

        curr_dt = timestamp or datetime.now(timezone.utc)

        # Filter detections with valid bounding boxes
        valid_dets: list[Detection] = [d for d in detections if d.bbox is not None]

        # Case 0: If no active tracks, initialize all detections as new tracks
        if not self._tracks:
            for det in valid_dets:
                self._create_track(det, curr_t, curr_dt)
            return self.active_tracks

        existing_track_ids = list(self._tracks.keys())
        matched_tracks: set[int] = set()
        matched_dets: set[int] = set()

        # Phase 1: IoU Matching
        iou_matrix = np.zeros((len(existing_track_ids), len(valid_dets)), dtype=np.float32)
        for i, tid in enumerate(existing_track_ids):
            for j, det in enumerate(valid_dets):
                iou_matrix[i, j] = compute_bbox_iou(self._tracks[tid].bbox, det.bbox)  # type: ignore

        # Match highest IoU first
        while True:
            if iou_matrix.size == 0 or np.max(iou_matrix) < self.iou_threshold:
                break
            best_idx = np.unravel_index(np.argmax(iou_matrix), iou_matrix.shape)
            i, j = int(best_idx[0]), int(best_idx[1])
            tid = existing_track_ids[i]

            if tid not in matched_tracks and j not in matched_dets:
                self._update_track(tid, valid_dets[j], curr_t, curr_dt)
                matched_tracks.add(tid)
                matched_dets.add(j)

            # Invalidate this row and column
            iou_matrix[i, :] = -1.0
            iou_matrix[:, j] = -1.0

        # Phase 2: Centroid Proximity Fallback for remaining unmatched detections
        unmatched_tids = [tid for tid in existing_track_ids if tid not in matched_tracks]
        unmatched_det_indices = [j for j in range(len(valid_dets)) if j not in matched_dets]

        if unmatched_tids and unmatched_det_indices:
            dist_matrix = np.zeros((len(unmatched_tids), len(unmatched_det_indices)), dtype=np.float32)
            for i, tid in enumerate(unmatched_tids):
                t_cx, t_cy = self._tracks[tid].centroid
                for j_idx, det_idx in enumerate(unmatched_det_indices):
                    d_cx, d_cy = compute_centroid(valid_dets[det_idx].bbox)  # type: ignore
                    dist_matrix[i, j_idx] = math.hypot(t_cx - d_cx, t_cy - d_cy)

            while True:
                if dist_matrix.size == 0 or np.min(dist_matrix) > self.max_centroid_distance:
                    break
                best_idx = np.unravel_index(np.argmin(dist_matrix), dist_matrix.shape)
                i, j_idx = int(best_idx[0]), int(best_idx[1])
                tid = unmatched_tids[i]
                det_idx = unmatched_det_indices[j_idx]

                if tid not in matched_tracks and det_idx not in matched_dets:
                    self._update_track(tid, valid_dets[det_idx], curr_t, curr_dt)
                    matched_tracks.add(tid)
                    matched_dets.add(det_idx)

                dist_matrix[i, :] = 999999.0
                dist_matrix[:, j_idx] = 999999.0

        # Phase 3: Create new tracks for unmatched detections
        for j, det in enumerate(valid_dets):
            if j not in matched_dets:
                self._create_track(det, curr_t, curr_dt)

        # Phase 4: Handle lost tracks and aging
        dead_tracks: list[int] = []
        for tid in existing_track_ids:
            if tid not in matched_tracks:
                track = self._tracks[tid]
                track.lost_frames += 1
                if track.lost_frames > self.max_lost_frames:
                    dead_tracks.append(tid)

        for tid in dead_tracks:
            del self._tracks[tid]

        return self.active_tracks

    def _create_track(self, det: Detection, curr_t: float, curr_dt: datetime) -> TrackedVehicle:
        """Create and register a brand new TrackedVehicle."""
        assert det.bbox is not None
        centroid = compute_centroid(det.bbox)
        tid = self._next_track_id
        self._next_track_id += 1

        new_track = TrackedVehicle(
            track_id=tid,
            label=det.label,
            confidence=det.confidence,
            bbox=det.bbox,
            centroid=centroid,
            history=[(centroid, curr_t)],
            speed_px_s=None,  # Single frame: speed cannot be calculated
            speed_kmh=None,
            displacement_px=0.0,
            hits=1,
            lost_frames=0,
            first_seen_timestamp=curr_dt,
            last_seen_timestamp=curr_dt,
        )
        self._tracks[tid] = new_track
        return new_track

    def _update_track(
        self,
        tid: int,
        det: Detection,
        curr_t: float,
        curr_dt: datetime,
    ) -> None:
        """Update an existing track with new detection coordinates and compute speed."""
        assert det.bbox is not None
        track = self._tracks[tid]
        new_centroid = compute_centroid(det.bbox)
        prev_centroid = track.centroid

        disp_px = math.hypot(new_centroid[0] - prev_centroid[0], new_centroid[1] - prev_centroid[1])

        track.bbox = det.bbox
        track.centroid = new_centroid
        track.label = det.label
        track.confidence = det.confidence
        track.lost_frames = 0
        track.hits += 1
        track.displacement_px = round(disp_px, 2)
        track.last_seen_timestamp = curr_dt
        track.history.append((new_centroid, curr_t))

        # Calculate speed from multi-frame history
        speed_px_s, speed_kmh = estimate_speed_from_history(
            history=track.history,
            pixels_per_meter=self.pixels_per_meter,
            max_history_window=5,
            strict=False,
        )
        track.speed_px_s = speed_px_s
        track.speed_kmh = speed_kmh

    def get_track_speed(self, track_id: int, strict: bool = False) -> tuple[float | None, float | None]:
        """Retrieve estimated speed for a given track.

        Args:
            track_id: Track integer identifier.
            strict: If True, raise SingleFrameSpeedError when track has < 2 historical frames.

        Returns:
            tuple[float | None, float | None]: (speed_px_s, speed_kmh).

        Raises:
            KeyError: If track_id does not exist.
            SingleFrameSpeedError: If strict=True and track lacks temporal displacement history.
        """
        if track_id not in self._tracks:
            raise KeyError(f"Track ID {track_id} not found in active tracks.")

        track = self._tracks[track_id]
        return estimate_speed_from_history(
            history=track.history,
            pixels_per_meter=self.pixels_per_meter,
            strict=strict,
        )
