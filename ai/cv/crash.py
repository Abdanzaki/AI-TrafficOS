"""Automated crash and collision candidate detection heuristic for AI TrafficOS.

Provides deterministic computer vision heuristics for identifying candidate traffic
collisions from vehicle tracking trajectories and speed histories:
1. Multi-vehicle sudden stop cluster: >= 2 tracks transitioning to stopped within a
   short frame/time window in close spatial proximity (building on StoppedVehicleHeuristic semantics).
2. Abrupt deceleration anomaly: per-track speed drop exceeding a configurable threshold
   between consecutive temporal windows (computed via estimate_speed_from_history).
3. Trajectory convergence anomaly: two or more tracks whose projected trajectories
   converge within a small radius at high combined speed shortly before stopping.

CRITICAL ARCHITECTURAL & HONESTY NOTICE:
----------------------------------------
This module is a DETERMINISTIC HEURISTIC ON 2D OPTICAL TRACKS, NOT A TRAINED MACHINE
LEARNING ACCIDENT DETECTION CLASSIFIER VALIDATED ON REAL CRASH FOOTAGE.
- 2D camera projections are subject to perspective foreshortening, occlusions, and optical noise.
- Every event emitted is a CANDIDATE requiring human traffic officer / dispatcher verification.
- Confidence is mathematically bounded in [0.0, 1.0] based on empirical signal strength.
- Low-confidence events STRICTLY retain the verdict 'possible'. The system NEVER asserts
  a crash with 'likely' unless multiple strong physical signals fire with sufficient margins.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import math
from typing import Any, Optional, Sequence

from ai.cv.tracking import (
    TrackedVehicle,
    compute_bbox_iou,
    compute_centroid,
    estimate_speed_from_history,
)


@dataclass(frozen=True)
class CrashCandidate:
    """Heuristically identified candidate collision or crash anomaly.

    Attributes:
        involved_track_ids: Stable tracking identifiers of the involved vehicles.
        timestamp: Measurement capture timestamp.
        confidence: Normalized empirical confidence score [0.0, 1.0].
        verdict: Categorical assessment ('likely' if confidence >= 0.75 else 'possible').
        junction_id: Optional intersection/junction ID where the anomaly was detected.
        camera_id: Optional camera identifier.
        location: Optional (cx, cy) pixel centroid of the collision cluster.
        signals_fired: List of signal identifiers that contributed to the detection.
        details: Diagnostic breakdown metadata dictionary.
        evidence_ref: Optional file path or URL to evidence frame snapshot.
    """

    involved_track_ids: list[int]
    timestamp: datetime
    confidence: float
    verdict: str  # 'likely' | 'possible'
    junction_id: Optional[int] = None
    camera_id: Optional[str] = None
    location: Optional[tuple[float, float]] = None
    signals_fired: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)
    evidence_ref: Optional[str] = None


class CrashHeuristic:
    """Deterministic CV heuristic combining multi-vehicle trajectory and speed anomalies.

    Signals Evaluated:
    - Signal A (Multi-Vehicle Stop Cluster): >=2 tracks transitioning to stopped within
      a short frame window in close spatial proximity.
    - Signal B (Abrupt Deceleration Anomaly): Speed drop exceeding a configurable threshold
      between consecutive history windows.
    - Signal C (Trajectory Convergence Anomaly): Tracks whose predicted positions converge
      within a small radius at high combined speed shortly before stopping.
    """

    def __init__(
        self,
        # Signal A: Multi-vehicle stop cluster parameters
        min_cluster_vehicles: int = 2,
        proximity_threshold_px: float = 100.0,
        stopped_speed_threshold_px_s: float = 5.0,
        max_cluster_stopped_frames: int = 15,
        # Signal B: Abrupt deceleration anomaly parameters
        deceleration_window_size: int = 5,
        min_prior_speed_px_s: float = 15.0,
        deceleration_drop_threshold_px_s: float = 20.0,
        min_drop_ratio: float = 0.50,
        # Signal C: Trajectory convergence anomaly parameters
        convergence_radius_px: float = 50.0,
        min_combined_speed_px_s: float = 30.0,
        convergence_lookahead_s: float = 2.5,
        # Verdict and scoring thresholds
        likely_confidence_threshold: float = 0.75,
        allow_single_vehicle_candidates: bool = True,
        cooldown_seconds: float = 10.0,
    ) -> None:
        """Initialize CrashHeuristic with configurable physical thresholds.

        Args:
            min_cluster_vehicles: Minimum vehicles required for a multi-vehicle cluster (default: 2).
            proximity_threshold_px: Maximum distance in pixels between vehicle centroids (default: 100.0).
            stopped_speed_threshold_px_s: Speed upper bound to consider stationary (default: 5.0 px/s).
            max_cluster_stopped_frames: Maximum frames vehicle may be stopped while still considered a fresh stop (default: 15).
            deceleration_window_size: Number of history observations per comparison window (default: 5).
            min_prior_speed_px_s: Minimum prior speed required to consider deceleration an anomaly (default: 15.0 px/s).
            deceleration_drop_threshold_px_s: Minimum speed drop (px/s) to flag deceleration anomaly (default: 20.0 px/s).
            min_drop_ratio: Minimum fractional speed drop (delta_v / v_prior) required (default: 0.50).
            convergence_radius_px: Smallest projected distance for trajectory convergence (default: 50.0 px).
            min_combined_speed_px_s: Combined approach speed threshold for convergence (default: 30.0 px/s).
            convergence_lookahead_s: Forward projection time horizon in seconds (default: 2.5s).
            likely_confidence_threshold: Confidence boundary dividing 'likely' from 'possible' (default: 0.75).
            allow_single_vehicle_candidates: If True, allow single-vehicle abrupt stop to emit 'possible' candidate (default: True).
            cooldown_seconds: Minimum seconds before re-emitting duplicate candidate for same track set (default: 10.0).
        """
        self.min_cluster_vehicles = int(min_cluster_vehicles)
        self.proximity_threshold_px = float(proximity_threshold_px)
        self.stopped_speed_threshold_px_s = float(stopped_speed_threshold_px_s)
        self.max_cluster_stopped_frames = int(max_cluster_stopped_frames)

        self.deceleration_window_size = int(deceleration_window_size)
        self.min_prior_speed_px_s = float(min_prior_speed_px_s)
        self.deceleration_drop_threshold_px_s = float(deceleration_drop_threshold_px_s)
        self.min_drop_ratio = float(min_drop_ratio)

        self.convergence_radius_px = float(convergence_radius_px)
        self.min_combined_speed_px_s = float(min_combined_speed_px_s)
        self.convergence_lookahead_s = float(convergence_lookahead_s)

        self.likely_confidence_threshold = float(likely_confidence_threshold)
        self.allow_single_vehicle_candidates = bool(allow_single_vehicle_candidates)
        self.cooldown_seconds = float(cooldown_seconds)

        # Internal state tracking
        self._stopped_frame_counts: dict[int, int] = {}
        self._last_emitted_clusters: dict[frozenset[int], float] = {}

    def reset(self) -> None:
        """Reset internal heuristic state and cooldown history."""
        self._stopped_frame_counts.clear()
        self._last_emitted_clusters.clear()

    def _get_effective_speed(self, track: TrackedVehicle) -> Optional[float]:
        """Determine current instantaneous/recent speed for a track."""
        if track.speed_px_s is not None:
            return float(track.speed_px_s)
        if len(track.history) >= 2:
            s_px, _ = estimate_speed_from_history(track.history[-3:], strict=False)
            return s_px
        return None

    def evaluate_deceleration_anomaly(
        self, track: TrackedVehicle
    ) -> tuple[bool, float, dict[str, Any]]:
        """Evaluate Signal B: Abrupt deceleration anomaly for a single track.

        Computes speed drop between an earlier temporal window and the most recent window
        using `estimate_speed_from_history`.

        Returns:
            tuple[bool, float, dict[str, Any]]: (fired, score_margin, diagnostic_details).
        """
        history = track.history
        min_required = max(3, self.deceleration_window_size)
        if len(history) < min_required:
            return False, 0.0, {"reason": "insufficient_history"}

        # Determine split window lengths
        w = min(self.deceleration_window_size, max(2, len(history) // 2))
        earlier_window = history[-(2 * w) : -w]
        recent_window = history[-w:]

        v_prior, _ = estimate_speed_from_history(earlier_window, strict=False)
        v_recent, _ = estimate_speed_from_history(recent_window, strict=False)

        if v_prior is None or v_recent is None:
            return False, 0.0, {"reason": "speed_estimation_none"}

        speed_drop = v_prior - v_recent
        drop_ratio = speed_drop / max(v_prior, 1e-3)

        dt = max(1e-3, recent_window[-1][1] - earlier_window[0][1])
        deceleration_rate = max(0.0, speed_drop / dt)

        # Check thresholds
        fired = (
            speed_drop >= self.deceleration_drop_threshold_px_s
            and v_prior >= self.min_prior_speed_px_s
            and drop_ratio >= self.min_drop_ratio
        )

        details = {
            "v_prior": round(v_prior, 2),
            "v_recent": round(v_recent, 2),
            "speed_drop": round(speed_drop, 2),
            "drop_ratio": round(drop_ratio, 3),
            "deceleration_rate": round(deceleration_rate, 2),
            "threshold_drop": self.deceleration_drop_threshold_px_s,
        }

        if not fired:
            return False, 0.0, details

        # Normalized score [0.5, 1.0] reflecting margin above threshold
        excess = speed_drop - self.deceleration_drop_threshold_px_s
        score = min(1.0, 0.50 + 0.30 * min(1.0, excess / 25.0) + 0.20 * min(1.0, drop_ratio))
        return True, round(score, 3), details

    def evaluate_trajectory_convergence(
        self,
        track_a: TrackedVehicle,
        track_b: TrackedVehicle,
    ) -> tuple[bool, float, dict[str, Any]]:
        """Evaluate Signal C: Trajectory convergence anomaly between two tracks.

        Checks whether the projected positions of two vehicles converge within a small radius
        at high combined speed shortly before stopping, or converged in their motion history.

        Returns:
            tuple[bool, float, dict[str, Any]]: (fired, score_margin, diagnostic_details).
        """
        hist_a = track_a.history
        hist_b = track_b.history

        if len(hist_a) < 2 or len(hist_b) < 2:
            return False, 0.0, {"reason": "insufficient_history"}

        # Candidate window pairs:
        # 1. Recent observations
        # 2. Pre-stop window (where vehicles were still moving at speed before standstill)
        w = min(self.deceleration_window_size, max(2, min(len(hist_a), len(hist_b)) // 2))
        window_pairs = []

        # Recent window
        window_pairs.append((hist_a[-w:], hist_b[-w:]))

        # Pre-stop window (shortly before stopping)
        if len(hist_a) >= 2 * w and len(hist_b) >= 2 * w:
            window_pairs.append((hist_a[-(2 * w) : -w], hist_b[-(2 * w) : -w]))

        # Full history spanning movement
        window_pairs.append((hist_a, hist_b))

        best_fired = False
        best_score = 0.0
        best_details: dict[str, Any] = {}

        for win_a, win_b in window_pairs:
            p_a1, t_a1 = win_a[0]
            p_a2, t_a2 = win_a[-1]
            dt_a = max(1e-3, t_a2 - t_a1)
            v_a = ((p_a2[0] - p_a1[0]) / dt_a, (p_a2[1] - p_a1[1]) / dt_a)
            speed_a = math.hypot(v_a[0], v_a[1])

            p_b1, t_b1 = win_b[0]
            p_b2, t_b2 = win_b[-1]
            dt_b = max(1e-3, t_b2 - t_b1)
            v_b = ((p_b2[0] - p_b1[0]) / dt_b, (p_b2[1] - p_b1[1]) / dt_b)
            speed_b = math.hypot(v_b[0], v_b[1])

            combined_speed = speed_a + speed_b
            if combined_speed < self.min_combined_speed_px_s:
                continue

            current_distance = math.hypot(p_a2[0] - p_b2[0], p_a2[1] - p_b2[1])

            # Projected closest approach
            rx = p_b2[0] - p_a2[0]
            ry = p_b2[1] - p_a2[1]
            vrx = v_b[0] - v_a[0]
            vry = v_b[1] - v_a[1]
            vr_sq = vrx * vrx + vry * vry

            min_separation = current_distance
            t_star = 0.0

            if vr_sq > 1e-4:
                t_star = -(rx * vrx + ry * vry) / vr_sq
                if 0.0 < t_star <= self.convergence_lookahead_s:
                    pred_rx = rx + vrx * t_star
                    pred_ry = ry + vry * t_star
                    min_separation = math.hypot(pred_rx, pred_ry)

            # Empirical separation reduction in motion history
            hist_sep_start = math.hypot(p_a1[0] - p_b1[0], p_a1[1] - p_b1[1])
            final_separation = math.hypot(hist_a[-1][0][0] - hist_b[-1][0][0], hist_a[-1][0][1] - hist_b[-1][0][1])
            empirical_convergence = (
                (final_separation <= self.convergence_radius_px or current_distance <= self.convergence_radius_px)
                and hist_sep_start > final_separation + 15.0
            )

            fired = (min_separation <= self.convergence_radius_px) or empirical_convergence

            if fired:
                prox_margin = max(0.0, 1.0 - min(min_separation, final_separation) / self.convergence_radius_px)
                speed_margin = min(1.0, (combined_speed - self.min_combined_speed_px_s) / 40.0)
                score = min(1.0, 0.50 + 0.30 * prox_margin + 0.20 * speed_margin)

                if score > best_score:
                    best_fired = True
                    best_score = round(score, 3)
                    best_details = {
                        "speed_a": round(speed_a, 2),
                        "speed_b": round(speed_b, 2),
                        "combined_speed": round(combined_speed, 2),
                        "current_distance": round(current_distance, 2),
                        "min_separation": round(min_separation, 2),
                        "final_separation": round(final_separation, 2),
                        "t_star": round(t_star, 2),
                        "empirical_convergence": empirical_convergence,
                    }

        if best_fired:
            return True, best_score, best_details

        return False, 0.0, {"reason": "no_convergence_trajectory"}

    def evaluate(
        self,
        tracks: Sequence[TrackedVehicle],
        timestamp: Optional[datetime] = None,
        junction_id: Optional[int] = None,
        camera_id: Optional[str] = None,
        pixels_per_meter: Optional[float] = None,
    ) -> list[CrashCandidate]:
        """Evaluate active tracked vehicles for crash and collision candidates.

        Args:
            tracks: Sequence of actively tracked vehicles.
            timestamp: Capture timestamp (defaults to current UTC).
            junction_id: Optional intersection/junction identifier.
            camera_id: Optional camera identifier.
            pixels_per_meter: Optional physical scale factor.

        Returns:
            list[CrashCandidate]: Detected crash candidate events.
        """
        now = timestamp or datetime.now(timezone.utc)
        now_ts = now.timestamp()
        candidates: list[CrashCandidate] = []

        active_track_ids = {t.track_id for t in tracks}
        tracks_by_id = {t.track_id: t for t in tracks}

        # 1. Update stationary counts and identify freshly stopped tracks
        freshly_stopped_ids: set[int] = set()
        deceleration_signals: dict[int, tuple[bool, float, dict[str, Any]]] = {}

        for track in tracks:
            tid = track.track_id
            spd = self._get_effective_speed(track)

            if spd is not None and spd <= self.stopped_speed_threshold_px_s:
                cnt = self._stopped_frame_counts.get(tid, 0) + 1
                self._stopped_frame_counts[tid] = cnt

                # Consider it a fresh stop transition if stopped count is within window
                if cnt <= self.max_cluster_stopped_frames:
                    freshly_stopped_ids.add(tid)
            else:
                self._stopped_frame_counts[tid] = 0

            # Evaluate deceleration anomaly for every track with history
            decel_fired, decel_score, decel_meta = self.evaluate_deceleration_anomaly(track)
            deceleration_signals[tid] = (decel_fired, decel_score, decel_meta)

        # Prune stale track IDs from stationary counters
        for tid in list(self._stopped_frame_counts.keys()):
            if tid not in active_track_ids:
                del self._stopped_frame_counts[tid]

        # 2. Build multi-vehicle spatial clusters among freshly stopped tracks
        stopped_list = [tracks_by_id[tid] for tid in freshly_stopped_ids]
        clusters: list[list[TrackedVehicle]] = []
        visited_ids: set[int] = set()

        for i, t_i in enumerate(stopped_list):
            if t_i.track_id in visited_ids:
                continue
            cluster = [t_i]
            visited_ids.add(t_i.track_id)

            for j, t_j in enumerate(stopped_list):
                if t_j.track_id in visited_ids:
                    continue
                dist = math.hypot(
                    t_i.centroid[0] - t_j.centroid[0],
                    t_i.centroid[1] - t_j.centroid[1],
                )
                iou = compute_bbox_iou(t_i.bbox, t_j.bbox)
                if dist <= self.proximity_threshold_px or iou > 0.05:
                    cluster.append(t_j)
                    visited_ids.add(t_j.track_id)

            clusters.append(cluster)

        # 3. Evaluate each cluster (multi-vehicle)
        processed_cluster_track_ids: set[int] = set()

        for cluster in clusters:
            cluster_tids = sorted([t.track_id for t in cluster])
            cluster_key = frozenset(cluster_tids)

            # Check cooldown to prevent duplicate emissions
            last_time = self._last_emitted_clusters.get(cluster_key, 0.0)
            if (now_ts - last_time) < self.cooldown_seconds:
                processed_cluster_track_ids.update(cluster_tids)
                continue

            # Multi-vehicle cluster criteria
            if len(cluster) >= self.min_cluster_vehicles:
                processed_cluster_track_ids.update(cluster_tids)

                # Signal A: Multi-vehicle stop cluster fired
                signal_a_fired = True
                # Compute average distance in cluster
                distances = []
                for idx_a in range(len(cluster)):
                    for idx_b in range(idx_a + 1, len(cluster)):
                        d = math.hypot(
                            cluster[idx_a].centroid[0] - cluster[idx_b].centroid[0],
                            cluster[idx_a].centroid[1] - cluster[idx_b].centroid[1],
                        )
                        distances.append(d)
                avg_dist = sum(distances) / max(1, len(distances)) if distances else 0.0
                prox_margin = max(0.0, 1.0 - (avg_dist / self.proximity_threshold_px))
                score_a = min(1.0, 0.60 + 0.30 * prox_margin + 0.10 * (len(cluster) - 2))

                # Signal B: Abrupt deceleration anomaly across cluster tracks
                cluster_decel_scores = [
                    deceleration_signals[tid][1]
                    for tid in cluster_tids
                    if deceleration_signals[tid][0]
                ]
                signal_b_fired = len(cluster_decel_scores) > 0
                score_b = (
                    sum(cluster_decel_scores) / len(cluster_decel_scores)
                    if signal_b_fired
                    else 0.0
                )

                # Signal C: Trajectory convergence anomaly between any pair in cluster
                signal_c_fired = False
                score_c = 0.0
                conv_details = {}
                for idx_a in range(len(cluster)):
                    for idx_b in range(idx_a + 1, len(cluster)):
                        c_fired, c_score, c_meta = self.evaluate_trajectory_convergence(
                            cluster[idx_a], cluster[idx_b]
                        )
                        if c_fired:
                            signal_c_fired = True
                            if c_score > score_c:
                                score_c = c_score
                                conv_details = c_meta

                # Combine signals and score confidence
                signals_fired = ["multi_vehicle_stop_cluster"]
                if signal_b_fired:
                    signals_fired.append("abrupt_deceleration")
                if signal_c_fired:
                    signals_fired.append("trajectory_convergence")

                # Scoring function:
                # - 3 signals fired: [0.80, 0.98] -> 'likely'
                # - Stop cluster + deceleration fired: [0.75, 0.88] -> 'likely'
                # - Stop cluster only (weak/no deceleration or convergence): [0.45, 0.65] -> 'possible'
                if signal_a_fired and signal_b_fired and signal_c_fired:
                    conf = 0.35 * score_a + 0.35 * score_b + 0.20 * score_c + 0.10
                elif signal_a_fired and signal_b_fired:
                    # Both stop cluster and abrupt deceleration fired
                    conf = 0.40 * score_a + 0.40 * score_b + 0.05
                elif signal_a_fired and signal_c_fired:
                    conf = 0.50 * score_a + 0.35 * score_c
                else:
                    # Stop cluster alone without confirmed abrupt deceleration or convergence
                    # Low-confidence events MUST STAY 'possible'
                    conf = min(0.65, 0.35 + 0.25 * score_a)

                conf = round(min(0.98, max(0.10, conf)), 2)
                verdict = "likely" if conf >= self.likely_confidence_threshold else "possible"

                # Cluster centroid
                cx = sum(t.centroid[0] for t in cluster) / len(cluster)
                cy = sum(t.centroid[1] for t in cluster) / len(cluster)

                cand = CrashCandidate(
                    involved_track_ids=cluster_tids,
                    timestamp=now,
                    confidence=conf,
                    verdict=verdict,
                    junction_id=junction_id,
                    camera_id=camera_id,
                    location=(round(cx, 1), round(cy, 1)),
                    signals_fired=signals_fired,
                    details={
                        "vehicle_count": len(cluster),
                        "cluster_avg_distance_px": round(avg_dist, 1),
                        "signal_scores": {
                            "stop_cluster": round(score_a, 3),
                            "deceleration": round(score_b, 3),
                            "convergence": round(score_c, 3),
                        },
                        "convergence_details": conv_details,
                    },
                )
                candidates.append(cand)
                self._last_emitted_clusters[cluster_key] = now_ts

        # 4. Evaluate single-vehicle candidates (e.g. vehicle experiencing an abrupt deceleration spike)
        if self.allow_single_vehicle_candidates:
            for track in tracks:
                tid = track.track_id
                if tid in processed_cluster_track_ids:
                    continue

                decel_fired, decel_score, decel_meta = deceleration_signals[tid]
                if decel_fired:
                    single_key = frozenset([tid])
                    last_time = self._last_emitted_clusters.get(single_key, 0.0)
                    if (now_ts - last_time) < self.cooldown_seconds:
                        continue

                    # Single vehicle deceleration anomaly:
                    # STRICT HONESTY RULE: Single-vehicle stop stays 'possible' (ceiling < 0.75)
                    conf = round(min(0.65, 0.35 + 0.25 * decel_score), 2)
                    verdict = "possible"

                    cand = CrashCandidate(
                        involved_track_ids=[tid],
                        timestamp=now,
                        confidence=conf,
                        verdict=verdict,
                        junction_id=junction_id,
                        camera_id=camera_id,
                        location=track.centroid,
                        signals_fired=["abrupt_deceleration"],
                        details={
                            "vehicle_count": 1,
                            "deceleration_details": decel_meta,
                            "signal_scores": {"deceleration": round(decel_score, 3)},
                        },
                    )
                    candidates.append(cand)
                    self._last_emitted_clusters[single_key] = now_ts

        return candidates
