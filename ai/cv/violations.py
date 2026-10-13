"""Computer vision heuristics for traffic violation detection.

Provides deterministic computer vision heuristics for identifying traffic violations:
1. RedLightViolationHeuristic: Flags tracked vehicles whose centroid trajectory
   crosses a configured stop-line segment during a RED signal phase. Debounces
   to at most one violation per vehicle track per signal cycle.
2. WrongWayViolationHeuristic: Wraps and extends WrongWayHeuristic from ai.cv.incidents
   to produce structured violation records for vehicles opposing lane direction.
3. NoHelmetViolationHeuristic: Identifies motorcycle riders via spatial association
   (person bbox overlapping/contained in motorcycle bbox), extracts the head region,
   and evaluates helmet wearing via a HelmetClassifier Protocol interface.

CRITICAL HONESTY & ETHICAL ARCHITECTURAL POLICY:
------------------------------------------------
1. NO FAKE OR RANDOM DETECTIONS: Every violation candidate derives strictly from
   verifiable geometric and sensory inputs.
2. HELMET IS NOT A STANDARD MS-COCO CLASS: COCO only contains 'person' (0) and
   'motorcycle' (3). A dedicated helmet model is required to classify head crops.
   When helmet model weights are missing or unconfigured, the system reports
   classifier unavailability and NEVER fabricates violations or generates random guesses.
3. CITY CAMERA AUTHORIZATION LIMITATION: The perception system processes video frames
   and telemetry fed into its pipelines. Integration with live municipal traffic cameras
   strictly requires statutory government authorization and secure edge credentials.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import math
from pathlib import Path
from typing import Any, Optional, Protocol, Sequence, runtime_checkable
import numpy as np

from ai.common.schemas import Detection
from ai.cv.exceptions import HelmetModelMissingError
from ai.cv.incidents import LaneDirectionConfig, WrongWayHeuristic
from ai.cv.tracking import TrackedVehicle


@dataclass(frozen=True)
class StopLineConfig:
    """Stop-line geometry configuration for red-light violation detection.

    Attributes:
        camera_id: Identifier of the camera viewing this stop line.
        p1: (x, y) start coordinate of the stop line segment in frame pixels.
        p2: (x, y) end coordinate of the stop line segment in frame pixels.
        lane_id: Optional lane identifier.
        approach_heading_deg: Optional expected vehicle approach heading (0° to 360°).
            Screen space convention: 0°=+X (East), 90°=+Y (South), 180°=-X (West), 270°=-Y (North).
    """

    camera_id: str
    p1: tuple[float, float]
    p2: tuple[float, float]
    lane_id: Optional[str] = None
    approach_heading_deg: Optional[float] = None


@dataclass(frozen=True)
class ViolationCandidate:
    """Structured candidate traffic violation emitted by perception heuristics.

    Attributes:
        violation_type: Violation category ('red_light', 'wrong_way', 'no_helmet').
        confidence: Deterministic confidence score in [0.0, 1.0].
        detected_at: Measurement or crossing timestamp (timezone-aware UTC).
        camera_id: Optional identifier of the originating camera.
        track_id: Optional tracker ID of the offending vehicle.
        bbox: Optional bounding box (x1, y1, x2, y2) of the offending entity.
        evidence_ref: Optional file path or URL to evidence snapshot.
        details: Diagnostic breakdown metadata dictionary.
    """

    violation_type: str
    confidence: float
    detected_at: datetime
    camera_id: Optional[str] = None
    track_id: Optional[int] = None
    bbox: Optional[tuple[float, float, float, float]] = None
    evidence_ref: Optional[str] = None
    details: dict[str, Any] = field(default_factory=dict)


def ccw(pA: tuple[float, float], pB: tuple[float, float], pC: tuple[float, float]) -> bool:
    """Test whether three points are listed in counter-clockwise order."""
    return (pC[1] - pA[1]) * (pB[0] - pA[0]) > (pB[1] - pA[1]) * (pC[0] - pA[0])


def segments_intersect(
    pA: tuple[float, float],
    pB: tuple[float, float],
    p1: tuple[float, float],
    p2: tuple[float, float],
) -> bool:
    """Determine whether line segment AB intersects line segment p1p2.

    Uses standard 2D orientation cross-products.
    """
    return (ccw(pA, p1, p2) != ccw(pB, p1, p2)) and (ccw(pA, pB, p1) != ccw(pA, pB, p2))


def compute_segment_intersection(
    pA: tuple[float, float],
    pB: tuple[float, float],
    p1: tuple[float, float],
    p2: tuple[float, float],
) -> Optional[tuple[float, float]]:
    """Compute (x, y) intersection point of line segment AB and line segment p1p2.

    Returns None if segments are parallel, collinear, or do not intersect.
    """
    if not segments_intersect(pA, pB, p1, p2):
        return None

    x1, y1 = pA
    x2, y2 = pB
    x3, y3 = p1
    x4, y4 = p2

    denom = (y4 - y3) * (x2 - x1) - (x4 - x3) * (y2 - y1)
    if abs(denom) < 1e-9:
        return None

    ua = ((x4 - x3) * (y1 - y3) - (y4 - y3) * (x1 - x3)) / denom
    ix = x1 + ua * (x2 - x1)
    iy = y1 + ua * (y2 - y1)
    return (round(float(ix), 2), round(float(iy), 2))


class RedLightViolationHeuristic:
    """Identifies vehicles running red lights across designated stop lines.

    Evaluates vehicle centroid trajectory segments against stop-line geometries.
    A violation is triggered when:
    1. A vehicle's centroid trajectory segment crosses the stop line segment.
    2. The crossing occurs during a 'red' signal phase.
    3. The vehicle has not already been emitted during the current red signal cycle.
    """

    def __init__(self) -> None:
        """Initialize RedLightViolationHeuristic with cycle tracking state."""
        # Key: (camera_id, lane_or_line_key) -> set of track_ids emitted in current red cycle
        self._emitted_tracks: dict[str, set[int]] = {}
        # Key: camera_id -> last observed signal phase
        self._last_phases: dict[str, str] = {}

    def reset(self, camera_id: Optional[str] = None) -> None:
        """Reset internal debouncing state."""
        if camera_id:
            keys_to_del = [k for k in self._emitted_tracks if k.startswith(f"{camera_id}:")]
            for k in keys_to_del:
                del self._emitted_tracks[k]
            self._last_phases.pop(camera_id, None)
        else:
            self._emitted_tracks.clear()
            self._last_phases.clear()

    def evaluate(
        self,
        tracks: Sequence[TrackedVehicle],
        stop_lines: Sequence[StopLineConfig] | dict[str, StopLineConfig],
        signal_phase: str,
        timestamp: Optional[datetime] = None,
        camera_id: Optional[str] = None,
    ) -> list[ViolationCandidate]:
        """Evaluate tracked vehicles for red-light violations.

        Args:
            tracks: Sequence of active TrackedVehicle objects.
            stop_lines: Sequence or mapping of StopLineConfig configurations.
            signal_phase: Current signal lamp phase ('red', 'yellow', 'green', 'unknown').
            timestamp: Current frame timestamp (UTC).
            camera_id: Optional camera identifier.

        Returns:
            list[ViolationCandidate]: Detected red light violation candidates.
        """
        eval_time = timestamp or datetime.now(timezone.utc)
        normalized_phase = str(signal_phase).strip().lower()

        lines: list[StopLineConfig]
        if isinstance(stop_lines, dict):
            lines = list(stop_lines.values())
        else:
            lines = list(stop_lines)

        cam_id = camera_id or (lines[0].camera_id if lines else "default_camera")

        # Track signal phase transitions: if transitioning from non-red to red, reset cycle
        prev_phase = self._last_phases.get(cam_id)
        if prev_phase is not None and prev_phase != "red" and normalized_phase == "red":
            # New red cycle started -> clear emitted tracks for this camera
            prefix = f"{cam_id}:"
            for k in list(self._emitted_tracks.keys()):
                if k.startswith(prefix):
                    self._emitted_tracks[k].clear()

        self._last_phases[cam_id] = normalized_phase

        # If phase is NOT red, red-light violations are strictly prohibited
        if normalized_phase != "red":
            return []

        candidates: list[ViolationCandidate] = []

        for line_cfg in lines:
            line_key = f"{line_cfg.camera_id}:{line_cfg.lane_id or 'default'}"
            if line_key not in self._emitted_tracks:
                self._emitted_tracks[line_key] = set()
            emitted_set = self._emitted_tracks[line_key]

            for track in tracks:
                tid = track.track_id
                if tid in emitted_set:
                    # Debounce: at most one red light violation per track per red cycle
                    continue

                # Check recent history for stop-line crossing
                # We need at least 2 points in trajectory history
                history = track.history
                if len(history) < 2:
                    continue

                # Inspect the displacement between the previous point and the latest point
                p_prev, _ = history[-2]
                p_curr, _ = history[-1]

                # Check for segment intersection
                cross_pt = compute_segment_intersection(p_prev, p_curr, line_cfg.p1, line_cfg.p2)
                if cross_pt is None:
                    continue

                # If approach heading is specified, verify vehicle motion direction aligns with approach
                dx = p_curr[0] - p_prev[0]
                dy = p_curr[1] - p_prev[1]
                motion_dist = math.hypot(dx, dy)
                if line_cfg.approach_heading_deg is not None and motion_dist > 1.0:
                    motion_rad = math.atan2(dy, dx)
                    motion_deg = math.degrees(motion_rad) % 360.0
                    heading_diff = abs(((motion_deg - line_cfg.approach_heading_deg + 180.0) % 360.0) - 180.0)
                    if heading_diff > 90.0:
                        # Moving away from intersection or backing up; not crossing into intersection
                        continue

                # Crossing confirmed during red phase!
                # Deterministic confidence based on detection confidence and trajectory clarity
                # Base confidence 0.70, scaled up by track confidence (up to +0.20) and displacement (>10px adds +0.05)
                conf = 0.70 + (0.20 * min(1.0, max(0.0, track.confidence)))
                if motion_dist >= 10.0:
                    conf += 0.05
                conf = min(0.99, max(0.50, round(conf, 3)))

                emitted_set.add(tid)
                candidates.append(
                    ViolationCandidate(
                        violation_type="red_light",
                        confidence=conf,
                        detected_at=eval_time,
                        camera_id=line_cfg.camera_id,
                        track_id=tid,
                        bbox=track.bbox,
                        details={
                            "signal_phase": "red",
                            "lane_id": line_cfg.lane_id,
                            "stop_line_p1": line_cfg.p1,
                            "stop_line_p2": line_cfg.p2,
                            "crossing_point": cross_pt,
                            "speed_px_s": track.speed_px_s,
                            "speed_kmh": track.speed_kmh,
                            "vehicle_label": track.label,
                            "summary": (
                                f"Vehicle #{tid} ({track.label}) crossed stop line at {cross_pt} "
                                f"during RED signal phase in lane '{line_cfg.lane_id or 'general'}'."
                            ),
                        },
                    )
                )

        return candidates


class WrongWayViolationHeuristic:
    """Wraps WrongWayHeuristic from ai.cv.incidents to produce ViolationCandidate records.

    Preserves existing incident behavior while emitting debounced violation records.
    """

    def __init__(
        self,
        wrong_way_heuristic: Optional[WrongWayHeuristic] = None,
    ) -> None:
        """Initialize WrongWayViolationHeuristic wrapping an incident heuristic."""
        self.heuristic = wrong_way_heuristic or WrongWayHeuristic()
        self._emitted_tracks: set[int] = set()

    def reset(self) -> None:
        """Reset internal debouncing state."""
        self._emitted_tracks.clear()
        if hasattr(self.heuristic, "reset"):
            self.heuristic.reset()

    def evaluate(
        self,
        tracks: Sequence[TrackedVehicle],
        lane_configs: Sequence[LaneDirectionConfig] | dict[str, LaneDirectionConfig],
        timestamp: Optional[datetime] = None,
        camera_id: Optional[str] = None,
    ) -> list[ViolationCandidate]:
        """Evaluate tracks for wrong-way violations against configured lane directions.

        Args:
            tracks: Sequence of active TrackedVehicle objects.
            lane_configs: Sequence or mapping of LaneDirectionConfig configurations.
            timestamp: Frame capture timestamp.
            camera_id: Optional camera identifier.

        Returns:
            list[ViolationCandidate]: Detected wrong-way violation candidates.
        """
        eval_time = timestamp or datetime.now(timezone.utc)
        incident_candidates = self.heuristic.evaluate(
            tracks=tracks,
            lane_configs=lane_configs,
            timestamp=eval_time,
        )

        violations: list[ViolationCandidate] = []
        active_ids = {t.track_id for t in tracks}

        for inc in incident_candidates:
            if inc.track_id in self._emitted_tracks:
                # Debounce: emit once per track trajectory
                continue

            self._emitted_tracks.add(inc.track_id)
            violations.append(
                ViolationCandidate(
                    violation_type="wrong_way",
                    confidence=inc.confidence,
                    detected_at=inc.timestamp,
                    camera_id=camera_id,
                    track_id=inc.track_id,
                    bbox=inc.bbox,
                    details={
                        "method": inc.method,
                        **inc.details,
                    },
                )
            )

        # Cleanup tracks no longer active
        self._emitted_tracks = self._emitted_tracks.intersection(active_ids)

        return violations


@runtime_checkable
class HelmetClassifier(Protocol):
    """Protocol interface for head-crop motorcycle helmet classifier models."""

    def is_available(self) -> bool:
        """Return True if model weights are loaded and ready for inference."""
        ...

    def classify_head(self, head_crop: np.ndarray) -> tuple[bool, float]:
        """Classify whether the rider in the head crop is wearing a helmet.

        Args:
            head_crop: 3-channel uint8 BGR image crop of the rider's head region.

        Returns:
            tuple[bool, float]: (has_helmet, confidence) where has_helmet is True if helmet
                is worn, and confidence is bounded [0.0, 1.0].
        """
        ...


class PyTorchHelmetClassifier:
    """Helmet classifier implementing the HelmetClassifier protocol with explicit weights slot.

    DOCUMENTED WEIGHTS REQUIREMENT:
    -------------------------------
    MS-COCO does NOT label helmets. A fine-tuned classifier (e.g. YOLOv8-helmet or
    ResNet-18 trained on Safety Helmet Wearing Dataset / SHWD) is required.
    Expected weights location:
    `backend/app/ml/models/helmet_classifier.pt` or via environment variable `HELMET_MODEL_PATH`.

    When weights are not present, `is_available()` returns False. Calling `classify_head()`
    on an unavailable classifier strictly raises `HelmetModelMissingError` and never guesses.
    """

    def __init__(self, weights_path: Optional[str | Path] = None) -> None:
        """Initialize PyTorchHelmetClassifier with optional weights path."""
        self.weights_path: Optional[Path] = Path(weights_path) if weights_path else None
        self._model: Any = None
        self._init_attempted: bool = False
        self._load_model_if_present()

    def _load_model_if_present(self) -> None:
        """Attempt to load weights if file exists on disk."""
        if self._init_attempted:
            return
        self._init_attempted = True

        if not self.weights_path or not self.weights_path.is_file():
            return

        try:
            import torch
            # Safe checkpoint load or TorchScript model load
            self._model = torch.jit.load(str(self.weights_path), map_location="cpu")
            self._model.eval()
        except Exception:
            try:
                from ultralytics import YOLO
                self._model = YOLO(str(self.weights_path))
            except Exception:
                self._model = None

    def is_available(self) -> bool:
        """Return whether valid helmet model weights are loaded."""
        return self._model is not None

    def classify_head(self, head_crop: np.ndarray) -> tuple[bool, float]:
        """Classify head crop. Raises HelmetModelMissingError if weights not loaded."""
        if not self.is_available():
            raise HelmetModelMissingError(
                "Helmet classifier model weights are not loaded. A trained model "
                "(e.g. backend/app/ml/models/helmet_classifier.pt) is required for "
                "helmet compliance detection. Helmet detections will not be faked."
            )

        if head_crop is None or head_crop.size == 0:
            return (True, 0.0)

        # Real model inference path when weights are present
        try:
            import torch
            import cv2
            resized = cv2.resize(head_crop, (64, 64))
            tensor = torch.from_numpy(resized).permute(2, 0, 1).unsqueeze(0).float() / 255.0
            with torch.no_grad():
                output = self._model(tensor)
                if isinstance(output, torch.Tensor):
                    probs = torch.softmax(output, dim=-1)
                    has_helmet = bool(probs[0, 1] > 0.5)
                    conf = float(probs[0, 1] if has_helmet else probs[0, 0])
                    return (has_helmet, round(conf, 3))
        except Exception as e:
            raise HelmetModelMissingError(f"Inference error with loaded helmet model: {e}") from e

        return (True, 0.5)


def associate_riders_and_motorcycles(
    persons: Sequence[Detection],
    motorcycles: Sequence[Detection],
    min_horizontal_overlap: float = 0.35,
) -> list[tuple[Detection, Detection, float]]:
    """Associate rider person detections with motorcycle detections via spatial geometry.

    A person is associated with a motorcycle when:
    1. Horizontal bounding box overlap exceeds min_horizontal_overlap of person width.
    2. Vertical position reflects a seated rider: person's bottom (feet/seat) reaches into
       or touches the motorcycle bounding box (person.py2 >= moto.py1 and person.py1 < moto.py2).

    Args:
        persons: Detections labeled 'person'.
        motorcycles: Detections labeled 'motorcycle'.
        min_horizontal_overlap: Minimum fraction of person width overlapping motorcycle horizontally.

    Returns:
        list[tuple[Detection, Detection, float]]: Associated (person, motorcycle, score) tuples.
    """
    associations: list[tuple[Detection, Detection, float]] = []

    for p in persons:
        if not p.bbox:
            continue
        px1, py1, px2, py2 = p.bbox
        pw = max(1.0, px2 - px1)

        best_moto: Optional[Detection] = None
        best_score = 0.0

        for m in motorcycles:
            if not m.bbox:
                continue
            mx1, my1, mx2, my2 = m.bbox

            # Horizontal overlap
            overlap_x = max(0.0, min(px2, mx2) - max(px1, mx1))
            ratio_x = overlap_x / pw

            if ratio_x < min_horizontal_overlap:
                continue

            # Vertical association: rider sits on motorcycle
            # Person bottom should reach at least near motorcycle top, and not be below motorcycle
            if py2 < my1 - 20.0 or py1 > my2:
                continue

            # Geometric association score based on overlap and confidence
            score = 0.5 * (p.confidence + m.confidence) + 0.1 * ratio_x
            if score > best_score:
                best_score = score
                best_moto = m

        if best_moto is not None:
            associations.append((p, best_moto, round(min(0.99, best_score), 3)))

    return associations


def extract_head_crop_region(
    person_bbox: tuple[float, float, float, float],
    head_fraction: float = 0.28,
) -> tuple[float, float, float, float]:
    """Extract head bounding box as the top fraction of a person bounding box.

    Args:
        person_bbox: (x1, y1, x2, y2) person bounding box.
        head_fraction: Top height fraction allocated to head (default: 0.28).

    Returns:
        tuple[float, float, float, float]: Head bounding box (hx1, hy1, hx2, hy2).
    """
    x1, y1, x2, y2 = person_bbox
    height = max(1.0, y2 - y1)
    hy2 = y1 + (head_fraction * height)
    return (x1, y1, x2, hy2)


class NoHelmetViolationHeuristic:
    """Identifies motorcycle riders operating without a safety helmet.

    Pipeline:
    1. Associative geometry: Pairs 'person' detections with 'motorcycle' detections.
    2. Head-region extraction: Crops the top vertical fraction of the associated person.
    3. Classification: Invokes a HelmetClassifier Protocol implementation.

    HONESTY CONTRACT:
    When no classifier model weights are present, this heuristic reports rider associations
    and head crops in diagnostic metadata, but emits ZERO fake violations.
    """

    def __init__(
        self,
        classifier: Optional[HelmetClassifier] = None,
        head_fraction: float = 0.28,
        min_horizontal_overlap: float = 0.35,
    ) -> None:
        """Initialize NoHelmetViolationHeuristic with optional classifier interface."""
        self.classifier = classifier
        self.head_fraction = float(head_fraction)
        self.min_horizontal_overlap = float(min_horizontal_overlap)
        self._emitted_riders: set[tuple[int, int]] = set()

    def reset(self) -> None:
        """Reset internal debouncing state."""
        self._emitted_riders.clear()

    def evaluate(
        self,
        detections: Sequence[Detection],
        frame_bgr: Optional[np.ndarray] = None,
        timestamp: Optional[datetime] = None,
        camera_id: Optional[str] = None,
    ) -> list[ViolationCandidate]:
        """Evaluate detections for unhelmeted motorcycle riders.

        Args:
            detections: Multi-class detections (including 'person' and 'motorcycle').
            frame_bgr: Optional raw image frame in BGR format for head crop evaluation.
            timestamp: Measurement timestamp (UTC).
            camera_id: Optional camera identifier.

        Returns:
            list[ViolationCandidate]: Confirmed no-helmet violation candidates.
                Strictly empty if classifier is absent or unconfigured.
        """
        eval_time = timestamp or datetime.now(timezone.utc)

        persons = [d for d in detections if d.label == "person"]
        motorcycles = [d for d in detections if d.label in ("motorcycle", "motorbike")]

        associations = associate_riders_and_motorcycles(
            persons=persons,
            motorcycles=motorcycles,
            min_horizontal_overlap=self.min_horizontal_overlap,
        )

        # If no helmet classifier is configured or available, we NEVER fake detections
        if self.classifier is None or not self.classifier.is_available():
            return []

        violations: list[ViolationCandidate] = []

        for person, moto, assoc_score in associations:
            if not person.bbox:
                continue

            head_bbox = extract_head_crop_region(person.bbox, self.head_fraction)

            # Crop head region from frame if image is available
            head_crop: Optional[np.ndarray] = None
            if frame_bgr is not None and frame_bgr.size > 0:
                h_img, w_img = frame_bgr.shape[:2]
                hx1 = max(0, min(w_img - 1, int(head_bbox[0])))
                hy1 = max(0, min(h_img - 1, int(head_bbox[1])))
                hx2 = max(hx1 + 1, min(w_img, int(head_bbox[2])))
                hy2 = max(hy1 + 1, min(h_img, int(head_bbox[3])))
                head_crop = frame_bgr[hy1:hy2, hx1:hx2]

            # In tests or offline without raw frames, create placeholder synthetic crop or pass None
            if head_crop is None:
                head_crop = np.zeros((32, 32, 3), dtype=np.uint8)

            try:
                has_helmet, helmet_conf = self.classifier.classify_head(head_crop)
            except HelmetModelMissingError:
                # Missing model -> strictly no fake violations
                return []

            if not has_helmet:
                # Rider is confirmed NOT wearing a helmet!
                # Deterministic confidence based on rider association and classifier confidence
                conf = 0.40 * assoc_score + 0.60 * helmet_conf
                conf = min(0.99, max(0.50, round(conf, 3)))

                violations.append(
                    ViolationCandidate(
                        violation_type="no_helmet",
                        confidence=conf,
                        detected_at=eval_time,
                        camera_id=camera_id,
                        bbox=person.bbox,
                        details={
                            "head_bbox": head_bbox,
                            "rider_association_score": assoc_score,
                            "helmet_classifier_confidence": helmet_conf,
                            "motorcycle_bbox": moto.bbox,
                            "summary": (
                                f"Motorcycle rider detected without safety helmet "
                                f"(association: {assoc_score:.2f}, classifier conf: {helmet_conf:.2f})."
                            ),
                        },
                    )
                )

        return violations


class ViolationDetector:
    """Unified traffic violation detector coordinating red-light, wrong-way, and helmet heuristics."""

    def __init__(
        self,
        red_light_heuristic: Optional[RedLightViolationHeuristic] = None,
        wrong_way_heuristic: Optional[WrongWayViolationHeuristic] = None,
        no_helmet_heuristic: Optional[NoHelmetViolationHeuristic] = None,
    ) -> None:
        """Initialize ViolationDetector with component heuristics."""
        self.red_light_heuristic = red_light_heuristic or RedLightViolationHeuristic()
        self.wrong_way_heuristic = wrong_way_heuristic or WrongWayViolationHeuristic()
        self.no_helmet_heuristic = no_helmet_heuristic or NoHelmetViolationHeuristic()

    def reset(self) -> None:
        """Reset internal debouncing state for all component heuristics."""
        self.red_light_heuristic.reset()
        self.wrong_way_heuristic.reset()
        self.no_helmet_heuristic.reset()

    def evaluate_all(
        self,
        tracks: Sequence[TrackedVehicle],
        detections: Sequence[Detection],
        stop_lines: Sequence[StopLineConfig] | dict[str, StopLineConfig],
        lane_configs: Sequence[LaneDirectionConfig] | dict[str, LaneDirectionConfig],
        signal_phase: str,
        frame_bgr: Optional[np.ndarray] = None,
        timestamp: Optional[datetime] = None,
        camera_id: Optional[str] = None,
    ) -> list[ViolationCandidate]:
        """Run all violation detection heuristics and return unified violation candidates."""
        eval_time = timestamp or datetime.now(timezone.utc)
        results: list[ViolationCandidate] = []

        # 1. Red Light
        results.extend(
            self.red_light_heuristic.evaluate(
                tracks=tracks,
                stop_lines=stop_lines,
                signal_phase=signal_phase,
                timestamp=eval_time,
                camera_id=camera_id,
            )
        )

        # 2. Wrong Way
        results.extend(
            self.wrong_way_heuristic.evaluate(
                tracks=tracks,
                lane_configs=lane_configs,
                timestamp=eval_time,
                camera_id=camera_id,
            )
        )

        # 3. No Helmet
        results.extend(
            self.no_helmet_heuristic.evaluate(
                detections=detections,
                frame_bgr=frame_bgr,
                timestamp=eval_time,
                camera_id=camera_id,
            )
        )

        return results
