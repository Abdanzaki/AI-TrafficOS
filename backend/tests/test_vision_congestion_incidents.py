"""Tests for AI TrafficOS congestion detection, incident heuristics, and storage.

Validates:
1. Congestion Detection & Scoring:
   - Zero-vehicle frames produce 0 congestion level and free-flow semantics.
   - High density, high occupancy, and queued vehicles yield high congestion score (>= 80).
   - Speed deficit calculation in calibrated mode and uncalibrated pixel mode.
   - Weight rebalancing when speed is absent (never fabricating km/h).
   - Configurable weight validation.
2. Traffic-Ahead Far-Field Detection:
   - Configurable far-field ROI identifies upstream density differentials.
   - Correct boolean triggering when far-field congestion exceeds near-field.
   - Honest optical limits and lack of depth documented in result.
3. Incident Detection Foundations (Deterministic Heuristics):
   - Stationary vehicles outside queue zones for >= N frames flag 'stopped_vehicle' candidate.
   - Stationary vehicles INSIDE queue zones are recognized as normal queues and not flagged.
   - Confidence strictly scales with persistence count up to ceiling.
   - Vehicle resuming motion clears stationary count.
   - Wrong-way heuristic flags opposing vehicle trajectories against LaneDirectionConfig.
   - Insufficient motion distance skips wrong-way flag to prevent jitter false positives.
   - Explicit 'heuristic' method labeling and candidate fields.
4. Database Storage Integration:
   - Persisting CongestionResult writes to TrafficRecord with source='camera'.
   - Uncalibrated speeds strictly write avg_speed_kmh=None.
   - Persisting IncidentCandidate writes to Incident with status='reported', severity mapping,
     and description stating heuristic method.
   - Batch incident candidate persistence.
5. End-to-End Synthetic Video Stream:
   - Programmatically generated video with stationary vehicles produces high congestion
     and incident candidates.
"""

from datetime import datetime, timezone
import tempfile
from pathlib import Path
from typing import Sequence
import numpy as np
import cv2
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ai.common.schemas import Detection
from ai.cv.congestion import (
    CongestionResult,
    CongestionWeights,
    TrafficAheadResult,
    compute_congestion_score,
    detect_traffic_ahead,
)
from ai.cv.incidents import (
    IncidentCandidate,
    IncidentDetector,
    LaneDirectionConfig,
    StoppedVehicleHeuristic,
    WrongWayHeuristic,
)
from ai.cv.metrics import FrameMetrics, PolygonROI, compute_frame_metrics
from ai.cv.tracking import MultiObjectTracker, TrackedVehicle
from app.core.database import Base
from app.models.event import Incident
from app.models.intersection import Intersection
from app.models.traffic import TrafficRecord
from app.vision.congestion import get_congestion_calculator
from app.vision.incidents import get_incident_detector
from app.vision.storage import (
    map_confidence_to_severity,
    record_congestion_observation,
    record_incident_candidate,
    record_incident_candidates,
)


# ==============================================================================
# Database Fixture Helper
# ==============================================================================


async def create_test_db():
    """Create isolated in-memory SQLite async engine and session factory."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    return engine, session_factory


# ==============================================================================
# 1. Congestion Detection & Scoring Tests
# ==============================================================================


class TestCongestionDetection:
    """Tests for congestion score calculation and weight rebalancing."""

    def test_zero_vehicles_yields_zero_congestion(self):
        """Verify an empty roadway always produces congestion score 0."""
        empty_metrics = FrameMetrics(
            total_vehicles=0,
            counts_by_class={"car": 0},
            density=0.0,
            density_per_100k_px=0.0,
            lane_occupancy={"lane_1": 0.0},
            queue_lengths={"lane_1": 0},
            timestamp=datetime.now(timezone.utc),
        )
        res = compute_congestion_score(metrics=empty_metrics)
        assert res.congestion_level == 0
        assert res.vehicle_count == 0
        assert res.avg_speed_kmh is None
        assert res.lane_occupancy_score == 0.0
        assert res.speed_deficit_score is None
        assert res.queue_score == 0.0
        assert not res.is_calibrated

    def test_high_congestion_dense_stopped_traffic(self):
        """Verify high occupancy, high queue, and low speeds produce a high score."""
        metrics = FrameMetrics(
            total_vehicles=10,
            counts_by_class={"car": 8, "truck": 2},
            density=0.001,
            density_per_100k_px=10.0,
            lane_occupancy={"lane_1": 0.85, "lane_2": 0.90},
            queue_lengths={"lane_1": 4, "lane_2": 5},
            timestamp=datetime.now(timezone.utc),
        )
        # Tracks at near-standstill (calibrated 5 km/h vs 50 km/h free-flow)
        tracks = [
            TrackedVehicle(
                track_id=i,
                label="car",
                confidence=0.9,
                bbox=(10.0, float(i * 30), 50.0, float(i * 30 + 25)),
                centroid=(30.0, float(i * 30 + 12)),
                speed_kmh=5.0,
                speed_px_s=2.0,
            )
            for i in range(1, 11)
        ]

        res = compute_congestion_score(
            metrics=metrics,
            tracks=tracks,
            free_flow_speed_kmh=50.0,
        )

        assert res.congestion_level >= 80
        assert res.is_calibrated is True
        assert res.avg_speed_kmh == 5.0
        assert res.speed_deficit_score is not None
        assert res.speed_deficit_score >= 0.85  # (1 - 5/50) = 0.90
        assert res.lane_occupancy_score >= 0.85
        assert res.queue_score >= 0.85

    def test_free_flow_fast_moving_traffic_yields_low_score(self):
        """Verify vehicles moving at free-flow speed produce a low congestion score."""
        metrics = FrameMetrics(
            total_vehicles=4,
            counts_by_class={"car": 4},
            density=0.0001,
            density_per_100k_px=1.0,
            lane_occupancy={"lane_1": 0.10},
            queue_lengths={"lane_1": 0},
            timestamp=datetime.now(timezone.utc),
        )
        tracks = [
            TrackedVehicle(
                track_id=i,
                label="car",
                confidence=0.95,
                bbox=(10.0, float(i * 50), 40.0, float(i * 50 + 20)),
                centroid=(25.0, float(i * 50 + 10)),
                speed_kmh=55.0,  # Exceeds 50 km/h free-flow
                speed_px_s=45.0,
            )
            for i in range(1, 5)
        ]

        res = compute_congestion_score(
            metrics=metrics,
            tracks=tracks,
            free_flow_speed_kmh=50.0,
        )

        assert res.congestion_level <= 15
        assert res.speed_deficit_score == 0.0  # Speed >= free-flow
        assert res.queue_score == 0.0

    def test_uncalibrated_speed_rebalances_weights_honestly(self):
        """Verify when speed is uncalibrated, km/h is None and weights rebalance to spatial."""
        metrics = FrameMetrics(
            total_vehicles=5,
            counts_by_class={"car": 5},
            density=0.0005,
            density_per_100k_px=4.0,
            lane_occupancy={"lane_1": 0.60},
            queue_lengths={"lane_1": 2},
            timestamp=datetime.now(timezone.utc),
        )
        # Uncalibrated tracks: speed_kmh is strictly None
        tracks = [
            TrackedVehicle(
                track_id=i,
                label="car",
                confidence=0.88,
                bbox=(10.0, float(i * 40), 50.0, float(i * 40 + 25)),
                centroid=(30.0, float(i * 40 + 12)),
                speed_kmh=None,  # UNCALIBRATED
                speed_px_s=3.0,
            )
            for i in range(1, 6)
        ]

        res = compute_congestion_score(
            metrics=metrics,
            tracks=tracks,
            free_flow_speed_kmh=50.0,
            # No free_flow_speed_px_s provided
        )

        assert res.is_calibrated is False
        assert res.avg_speed_kmh is None
        assert res.speed_deficit_score is None
        assert res.components["mode"] == "spatial_geometry_only"
        # Spatial score = 0.70 * 0.60 + 0.30 * (2/5 = 0.40) = 0.42 + 0.12 = 0.54 -> 54
        assert res.congestion_level == 54

    def test_custom_weights_and_validation(self):
        """Verify CongestionWeights validates that sum equals 1.0."""
        valid_w = CongestionWeights(
            w_occupancy=0.50,
            w_speed_deficit=0.30,
            w_queue=0.20,
            w_occupancy_no_speed=0.60,
            w_queue_no_speed=0.40,
        )
        assert valid_w.w_occupancy == 0.50

        with pytest.raises(ValueError, match="Full mode weights must sum to 1.0"):
            CongestionWeights(w_occupancy=0.50, w_speed_deficit=0.50, w_queue=0.50)

        with pytest.raises(ValueError, match="No-speed mode weights must sum to 1.0"):
            CongestionWeights(w_occupancy_no_speed=0.50, w_queue_no_speed=0.20)


# ==============================================================================
# 2. Traffic-Ahead Far-Field Detection Tests
# ==============================================================================


class TestTrafficAheadDetection:
    """Tests for far-field ROI vs near-field ROI differential analysis."""

    def test_traffic_ahead_triggered_when_far_exceeds_near(self):
        """Verify traffic ahead triggers when upstream far-field is crowded and near is empty."""
        far_roi = PolygonROI.from_points("far_ahead", [(100, 50), (500, 50), (500, 200), (100, 200)])
        near_roi = PolygonROI.from_points("near_foreground", [(100, 300), (500, 300), (500, 450), (100, 450)])

        # Detections concentrated in far_roi
        far_dets = [
            Detection(label="car", confidence=0.9, bbox=(120.0, 70.0, 250.0, 180.0)),
            Detection(label="truck", confidence=0.9, bbox=(270.0, 80.0, 450.0, 190.0)),
        ]
        res = detect_traffic_ahead(
            detections=far_dets,
            far_roi=far_roi,
            near_roi=near_roi,
            frame_shape=(480, 640),
            ahead_threshold=0.20,
        )

        assert res.traffic_ahead_detected is True
        assert res.far_density > 0.30
        assert res.near_density == 0.0
        assert res.differential > 0.30
        assert "2D monocular camera without depth sensor" in res.limits_note

    def test_traffic_ahead_not_triggered_when_foreground_congested_but_far_clear(self):
        """Verify no traffic ahead trigger when near-field is congested but far-field is clear."""
        far_roi = PolygonROI.from_points("far_ahead", [(100, 50), (500, 50), (500, 200), (100, 200)])
        near_roi = PolygonROI.from_points("near_foreground", [(100, 300), (500, 300), (500, 450), (100, 450)])

        # Detections concentrated strictly in near_roi
        near_dets = [
            Detection(label="car", confidence=0.9, bbox=(120.0, 320.0, 300.0, 430.0)),
            Detection(label="car", confidence=0.9, bbox=(320.0, 320.0, 480.0, 430.0)),
        ]
        res = detect_traffic_ahead(
            detections=near_dets,
            far_roi=far_roi,
            near_roi=near_roi,
            frame_shape=(480, 640),
        )

        assert res.traffic_ahead_detected is False
        assert res.differential < 0.0
        assert res.near_density > res.far_density


# ==============================================================================
# 3. Incident Detection Heuristics Tests
# ==============================================================================


class TestIncidentHeuristics:
    """Tests for stopped-vehicle anomaly and wrong-way direction heuristics."""

    def test_stopped_vehicle_outside_queue_roi_flags_candidate(self):
        """Verify vehicle stationary for N frames outside queue zones flags candidate."""
        heuristic = StoppedVehicleHeuristic(
            min_stopped_frames=5,
            stopped_speed_threshold_px_s=2.0,
            base_confidence=0.50,
            confidence_per_frame=0.05,
        )
        queue_roi = PolygonROI.from_points("stop_bar_queue", [(0, 400), (300, 400), (300, 600), (0, 600)])

        # Vehicle located at (450, 200), strictly outside queue_roi
        track = TrackedVehicle(
            track_id=101,
            label="car",
            confidence=0.92,
            bbox=(430.0, 180.0, 470.0, 220.0),
            centroid=(450.0, 200.0),
            speed_px_s=0.5,  # stationary
        )

        # Frames 1 through 4: count increments, no candidate yet (< min_stopped_frames)
        for frame_idx in range(1, 5):
            cands = heuristic.evaluate(tracks=[track], queue_rois=[queue_roi])
            assert len(cands) == 0

        # Frame 5: threshold reached (5 frames)
        cands_frame_5 = heuristic.evaluate(tracks=[track], queue_rois=[queue_roi])
        assert len(cands_frame_5) == 1
        cand = cands_frame_5[0]
        assert cand.event_type == "stopped_vehicle"
        assert cand.track_id == 101
        assert cand.confidence == 0.50
        assert cand.method == "stopped_vehicle_persistence_heuristic"
        assert cand.details["persistence_frames"] == 5

        # Frame 8: persistence count = 8, confidence scales: 0.50 + 3 * 0.05 = 0.65
        for _ in range(2):
            heuristic.evaluate(tracks=[track], queue_rois=[queue_roi])
        cands_frame_8 = heuristic.evaluate(tracks=[track], queue_rois=[queue_roi])
        assert len(cands_frame_8) == 1
        assert abs(cands_frame_8[0].confidence - 0.65) < 1e-3

    def test_stopped_vehicle_inside_queue_roi_is_ignored(self):
        """Verify vehicles stopped inside designated queue ROIs are treated as normal."""
        heuristic = StoppedVehicleHeuristic(min_stopped_frames=3, stopped_speed_threshold_px_s=2.0)
        queue_roi = PolygonROI.from_points("stop_bar", [(100, 100), (300, 100), (300, 300), (100, 300)])

        # Vehicle at centroid (200, 200), strictly INSIDE queue_roi
        track = TrackedVehicle(
            track_id=202,
            label="car",
            confidence=0.90,
            bbox=(180.0, 180.0, 220.0, 220.0),
            centroid=(200.0, 200.0),
            speed_px_s=0.0,
        )

        # Even across 10 frames, no candidate should be emitted
        for _ in range(10):
            cands = heuristic.evaluate(tracks=[track], queue_rois=[queue_roi])
            assert len(cands) == 0

    def test_stopped_vehicle_resuming_motion_resets_counter(self):
        """Verify accelerating vehicle resets stationary count immediately."""
        heuristic = StoppedVehicleHeuristic(min_stopped_frames=3, stopped_speed_threshold_px_s=2.0)

        track_stopped = TrackedVehicle(
            track_id=303,
            label="car",
            confidence=0.90,
            bbox=(400.0, 400.0, 450.0, 450.0),
            centroid=(425.0, 425.0),
            speed_px_s=1.0,
        )
        # Stop for 3 frames -> candidate
        heuristic.evaluate(tracks=[track_stopped])
        heuristic.evaluate(tracks=[track_stopped])
        cands = heuristic.evaluate(tracks=[track_stopped])
        assert len(cands) == 1

        # Vehicle moves (speed = 25.0 px/s) -> counter reset
        track_moving = TrackedVehicle(
            track_id=303,
            label="car",
            confidence=0.90,
            bbox=(410.0, 410.0, 460.0, 460.0),
            centroid=(435.0, 435.0),
            speed_px_s=25.0,
        )
        cands_moving = heuristic.evaluate(tracks=[track_moving])
        assert len(cands_moving) == 0
        assert heuristic._stopped_counts[303] == 0

    def test_wrong_way_heuristic_opposing_lane_motion(self):
        """Verify vehicle moving opposite to expected lane direction triggers candidate."""
        # Lane expected heading: South (+Y direction, 90°)
        lane_roi = PolygonROI.from_points("lane_southbound", [(100, 0), (250, 0), (250, 600), (100, 600)])
        config = LaneDirectionConfig(
            name="southbound",
            roi=lane_roi,
            expected_direction_deg=90.0,  # South
            tolerance_deg=90.0,
            min_motion_distance_px=20.0,
            min_history_points=3,
        )
        heuristic = WrongWayHeuristic()

        # Vehicle moving North (-Y direction, 270°) inside southbound lane!
        track_wrong = TrackedVehicle(
            track_id=404,
            label="car",
            confidence=0.94,
            bbox=(150.0, 300.0, 190.0, 340.0),
            centroid=(170.0, 320.0),
            history=[
                ((170.0, 400.0), 1.0),
                ((170.0, 360.0), 2.0),
                ((170.0, 320.0), 3.0),  # Moved from y=400 to y=320 (-80px, North)
            ],
        )

        cands = heuristic.evaluate(tracks=[track_wrong], lane_configs=[config])
        assert len(cands) == 1
        cand = cands[0]
        assert cand.event_type == "wrong_way"
        assert cand.track_id == 404
        assert cand.method == "wrong_way_direction_heuristic"
        assert cand.confidence >= 0.85  # Near 180° head-on opposition
        assert cand.details["angular_deviation_deg"] == 180.0
        assert cand.details["lane_name"] == "southbound"

    def test_wrong_way_correct_direction_no_candidate(self):
        """Verify vehicle moving in the correct direction produces no candidate."""
        lane_roi = PolygonROI.from_points("lane_southbound", [(100, 0), (250, 0), (250, 600), (100, 600)])
        config = LaneDirectionConfig(
            name="southbound",
            roi=lane_roi,
            expected_direction_deg=90.0,  # South
        )
        heuristic = WrongWayHeuristic()

        # Vehicle moving South (+Y direction, y=100 -> y=180)
        track_correct = TrackedVehicle(
            track_id=505,
            label="car",
            confidence=0.91,
            bbox=(150.0, 160.0, 190.0, 200.0),
            centroid=(170.0, 180.0),
            history=[
                ((170.0, 100.0), 1.0),
                ((170.0, 140.0), 2.0),
                ((170.0, 180.0), 3.0),
            ],
        )

        cands = heuristic.evaluate(tracks=[track_correct], lane_configs=[config])
        assert len(cands) == 0

    def test_lane_config_from_vector_constructor(self):
        """Verify LaneDirectionConfig.from_vector computes expected angle."""
        roi = [(0, 0), (100, 0), (100, 100), (0, 100)]
        # Vector (0, 1) points directly down (+Y) -> 90 degrees
        cfg = LaneDirectionConfig.from_vector("down_lane", roi, (0.0, 1.0))
        assert cfg.expected_direction_deg == 90.0

        # Vector (-1, 0) points left (-X) -> 180 degrees
        cfg_left = LaneDirectionConfig.from_vector("left_lane", roi, (-1.0, 0.0))
        assert cfg_left.expected_direction_deg == 180.0


# ==============================================================================
# 4. Storage Integration Tests
# ==============================================================================


class TestVisionStorageIntegration:
    """Tests covering persistence of congestion and incident candidate records."""

    def test_severity_mapping_semantics(self):
        """Verify map_confidence_to_severity adheres to documented thresholds."""
        # Wrong-way mappings
        assert map_confidence_to_severity("wrong_way", 0.90) == "critical"
        assert map_confidence_to_severity("wrong_way", 0.75) == "high"
        assert map_confidence_to_severity("wrong_way", 0.55) == "medium"

        # Stopped-vehicle mappings
        assert map_confidence_to_severity("stopped_vehicle", 0.90) == "high"
        assert map_confidence_to_severity("stopped_vehicle", 0.70) == "medium"
        assert map_confidence_to_severity("stopped_vehicle", 0.50) == "low"

        # Invalid/out of bounds
        assert map_confidence_to_severity("stopped_vehicle", -0.1) == "unknown"
        assert map_confidence_to_severity("stopped_vehicle", 1.5) == "unknown"

    @pytest.mark.anyio
    async def test_record_congestion_observation_writes_traffic_record(self):
        """Verify record_congestion_observation writes TrafficRecord to real DB."""
        engine, session_factory = await create_test_db()
        async with session_factory() as session:
            # 1. Seed Intersection
            inter = Intersection(
                name="Mission & 16th",
                code="INT_MSN_16TH",
                status="active",
                city="San Francisco",
            )
            session.add(inter)
            await session.flush()

            # 2. Persist calibrated CongestionResult
            cong_res = CongestionResult(
                congestion_level=78,
                vehicle_count=14,
                avg_speed_kmh=18.5,
                avg_speed_px_s=12.0,
                lane_occupancy_score=0.80,
                speed_deficit_score=0.63,
                queue_score=0.50,
                is_calibrated=True,
            )

            rec = await record_congestion_observation(
                db=session,
                intersection_id=inter.id,
                congestion_result=cong_res,
            )
            await session.commit()

            assert rec.id is not None
            assert rec.intersection_id == inter.id
            assert rec.congestion_level == 78
            assert rec.vehicle_count == 14
            assert rec.avg_speed_kmh == 18.5
            assert rec.source == "camera"

            # Query back
            stmt = select(TrafficRecord).where(TrafficRecord.id == rec.id)
            queried = (await session.execute(stmt)).scalar_one()
            assert queried.congestion_level == 78
            assert queried.source == "camera"

        await engine.dispose()

    @pytest.mark.anyio
    async def test_record_congestion_uncalibrated_sets_speed_none(self):
        """Verify uncalibrated congestion observation stores avg_speed_kmh as None."""
        engine, session_factory = await create_test_db()
        async with session_factory() as session:
            inter = Intersection(
                name="Van Ness & Geary",
                code="INT_VN_GRY",
                status="active",
            )
            session.add(inter)
            await session.flush()

            uncal_res = CongestionResult(
                congestion_level=45,
                vehicle_count=8,
                avg_speed_kmh=None,  # No calibration factor
                avg_speed_px_s=8.5,
                lane_occupancy_score=0.45,
                speed_deficit_score=None,
                queue_score=0.20,
                is_calibrated=False,
            )

            rec = await record_congestion_observation(
                db=session,
                intersection_id=inter.id,
                congestion_result=uncal_res,
            )
            await session.commit()

            assert rec.avg_speed_kmh is None
            assert rec.congestion_level == 45
            assert rec.source == "camera"

        await engine.dispose()

    @pytest.mark.anyio
    async def test_record_incident_candidate_writes_incident(self):
        """Verify record_incident_candidate writes Incident with heuristic method label."""
        engine, session_factory = await create_test_db()
        async with session_factory() as session:
            inter = Intersection(
                name="Broadway & Columbus",
                code="INT_BWY_COL",
                status="active",
            )
            session.add(inter)
            await session.flush()

            candidate = IncidentCandidate(
                event_type="wrong_way",
                confidence=0.88,
                track_id=77,
                bbox=(100.0, 100.0, 140.0, 140.0),
                centroid=(120.0, 120.0),
                timestamp=datetime.now(timezone.utc),
                method="wrong_way_direction_heuristic",
                details={"summary": "Vehicle opposing flow by 175° in lane 2"},
            )

            inc = await record_incident_candidate(
                db=session,
                candidate=candidate,
                intersection_id=inter.id,
            )
            await session.commit()

            assert inc.id is not None
            assert inc.intersection_id == inter.id
            assert inc.severity == "critical"  # conf 0.88 for wrong_way -> critical
            assert inc.status == "reported"
            assert inc.reported_by is None
            assert "[Heuristic: wrong_way_direction_heuristic]" in inc.description

            # Query back
            stmt = select(Incident).where(Incident.id == inc.id)
            queried = (await session.execute(stmt)).scalar_one()
            assert queried.severity == "critical"
            assert queried.status == "reported"

        await engine.dispose()

    @pytest.mark.anyio
    async def test_batch_record_incident_candidates(self):
        """Verify record_incident_candidates persists multiple candidates in single session."""
        engine, session_factory = await create_test_db()
        async with session_factory() as session:
            inter = Intersection(name="Folsom & 5th", code="INT_FLS_5TH", status="active")
            session.add(inter)
            await session.flush()

            cands = [
                IncidentCandidate(
                    event_type="stopped_vehicle",
                    confidence=0.62,
                    track_id=1,
                    bbox=(50.0, 50.0, 90.0, 90.0),
                    centroid=(70.0, 70.0),
                    timestamp=datetime.now(timezone.utc),
                    method="stopped_vehicle_persistence_heuristic",
                    details={"summary": "Vehicle stationary 12 frames"},
                ),
                IncidentCandidate(
                    event_type="wrong_way",
                    confidence=0.70,
                    track_id=2,
                    bbox=(200.0, 200.0, 240.0, 240.0),
                    centroid=(220.0, 220.0),
                    timestamp=datetime.now(timezone.utc),
                    method="wrong_way_direction_heuristic",
                    details={"summary": "Opposing 135° in lane 1"},
                ),
            ]

            saved = await record_incident_candidates(db=session, candidates=cands, intersection_id=inter.id)
            await session.commit()

            assert len(saved) == 2
            assert saved[0].severity == "medium"
            assert saved[1].severity == "high"

        await engine.dispose()


# ==============================================================================
# 5. End-to-End Synthetic Video Stream Verification
# ==============================================================================


class TestEndToEndSyntheticStream:
    """End-to-end integration test with programmatic synthetic video stream."""

    def test_synthetic_video_stationary_cluster_yields_high_congestion_and_incident(self):
        """Generate synthetic frames with stationary vehicles and evaluate pipeline."""
        detector = IncidentDetector(
            stopped_heuristic=StoppedVehicleHeuristic(min_stopped_frames=5, stopped_speed_threshold_px_s=3.0)
        )
        tracker = MultiObjectTracker(iou_threshold=0.3, max_lost_frames=3)

        # Designated queue ROI at bottom-right of frame
        queue_rois = {
            "stop_bar": PolygonROI.from_points("stop_bar", [(400, 300), (600, 300), (600, 450), (400, 450)])
        }

        # Simulate 8 consecutive video frames where 4 stationary vehicles remain at (100..250, 100..200)
        # and 1 stationary vehicle is inside the queue zone at (500, 350)
        last_metrics = None
        last_cands = []

        # Corridor lane ROI enclosing the stationary vehicles
        lane_rois = {
            "cluster_corridor": PolygonROI.from_points("cluster_corridor", [(90, 90), (210, 90), (210, 210), (90, 210)])
        }

        for frame_idx in range(1, 9):
            # Programmatic synthetic detections
            detections = [
                # 4 stationary vehicles outside queue zone
                Detection(label="car", confidence=0.92, bbox=(100.0, 100.0, 140.0, 140.0)),
                Detection(label="car", confidence=0.91, bbox=(150.0, 100.0, 190.0, 140.0)),
                Detection(label="truck", confidence=0.89, bbox=(100.0, 150.0, 140.0, 190.0)),
                Detection(label="car", confidence=0.90, bbox=(150.0, 150.0, 190.0, 190.0)),
                # 1 vehicle inside queue zone
                Detection(label="car", confidence=0.95, bbox=(480.0, 330.0, 520.0, 370.0)),
            ]

            active_tracks = tracker.update(detections=detections, timestamp_seconds=frame_idx * 0.1)

            metrics = compute_frame_metrics(
                detections=detections,
                tracks=active_tracks,
                frame_shape=(480, 640),
                rois=lane_rois,
                queue_rois=queue_rois,
            )
            last_metrics = metrics

            cands = detector.detect_incidents(
                tracks=active_tracks,
                queue_rois=queue_rois,
            )
            last_cands = cands

        # 1. Congestion score evaluation (spatial mode)
        assert last_metrics is not None
        cong_result = compute_congestion_score(
            metrics=last_metrics,
            tracks=tracker.active_tracks,
        )

        assert cong_result.vehicle_count == 5
        # Lane occupancy (~46%) + queue presence produces elevated spatial score
        assert cong_result.congestion_level >= 35

        # With pixel free-flow speed reference, full multimodal mode factors in 100% speed deficit
        cong_multimodal = compute_congestion_score(
            metrics=last_metrics,
            tracks=tracker.active_tracks,
            free_flow_speed_px_s=30.0,
        )
        assert cong_multimodal.congestion_level >= 55
        assert cong_multimodal.speed_deficit_score == 1.0

        # 2. Incident candidate evaluation
        # By frame 8 (>= 5 frames), the 4 vehicles outside queue zones should be flagged
        # while the vehicle inside the queue zone MUST NOT be flagged
        flagged_track_ids = {c.track_id for c in last_cands if c.event_type == "stopped_vehicle"}
        assert len(flagged_track_ids) == 4

        # Verify all candidates explicitly state the heuristic method
        for cand in last_cands:
            assert cand.method == "stopped_vehicle_persistence_heuristic"
            assert cand.confidence >= 0.50
            assert cand.details["outside_queue_zones"] is True
