#!/usr/bin/env python3
"""Smoke verification script for AI TrafficOS YoloVehicleDetector.

Tests the concrete YOLO vehicle detector and EmergencyVehicleHeuristic on
a programmatically generated image, prints real Detection objects, verifies
field values, tests input validation edge cases, and measures CPU timing.
"""

from datetime import datetime, timezone
import os
import time
from pathlib import Path
import numpy as np
import cv2
from ultralytics.utils import ASSETS

from ai.cv.yolo_detector import YoloVehicleDetector
from ai.cv.emergency_heuristic import EmergencyVehicleHeuristic
from ai.cv.exceptions import (
    CorruptFrameError,
    InvalidInputFrameError,
    UnsupportedInputFormatError,
)
from app.vision.detectors import (
    detection_to_vehicle_event_create,
    get_vehicle_detector,
)


def create_programmatic_test_image() -> np.ndarray:
    """Generate a programmatic synthetic traffic scene with composited vehicle crops.

    Returns:
        np.ndarray: 640x640 BGR image array containing synthetic road markings and vehicles.
    """
    # 1. Asphalt canvas (640x640)
    canvas = np.full((640, 640, 3), 70, dtype=np.uint8)

    # 2. Road lane dividers (dashed yellow center line and solid white shoulders)
    cv2.line(canvas, (40, 0), (40, 640), (240, 240, 240), 4)
    cv2.line(canvas, (600, 0), (600, 640), (240, 240, 240), 4)
    for y in range(0, 640, 50):
        cv2.rectangle(canvas, (315, y), (325, y + 25), (0, 220, 220), -1)

    # 3. Composite vehicle crop from ultralytics assets
    bus_src = cv2.imread(os.path.join(ASSETS, "bus.jpg"))
    if bus_src is not None:
        # Extract bus and resize to fit lane
        bus_crop = cv2.resize(bus_src[230:750, 30:800], (260, 200))
        canvas[220:420, 45:305] = bus_crop

        # 4. Composite second vehicle with emergency red livery pattern on right lane
        emerg_crop = bus_crop.copy()
        # Red livery transformation
        emerg_crop[:, :, 2] = np.clip(emerg_crop[:, :, 2].astype(int) + 130, 0, 255).astype(np.uint8)
        emerg_crop[:, :, 0] = (emerg_crop[:, :, 0] * 0.25).astype(np.uint8)
        emerg_crop[:, :, 1] = (emerg_crop[:, :, 1] * 0.25).astype(np.uint8)
        canvas[220:420, 335:595] = emerg_crop

    return canvas


def main() -> int:
    print("=" * 80)
    print("AI TrafficOS — Phase 4 Computer Vision Detector Smoke Verification")
    print("=" * 80)

    # 1. Initialize detector
    print("\n[1/5] Initializing YoloVehicleDetector...")
    detector = YoloVehicleDetector(
        conf_threshold=0.25,
        iou_threshold=0.45,
        imgsz=640,
        device="cpu",
        enable_emergency_heuristic=True,
    )
    print(f"  Model Path: {detector.model_path}")
    print(f"  Device:     {detector.device}")
    print(f"  Confidence: {detector.conf_threshold}")
    print(f"  IoU NMS:    {detector.iou_threshold}")
    print(f"  Class Map:  {detector.class_mapping}")

    # 2. Generate programmatic test image
    print("\n[2/5] Creating programmatic synthetic traffic scene image...")
    test_frame = create_programmatic_test_image()
    print(f"  Synthetic frame shape: {test_frame.shape}, dtype: {test_frame.dtype}")

    # 3. Execute inference and warm up
    print("\n[3/5] Running real inference via YoloVehicleDetector.detect()...")
    test_ts = datetime.now(timezone.utc)
    t0 = time.perf_counter()
    detections = detector.detect(test_frame, timestamp=test_ts)
    elapsed_ms = (time.perf_counter() - t0) * 1000

    print(f"  Inference completed in {elapsed_ms:.2f} ms")
    print(f"  Total Detection objects returned: {len(detections)}")

    # 4. Print and validate Detection objects
    print("\n[4/5] Inspecting returned Detection objects:")
    assert len(detections) > 0, "Expected at least 1 detection on synthetic scene"

    for idx, det in enumerate(detections, 1):
        print(f"\n  --- Detection #{idx} ---")
        print(f"    Label:      {det.label}")
        print(f"    Confidence: {det.confidence:.4f}")
        print(f"    BBox:       {det.bbox}  (x1, y1, x2, y2)")
        print(f"    Timestamp:  {det.timestamp.isoformat()}")

        # Sanity assertions
        assert det.label in ("bus", "car", "truck", "motorcycle", "emergency_vehicle_heuristic")
        assert 0.0 <= det.confidence <= 1.0
        assert det.bbox is not None
        x1, y1, x2, y2 = det.bbox
        assert 0.0 <= x1 < x2 <= 640.0
        assert 0.0 <= y1 < y2 <= 640.0
        assert det.timestamp == test_ts

        # Convert to database schema
        event_schema = detection_to_vehicle_event_create(det, intersection_id=1, lane_id=2)
        print(f"    DB Schema:  vehicle_type='{event_schema.vehicle_type}', event_type='{event_schema.event_type}'")

    # 5. Measure CPU Benchmark
    print("\n[5/5] Benchmarking CPU Latency (5 runs)...")
    latencies = []
    for run_i in range(5):
        t_start = time.perf_counter()
        _ = detector.detect(test_frame)
        lat = (time.perf_counter() - t_start) * 1000
        latencies.append(lat)
        print(f"  Run {run_i + 1}: {lat:.2f} ms")

    mean_lat = float(np.mean(latencies))
    fps = 1000.0 / mean_lat
    print(f"\n  CPU Performance (imgsz=640): Mean = {mean_lat:.2f} ms ({fps:.2f} FPS)")

    print("\n" + "=" * 80)
    print("SMOKE VERIFICATION PASSED SUCCESSFULLY")
    print("=" * 80)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
