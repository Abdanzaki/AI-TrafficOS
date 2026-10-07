#!/usr/bin/env python3
"""Smoke verification script for AI TrafficOS traffic-signal perception pipeline.

Draws 3 synthetic traffic signal heads (red, yellow, green), runs end-to-end
detection and classical-CV state classification, and prints formatted results.
"""

from datetime import datetime, timezone
import sys
import numpy as np
import cv2

from ai.cv.signal_detector import TrafficSignalDetector
from ai.cv.signal_state_heuristic import SignalStateHeuristic


def create_smoke_verification_scene() -> tuple[np.ndarray, dict[str, tuple[int, int, int, int]]]:
    """Draw a 900x640 frame containing 3 realistic signal heads with poles."""
    height, width = 640, 900
    canvas = np.full((height, width, 3), 195, dtype=np.uint8)  # Daylight gray sky

    configs = [
        ("red", 160),
        ("yellow", 440),
        ("green", 720),
    ]

    head_w = 70
    head_h = 200
    y_top = 120
    lamp_r = head_w // 4

    ground_truth_boxes = {}

    for lit, cx in configs:
        x1 = cx - head_w // 2
        x2 = cx + head_w // 2
        ground_truth_boxes[lit] = (x1, y_top, x2, y_top + head_h)

        # 1. Pole
        cv2.rectangle(canvas, (cx - 4, y_top + head_h), (cx + 4, y_top + head_h + 200), (80, 80, 80), -1)

        # 2. Housing with dark border
        cv2.rectangle(canvas, (x1, y_top), (x2, y_top + head_h), (35, 35, 35), -1)
        cv2.rectangle(canvas, (x1 - 3, y_top - 3), (x2 + 3, y_top + head_h + 3), (20, 20, 20), 2)

        # 3. Visors and Lamps
        cy_red = y_top + head_h // 6
        cy_yel = y_top + head_h // 2
        cy_grn = y_top + 5 * head_h // 6

        for cy in (cy_red, cy_yel, cy_grn):
            cv2.ellipse(canvas, (cx, cy - lamp_r), (lamp_r + 2, 6), 0, 180, 360, (15, 15, 15), -1)

        c_red = (0, 0, 255) if lit == "red" else (40, 40, 40)
        c_yel = (0, 230, 255) if lit == "yellow" else (40, 40, 40)
        c_grn = (0, 255, 0) if lit == "green" else (40, 40, 40)

        cv2.circle(canvas, (cx, cy_red), lamp_r, c_red, -1)
        cv2.circle(canvas, (cx, cy_yel), lamp_r, c_yel, -1)
        cv2.circle(canvas, (cx, cy_grn), lamp_r, c_grn, -1)

    return canvas, ground_truth_boxes


def main() -> int:
    """Execute smoke verification."""
    print("=" * 80)
    print("AI TrafficOS — Phase 4 Traffic Signal Perception Smoke Verification")
    print("=" * 80)

    # 1. Generate synthetic scene
    print("\n[Step 1/3] Generating synthetic scene with 3 traffic signal heads (Red, Yellow, Green)...")
    scene, gt_boxes = create_smoke_verification_scene()
    print(f"Canvas size: {scene.shape[1]}x{scene.shape[0]} px | Ground truth targets: 3 heads")

    # 2. Initialize detector
    print("\n[Step 2/3] Initializing TrafficSignalDetector (YOLO COCO Class 9 + SignalStateHeuristic)...")
    detector = TrafficSignalDetector(conf_threshold=0.15)
    print(f"Detector initialized: device={detector.device}, conf_thresh={detector.conf_threshold}")

    # 3. Execute detection and classification
    print("\n[Step 3/3] Running inference and classical-CV state recognition...")
    now = datetime.now(timezone.utc)
    detections = detector.detect(scene, timestamp=now)

    print(f"Total signal heads detected: {len(detections)}")

    if len(detections) != 3:
        print(f"ERROR: Expected 3 signal heads detected, got {len(detections)}")
        return 1

    # Sort left to right
    detections.sort(key=lambda d: d.bbox[0])

    print("\n" + "-" * 88)
    print(f"{'Idx':<4} | {'Target':<7} | {'BBox [x1, y1, x2, y2]':<26} | {'YOLO Conf':<10} | {'State':<8} | {'State Conf':<10} | {'Margin':<8}")
    print("-" * 88)

    expected_states = ["red", "yellow", "green"]
    all_passed = True

    for i, (det, exp_state) in enumerate(zip(detections, expected_states)):
        metrics = det.color_metrics or {}
        margin = metrics.get("margin", 0.0)
        bbox_str = f"[{det.bbox[0]:.1f}, {det.bbox[1]:.1f}, {det.bbox[2]:.1f}, {det.bbox[3]:.1f}]"
        
        status_match = "PASS" if det.state == exp_state else "FAIL"
        if det.state != exp_state:
            all_passed = False

        print(
            f"#{i+1:<3} | {exp_state:<7} | {bbox_str:<26} | {det.confidence:<10.3f} | "
            f"{det.state:<8} | {det.state_confidence:<10.3f} | {margin:<8.3f} [{status_match}]"
        )

    print("-" * 88)

    # Standalone heuristic verification on direct crop
    print("\n[Standalone Heuristic Check on Ambiguous Inputs]")
    heuristic = SignalStateHeuristic()
    
    # Ambiguous conflicting crop (red + green)
    ambiguous_crop = np.full((150, 50, 3), 30, dtype=np.uint8)
    cv2.circle(ambiguous_crop, (25, 30), 14, (0, 0, 255), -1)
    cv2.circle(ambiguous_crop, (25, 120), 14, (0, 255, 0), -1)
    res_amb = heuristic.evaluate_crop(ambiguous_crop)
    print(f"• Conflicting red+green lit: state={res_amb.state} (conf={res_amb.confidence}, margin={res_amb.margin}) -> {'PASS' if res_amb.state == 'unknown' else 'FAIL'}")

    # Dark / unlit crop
    dark_crop = np.full((150, 50, 3), 30, dtype=np.uint8)
    cv2.circle(dark_crop, (25, 30), 14, (45, 45, 45), -1)
    cv2.circle(dark_crop, (25, 75), 14, (45, 45, 45), -1)
    cv2.circle(dark_crop, (25, 120), 14, (45, 45, 45), -1)
    res_dark = heuristic.evaluate_crop(dark_crop)
    print(f"• Unlit signal head:         state={res_dark.state} (conf={res_dark.confidence}) -> {'PASS' if res_dark.state == 'unknown' else 'FAIL'}")

    if all_passed and res_amb.state == "unknown" and res_dark.state == "unknown":
        print("\n" + "=" * 80)
        print(">>> ALL SMOKE VERIFICATION CHECKS PASSED SUCCESSFULLY <<<")
        print("=" * 80)
        return 0
    else:
        print("\n>>> SMOKE VERIFICATION FAILED <<<")
        return 1


if __name__ == "__main__":
    sys.exit(main())
