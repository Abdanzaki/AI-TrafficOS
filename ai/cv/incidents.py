"""Foundational incident and anomaly detection heuristics for AI TrafficOS.

Provides deterministic computer vision heuristics for identifying candidate traffic
anomalies:
1. Stopped-Vehicle Anomaly: Flags vehicles with near-zero speed persisting across
   N consecutive frames OUTSIDE designated queue ROIs.
2. Wrong-Way Heuristic: Compares vehicle trajectory displacement vectors against
   a per-camera expected lane direction configuration.

CRITICAL ARCHITECTURAL & HONESTY NOTICE:
----------------------------------------
These components are RULE-BASED CV HEURISTICS, NOT TRAINED MACHINE LEARNING ACCIDENT
DETECTION MODELS. Bounding boxes and optical centroid tracks do not establish intent,
mechanical failure, or collision kinematics. Every candidate emitted by this module:
- Carries an explicit method label ('stopped_vehicle_persistence_heuristic' or
  'wrong_way_direction_heuristic').
- Assigns a mathematically bounded confidence score reflecting empirical observation persistence.
- Is designated as a CANDIDATE event requiring human traffic officer validation or
  multi-sensor fusion before dispatching emergency services.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import math
from typing import Any, Sequence
import numpy as np
import cv2

from ai.cv.metrics import PolygonROI, _roi_to_points_list
from ai.cv.tracking import TrackedVehicle


@dataclass(frozen=True)
class LaneDirectionConfig:
    """Per-camera lane direction configuration for wrong-way detection.

    Attributes:
        name: Unique lane identifier (e.g. 'lane_1_northbound').
        roi: PolygonROI or sequence of (x, y) coordinates defining the lane polygon.
        expected_direction_deg: Expected motion heading in degrees (0° to 360°).
            Screen space convention:
            0°   = +X (Right / East)
            90°  = +Y (Down / South)
            180° = -X (Left / West)
            270° = -Y (Up / North)
        tolerance_deg: Angular deviation threshold beyond which vehicle is considered
            opposing traffic flow (default: 90.0°).
        min_motion_distance_px: Minimum Euclidean pixel displacement required across
            the history window to reliably compute motion angle (default: 15.0 px).
        min_history_points: Minimum history points required (default: 3).
    """

    name: str
    roi: PolygonROI | Sequence[tuple[float, float]]
    expected_direction_deg: float
    tolerance_deg: float = 90.0
    min_motion_distance_px: float = 15.0
    min_history_points: int = 3

    @classmethod
    def from_vector(
        cls,
        name: str,
        roi: PolygonROI | Sequence[tuple[float, float]],
        direction_vector: tuple[float, float],
        tolerance_deg: float = 90.0,
        min_motion_distance_px: float = 15.0,
        min_history_points: int = 3,
    ) -> "LaneDirectionConfig":
        """Instantiate LaneDirectionConfig from a 2D direction vector (dx, dy)."""
        dx, dy = float(direction_vector[0]), float(direction_vector[1])
        angle_rad = math.atan2(dy, dx)
        angle_deg = (math.degrees(angle_rad)) % 360.0
        return cls(
            name=name,
            roi=roi,
            expected_direction_deg=round(angle_deg, 2),
            tolerance_deg=tolerance_deg,
            min_motion_distance_px=min_motion_distance_px,
            min_history_points=min_history_points,
        )


@dataclass(frozen=True)
class IncidentCandidate:
    """Heuristically identified candidate incident event.

    Attributes:
        event_type: Category of anomaly ('stopped_vehicle', 'wrong_way').
        confidence: Empirical confidence score [0.0, 1.0].
        track_id: Integer tracking identifier of the associated vehicle.
        bbox: Bounding box coordinates (x1, y1, x2, y2).
        centroid: Vehicle centroid coordinates (cx, cy).
        timestamp: Measurement capture timestamp.
        method: Explicit heuristic method label.
        details: Diagnostic breakdown metadata dictionary.
    """

    event_type: str
    confidence: float
    track_id: int
    bbox: tuple[float, float, float, float]
    centroid: tuple[float, float]
    timestamp: datetime
    method: str
    details: dict[str, Any] = field(default_factory=dict)


class StoppedVehicleHeuristic:
    """Identifies stationary vehicles persisting outside designated queue zones.

    Vehicles stopped inside designated queue ROIs (such as stop bars during red lights)
    are treated as normal operational queues and explicitly ignored.
    Vehicles with near-zero speed persisting outside queue zones for N consecutive frames
    trigger candidate 'stopped_vehicle' events with confidence proportional to persistence.
    """

    def __init__(
        self,
        min_stopped_frames: int = 10,
        stopped_speed_threshold_px_s: float = 3.0,
        base_confidence: float = 0.50,
        max_confidence: float = 0.95,
        confidence_per_frame: float = 0.03,
    ) -> None:
        """Initialize StoppedVehicleHeuristic.

        Args:
            min_stopped_frames: Consecutive frames at ~zero speed required to flag (default: 10).
            stopped_speed_threshold_px_s: Speed upper bound to consider stationary (default: 3.0 px/s).
            base_confidence: Confidence assigned at threshold frame count (default: 0.50).
            max_confidence: Upper ceiling for confidence (default: 0.95).
            confidence_per_frame: Incremental confidence gain per additional stationary frame (default: 0.03).
        """
        self.min_stopped_frames = int(min_stopped_frames)
        self.stopped_speed_threshold_px_s = float(stopped_speed_threshold_px_s)
        self.base_confidence = float(base_confidence)
        self.max_confidence = float(max_confidence)
        self.confidence_per_frame = float(confidence_per_frame)

        # Mapping of track_id -> consecutive stationary frames outside queue ROIs
        self._stopped_counts: dict[int, int] = {}

    def reset(self) -> None:
        """Reset internal tracking state."""
        self._stopped_counts.clear()

    def evaluate(
        self,
        tracks: Sequence[TrackedVehicle],
        queue_rois: dict[str, PolygonROI | Sequence[tuple[float, float]]] | Sequence[PolygonROI | Sequence[tuple[float, float]]] | None = None,
        timestamp: datetime | None = None,
    ) -> list[IncidentCandidate]:
        """Evaluate tracks for stationary anomalies outside queue zones.

        Args:
            tracks: Sequence of active TrackedVehicle objects.
            queue_rois: Designated queue zone polygons where stopped vehicles are expected.
            timestamp: Frame capture timestamp.

        Returns:
            list[IncidentCandidate]: Detected stopped vehicle candidate events.
        """
        eval_time = timestamp or datetime.now(timezone.utc)
        candidates: list[IncidentCandidate] = []

        # Prepare normalized queue polygon point arrays
        queue_polys: list[np.ndarray] = []
        if queue_rois:
            roi_items = queue_rois.values() if isinstance(queue_rois, dict) else queue_rois
            for q_roi in roi_items:
                pts = _roi_to_points_list(q_roi)
                queue_polys.append(np.array(pts, dtype=np.int32).reshape((-1, 1, 2)))

        active_track_ids = set()

        for track in tracks:
            tid = track.track_id
            active_track_ids.add(tid)
            cx, cy = track.centroid

            # 1. Test if vehicle is inside ANY designated queue ROI
            inside_queue = False
            for poly in queue_polys:
                if cv2.pointPolygonTest(poly, (float(cx), float(cy)), False) >= 0:
                    inside_queue = True
                    break

            if inside_queue:
                # Vehicle is in an expected queue zone (e.g. stop bar) -> reset stationary count
                self._stopped_counts[tid] = 0
                continue

            # 2. Vehicle is OUTSIDE queue zones. Check speed for standstill.
            speed = track.speed_px_s
            if speed is not None and speed <= self.stopped_speed_threshold_px_s:
                count = self._stopped_counts.get(tid, 0) + 1
                self._stopped_counts[tid] = count

                if count >= self.min_stopped_frames:
                    extra_frames = count - self.min_stopped_frames
                    conf = min(
                        self.max_confidence,
                        self.base_confidence + (extra_frames * self.confidence_per_frame),
                    )
                    candidates.append(
                        IncidentCandidate(
                            event_type="stopped_vehicle",
                            confidence=round(conf, 3),
                            track_id=tid,
                            bbox=track.bbox,
                            centroid=track.centroid,
                            timestamp=eval_time,
                            method="stopped_vehicle_persistence_heuristic",
                            details={
                                "persistence_frames": count,
                                "min_threshold_frames": self.min_stopped_frames,
                                "speed_px_s": round(speed, 2),
                                "speed_kmh": track.speed_kmh,
                                "outside_queue_zones": True,
                                "summary": (
                                    f"Vehicle stationary for {count} consecutive frames "
                                    f"(speed {speed:.1f} px/s) outside queue zones."
                                ),
                            },
                        )
                    )
            else:
                # Vehicle is moving or has no confirmed stationary status -> reset counter
                self._stopped_counts[tid] = 0

        # Prune inactive tracks
        stale_ids = [tid for tid in self._stopped_counts if tid not in active_track_ids]
        for tid in stale_ids:
            del self._stopped_counts[tid]

        return candidates


class WrongWayHeuristic:
    """Identifies vehicles moving counter to designated lane directions.

    Compares the historical displacement vector of each tracked vehicle against
    the configured lane heading angle. Requires per-camera lane geometry configuration.
    """

    def __init__(
        self,
        min_alignment_confidence: float = 0.50,
        max_confidence: float = 0.95,
    ) -> None:
        """Initialize WrongWayHeuristic.

        Args:
            min_alignment_confidence: Base confidence for threshold opposing motion (default: 0.50).
            max_confidence: Maximum confidence ceiling for near-180° head-on opposition (default: 0.95).
        """
        self.min_alignment_confidence = float(min_alignment_confidence)
        self.max_confidence = float(max_confidence)

    def evaluate(
        self,
        tracks: Sequence[TrackedVehicle],
        lane_configs: Sequence[LaneDirectionConfig] | dict[str, LaneDirectionConfig],
        timestamp: datetime | None = None,
    ) -> list[IncidentCandidate]:
        """Evaluate tracks for wrong-way motion against configured lane directions.

        Args:
            tracks: Sequence of active TrackedVehicle objects.
            lane_configs: Sequence or mapping of LaneDirectionConfig definitions.
            timestamp: Frame capture timestamp.

        Returns:
            list[IncidentCandidate]: Detected wrong-way candidate events.
        """
        eval_time = timestamp or datetime.now(timezone.utc)
        candidates: list[IncidentCandidate] = []

        configs = list(lane_configs.values()) if isinstance(lane_configs, dict) else list(lane_configs)
        if not configs:
            return candidates

        # Precompute polygon arrays for each lane config
        prepared_configs: list[tuple[LaneDirectionConfig, np.ndarray]] = []
        for cfg in configs:
            pts = _roi_to_points_list(cfg.roi)
            poly_np = np.array(pts, dtype=np.int32).reshape((-1, 1, 2))
            prepared_configs.append((cfg, poly_np))

        for track in tracks:
            cx, cy = track.centroid

            # Check track against each configured lane
            for cfg, poly_np in prepared_configs:
                if cv2.pointPolygonTest(poly_np, (float(cx), float(cy)), False) < 0:
                    continue

                # Vehicle is inside this lane ROI. Check motion history.
                if len(track.history) < cfg.min_history_points:
                    continue

                # Compute net displacement across recent history window
                window = track.history[-max(cfg.min_history_points, 5):]
                start_centroid, _ = window[0]
                end_centroid, _ = window[-1]

                dx = end_centroid[0] - start_centroid[0]
                dy = end_centroid[1] - start_centroid[1]
                distance = math.hypot(dx, dy)

                if distance < cfg.min_motion_distance_px:
                    # Vehicle has not traveled far enough to reliably determine trajectory heading
                    continue

                # Screen space heading angle
                motion_rad = math.atan2(dy, dx)
                motion_deg = (math.degrees(motion_rad)) % 360.0

                # Compute shortest angular deviation |actual - expected| in [-180, 180]
                diff = ((motion_deg - cfg.expected_direction_deg + 180.0) % 360.0) - 180.0
                abs_dev = abs(diff)

                if abs_dev > cfg.tolerance_deg:
                    # Opposing motion detected!
                    # Scale confidence: 90° deviation -> min_confidence; 180° deviation -> max_confidence
                    opposing_span = 180.0 - cfg.tolerance_deg
                    if opposing_span > 0:
                        alignment_ratio = (abs_dev - cfg.tolerance_deg) / opposing_span
                    else:
                        alignment_ratio = 1.0

                    conf = self.min_alignment_confidence + (
                        (self.max_confidence - self.min_alignment_confidence) * alignment_ratio
                    )
                    conf = min(self.max_confidence, max(self.min_alignment_confidence, conf))

                    candidates.append(
                        IncidentCandidate(
                            event_type="wrong_way",
                            confidence=round(conf, 3),
                            track_id=track.track_id,
                            bbox=track.bbox,
                            centroid=track.centroid,
                            timestamp=eval_time,
                            method="wrong_way_direction_heuristic",
                            details={
                                "lane_name": cfg.name,
                                "motion_angle_deg": round(motion_deg, 1),
                                "expected_angle_deg": round(cfg.expected_direction_deg, 1),
                                "angular_deviation_deg": round(abs_dev, 1),
                                "displacement_px": round(distance, 1),
                                "summary": (
                                    f"Vehicle heading {motion_deg:.1f}° opposes expected "
                                    f"lane heading {cfg.expected_direction_deg:.1f}° by {abs_dev:.1f}° "
                                    f"in lane '{cfg.name}'."
                                ),
                            },
                        )
                    )

        return candidates


class IncidentDetector:
    """Unified incident candidate detector combining stopped and wrong-way heuristics.

    Designed for frame-by-frame invocation alongside multi-object tracking.
    """

    def __init__(
        self,
        stopped_heuristic: StoppedVehicleHeuristic | None = None,
        wrong_way_heuristic: WrongWayHeuristic | None = None,
    ) -> None:
        """Initialize IncidentDetector with component heuristics."""
        self.stopped_heuristic = stopped_heuristic or StoppedVehicleHeuristic()
        self.wrong_way_heuristic = wrong_way_heuristic or WrongWayHeuristic()

    def reset(self) -> None:
        """Reset internal heuristic states."""
        self.stopped_heuristic.reset()

    def detect_incidents(
        self,
        tracks: Sequence[TrackedVehicle],
        queue_rois: dict[str, PolygonROI | Sequence[tuple[float, float]]] | Sequence[PolygonROI | Sequence[tuple[float, float]]] | None = None,
        lane_configs: Sequence[LaneDirectionConfig] | dict[str, LaneDirectionConfig] | None = None,
        timestamp: datetime | None = None,
    ) -> list[IncidentCandidate]:
        """Detect candidate traffic anomalies in the current frame.

        Args:
            tracks: Sequence of active TrackedVehicle objects from MultiObjectTracker.
            queue_rois: Designated queue regions where stopping is expected.
            lane_configs: Lane direction specifications for wrong-way detection.
            timestamp: Frame measurement timestamp.

        Returns:
            list[IncidentCandidate]: Consolidated list of candidate incident events.
        """
        results: list[IncidentCandidate] = []

        # 1. Stopped-Vehicle Anomaly Heuristic
        stopped_candidates = self.stopped_heuristic.evaluate(
            tracks=tracks,
            queue_rois=queue_rois,
            timestamp=timestamp,
        )
        results.extend(stopped_candidates)

        # 2. Wrong-Way Motion Heuristic
        if lane_configs:
            wrong_way_candidates = self.wrong_way_heuristic.evaluate(
                tracks=tracks,
                lane_configs=lane_configs,
                timestamp=timestamp,
            )
            results.extend(wrong_way_candidates)

        return results
