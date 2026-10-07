#!/usr/bin/env python3
"""Smoke verification script for AI TrafficOS Video Processing Pipeline.

Generates a synthetic 2-second video (20 frames at 10 FPS) with moving vehicle
rectangles, executes VideoProcessor with real detection, multi-object tracking,
and operational metrics, and prints per-frame counts and speed estimates.
"""

from datetime import datetime, timezone
import os
from pathlib import Path
import tempfile
import time
import numpy as np
import cv2
from ultralytics.utils import ASSETS

from ai.cv.metrics import PolygonROI
from ai.cv.tracking import MultiObjectTracker
from ai.cv.video_processor import VideoProcessor
from ai.cv.yolo_detector import YoloVehicleDetector
from backend.app.vision import get_video_processor


def create_synthetic_traffic_video(
    output_path: Path,
    num_frames: int = 20,
    fps: float = 10.0,
    width: int = 640,
    height: int = 480,
) -> Path:
    """Generate a 2-second synthetic video with moving vehicles and road markings.

    Args:
        output_path: Destination path for the synthetic MP4 video file.
        num_frames: Total frames (20 frames at 10 FPS = 2.0 seconds).
        fps: Playback frame rate.
        width: Video frame width in pixels.
        height: Video frame height in pixels.

    Returns:
        Path: Path to the generated video file.
    """
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(output_path), fourcc, fps, (width, height))

    # Optional: load real bus crop from ultralytics assets for realistic detector response
    bus_src = cv2.imread(os.path.join(ASSETS, "bus.jpg"))
    car_crop = None
    if bus_src is not None:
        # Resize to 120x80 vehicle crop
        car_crop = cv2.resize(bus_src[230:750, 30:800], (120, 80))

    for frame_idx in range(num_frames):
        # 1. Asphalt canvas
        canvas = np.full((height, width, 3), 55, dtype=np.uint8)

        # 2. Road lanes (two lanes separated by dashed white line)
        # Shoulders
        cv2.line(canvas, (60, 0), (60, height), (220, 220, 220), 3)
        cv2.line(canvas, (580, 0), (580, height), (220, 220, 220), 3)
        # Center dashed divider
        for y in range(0, height, 40):
            cv2.line(canvas, (320, y), (320, y + 20), (0, 220, 220), 2)

        # Stop bar at y = 380 (Queue zone)
        cv2.line(canvas, (60, 380), (580, 380), (255, 255, 255), 4)

        # 3. Moving Vehicle 1 in Lane 1 (moves downward 12 pixels per frame: 120 px/s)
        v1_y = int(60 + frame_idx * 12)
        v1_x = 130
        if car_crop is not None and (v1_y + 80 < height):
            canvas[v1_y : v1_y + 80, v1_x : v1_x + 120] = car_crop
        else:
            cv2.rectangle(canvas, (v1_x, v1_y), (v1_x + 120, v1_y + 80), (0, 0, 220), -1)

        # 4. Stationary Vehicle 2 in Lane 2 inside Queue Zone (near stop bar)
        v2_y = 300
        v2_x = 390
        if car_crop is not None:
            # Shift tint slightly to represent a second distinct vehicle
            v2_crop = np.roll(car_crop, 40, axis=2)
            canvas[v2_y : v2_y + 80, v2_x : v2_x + 120] = v2_crop
        else:
            cv2.rectangle(canvas, (v2_x, v2_y), (v2_x + 120, v2_y + 80), (200, 100, 0), -1)

        writer.write(canvas)

    writer.release()
    return output_path


def main() -> int:
    print("=" * 80)
    print("AI TrafficOS — Phase 4 Video Processing Pipeline Smoke Verification")
    print("=" * 80)

    # 1. Generate 2-second synthetic video
    temp_dir = tempfile.TemporaryDirectory()
    video_path = Path(temp_dir.name) / "synthetic_traffic_2s.mp4"
    print(f"\n[1/4] Generating 2-second synthetic video: {video_path}")
    t0_gen = time.perf_counter()
    create_synthetic_traffic_video(video_path, num_frames=20, fps=10.0, width=640, height=480)
    gen_time_ms = (time.perf_counter() - t0_gen) * 1000
    print(f"  Generated 20 frames (10.0 FPS, 640x480) in {gen_time_ms:.1f} ms")
    print(f"  File size: {video_path.stat().st_size} bytes")

    # 2. Configure ROIs (North lane and Stop-bar Queue zone)
    print("\n[2/4] Defining Polygon ROIs for Lane Occupancy and Queue Monitoring...")
    # Lane 1 ROI (polygon covering left lane)
    lane1_roi = PolygonROI.from_points(
        "lane_north_1",
        [(60, 40), (310, 40), (310, 440), (60, 440)],
    )
    # Queue Zone ROI (polygon covering area immediately preceding the stop bar)
    queue_roi = PolygonROI.from_points(
        "stop_bar_queue",
        [(330, 260), (570, 260), (570, 400), (330, 400)],
    )
    print(f"  ROI 1 ({lane1_roi.name}): {len(lane1_roi.points)} vertices")
    print(f"  ROI 2 ({queue_roi.name}): {len(queue_roi.points)} vertices")

    # 3. Instantiate VideoProcessor
    print("\n[3/4] Initializing VideoProcessor with YOLO detector & tracker...")
    detector = YoloVehicleDetector(
        conf_threshold=0.20,
        iou_threshold=0.45,
        imgsz=320,  # Fast 320 edge mode for responsive CPU processing
        device="cpu",
    )
    # Set camera calibration: 10 pixels per meter (so 120 px/s = 12 m/s = 43.2 km/h)
    pixels_per_meter = 10.0
    tracker = MultiObjectTracker(
        iou_threshold=0.3,
        max_centroid_distance=90.0,
        pixels_per_meter=pixels_per_meter,
    )

    processor = VideoProcessor(
        detector=detector,
        tracker=tracker,
        frame_stride=1,  # Sample every frame
        rois={"lane_north_1": lane1_roi},
        queue_rois={"stop_bar_queue": queue_roi},
        pixels_per_meter=pixels_per_meter,
        speed_threshold_px_s=10.0,  # Stationary / queued threshold <= 10 px/s
    )

    # 4. Stream and execute processing
    print("\n[4/4] Processing synthetic video stream...")
    t_start = time.perf_counter()
    frame_results = list(processor.process_video(video_path))
    total_elapsed_ms = (time.perf_counter() - t_start) * 1000

    print(f"  Processed {len(frame_results)} frames in {total_elapsed_ms:.1f} ms (Mean: {total_elapsed_ms / len(frame_results):.1f} ms/frame)")
    print("\n" + "-" * 80)
    print("PER-FRAME SUMMARY:")
    print("-" * 80)

    for res in frame_results:
        speeds_px_s = [f"{t.speed_px_s} px/s" for t in res.tracks if t.speed_px_s is not None]
        speeds_kmh = [f"{t.speed_kmh} km/h" for t in res.tracks if t.speed_kmh is not None]
        speed_str = ", ".join(speeds_kmh) if speeds_kmh else ("None (1st frame)" if not speeds_px_s else ", ".join(speeds_px_s))

        occ_l1 = res.metrics.lane_occupancy.get("lane_north_1", 0.0)
        q_count = res.metrics.queue_lengths.get("stop_bar_queue", 0)

        print(
            f"Frame #{res.frame_index:02d} (t={res.timestamp_seconds:.2f}s) | "
            f"Vehicles: {res.metrics.total_vehicles} | "
            f"Counts: {res.metrics.counts_by_class} | "
            f"Lane Occ: {occ_l1 * 100:.1f}% | "
            f"Queue: {q_count} | "
            f"Track Speeds: [{speed_str}]"
        )

    # Sanity checks on final frame results
    assert len(frame_results) == 20, f"Expected 20 frames, got {len(frame_results)}"
    last_frame = frame_results[-1]
    assert last_frame.metrics.total_vehicles >= 1, "Expected vehicles detected in synthetic video"

    # Verify at least one vehicle established multi-frame speed
    has_speed = any(t.speed_px_s is not None for t in last_frame.tracks)
    assert has_speed, "Expected established speed estimate on moving vehicle after consecutive frames"

    print("\n" + "=" * 80)
    print("SMOKE VERIFICATION PASSED SUCCESSFULLY")
    print("=" * 80)
    temp_dir.cleanup()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
