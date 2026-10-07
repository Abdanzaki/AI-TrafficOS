"""Traffic metrics calculation module for AI TrafficOS perception pipeline.

Computes operational traffic metrics from bounding box Detection objects and
tracked vehicles:
1. Vehicle counts: counts per class and total volume.
2. Traffic density: vehicles per frame pixel area (with documented physical calibration notes).
3. Lane occupancy: fraction of a polygon Region of Interest (ROI) covered by vehicle bounding boxes.
4. Queue length: count of low-movement vehicles inside a queue ROI across consecutive frames.

All definitions and physical limitations are explicitly documented.
No fabricated metrics, no simulated values.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Sequence
import numpy as np
import cv2

from ai.common.schemas import Detection


@dataclass(frozen=True)
class PolygonROI:
    """Region of interest defined by a 2D polygon in pixel coordinates.

    Attributes:
        name: Unique identifier or lane label (e.g., 'lane_north_bound', 'queue_zone_1').
        points: Ordered sequence of (x, y) vertex tuples enclosing the region.
    """

    name: str
    points: tuple[tuple[float, float], ...]

    @classmethod
    def from_points(cls, name: str, points: Sequence[tuple[float, float]]) -> "PolygonROI":
        """Instantiate PolygonROI from any sequence of (x, y) coordinates."""
        if len(points) < 3:
            raise ValueError(f"Polygon ROI '{name}' requires at least 3 vertices, received {len(points)}.")
        return cls(name=name, points=tuple((float(x), float(y)) for x, y in points))


@dataclass(frozen=True)
class FrameMetrics:
    """Comprehensive traffic perception metrics computed for a single video frame.

    Attributes:
        total_vehicles: Total count of physical vehicles detected in the frame.
        counts_by_class: Mapping of vehicle category to count (e.g. {'car': 4, 'truck': 1}).
        density: Number of vehicles per pixel area (vehicles / (width * height)).
        density_per_100k_px: Normalized vehicle density per 100,000 square pixels.
        lane_occupancy: Mapping of ROI name to fraction of ROI occupied [0.0, 1.0].
        queue_lengths: Mapping of ROI name to count of low-movement queued vehicles.
        timestamp: Measurement capture timestamp.
    """

    total_vehicles: int
    counts_by_class: dict[str, int]
    density: float
    density_per_100k_px: float
    lane_occupancy: dict[str, float]
    queue_lengths: dict[str, int]
    timestamp: datetime | None = None


def compute_vehicle_counts(
    detections: Sequence[Detection],
    vehicle_classes: tuple[str, ...] = ("car", "motorcycle", "bus", "truck"),
) -> tuple[dict[str, int], int]:
    """Compute per-class vehicle counts and total physical vehicle count.

    Counts instances for each recognized vehicle class. If secondary heuristic detections
    (such as 'emergency_vehicle_heuristic') share a bounding box with a primary vehicle,
    physical deduplication is applied so that a single vehicle is not double-counted.

    Args:
        detections: Sequence of Detection dataclasses from detector.
        vehicle_classes: Recognized primary vehicle class labels.

    Returns:
        tuple[dict[str, int], int]: (counts_by_class dictionary, total_vehicles integer).
    """
    counts: dict[str, int] = {cls_name: 0 for cls_name in vehicle_classes}
    seen_bboxes: set[tuple[float, float, float, float]] = set()
    total_physical_count = 0

    for det in detections:
        # Tally label in counts dictionary
        lbl = det.label
        counts[lbl] = counts.get(lbl, 0) + 1

        # Deduplicate total physical vehicle count by bounding box if available
        if det.bbox is not None:
            # Round slightly to absorb floating point variations
            box_key = (
                round(det.bbox[0], 1),
                round(det.bbox[1], 1),
                round(det.bbox[2], 1),
                round(det.bbox[3], 1),
            )
            if box_key not in seen_bboxes:
                seen_bboxes.add(box_key)
                total_physical_count += 1
        else:
            total_physical_count += 1

    return counts, total_physical_count


def calculate_traffic_density(
    detections: Sequence[Detection] | int,
    frame_shape: tuple[int, ...] | None = None,
    frame_width: float | None = None,
    frame_height: float | None = None,
) -> float:
    """Calculate 2D image-space traffic density as vehicles per frame pixel area.

    Mathematical Definition:
        Density = Total_Vehicles / (Frame_Width * Frame_Height)

    LIMITATION & CALIBRATION NOTE:
    Real-world traffic engineering density is expressed in vehicles per lane-kilometer
    (veh/km) or vehicles per square meter (veh/m^2).
    Projecting 2D camera pixel area density to physical ground plane density is strictly
    non-linear and requires per-camera geometric calibration:
    1. Camera intrinsic matrix (focal length, principal point).
    2. Camera extrinsic matrix (mount elevation, pitch, yaw, roll angles).
    3. Ground-plane homography / perspective transformation matrix.
    Without per-camera calibration, pixel-area density reflects only 2D screen space
    and MUST NOT be interpreted as physical road network density.

    Args:
        detections: Sequence of Detection objects or pre-computed integer vehicle count.
        frame_shape: Shape tuple (H, W) or (H, W, C) from image/video.
        frame_width: Explicit frame width in pixels (if frame_shape not provided).
        frame_height: Explicit frame height in pixels (if frame_shape not provided).

    Returns:
        float: Vehicles per pixel area.

    Raises:
        ValueError: If frame dimensions are missing, zero, or negative.
    """
    if frame_shape is not None and len(frame_shape) >= 2:
        h, w = float(frame_shape[0]), float(frame_shape[1])
    elif frame_width is not None and frame_height is not None:
        w, h = float(frame_width), float(frame_height)
    else:
        raise ValueError("Must provide either frame_shape or both frame_width and frame_height.")

    if w <= 0.0 or h <= 0.0:
        raise ValueError(f"Frame dimensions must be positive, got width={w}, height={h}.")

    area_pixels = w * h

    if isinstance(detections, int):
        vehicle_count = detections
    else:
        _, vehicle_count = compute_vehicle_counts(detections)

    return float(vehicle_count / area_pixels)


def _roi_to_points_list(roi: PolygonROI | Sequence[tuple[float, float]]) -> list[tuple[float, float]]:
    """Normalize PolygonROI or point sequence into a list of (x, y) float tuples."""
    if isinstance(roi, PolygonROI):
        return list(roi.points)
    if not isinstance(roi, Sequence) or len(roi) < 3:
        raise ValueError(f"ROI must be a sequence of at least 3 points, got: {roi}")
    return [(float(pt[0]), float(pt[1])) for pt in roi]


def calculate_lane_occupancy(
    detections: Sequence[Detection],
    roi: PolygonROI | Sequence[tuple[float, float]],
    frame_shape: tuple[int, ...] | None = None,
) -> float:
    """Calculate the fraction of a polygon Region of Interest (ROI) occupied by vehicle bounding boxes.

    Mathematical Definition:
        Occupancy = Area( Union(Bounding_Boxes) ∩ ROI_Polygon ) / Area( ROI_Polygon )

    Computed via OpenCV binary rasterization masks, which naturally avoids double-counting
    overlapping vehicle bounding boxes and handles arbitrary convex or concave polygons.

    LIMITATION & CALIBRATION NOTE:
    Mapping 2D image polygons (ROIs) to real physical road lanes requires manual per-camera
    geometry calibration. Because of perspective distortion (foreshortening), an identical 10m
    stretch of highway occupies significantly fewer pixels when distant from the camera than
    when near the camera. Consequently, pixel-area occupancy is an image-space proxy and
    must not be confused with physical inductive-loop time-occupancy unless inverse perspective
    mapping (IPM) is applied.

    Args:
        detections: Sequence of Detection objects containing bounding boxes.
        roi: PolygonROI or sequence of (x, y) coordinates.
        frame_shape: Optional frame shape (H, W) or (H, W, C) for bounds. If None,
            computed from maximum ROI/bbox coordinates.

    Returns:
        float: Occupancy ratio between 0.0 (completely empty) and 1.0 (fully covered).
    """
    points = _roi_to_points_list(roi)
    pts_np = np.array(points, dtype=np.int32).reshape((-1, 1, 2))

    # Determine canvas dimensions
    if frame_shape is not None and len(frame_shape) >= 2:
        canvas_h, canvas_w = int(frame_shape[0]), int(frame_shape[1])
    else:
        max_x = int(np.max(pts_np[:, 0, 0])) + 50
        max_y = int(np.max(pts_np[:, 0, 1])) + 50
        for det in detections:
            if det.bbox is not None:
                max_x = max(max_x, int(det.bbox[2]) + 50)
                max_y = max(max_y, int(det.bbox[3]) + 50)
        canvas_w = max(canvas_x, 1) if (canvas_x := max_x) else 640
        canvas_h = max(canvas_y, 1) if (canvas_y := max_y) else 640

    if canvas_w <= 0 or canvas_h <= 0:
        return 0.0

    # 1. Rasterize ROI polygon mask
    roi_mask = np.zeros((canvas_h, canvas_w), dtype=np.uint8)
    cv2.fillPoly(roi_mask, [pts_np], 1)
    roi_area_pixels = int(np.count_nonzero(roi_mask))

    if roi_area_pixels == 0:
        return 0.0

    # 2. Rasterize Union of vehicle bounding boxes mask
    bbox_mask = np.zeros((canvas_h, canvas_w), dtype=np.uint8)
    for det in detections:
        if det.bbox is None:
            continue
        x1, y1, x2, y2 = det.bbox
        ix1 = max(0, min(canvas_w, int(round(x1))))
        iy1 = max(0, min(canvas_h, int(round(y1))))
        ix2 = max(0, min(canvas_w, int(round(x2))))
        iy2 = max(0, min(canvas_h, int(round(y2))))
        if ix2 > ix1 and iy2 > iy1:
            cv2.rectangle(bbox_mask, (ix1, iy1), (ix2, iy2), 1, -1)

    # 3. Compute intersection area and occupancy fraction
    intersection_mask = np.bitwise_and(roi_mask, bbox_mask)
    occupied_pixels = int(np.count_nonzero(intersection_mask))

    occupancy_fraction = float(occupied_pixels) / float(roi_area_pixels)
    return min(1.0, max(0.0, round(occupancy_fraction, 4)))


def calculate_queue_length(
    tracks: Sequence[Any],
    roi: PolygonROI | Sequence[tuple[float, float]],
    speed_threshold_px_s: float = 5.0,
) -> int:
    """Calculate queue length as the number of low-movement vehicles inside a queue ROI.

    Definition:
    A vehicle is counted as part of a queue if:
    1. Its spatial position (centroid) is geometrically inside the designated queue ROI polygon.
    2. Its tracked speed across consecutive frames is strictly below `speed_threshold_px_s`.
       Vehicles without temporal tracking history (e.g. newly appeared in 1st frame) have
       unconfirmed motion and are excluded to avoid counting moving vehicles entering the zone.

    LIMITATION & CALIBRATION NOTE:
    Queue length in real-world traffic management represents physical meters of queued vehicles
    or vehicle count queued behind a red light stop bar. This metric counts low-speed tracked
    bounding boxes inside a camera ROI polygon. Camera occlusion (e.g., a tall bus blocking
    small sedans behind it) will cause undercounting in dense queues.

    Args:
        tracks: Sequence of TrackedVehicle objects with attributes `centroid`, `speed_px_s`, `bbox`.
        roi: PolygonROI or sequence of (x, y) coordinates defining the queue zone.
        speed_threshold_px_s: Maximum speed threshold in pixels/sec to qualify as 'low-movement'.

    Returns:
        int: Count of queued (low-movement) vehicles within the ROI.
    """
    points = _roi_to_points_list(roi)
    pts_np = np.array(points, dtype=np.int32).reshape((-1, 1, 2))

    queued_count = 0

    for track in tracks:
        # Track must have spatial position
        centroid = getattr(track, "centroid", None)
        if centroid is None:
            bbox = getattr(track, "bbox", None)
            if bbox is not None:
                centroid = ((bbox[0] + bbox[2]) / 2.0, (bbox[1] + bbox[3]) / 2.0)
            else:
                continue

        cx, cy = float(centroid[0]), float(centroid[1])

        # Test if centroid is inside ROI polygon (>= 0 indicates on edge or inside)
        if cv2.pointPolygonTest(pts_np, (cx, cy), False) < 0:
            continue

        # Check low-movement requirement across consecutive frames
        speed_px_s = getattr(track, "speed_px_s", None)
        if speed_px_s is not None and speed_px_s <= speed_threshold_px_s:
            queued_count += 1

    return queued_count


def compute_frame_metrics(
    detections: Sequence[Detection],
    tracks: Sequence[Any] | None = None,
    frame_shape: tuple[int, ...] | None = None,
    frame_width: float | None = None,
    frame_height: float | None = None,
    rois: dict[str, PolygonROI | Sequence[tuple[float, float]]] | None = None,
    queue_rois: dict[str, PolygonROI | Sequence[tuple[float, float]]] | None = None,
    speed_threshold_px_s: float = 5.0,
    timestamp: datetime | None = None,
) -> FrameMetrics:
    """Compute all operational traffic metrics for a single video frame.

    Args:
        detections: Sequence of Detection objects from detector.
        tracks: Optional sequence of TrackedVehicle objects from multi-object tracker.
        frame_shape: Frame dimensions (H, W) or (H, W, C).
        frame_width: Explicit width (if frame_shape is None).
        frame_height: Explicit height (if frame_shape is None).
        rois: Dictionary of named polygon ROIs for lane occupancy calculation.
        queue_rois: Dictionary of named polygon ROIs for queue length calculation.
        speed_threshold_px_s: Low-movement speed threshold for queue estimation.
        timestamp: Measurement timestamp.

    Returns:
        FrameMetrics: Consolidated metrics dataclass.
    """
    counts_by_class, total_vehicles = compute_vehicle_counts(detections)

    # 1. Traffic Density
    density = 0.0
    density_per_100k = 0.0
    if frame_shape is not None or (frame_width is not None and frame_height is not None):
        density = calculate_traffic_density(
            detections=total_vehicles,
            frame_shape=frame_shape,
            frame_width=frame_width,
            frame_height=frame_height,
        )
        density_per_100k = round(density * 100_000.0, 4)

    # 2. Lane Occupancy
    occupancies: dict[str, float] = {}
    if rois:
        for roi_name, roi_geom in rois.items():
            occupancies[roi_name] = calculate_lane_occupancy(
                detections=detections,
                roi=roi_geom,
                frame_shape=frame_shape,
            )

    # 3. Queue Lengths
    queue_lengths: dict[str, int] = {}
    active_tracks = tracks or []
    if queue_rois:
        for q_name, q_geom in queue_rois.items():
            queue_lengths[q_name] = calculate_queue_length(
                tracks=active_tracks,
                roi=q_geom,
                speed_threshold_px_s=speed_threshold_px_s,
            )

    # Timestamp
    ts = timestamp
    if ts is None and detections:
        ts = detections[0].timestamp

    return FrameMetrics(
        total_vehicles=total_vehicles,
        counts_by_class=counts_by_class,
        density=density,
        density_per_100k_px=density_per_100k,
        lane_occupancy=occupancies,
        queue_lengths=queue_lengths,
        timestamp=ts,
    )
