"""Smoke verification script for AI TrafficOS congestion detection & incident heuristics.

Generates a synthetic video stream with a cluster of stationary vehicles outside queue zones
and runs end-to-end perception:
- MultiObjectTracker
- FrameMetrics
- Congestion scoring (compute_congestion_score)
- Incident anomaly heuristics (IncidentDetector)

Prints evaluated congestion metrics and candidate incident events.
"""

from datetime import datetime, timezone
from pathlib import Path
import tempfile
import numpy as np
import cv2

from ai.common.schemas import Detection
from ai.cv.congestion import compute_congestion_score
from ai.cv.incidents import IncidentDetector, StoppedVehicleHeuristic, WrongWayHeuristic, LaneDirectionConfig
from ai.cv.metrics import PolygonROI, compute_frame_metrics
from ai.cv.tracking import MultiObjectTracker


def run_smoke_verification() -> None:
    print("=" * 70)
    print("AI TrafficOS Phase 4: Congestion & Incident Perception Smoke Test")
    print("=" * 70)

    # 1. Setup ROIs: Stop bar queue zone vs corridor lane
    queue_rois = {
        "stop_bar": PolygonROI.from_points("stop_bar", [(400, 300), (600, 300), (600, 450), (400, 450)])
    }
    lane_rois = {
        "main_corridor": PolygonROI.from_points("main_corridor", [(80, 80), (320, 80), (320, 320), (80, 320)])
    }
    far_roi = PolygonROI.from_points("far_ahead", [(100, 50), (500, 50), (500, 150), (100, 150)])

    # Wrong-way lane direction configuration
    wrong_way_cfg = LaneDirectionConfig(
        name="onramp_south",
        roi=PolygonROI.from_points("onramp_south", [(50, 350), (200, 350), (200, 470), (50, 470)]),
        expected_direction_deg=90.0,  # South (+Y)
    )

    tracker = MultiObjectTracker(iou_threshold=0.3, max_lost_frames=5)
    incident_detector = IncidentDetector(
        stopped_heuristic=StoppedVehicleHeuristic(
            min_stopped_frames=5,
            stopped_speed_threshold_px_s=3.0,
            base_confidence=0.55,
        ),
        wrong_way_heuristic=WrongWayHeuristic(),
    )

    print("\n[1] Initializing 15-frame Synthetic Video Stream (640x480)...")

    # Stationary cluster outside queue zones
    stationary_cluster = [
        (100.0, 100.0, 140.0, 140.0, "car"),
        (150.0, 100.0, 190.0, 140.0, "car"),
        (100.0, 150.0, 140.0, 190.0, "truck"),
        (150.0, 150.0, 190.0, 190.0, "car"),
    ]
    # Stationary car inside queue zone
    in_queue_car = (480.0, 330.0, 520.0, 370.0, "car")

    last_congestion = None
    last_incidents = []

    for frame_idx in range(1, 16):
        t_sec = frame_idx * 0.1
        now = datetime.now(timezone.utc)

        # Build detections
        detections = []
        for x1, y1, x2, y2, lbl in stationary_cluster:
            detections.append(Detection(label=lbl, confidence=0.92, bbox=(x1, y1, x2, y2), timestamp=now))
        # Add car in queue zone
        detections.append(Detection(label=in_queue_car[4], confidence=0.95, bbox=in_queue_car[:4], timestamp=now))

        # Add 1 wrong-way vehicle moving North (270°) in southbound on-ramp
        ww_y = 450.0 - (frame_idx * 6.0)  # Moving up (-Y)
        detections.append(
            Detection(label="car", confidence=0.88, bbox=(100.0, ww_y - 20.0, 140.0, ww_y + 20.0), timestamp=now)
        )

        # Update tracker
        active_tracks = tracker.update(detections=detections, timestamp_seconds=t_sec)

        # Compute frame metrics
        metrics = compute_frame_metrics(
            detections=detections,
            tracks=active_tracks,
            frame_shape=(480, 640),
            rois=lane_rois,
            queue_rois=queue_rois,
        )

        # Detect incidents
        incidents = incident_detector.detect_incidents(
            tracks=active_tracks,
            queue_rois=queue_rois,
            lane_configs=[wrong_way_cfg],
        )

        # Compute congestion score
        congestion = compute_congestion_score(
            metrics=metrics,
            tracks=active_tracks,
            free_flow_speed_px_s=30.0,
            far_roi=far_roi,
            detections=detections,
            frame_shape=(480, 640),
        )

        last_congestion = congestion
        last_incidents = incidents

    print("\n[2] Video Stream Processing Finished (15 frames). Results:")
    print("-" * 70)
    print(f"Vehicle Count:          {last_congestion.vehicle_count}")
    print(f"Congestion Score:       {last_congestion.congestion_level} / 100")
    print(f"Lane Occupancy Score:   {last_congestion.lane_occupancy_score:.4f}")
    print(f"Speed Deficit Score:    {last_congestion.speed_deficit_score}")
    print(f"Queue Score:            {last_congestion.queue_score:.4f}")
    print(f"Calculation Mode:       {last_congestion.components.get('mode')}")
    if last_congestion.traffic_ahead:
        print(f"Traffic Ahead Detected: {last_congestion.traffic_ahead.traffic_ahead_detected} "
              f"(Differential: {last_congestion.traffic_ahead.differential:.4f})")

    print("\n[3] Candidate Incident Events Emitted:")
    print("-" * 70)
    if not last_incidents:
        print("No incident candidates emitted.")
    else:
        for idx, inc in enumerate(last_incidents, 1):
            print(f"Candidate #{idx}:")
            print(f"  Type:        {inc.event_type}")
            print(f"  Track ID:    {inc.track_id}")
            print(f"  Confidence:  {inc.confidence:.3f}")
            print(f"  Method:      {inc.method}")
            print(f"  Centroid:    {inc.centroid}")
            print(f"  Summary:     {inc.details.get('summary', '')}")
            print()

    print("=" * 70)
    print("Smoke Verification SUCCESSFUL")
    print("=" * 70)


if __name__ == "__main__":
    run_smoke_verification()
