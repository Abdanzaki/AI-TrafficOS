"""Deterministic unit tests for CrashHeuristic (ai/cv/crash.py).

HONESTY & TESTING NOTICE:
-------------------------
All fixtures in this file are SYNTHETIC, ARTIFICIALLY GENERATED 2D trajectory sequences
designed to rigorously and deterministically verify the heuristic algorithms.
They DO NOT represent real-world physical crash video datasets or vehicle telemetry.
"""

from datetime import datetime, timezone
import pytest

from ai.cv.crash import CrashCandidate, CrashHeuristic
from ai.cv.tracking import TrackedVehicle


def make_synthetic_track(
    track_id: int,
    positions: list[tuple[float, float]],
    timestamps: list[float],
    bbox_size: tuple[float, float] = (40.0, 40.0),
    label: str = "car",
    speed_px_s: float | None = None,
) -> TrackedVehicle:
    """SYNTHETIC FIXTURE HELPER: Build a TrackedVehicle from deterministic (x, y, t) tuples."""
    assert len(positions) == len(timestamps), "positions and timestamps must align"
    history = list(zip(positions, timestamps))
    cx, cy = positions[-1]
    w, h = bbox_size
    bbox = (cx - w / 2.0, cy - h / 2.0, cx + w / 2.0, cy + h / 2.0)

    # Compute instantaneous speed if not provided
    if speed_px_s is None and len(positions) >= 2:
        dx = positions[-1][0] - positions[-2][0]
        dy = positions[-1][1] - positions[-2][1]
        dt = max(1e-3, timestamps[-1] - timestamps[-2])
        calc_speed = round(((dx * dx + dy * dy) ** 0.5) / dt, 2)
    else:
        calc_speed = speed_px_s

    return TrackedVehicle(
        track_id=track_id,
        label=label,
        confidence=0.95,
        bbox=bbox,
        centroid=(cx, cy),
        history=history,
        speed_px_s=calc_speed,
        speed_kmh=None,
        displacement_px=0.0,
        hits=len(positions),
        lost_frames=0,
    )


# ==============================================================================
# 1. Multi-vehicle sudden-stop cluster -> 'likely'
# ==============================================================================

def test_multi_vehicle_sudden_stop_cluster_yields_likely():
    """SYNTHETIC TEST: Two vehicles approaching at high speed, converging, and abruptly stopping together."""
    # Track 1: Moving right at ~50 px/s for 6 frames, then stopped for 4 frames at (130, 100)
    t_vals = [i * 0.1 for i in range(11)]  # 0.0 to 1.0s
    pos_1 = [
        (100.0 + i * 5.0, 100.0) if i <= 6 else (130.0, 100.0)
        for i in range(11)
    ]
    track_1 = make_synthetic_track(1, pos_1, t_vals, speed_px_s=0.0)

    # Track 2: Moving left at ~60 px/s for 6 frames, converging to (138, 102), then stopped
    pos_2 = [
        (174.0 - i * 6.0, 102.0) if i <= 6 else (138.0, 102.0)
        for i in range(11)
    ]
    track_2 = make_synthetic_track(2, pos_2, t_vals, speed_px_s=0.0)

    heuristic = CrashHeuristic()
    eval_time = datetime(2026, 10, 13, 12, 0, 0, tzinfo=timezone.utc)
    candidates = heuristic.evaluate([track_1, track_2], timestamp=eval_time, junction_id=42)

    assert len(candidates) == 1, "Must emit exactly one candidate for the multi-vehicle cluster"
    cand = candidates[0]
    assert set(cand.involved_track_ids) == {1, 2}
    assert cand.junction_id == 42
    assert cand.confidence >= 0.75, f"Confidence {cand.confidence} must be >= 0.75 for multi-vehicle cluster"
    assert cand.verdict == "likely"
    assert "multi_vehicle_stop_cluster" in cand.signals_fired
    assert "abrupt_deceleration" in cand.signals_fired
    assert "trajectory_convergence" in cand.signals_fired
    assert cand.location is not None
    # Cluster centroid is approximately halfway between (130, 100) and (138, 102)
    assert 130.0 <= cand.location[0] <= 140.0


# ==============================================================================
# 2. Single-vehicle stop -> 'possible' or no candidate
# ==============================================================================

def test_single_vehicle_abrupt_stop_yields_possible():
    """SYNTHETIC TEST: Single vehicle abruptly decelerating into a barrier (no multi-vehicle cluster)."""
    t_vals = [i * 0.1 for i in range(11)]
    pos_1 = [
        (50.0 + i * 5.0, 50.0) if i <= 6 else (80.0, 50.0)
        for i in range(11)
    ]
    track_1 = make_synthetic_track(1, pos_1, t_vals, speed_px_s=0.0)

    # Isolated vehicle 2 cruising normally at 40 px/s, far away (400, 400)
    pos_2 = [(400.0 + i * 4.0, 400.0) for i in range(11)]
    track_2 = make_synthetic_track(2, pos_2, t_vals, speed_px_s=40.0)

    heuristic = CrashHeuristic(allow_single_vehicle_candidates=True)
    candidates = heuristic.evaluate([track_1, track_2])

    assert len(candidates) == 1
    cand = candidates[0]
    assert cand.involved_track_ids == [1]
    assert cand.verdict == "possible"
    assert cand.confidence < 0.75, "Single vehicle candidate MUST remain strictly 'possible' (< 0.75)"
    assert "abrupt_deceleration" in cand.signals_fired
    assert "multi_vehicle_stop_cluster" not in cand.signals_fired


def test_single_vehicle_normal_stop_yields_no_candidate():
    """SYNTHETIC TEST: Single vehicle stopped without prior high speed or abrupt deceleration yields no candidate."""
    t_vals = [i * 0.1 for i in range(11)]
    # Stationary for all frames
    pos = [(100.0, 100.0) for _ in range(11)]
    track = make_synthetic_track(1, pos, t_vals, speed_px_s=0.0)

    heuristic = CrashHeuristic()
    candidates = heuristic.evaluate([track])
    assert len(candidates) == 0, "Consistently stationary vehicle must not generate crash candidate"


# ==============================================================================
# 3. Gradual congestion slowdown -> no candidate (avoids traffic jam false alarms)
# ==============================================================================

def test_gradual_congestion_slowdown_yields_no_candidate():
    """SYNTHETIC TEST: Traffic jam where vehicles gradually slow down over 15 frames.
    
    Ensures zero false positives on gradual queue formation.
    """
    t_vals = [i * 0.1 for i in range(16)]

    # Vehicle A: Slows gradually from 25 px/s to 10 px/s (step sizes: 2.5, 2.4, 2.3...)
    pos_a = [(100.0, 100.0)]
    curr_x = 100.0
    for i in range(1, 16):
        curr_x += max(0.5, 2.5 - (i * 0.13))
        pos_a.append((round(curr_x, 2), 100.0))
    track_a = make_synthetic_track(10, pos_a, t_vals, speed_px_s=8.0)

    # Vehicle B: Trailing vehicle behind A, slowing gradually similarly
    pos_b = [(70.0, 100.0)]
    curr_x_b = 70.0
    for i in range(1, 16):
        curr_x_b += max(0.5, 2.4 - (i * 0.12))
        pos_b.append((round(curr_x_b, 2), 100.0))
    track_b = make_synthetic_track(11, pos_b, t_vals, speed_px_s=7.5)

    heuristic = CrashHeuristic()
    candidates = heuristic.evaluate([track_a, track_b])

    assert len(candidates) == 0, "Gradual congestion slowdown must NOT trigger crash candidates"


# ==============================================================================
# 4. Abrupt deceleration spike -> candidate
# ==============================================================================

def test_abrupt_deceleration_spike_triggers_candidate():
    """SYNTHETIC TEST: Vehicle cruising at 60 px/s experiences sudden deceleration drop of 50 px/s."""
    t_vals = [i * 0.1 for i in range(10)]
    # Cruising fast: 6.0 px per 0.1s (= 60 px/s)
    pos = [
        (200.0 + i * 6.0, 300.0) if i <= 5 else (230.0 + (i - 5) * 0.2, 300.0)
        for i in range(10)
    ]
    track = make_synthetic_track(3, pos, t_vals, speed_px_s=2.0)

    heuristic = CrashHeuristic()
    candidates = heuristic.evaluate([track])

    assert len(candidates) == 1
    cand = candidates[0]
    assert cand.involved_track_ids == [3]
    assert "abrupt_deceleration" in cand.signals_fired
    assert cand.verdict == "possible"
    assert cand.confidence < 0.75


# ==============================================================================
# 5. Cooldown deduplication and reset
# ==============================================================================

def test_cooldown_and_reset_behavior():
    """SYNTHETIC TEST: Verified candidate is suppressed during cooldown until reset() is called."""
    t_vals = [i * 0.1 for i in range(11)]
    pos_1 = [(100.0 + i * 5.0, 100.0) if i <= 6 else (130.0, 100.0) for i in range(11)]
    track_1 = make_synthetic_track(1, pos_1, t_vals, speed_px_s=0.0)

    pos_2 = [(174.0 - i * 6.0, 102.0) if i <= 6 else (138.0, 102.0) for i in range(11)]
    track_2 = make_synthetic_track(2, pos_2, t_vals, speed_px_s=0.0)

    heuristic = CrashHeuristic(cooldown_seconds=10.0)
    t0 = datetime(2026, 10, 13, 12, 0, 0, tzinfo=timezone.utc)
    cands_first = heuristic.evaluate([track_1, track_2], timestamp=t0)
    assert len(cands_first) == 1

    # Second frame within cooldown window (1s later)
    t1 = datetime(2026, 10, 13, 12, 0, 1, tzinfo=timezone.utc)
    cands_second = heuristic.evaluate([track_1, track_2], timestamp=t1)
    assert len(cands_second) == 0, "Duplicate cluster within cooldown must be suppressed"

    # Reset clears cooldown
    heuristic.reset()
    cands_after_reset = heuristic.evaluate([track_1, track_2], timestamp=t1)
    assert len(cands_after_reset) == 1, "Reset must allow re-evaluation"
