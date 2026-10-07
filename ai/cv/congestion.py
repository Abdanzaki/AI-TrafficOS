"""Congestion detection and traffic-ahead analysis for AI TrafficOS perception.

Computes an operational congestion score (0 to 100 integer scale) from physical
traffic metrics (lane occupancy, traffic density, speed deficit vs free-flow, and queue ratio)
mapping directly onto `TrafficRecord.congestion_level`.

Also implements far-field traffic-ahead detection via configurable Region of Interest (ROI)
differentials with explicitly documented physical and optical camera limits.

MATHEMATICAL FORMULA & CONGESTION SCORING SPECIFICATION:
-------------------------------------------------------
The congestion score C in [0, 100] is calculated via a multi-factor linear combination:

1. Lane Occupancy Component S_occ in [0.0, 1.0]:
   If lane ROIs are provided:
       S_occ = mean_{l in Lanes}(occupancy_l)
   If no lane ROIs are defined (uncalibrated screen-space):
       S_occ = min(1.0, density_per_100k_px / jam_density_per_100k_px)
   where jam_density_per_100k_px defaults to 5.0 vehicles / 100k px.

2. Speed Deficit Component S_speed in [0.0, 1.0]:
   Reflects the ratio by which observed vehicle speed falls below free-flow speed V_free:
       Deficit = max(0.0, min(1.0, 1.0 - (V_avg / V_free)))
   - Calibrated Mode: If tracked vehicles possess calibrated km/h speeds (pixels_per_meter > 0):
       V_avg = mean(speed_kmh), V_free = free_flow_speed_kmh (default 50.0 km/h)
   - Pixel Mode: If only uncalibrated pixel speeds exist and free_flow_speed_px_s is provided:
       V_avg = mean(speed_px_s), V_free = free_flow_speed_px_s
   - Uncalibrated / Absent Speed:
       If no temporal tracking history or speed data exists (e.g. single frame, or 0 moving vehicles),
       S_speed is marked as None. The engine NEVER fabricates speed.

3. Queue Ratio Component S_queue in [0.0, 1.0]:
   Fraction of vehicles at a standstill / low-movement inside queue zones:
       S_queue = min(1.0, total_queued / max(1, total_vehicles))

4. Honest Weight Rebalancing:
   - Full Mode (when speed deficit is valid):
       C_raw = 0.45 * S_occ + 0.35 * S_speed + 0.20 * S_queue
   - Spatial-Only Mode (when speed is uncalibrated / unavailable):
       C_raw = 0.70 * S_occ + 0.30 * S_queue
   - Zero-Vehicle Edge Case:
       If total_vehicles == 0, C = 0 (an empty roadway is free-flow, not congested).

   Final Score:
       C = int(round(clamp(C_raw * 100.0, 0.0, 100.0)))
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Sequence
import numpy as np
import cv2

from ai.common.schemas import Detection
from ai.cv.metrics import (
    FrameMetrics,
    PolygonROI,
    calculate_lane_occupancy,
    calculate_traffic_density,
    _roi_to_points_list,
)
from ai.cv.tracking import TrackedVehicle


@dataclass(frozen=True)
class CongestionWeights:
    """Configurable weights for congestion score factors.

    Attributes:
        w_occupancy: Weight for lane occupancy in full mode (default: 0.45).
        w_speed_deficit: Weight for speed deficit in full mode (default: 0.35).
        w_queue: Weight for queued vehicles in full mode (default: 0.20).
        w_occupancy_no_speed: Weight for occupancy when speed is unavailable (default: 0.70).
        w_queue_no_speed: Weight for queue when speed is unavailable (default: 0.30).
    """

    w_occupancy: float = 0.45
    w_speed_deficit: float = 0.35
    w_queue: float = 0.20
    w_occupancy_no_speed: float = 0.70
    w_queue_no_speed: float = 0.30

    def __post_init__(self) -> None:
        full_sum = self.w_occupancy + self.w_speed_deficit + self.w_queue
        if abs(full_sum - 1.0) > 1e-4:
            raise ValueError(f"Full mode weights must sum to 1.0, got {full_sum:.4f}")
        no_speed_sum = self.w_occupancy_no_speed + self.w_queue_no_speed
        if abs(no_speed_sum - 1.0) > 1e-4:
            raise ValueError(f"No-speed mode weights must sum to 1.0, got {no_speed_sum:.4f}")


@dataclass(frozen=True)
class TrafficAheadResult:
    """Result of far-field 'traffic-ahead' detection.

    Attributes:
        traffic_ahead_detected: True if far-field density indicates significant upstream backup.
        far_density: Far-field occupancy or normalized vehicle density [0.0, 1.0].
        near_density: Near-field occupancy or normalized vehicle density [0.0, 1.0].
        differential: Density differential (far_density - near_density).
        method: Method label ('far_field_roi_differential_heuristic').
        limits_note: Explicit physical and optical limitations documentation.
    """

    traffic_ahead_detected: bool
    far_density: float
    near_density: float
    differential: float
    method: str = "far_field_roi_differential_heuristic"
    limits_note: str = (
        "LIMITATIONS: 2D monocular camera without depth sensor. Distant objects are subject to "
        "perspective foreshortening (lower pixel resolution per vehicle), foreground geometric occlusion "
        "(tall vehicles blocking line-of-sight to the far field), and atmospheric attenuation. "
        "Requires per-camera far-field ROI calibration."
    )


@dataclass(frozen=True)
class CongestionResult:
    """Comprehensive congestion evaluation result.

    Attributes:
        congestion_level: Overall congestion percentage [0, 100].
        vehicle_count: Total vehicles in frame.
        avg_speed_kmh: Average speed in km/h (strictly None if uncalibrated).
        avg_speed_px_s: Average speed in pixels/second (None if no active tracks).
        lane_occupancy_score: Evaluated occupancy component [0.0, 1.0].
        speed_deficit_score: Evaluated speed deficit component [0.0, 1.0], or None.
        queue_score: Evaluated queue component [0.0, 1.0].
        is_calibrated: True if physical km/h speed calibration was used.
        traffic_ahead: Optional TrafficAheadResult if far-field ROI was evaluated.
        components: Detailed sub-score and configuration breakdown dictionary.
    """

    congestion_level: int
    vehicle_count: int
    avg_speed_kmh: float | None
    avg_speed_px_s: float | None
    lane_occupancy_score: float
    speed_deficit_score: float | None
    queue_score: float
    is_calibrated: bool
    traffic_ahead: TrafficAheadResult | None = None
    components: dict[str, Any] = field(default_factory=dict)


def detect_traffic_ahead(
    detections: Sequence[Detection],
    far_roi: PolygonROI | Sequence[tuple[float, float]],
    near_roi: PolygonROI | Sequence[tuple[float, float]] | None = None,
    frame_shape: tuple[int, ...] | None = None,
    ahead_threshold: float = 0.20,
) -> TrafficAheadResult:
    """Evaluate far-field vs near-field traffic density differential.

    Identifies upstream bottlenecks or traffic backup ahead of the camera before
    the immediate stop bar or foreground becomes congested.

    PHYSICAL LIMITATIONS & HONESTY STATEMENT:
    - Single fixed 2D cameras have NO intrinsic metric depth (no stereoscopic parallax, LiDAR, or radar).
    - Perspective foreshortening compresses distant ground planes: 10 meters of distant highway
      spans significantly fewer pixels than 10 meters directly below the camera.
    - Large near vehicles (buses, trucks) occlude far-field lanes entirely.
    - Far-field vehicle detections carry higher bounding box noise at low camera mounting angles.

    Args:
        detections: Detected vehicles in the current frame.
        far_roi: Polygon ROI defining the upstream / far-field roadway horizon.
        near_roi: Optional polygon ROI defining the foreground / stop-bar roadway. If None,
            the bottom half of frame_shape or coordinate envelope is used.
        frame_shape: Frame dimensions (H, W) or (H, W, C).
        ahead_threshold: Minimum differential (far - near) to trigger traffic_ahead_detected.

    Returns:
        TrafficAheadResult: Near vs far density measurements and detection boolean.
    """
    far_occ = calculate_lane_occupancy(detections=detections, roi=far_roi, frame_shape=frame_shape)

    if near_roi is not None:
        near_occ = calculate_lane_occupancy(detections=detections, roi=near_roi, frame_shape=frame_shape)
    elif frame_shape is not None and len(frame_shape) >= 2:
        h, w = int(frame_shape[0]), int(frame_shape[1])
        # Default foreground ROI: lower 45% of the frame
        default_near_points = [
            (0.0, float(h) * 0.55),
            (float(w), float(h) * 0.55),
            (float(w), float(h)),
            (0.0, float(h)),
        ]
        near_occ = calculate_lane_occupancy(
            detections=detections,
            roi=default_near_points,
            frame_shape=frame_shape,
        )
    else:
        # Fallback: without near ROI or frame shape, near_occ is 0.0
        near_occ = 0.0

    differential = round(far_occ - near_occ, 4)
    # Traffic ahead detected if far occupancy exceeds near by threshold, or far occupancy is high (>0.50)
    traffic_ahead_detected = bool(differential >= ahead_threshold or (far_occ >= 0.50 and differential > 0.05))

    return TrafficAheadResult(
        traffic_ahead_detected=traffic_ahead_detected,
        far_density=round(far_occ, 4),
        near_density=round(near_occ, 4),
        differential=differential,
    )


def compute_congestion_score(
    metrics: FrameMetrics,
    tracks: Sequence[TrackedVehicle] | None = None,
    free_flow_speed_kmh: float = 50.0,
    free_flow_speed_px_s: float | None = None,
    jam_density_per_100k_px: float = 5.0,
    weights: CongestionWeights | None = None,
    far_roi: PolygonROI | Sequence[tuple[float, float]] | None = None,
    near_roi: PolygonROI | Sequence[tuple[float, float]] | None = None,
    detections: Sequence[Detection] | None = None,
    frame_shape: tuple[int, ...] | None = None,
) -> CongestionResult:
    """Compute operational congestion score (0-100) and traffic-ahead metrics.

    Args:
        metrics: Pre-computed FrameMetrics dataclass from current frame.
        tracks: Optional sequence of active TrackedVehicle objects.
        free_flow_speed_kmh: Expected roadway free-flow speed in km/h when calibrated.
        free_flow_speed_px_s: Optional free-flow speed in pixels/s when uncalibrated.
        jam_density_per_100k_px: Reference jam density per 100k px for uncalibrated fallback.
        weights: Custom CongestionWeights instance (defaults to standard weights).
        far_roi: Optional far-field ROI for traffic-ahead detection.
        near_roi: Optional near-field ROI for traffic-ahead comparison.
        detections: Optional detections sequence (used for far-field ROI occupancy).
        frame_shape: Frame dimensions for ROI rasterization.

    Returns:
        CongestionResult: Standardized congestion evaluation.
    """
    w = weights or CongestionWeights()
    total_vehicles = metrics.total_vehicles

    # Edge Case: Zero vehicles means completely open roadway (congestion = 0)
    if total_vehicles == 0:
        traffic_ahead_res = None
        if far_roi is not None:
            traffic_ahead_res = detect_traffic_ahead(
                detections=detections or [],
                far_roi=far_roi,
                near_roi=near_roi,
                frame_shape=frame_shape,
            )

        return CongestionResult(
            congestion_level=0,
            vehicle_count=0,
            avg_speed_kmh=None,
            avg_speed_px_s=None,
            lane_occupancy_score=0.0,
            speed_deficit_score=None,
            queue_score=0.0,
            is_calibrated=False,
            traffic_ahead=traffic_ahead_res,
            components={"reason": "empty_roadway"},
        )

    # 1. Lane Occupancy Component S_occ [0.0, 1.0]
    if metrics.lane_occupancy:
        # Mean occupancy across defined lane ROIs
        occ_vals = list(metrics.lane_occupancy.values())
        s_occ = float(np.mean(occ_vals))
    else:
        # Fallback to normalized density per 100k pixels
        s_occ = min(1.0, float(metrics.density_per_100k_px) / max(0.1, jam_density_per_100k_px))
    s_occ = min(1.0, max(0.0, s_occ))

    # 2. Queue Ratio Component S_queue [0.0, 1.0]
    if metrics.queue_lengths:
        total_queued = sum(metrics.queue_lengths.values())
        s_queue = min(1.0, float(total_queued) / float(max(1, total_vehicles)))
    elif tracks:
        # Low movement tracks (< 5.0 px/s)
        low_move_count = sum(1 for t in tracks if t.speed_px_s is not None and t.speed_px_s <= 5.0)
        s_queue = min(1.0, float(low_move_count) / float(len(tracks)))
    else:
        s_queue = 0.0

    # 3. Speed Deficit Component S_speed [0.0, 1.0]
    s_speed: float | None = None
    avg_speed_kmh: float | None = None
    avg_speed_px_s: float | None = None
    is_calibrated = False

    active_tracks = tracks or []
    calibrated_speeds = [t.speed_kmh for t in active_tracks if t.speed_kmh is not None]
    pixel_speeds = [t.speed_px_s for t in active_tracks if t.speed_px_s is not None]

    if calibrated_speeds:
        avg_speed_kmh = round(float(np.mean(calibrated_speeds)), 2)
        is_calibrated = True
        if free_flow_speed_kmh > 0.0:
            speed_ratio = avg_speed_kmh / free_flow_speed_kmh
            s_speed = min(1.0, max(0.0, 1.0 - speed_ratio))
    elif pixel_speeds and free_flow_speed_px_s is not None and free_flow_speed_px_s > 0.0:
        avg_speed_px_s = round(float(np.mean(pixel_speeds)), 2)
        speed_ratio = avg_speed_px_s / free_flow_speed_px_s
        s_speed = min(1.0, max(0.0, 1.0 - speed_ratio))
    elif pixel_speeds:
        avg_speed_px_s = round(float(np.mean(pixel_speeds)), 2)
        # Speed available in px/s, but without reference free-flow speed, do not invent deficit

    # 4. Final Congestion Score Linear Combination
    if s_speed is not None:
        raw_score = (w.w_occupancy * s_occ) + (w.w_speed_deficit * s_speed) + (w.w_queue * s_queue)
        mode = "full_multimodal"
    else:
        raw_score = (w.w_occupancy_no_speed * s_occ) + (w.w_queue_no_speed * s_queue)
        mode = "spatial_geometry_only"

    congestion_level = int(round(min(100.0, max(0.0, raw_score * 100.0))))

    # 5. Traffic Ahead Evaluation (if requested)
    traffic_ahead_res = None
    if far_roi is not None:
        traffic_ahead_res = detect_traffic_ahead(
            detections=detections or [],
            far_roi=far_roi,
            near_roi=near_roi,
            frame_shape=frame_shape,
        )

    return CongestionResult(
        congestion_level=congestion_level,
        vehicle_count=total_vehicles,
        avg_speed_kmh=avg_speed_kmh,
        avg_speed_px_s=avg_speed_px_s,
        lane_occupancy_score=round(s_occ, 4),
        speed_deficit_score=round(s_speed, 4) if s_speed is not None else None,
        queue_score=round(s_queue, 4),
        is_calibrated=is_calibrated,
        traffic_ahead=traffic_ahead_res,
        components={
            "mode": mode,
            "weights": {
                "w_occupancy": w.w_occupancy if s_speed is not None else w.w_occupancy_no_speed,
                "w_speed_deficit": w.w_speed_deficit if s_speed is not None else 0.0,
                "w_queue": w.w_queue if s_speed is not None else w.w_queue_no_speed,
            },
            "raw_score": round(raw_score, 4),
        },
    )
