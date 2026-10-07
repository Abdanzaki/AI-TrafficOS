"""Tests for AI TrafficOS Computer Vision metrics, tracking, and video processing.

Validates operational mechanics using programmatically generated synthetic fixtures:
- Synthetic drawn bounding box detections
- Occupancy math on known geometric shapes (squares, rectangles, polygons)
- Centroid / IoU multi-object tracking stability across frames
- Honest speed estimation in px/s and calibrated km/h
- Strict rejection of single-frame speed estimation
- End-to-end VideoProcessor pipeline with programmatic cv2.VideoWriter fixtures
- Typed exception hierarchy for video and frame errors
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import numpy as np
import cv2
import pytest

from ai.common.schemas import Detection
from ai.cv.detectors import BaseDetector
from ai.cv.exceptions import (
    CorruptVideoError,
    EmptyVideoError,
    SingleFrameSpeedError,
    UnsupportedVideoFormatError,
    VideoOpenError,
)
from ai.cv.metrics import (
    FrameMetrics,
    PolygonROI,
    calculate_lane_occupancy,
    calculate_queue_length,
    calculate_traffic_density,
    compute_frame_metrics,
    compute_vehicle_counts,
)
from ai.cv.tracking import (
    MultiObjectTracker,
    TrackedVehicle,
    compute_bbox_iou,
    compute_centroid,
    estimate_speed_from_history,
)
from ai.cv.video_processor import VideoFrameResult, VideoProcessor
from backend.app.vision import (
    get_metrics_calculator,
    get_vehicle_tracker,
    get_video_processor,
)


# ==============================================================================
# 1. Vehicle Counts & Classification Tests
# ==============================================================================


def test_vehicle_counts_and_deduplication():
    """Verify class-based tallying and physical deduplication of detections."""
    ts = datetime.now(timezone.utc)
    detections = [
        Detection(label="car", confidence=0.9, bbox=(10.0, 10.0, 50.0, 50.0), timestamp=ts),
        Detection(label="car", confidence=0.85, bbox=(60.0, 10.0, 100.0, 50.0), timestamp=ts),
        Detection(label="truck", confidence=0.92, bbox=(120.0, 10.0, 200.0, 80.0), timestamp=ts),
        Detection(label="bus", confidence=0.88, bbox=(220.0, 10.0, 320.0, 90.0), timestamp=ts),
        Detection(label="motorcycle", confidence=0.75, bbox=(340.0, 10.0, 370.0, 40.0), timestamp=ts),
        # Secondary emergency heuristic sharing the identical bounding box with the bus
        Detection(label="emergency_vehicle_heuristic", confidence=0.8, bbox=(220.0, 10.0, 320.0, 90.0), timestamp=ts),
    ]

    counts, total_count = compute_vehicle_counts(detections)

    assert counts["car"] == 2
    assert counts["truck"] == 1
    assert counts["bus"] == 1
    assert counts["motorcycle"] == 1
    assert counts["emergency_vehicle_heuristic"] == 1
    # 5 unique physical bounding boxes; emergency heuristic does NOT double count
    assert total_count == 5


def test_vehicle_counts_empty():
    """Verify empty detection sequence yields zero counts."""
    counts, total_count = compute_vehicle_counts([])
    assert total_count == 0
    assert counts["car"] == 0
    assert counts["truck"] == 0


# ==============================================================================
# 2. Traffic Density Tests
# ==============================================================================


def test_traffic_density_mechanics():
    """Verify traffic density formula: vehicles / (width * height)."""
    # 4 vehicles in an 800x600 frame (480,000 pixels)
    density = calculate_traffic_density(4, frame_shape=(600, 800))
    expected = 4.0 / (800.0 * 600.0)
    assert abs(density - expected) < 1e-9

    # Using explicit width/height
    density_explicit = calculate_traffic_density(2, frame_width=1000.0, frame_height=500.0)
    assert abs(density_explicit - (2.0 / 500000.0)) < 1e-9


def test_traffic_density_invalid_dimensions():
    """Verify non-positive dimensions raise ValueError."""
    with pytest.raises(ValueError, match="Frame dimensions must be positive"):
        calculate_traffic_density(1, frame_width=-100, frame_height=200)

    with pytest.raises(ValueError, match="Must provide either frame_shape"):
        calculate_traffic_density(1)


# ==============================================================================
# 3. Lane Occupancy on Known Geometry
# ==============================================================================


def test_lane_occupancy_square_geometry():
    """Verify lane occupancy math on known rectangular ROI and bounding boxes."""
    # ROI: 100x100 square from (100, 100) to (200, 200). Area = 10,000 px^2.
    roi = PolygonROI.from_points(
        "lane_test",
        [(100, 100), (200, 100), (200, 200), (100, 200)],
    )

    # 1. Detection covering exactly bottom half: (100, 150) to (200, 200) -> 5,000 px^2 -> 50%
    det_half = Detection(label="car", confidence=0.9, bbox=(100.0, 150.0, 200.0, 200.0))
    occupancy_half = calculate_lane_occupancy([det_half], roi, frame_shape=(300, 300))
    assert abs(occupancy_half - 0.5) < 0.01

    # 2. Detection covering entire ROI: (100, 100) to (200, 200) -> 100%
    det_full = Detection(label="truck", confidence=0.9, bbox=(100.0, 100.0, 200.0, 200.0))
    occupancy_full = calculate_lane_occupancy([det_full], roi, frame_shape=(300, 300))
    assert abs(occupancy_full - 1.0) < 0.01

    # 3. Detection outside ROI: (0, 0) to (50, 50) -> 0%
    det_outside = Detection(label="car", confidence=0.9, bbox=(0.0, 0.0, 50.0, 50.0))
    occupancy_outside = calculate_lane_occupancy([det_outside], roi, frame_shape=(300, 300))
    assert occupancy_outside == 0.0


def test_lane_occupancy_overlapping_boxes_no_double_count():
    """Verify overlapping vehicle boxes are unified and do not exceed union area."""
    roi = PolygonROI.from_points(
        "lane_test",
        [(100, 100), (200, 100), (200, 200), (100, 200)],
    )

    # Two overlapping boxes covering (100, 100) to (200, 160) -> 6,000 px^2 -> 60%
    box1 = Detection(label="car", confidence=0.9, bbox=(100.0, 100.0, 200.0, 140.0))  # 40%
    box2 = Detection(label="car", confidence=0.8, bbox=(100.0, 120.0, 200.0, 160.0))  # 40% (overlaps 20%)

    # Simple addition would give 80%, but correct union occupancy is 60%
    occupancy = calculate_lane_occupancy([box1, box2], roi, frame_shape=(300, 300))
    assert abs(occupancy - 0.6) < 0.02


def test_lane_occupancy_triangular_polygon():
    """Verify lane occupancy handles arbitrary non-axis-aligned polygons."""
    # Triangular wedge: vertices (0, 0), (100, 0), (0, 100). Area = 0.5 * 100 * 100 = 5000.
    roi = PolygonROI.from_points("triangle_wedge", [(0, 0), (100, 0), (0, 100)])
    # Bounding box fully encompassing the triangle
    det = Detection(label="bus", confidence=0.9, bbox=(0.0, 0.0, 100.0, 100.0))
    occupancy = calculate_lane_occupancy([det], roi, frame_shape=(200, 200))
    # All pixels inside triangle are occupied -> 1.0
    assert abs(occupancy - 1.0) < 0.01


# ==============================================================================
# 4. Queue Length Tests
# ==============================================================================


def test_queue_length_mechanics():
    """Verify queue length counts only low-movement tracked vehicles inside queue ROI."""
    roi = PolygonROI.from_points(
        "queue_zone",
        [(50, 50), (250, 50), (250, 250), (50, 250)],
    )

    # Track 1: Inside ROI, low movement (speed = 2.0 px/s <= 5.0) -> QUEUED
    t1 = TrackedVehicle(
        track_id=1,
        label="car",
        confidence=0.9,
        bbox=(100.0, 100.0, 140.0, 140.0),
        centroid=(120.0, 120.0),
        speed_px_s=2.0,
    )

    # Track 2: Inside ROI, moving fast (speed = 60.0 px/s > 5.0) -> NOT QUEUED
    t2 = TrackedVehicle(
        track_id=2,
        label="car",
        confidence=0.88,
        bbox=(150.0, 150.0, 190.0, 190.0),
        centroid=(170.0, 170.0),
        speed_px_s=60.0,
    )

    # Track 3: Outside ROI, stationary (speed = 0.0 px/s) -> NOT QUEUED (outside zone)
    t3 = TrackedVehicle(
        track_id=3,
        label="truck",
        confidence=0.91,
        bbox=(400.0, 400.0, 480.0, 480.0),
        centroid=(440.0, 440.0),
        speed_px_s=0.0,
    )

    # Track 4: Inside ROI, newly appeared (speed_px_s = None) -> NOT QUEUED (unconfirmed motion)
    t4 = TrackedVehicle(
        track_id=4,
        label="car",
        confidence=0.85,
        bbox=(80.0, 80.0, 120.0, 120.0),
        centroid=(100.0, 100.0),
        speed_px_s=None,
    )

    queue_count = calculate_queue_length([t1, t2, t3, t4], roi, speed_threshold_px_s=5.0)
    assert queue_count == 1


# ==============================================================================
# 5. Multi-Object Tracking & Honest Speed Estimation Tests
# ==============================================================================


def test_tracker_preserves_id_across_frames():
    """Verify tracker keeps stable track IDs across consecutive moving frames."""
    tracker = MultiObjectTracker(iou_threshold=0.3, max_centroid_distance=50.0)

    # Frame 0 at t=0.0s
    dets_f0 = [
        Detection(label="car", confidence=0.9, bbox=(100.0, 100.0, 160.0, 160.0)),
        Detection(label="truck", confidence=0.85, bbox=(300.0, 100.0, 400.0, 180.0)),
    ]
    tracks_f0 = tracker.update(dets_f0, timestamp_seconds=0.0)
    assert len(tracks_f0) == 2
    id_car = tracks_f0[0].track_id
    id_truck = tracks_f0[1].track_id

    # Frame 1 at t=0.1s (slight motion)
    dets_f1 = [
        Detection(label="car", confidence=0.9, bbox=(105.0, 100.0, 165.0, 160.0)),
        Detection(label="truck", confidence=0.85, bbox=(310.0, 100.0, 410.0, 180.0)),
    ]
    tracks_f1 = tracker.update(dets_f1, timestamp_seconds=0.1)
    assert len(tracks_f1) == 2

    # Track IDs must be preserved
    ids_f1 = {t.label: t.track_id for t in tracks_f1}
    assert ids_f1["car"] == id_car
    assert ids_f1["truck"] == id_truck


def test_speed_estimation_px_s_and_never_fabricate_kmh():
    """Verify speed is computed in px/s, and km/h is NEVER fabricated without calibration."""
    tracker = MultiObjectTracker(iou_threshold=0.3, pixels_per_meter=None)

    # Frame 0 at t=0.0s: centroid=(125, 125)
    d0 = [Detection(label="car", confidence=0.9, bbox=(100.0, 100.0, 150.0, 150.0))]
    tracks0 = tracker.update(d0, timestamp_seconds=0.0)
    # First frame: speed MUST be None
    assert tracks0[0].speed_px_s is None
    assert tracks0[0].speed_kmh is None

    # Frame 1 at t=0.5s: centroid moved by 30 pixels horizontally to (155, 125)
    d1 = [Detection(label="car", confidence=0.9, bbox=(130.0, 100.0, 180.0, 150.0))]
    tracks1 = tracker.update(d1, timestamp_seconds=0.5)

    # Displacement = 30px / 0.5s = 60.0 px/s
    assert tracks1[0].speed_px_s == 60.0
    # No calibration factor provided -> speed_kmh MUST be None
    assert tracks1[0].speed_kmh is None


def test_speed_estimation_with_calibration():
    """Verify calibrated speed in km/h is computed when pixels_per_meter is provided."""
    # 10 pixels per meter calibration
    tracker = MultiObjectTracker(iou_threshold=0.3, pixels_per_meter=10.0)

    # Move 50 pixels in 1.0 second:
    # 50 px / 10 px/m = 5.0 meters in 1.0s = 5.0 m/s = 5.0 * 3.6 = 18.0 km/h
    d0 = [Detection(label="car", confidence=0.9, bbox=(100.0, 100.0, 150.0, 150.0))]
    d1 = [Detection(label="car", confidence=0.9, bbox=(150.0, 100.0, 200.0, 150.0))]

    tracker.update(d0, timestamp_seconds=0.0)
    tracks = tracker.update(d1, timestamp_seconds=1.0)

    assert tracks[0].speed_px_s == 50.0
    assert tracks[0].speed_kmh == 18.0


def test_single_image_speed_rejection_raises_error():
    """Verify speed estimation on a single frame raises SingleFrameSpeedError when requested."""
    # Single observation in history
    single_point = [((100.0, 100.0), 0.0)]

    # Non-strict mode returns (None, None)
    px_s, kmh = estimate_speed_from_history(single_point, strict=False)
    assert px_s is None
    assert kmh is None

    # Strict mode raises typed SingleFrameSpeedError
    with pytest.raises(SingleFrameSpeedError, match="Single images or unconfirmed tracks"):
        estimate_speed_from_history(single_point, strict=True)

    tracker = MultiObjectTracker()
    tracker.update([Detection(label="car", confidence=0.9, bbox=(10.0, 10.0, 50.0, 50.0))], timestamp_seconds=0.0)

    with pytest.raises(SingleFrameSpeedError):
        tracker.get_track_speed(track_id=1, strict=True)


def test_tracker_deregistration_on_aging():
    """Verify tracks are dropped after max_lost_frames consecutive misses."""
    tracker = MultiObjectTracker(max_lost_frames=2)

    d0 = [Detection(label="car", confidence=0.9, bbox=(10.0, 10.0, 50.0, 50.0))]
    tracker.update(d0, timestamp_seconds=0.0)
    assert len(tracker.active_tracks) == 1

    # Frame 1: missed (lost_frames=1 <= 2)
    tracker.update([], timestamp_seconds=0.1)
    # Frame 2: missed (lost_frames=2 <= 2)
    tracker.update([], timestamp_seconds=0.2)
    # Frame 3: missed (lost_frames=3 > 2) -> dropped
    tracker.update([], timestamp_seconds=0.3)

    assert len(tracker._tracks) == 0


# ==============================================================================
# 6. End-to-End Synthetic Video Processing Pipeline Tests
# ==============================================================================


class SyntheticMockDetector(BaseDetector):
    """Deterministic synthetic detector generating a moving bounding box for testing."""

    def __init__(self, step_px: float = 10.0) -> None:
        self.step_px = step_px
        self.call_count = 0

    def detect(self, frame, timestamp=None, vehicle_ids=None):
        self.call_count += 1
        x1 = 50.0 + (self.call_count * self.step_px)
        return [
            Detection(
                label="car",
                confidence=0.95,
                bbox=(x1, 100.0, x1 + 50.0, 150.0),
                timestamp=timestamp,
            )
        ]


def create_synthetic_video_file(output_path: Path, num_frames: int = 15, fps: float = 10.0) -> Path:
    """Generate a valid synthetic video file containing moving shapes using OpenCV VideoWriter."""
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(output_path), fourcc, fps, (320, 240))

    for i in range(num_frames):
        canvas = np.full((240, 320, 3), 40, dtype=np.uint8)
        # Draw moving rectangle
        x = int(50 + i * 10)
        cv2.rectangle(canvas, (x, 100), (x + 50, 150), (0, 200, 0), -1)
        writer.write(canvas)

    writer.release()
    return output_path


def test_video_processor_synthetic_stream(tmp_path: Path):
    """Verify VideoProcessor reads synthetic video, applies stride, and computes metrics."""
    vid_file = tmp_path / "test_traffic.mp4"
    create_synthetic_video_file(vid_file, num_frames=15, fps=10.0)

    detector = SyntheticMockDetector(step_px=10.0)
    tracker = MultiObjectTracker(pixels_per_meter=5.0)  # 5 px/m calibration

    roi = PolygonROI.from_points("lane_1", [(40, 90), (300, 90), (300, 160), (40, 160)])

    processor = VideoProcessor(
        detector=detector,
        tracker=tracker,
        frame_stride=2,  # sample every 2nd frame (0, 2, 4, 6, 8, 10, 12, 14 -> 8 frames)
        rois={"lane_1": roi},
        pixels_per_meter=5.0,
    )

    results = list(processor.process_video(vid_file))

    # 15 frames with stride 2 -> frames [0, 2, 4, 6, 8, 10, 12, 14] -> 8 results
    assert len(results) == 8

    # Verify first frame (stride 0)
    first_res = results[0]
    assert first_res.frame_index == 0
    assert first_res.timestamp_seconds == 0.0
    assert len(first_res.detections) == 1
    assert len(first_res.tracks) == 1
    assert first_res.tracks[0].speed_px_s is None  # 1st frame has no speed

    # Verify second sampled frame (stride 2) has computed speed
    second_res = results[1]
    assert second_res.frame_index == 2
    assert second_res.tracks[0].speed_px_s is not None
    assert second_res.tracks[0].speed_kmh is not None

    # Check metrics payload
    assert second_res.metrics.total_vehicles == 1
    assert "lane_1" in second_res.metrics.lane_occupancy
    assert second_res.metrics.lane_occupancy["lane_1"] > 0.0


# ==============================================================================
# 7. Video Error Handling & Typed Exception Tests
# ==============================================================================


def test_video_processor_nonexistent_file(tmp_path: Path):
    """Verify nonexistent video path raises VideoOpenError."""
    processor = VideoProcessor(detector=SyntheticMockDetector())
    with pytest.raises(VideoOpenError, match="Video file does not exist"):
        list(processor.process_video(tmp_path / "nonexistent.mp4"))


def test_video_processor_empty_zero_byte_file(tmp_path: Path):
    """Verify 0-byte video file raises EmptyVideoError."""
    empty_file = tmp_path / "empty.mp4"
    empty_file.touch()

    processor = VideoProcessor(detector=SyntheticMockDetector())
    with pytest.raises(EmptyVideoError, match="Video file is 0 bytes"):
        list(processor.process_video(empty_file))


def test_video_processor_unsupported_format(tmp_path: Path):
    """Verify unsupported video format raises UnsupportedVideoFormatError."""
    bad_format = tmp_path / "sample.txt"
    bad_format.write_text("not a video")

    processor = VideoProcessor(detector=SyntheticMockDetector())
    with pytest.raises(UnsupportedVideoFormatError, match="Unsupported video container"):
        list(processor.process_video(bad_format))


# ==============================================================================
# 8. Backend Vision Package Provider Functions
# ==============================================================================


def test_backend_vision_providers():
    """Verify backend/app/vision provider functions instantiate properly."""
    tracker = get_vehicle_tracker(pixels_per_meter=10.0)
    assert isinstance(tracker, MultiObjectTracker)
    assert tracker.pixels_per_meter == 10.0

    metrics_fn = get_metrics_calculator()
    assert callable(metrics_fn)
    assert metrics_fn == compute_frame_metrics

    processor = get_video_processor(
        detector=SyntheticMockDetector(),
        frame_stride=3,
        pixels_per_meter=12.0,
    )
    assert isinstance(processor, VideoProcessor)
    assert processor.frame_stride == 3
