"""Deterministic synthetic unit tests for WrongWayViolationHeuristic.

SYNTHETIC FIXTURE NOTICE:
-------------------------
All trajectory tracks and LaneDirectionConfig geometries in this module are
PROGRAMMATICALLY SYNTHETIC FIXTURES created for deterministic unit verification.
No real camera feeds or road recordings are used.
"""

from datetime import datetime, timezone
import pytest

from ai.cv.incidents import LaneDirectionConfig, WrongWayHeuristic
from ai.cv.metrics import PolygonROI
from ai.cv.tracking import TrackedVehicle
from ai.cv.violations import ViolationCandidate, WrongWayViolationHeuristic


@pytest.fixture
def synthetic_eastbound_lane() -> LaneDirectionConfig:
    """Synthetic lane ROI with expected Eastbound (+X / 0°) motion."""
    roi = [(100.0, 200.0), (800.0, 200.0), (800.0, 300.0), (100.0, 300.0)]
    return LaneDirectionConfig(
        name="lane_eastbound",
        roi=roi,
        expected_direction_deg=0.0,  # +X heading
        tolerance_deg=90.0,
        min_motion_distance_px=15.0,
        min_history_points=3,
    )


def build_synthetic_track(
    track_id: int,
    positions: list[tuple[float, float]],
    label: str = "car",
    confidence: float = 0.90,
) -> TrackedVehicle:
    """Build a deterministic synthetic TrackedVehicle with specified centroid history."""
    history = [((pos[0], pos[1]), float(i) * 0.1) for i, pos in enumerate(positions)]
    last_pos = positions[-1] if positions else (0.0, 0.0)
    w, h = 50.0, 30.0
    bbox = (last_pos[0] - w / 2, last_pos[1] - h / 2, last_pos[0] + w / 2, last_pos[1] + h / 2)
    return TrackedVehicle(
        track_id=track_id,
        label=label,
        confidence=confidence,
        bbox=bbox,
        centroid=last_pos,
        history=history,
        speed_px_s=40.0,
        hits=len(positions),
    )


def test_wrong_way_opposing_trajectory_emits_violation(synthetic_eastbound_lane: LaneDirectionConfig):
    """Vehicle moving Westbound (180°) in Eastbound (0°) lane must emit a wrong-way violation."""
    heuristic = WrongWayViolationHeuristic()
    now = datetime(2026, 10, 13, 12, 0, 0, tzinfo=timezone.utc)

    # Moving from X=500 to X=400 (Westward, opposing 0° expected heading by 180°)
    track = build_synthetic_track(
        track_id=201,
        positions=[(500.0, 250.0), (450.0, 250.0), (400.0, 250.0)],
        label="car",
    )

    violations = heuristic.evaluate(
        tracks=[track],
        lane_configs=[synthetic_eastbound_lane],
        timestamp=now,
        camera_id="cam_corridor_02",
    )

    assert len(violations) == 1
    v: ViolationCandidate = violations[0]
    assert v.violation_type == "wrong_way"
    assert v.track_id == 201
    assert v.camera_id == "cam_corridor_02"
    assert v.detected_at == now
    assert 0.50 <= v.confidence <= 1.0
    assert v.details["lane_name"] == "lane_eastbound"
    assert abs(v.details["angular_deviation_deg"] - 180.0) < 5.0


def test_wrong_way_aligned_trajectory_no_violation(synthetic_eastbound_lane: LaneDirectionConfig):
    """Vehicle moving Eastbound (+X) conforming to lane direction must NOT emit violation."""
    heuristic = WrongWayViolationHeuristic()
    now = datetime(2026, 10, 13, 12, 0, 0, tzinfo=timezone.utc)

    # Moving from X=200 to X=350 (Eastward, exactly aligned with 0° heading)
    track = build_synthetic_track(
        track_id=202,
        positions=[(200.0, 250.0), (280.0, 250.0), (350.0, 250.0)],
        label="bus",
    )

    violations = heuristic.evaluate(
        tracks=[track],
        lane_configs=[synthetic_eastbound_lane],
        timestamp=now,
        camera_id="cam_corridor_02",
    )

    assert len(violations) == 0


def test_wrong_way_debounce_same_track(synthetic_eastbound_lane: LaneDirectionConfig):
    """Repeated frames of the same offending track must be debounced to avoid flood."""
    heuristic = WrongWayViolationHeuristic()
    t1 = datetime(2026, 10, 13, 12, 0, 0, tzinfo=timezone.utc)
    t2 = datetime(2026, 10, 13, 12, 0, 1, tzinfo=timezone.utc)

    track_frame1 = build_synthetic_track(
        track_id=203,
        positions=[(600.0, 250.0), (550.0, 250.0), (500.0, 250.0)],
    )
    v1 = heuristic.evaluate(
        tracks=[track_frame1],
        lane_configs=[synthetic_eastbound_lane],
        timestamp=t1,
    )
    assert len(v1) == 1

    # Continuing in next frame
    track_frame2 = build_synthetic_track(
        track_id=203,
        positions=[(600.0, 250.0), (550.0, 250.0), (500.0, 250.0), (450.0, 250.0)],
    )
    v2 = heuristic.evaluate(
        tracks=[track_frame2],
        lane_configs=[synthetic_eastbound_lane],
        timestamp=t2,
    )
    # Debounced: should emit 0 violations
    assert len(v2) == 0


def test_wrong_way_incident_behavior_preserved(synthetic_eastbound_lane: LaneDirectionConfig):
    """Verify underlying WrongWayHeuristic from ai.cv.incidents functions concurrently."""
    underlying = WrongWayHeuristic()
    heuristic = WrongWayViolationHeuristic(wrong_way_heuristic=underlying)
    now = datetime(2026, 10, 13, 12, 0, 0, tzinfo=timezone.utc)

    track = build_synthetic_track(
        track_id=204,
        positions=[(500.0, 250.0), (450.0, 250.0), (400.0, 250.0)],
    )

    # Direct incident heuristic call
    incidents = underlying.evaluate(
        tracks=[track],
        lane_configs=[synthetic_eastbound_lane],
        timestamp=now,
    )
    assert len(incidents) == 1
    assert incidents[0].event_type == "wrong_way"

    # Wrapper violation heuristic call
    violations = heuristic.evaluate(
        tracks=[track],
        lane_configs=[synthetic_eastbound_lane],
        timestamp=now,
    )
    assert len(violations) == 1
    assert violations[0].violation_type == "wrong_way"
    assert violations[0].confidence == incidents[0].confidence
