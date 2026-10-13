"""Deterministic synthetic unit tests for RedLightViolationHeuristic.

SYNTHETIC FIXTURE NOTICE:
-------------------------
All video frames, trajectories, and TrackedVehicle sequences in this module are
PROGRAMMATICALLY SYNTHETIC FIXTURES created for deterministic unit verification.
No external video files or physical cameras are utilized.
"""

from datetime import datetime, timezone
import pytest

from ai.cv.tracking import TrackedVehicle
from ai.cv.violations import (
    RedLightViolationHeuristic,
    StopLineConfig,
    ViolationCandidate,
    compute_segment_intersection,
    segments_intersect,
)


@pytest.fixture
def synthetic_stop_line() -> StopLineConfig:
    """Synthetic stop-line segment across lane 1 at Y=300 (from X=100 to X=500)."""
    return StopLineConfig(
        camera_id="cam_junction_01",
        p1=(100.0, 300.0),
        p2=(500.0, 300.0),
        lane_id="lane_1_northbound",
        approach_heading_deg=270.0,  # Moving northward (-Y, screen angle 270°)
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
    w, h = 60.0, 40.0
    bbox = (last_pos[0] - w / 2, last_pos[1] - h / 2, last_pos[0] + w / 2, last_pos[1] + h / 2)
    return TrackedVehicle(
        track_id=track_id,
        label=label,
        confidence=confidence,
        bbox=bbox,
        centroid=last_pos,
        history=history,
        speed_px_s=45.0,
        hits=len(positions),
    )


def test_segment_intersection_geometry():
    """Verify 2D line segment intersection mathematical primitives."""
    # Perpendicular intersection
    pA, pB = (200.0, 350.0), (200.0, 250.0)  # Vertical line crossing Y=300
    p1, p2 = (100.0, 300.0), (500.0, 300.0)  # Horizontal stop line at Y=300
    assert segments_intersect(pA, pB, p1, p2) is True
    pt = compute_segment_intersection(pA, pB, p1, p2)
    assert pt == (200.0, 300.0)

    # Parallel non-intersecting line
    pA_par, pB_par = (100.0, 350.0), (500.0, 350.0)
    assert segments_intersect(pA_par, pB_par, p1, p2) is False
    assert compute_segment_intersection(pA_par, pB_par, p1, p2) is None

    # Line not reaching stop line
    pA_short, pB_short = (200.0, 380.0), (200.0, 320.0)
    assert segments_intersect(pA_short, pB_short, p1, p2) is False


def test_red_light_crossing_during_red_emits_violation(synthetic_stop_line: StopLineConfig):
    """Synthetic vehicle trajectory crossing stop-line while signal is RED must emit violation."""
    heuristic = RedLightViolationHeuristic()
    now = datetime(2026, 10, 13, 12, 0, 0, tzinfo=timezone.utc)

    # Vehicle approaches from Y=350, crosses Y=300 to Y=250
    track = build_synthetic_track(
        track_id=101,
        positions=[(250.0, 350.0), (250.0, 250.0)],
        label="car",
        confidence=0.92,
    )

    violations = heuristic.evaluate(
        tracks=[track],
        stop_lines=[synthetic_stop_line],
        signal_phase="red",
        timestamp=now,
    )

    assert len(violations) == 1
    v: ViolationCandidate = violations[0]
    assert v.violation_type == "red_light"
    assert v.track_id == 101
    assert v.camera_id == "cam_junction_01"
    assert v.detected_at == now
    assert 0.70 <= v.confidence <= 1.0
    assert v.details["crossing_point"] == [250.0, 300.0] or v.details["crossing_point"] == (250.0, 300.0)
    assert v.details["signal_phase"] == "red"
    assert v.details["lane_id"] == "lane_1_northbound"


def test_red_light_crossing_during_green_or_yellow_no_violation(synthetic_stop_line: StopLineConfig):
    """Synthetic vehicle crossing stop-line during GREEN or YELLOW must NOT emit violation."""
    heuristic = RedLightViolationHeuristic()
    now = datetime(2026, 10, 13, 12, 0, 0, tzinfo=timezone.utc)

    track = build_synthetic_track(
        track_id=102,
        positions=[(250.0, 350.0), (250.0, 250.0)],
        label="truck",
    )

    # 1. Green phase
    violations_green = heuristic.evaluate(
        tracks=[track],
        stop_lines=[synthetic_stop_line],
        signal_phase="green",
        timestamp=now,
    )
    assert len(violations_green) == 0

    # 2. Yellow phase
    violations_yellow = heuristic.evaluate(
        tracks=[track],
        stop_lines=[synthetic_stop_line],
        signal_phase="yellow",
        timestamp=now,
    )
    assert len(violations_yellow) == 0

    # 3. Unknown phase
    violations_unknown = heuristic.evaluate(
        tracks=[track],
        stop_lines=[synthetic_stop_line],
        signal_phase="unknown",
        timestamp=now,
    )
    assert len(violations_unknown) == 0


def test_red_light_not_crossing_stop_line(synthetic_stop_line: StopLineConfig):
    """Vehicle stopped before stop line or moving parallel during RED must NOT trigger violation."""
    heuristic = RedLightViolationHeuristic()
    now = datetime(2026, 10, 13, 12, 0, 0, tzinfo=timezone.utc)

    # Stopping at Y=320 (before stop line at Y=300)
    track_stopped = build_synthetic_track(
        track_id=103,
        positions=[(250.0, 340.0), (250.0, 320.0)],
    )

    violations = heuristic.evaluate(
        tracks=[track_stopped],
        stop_lines=[synthetic_stop_line],
        signal_phase="red",
        timestamp=now,
    )
    assert len(violations) == 0


def test_red_light_debounce_one_per_cycle(synthetic_stop_line: StopLineConfig):
    """Vehicle continuing in red phase is debounced: at most 1 violation per red signal cycle."""
    heuristic = RedLightViolationHeuristic()
    t1 = datetime(2026, 10, 13, 12, 0, 0, tzinfo=timezone.utc)
    t2 = datetime(2026, 10, 13, 12, 0, 1, tzinfo=timezone.utc)

    # Frame 1: crosses stop line
    track_f1 = build_synthetic_track(
        track_id=104,
        positions=[(250.0, 340.0), (250.0, 260.0)],
    )
    v1 = heuristic.evaluate(
        tracks=[track_f1],
        stop_lines=[synthetic_stop_line],
        signal_phase="red",
        timestamp=t1,
    )
    assert len(v1) == 1

    # Frame 2: continuing forward in the same red cycle
    track_f2 = build_synthetic_track(
        track_id=104,
        positions=[(250.0, 340.0), (250.0, 260.0), (250.0, 180.0)],
    )
    v2 = heuristic.evaluate(
        tracks=[track_f2],
        stop_lines=[synthetic_stop_line],
        signal_phase="red",
        timestamp=t2,
    )
    # Debounced: should emit 0 violations
    assert len(v2) == 0

    # Signal transitions to GREEN, then to RED (new cycle)
    heuristic.evaluate(tracks=[], stop_lines=[synthetic_stop_line], signal_phase="green")

    # New cycle with another crossing (e.g. same track or loop)
    t3 = datetime(2026, 10, 13, 12, 2, 0, tzinfo=timezone.utc)
    track_f3 = build_synthetic_track(
        track_id=104,
        positions=[(250.0, 350.0), (250.0, 250.0)],
    )
    v3 = heuristic.evaluate(
        tracks=[track_f3],
        stop_lines=[synthetic_stop_line],
        signal_phase="red",
        timestamp=t3,
    )
    # Allowed in new red cycle
    assert len(v3) == 1


def test_red_light_backing_up_rejected(synthetic_stop_line: StopLineConfig):
    """Vehicle backing up away from intersection (+Y heading) must NOT trigger violation."""
    heuristic = RedLightViolationHeuristic()
    now = datetime(2026, 10, 13, 12, 0, 0, tzinfo=timezone.utc)

    # Moves from Y=280 to Y=350 (backing up out of intersection)
    track_reversing = build_synthetic_track(
        track_id=105,
        positions=[(250.0, 280.0), (250.0, 350.0)],
    )

    violations = heuristic.evaluate(
        tracks=[track_reversing],
        stop_lines=[synthetic_stop_line],
        signal_phase="red",
        timestamp=now,
    )
    assert len(violations) == 0
