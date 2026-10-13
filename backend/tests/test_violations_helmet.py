"""Deterministic synthetic unit tests for NoHelmetViolationHeuristic.

SYNTHETIC FIXTURE NOTICE:
-------------------------
All Detection bounding boxes and synthetic classifier implementations in this module
are PROGRAMMATICALLY SYNTHETIC FIXTURES created for deterministic unit verification.
No real human faces or live camera streams are processed.
"""

from datetime import datetime, timezone
import numpy as np
import pytest

from ai.common.schemas import Detection
from ai.cv.exceptions import HelmetModelMissingError
from ai.cv.violations import (
    HelmetClassifier,
    NoHelmetViolationHeuristic,
    PyTorchHelmetClassifier,
    ViolationCandidate,
    associate_riders_and_motorcycles,
    extract_head_crop_region,
)


class SyntheticDeterministicHelmetClassifier:
    """Synthetic deterministic test classifier conforming to HelmetClassifier protocol."""

    def __init__(self, has_helmet: bool, confidence: float = 0.90) -> None:
        self._has_helmet = has_helmet
        self._confidence = confidence

    def is_available(self) -> bool:
        return True

    def classify_head(self, head_crop: np.ndarray) -> tuple[bool, float]:
        return (self._has_helmet, self._confidence)


def test_rider_association_spatial_overlap():
    """Verify person detection overlapping motorcycle detection is associated as rider."""
    # Motorcycle at X=[200, 300], Y=[350, 450]
    moto_det = Detection(
        label="motorcycle",
        confidence=0.88,
        bbox=(200.0, 350.0, 300.0, 450.0),
    )

    # Rider seated atop motorcycle: X=[220, 280], Y=[260, 380] (feet reach down into moto top)
    rider_det = Detection(
        label="person",
        confidence=0.92,
        bbox=(220.0, 260.0, 280.0, 380.0),
    )

    # Pedestrian on adjacent sidewalk: X=[50, 100], Y=[260, 400]
    ped_det = Detection(
        label="person",
        confidence=0.85,
        bbox=(50.0, 260.0, 100.0, 400.0),
    )

    associations = associate_riders_and_motorcycles(
        persons=[rider_det, ped_det],
        motorcycles=[moto_det],
        min_horizontal_overlap=0.35,
    )

    assert len(associations) == 1
    p, m, score = associations[0]
    assert p == rider_det
    assert m == moto_det
    assert 0.60 <= score <= 1.0


def test_head_region_extraction():
    """Verify head crop box extracts top vertical fraction of person bounding box."""
    person_bbox = (200.0, 200.0, 300.0, 600.0)  # Height = 400px
    head_bbox = extract_head_crop_region(person_bbox, head_fraction=0.25)
    # Height of head should be 0.25 * 400 = 100px -> Y: [200.0, 300.0]
    assert head_bbox == (200.0, 200.0, 300.0, 300.0)


def test_missing_model_path_never_emits_fake_violations():
    """When no classifier weights are provided, heuristic must emit ZERO fake violations."""
    # Default classifier without weights
    classifier = PyTorchHelmetClassifier(weights_path=None)
    assert classifier.is_available() is False

    heuristic = NoHelmetViolationHeuristic(classifier=classifier)
    now = datetime(2026, 10, 13, 12, 0, 0, tzinfo=timezone.utc)

    # Valid rider and motorcycle detections
    moto = Detection(label="motorcycle", confidence=0.90, bbox=(200.0, 350.0, 300.0, 450.0))
    rider = Detection(label="person", confidence=0.92, bbox=(220.0, 260.0, 280.0, 380.0))

    # Evaluate without trained weights: MUST return empty list
    violations = heuristic.evaluate(
        detections=[rider, moto],
        timestamp=now,
    )

    assert len(violations) == 0


def test_missing_model_raises_explicit_error_on_direct_inference():
    """Directly invoking classify_head without loaded weights must raise HelmetModelMissingError."""
    classifier = PyTorchHelmetClassifier(weights_path=None)
    assert classifier.is_available() is False

    dummy_crop = np.zeros((32, 32, 3), dtype=np.uint8)
    with pytest.raises(HelmetModelMissingError) as exc_info:
        classifier.classify_head(dummy_crop)

    assert "model weights are not loaded" in str(exc_info.value)


def test_synthetic_classifier_unhelmeted_rider_emits_violation():
    """Unhelmeted rider evaluated with synthetic classifier fixture must emit violation."""
    # Synthetic classifier predicting NO helmet with 0.85 confidence
    synthetic_classifier = SyntheticDeterministicHelmetClassifier(
        has_helmet=False,
        confidence=0.85,
    )
    assert synthetic_classifier.is_available() is True

    heuristic = NoHelmetViolationHeuristic(classifier=synthetic_classifier)
    now = datetime(2026, 10, 13, 12, 0, 0, tzinfo=timezone.utc)

    moto = Detection(label="motorcycle", confidence=0.88, bbox=(200.0, 350.0, 300.0, 450.0))
    rider = Detection(label="person", confidence=0.92, bbox=(220.0, 260.0, 280.0, 380.0))

    violations = heuristic.evaluate(
        detections=[rider, moto],
        timestamp=now,
        camera_id="cam_junction_south_03",
    )

    assert len(violations) == 1
    v: ViolationCandidate = violations[0]
    assert v.violation_type == "no_helmet"
    assert v.camera_id == "cam_junction_south_03"
    assert v.detected_at == now
    assert 0.50 <= v.confidence <= 1.0
    assert "head_bbox" in v.details
    assert "rider_association_score" in v.details
    assert v.details["helmet_classifier_confidence"] == 0.85


def test_synthetic_classifier_helmeted_rider_no_violation():
    """Helmeted rider evaluated with synthetic classifier fixture must NOT emit violation."""
    synthetic_classifier = SyntheticDeterministicHelmetClassifier(
        has_helmet=True,
        confidence=0.95,
    )
    heuristic = NoHelmetViolationHeuristic(classifier=synthetic_classifier)

    moto = Detection(label="motorcycle", confidence=0.90, bbox=(200.0, 350.0, 300.0, 450.0))
    rider = Detection(label="person", confidence=0.92, bbox=(220.0, 260.0, 280.0, 380.0))

    violations = heuristic.evaluate(detections=[rider, moto])
    assert len(violations) == 0


def test_pedestrian_without_motorcycle_ignored():
    """Pedestrian walking without motorcycle must never be flagged for no-helmet violation."""
    synthetic_classifier = SyntheticDeterministicHelmetClassifier(
        has_helmet=False,
        confidence=0.90,
    )
    heuristic = NoHelmetViolationHeuristic(classifier=synthetic_classifier)

    pedestrian = Detection(label="person", confidence=0.95, bbox=(100.0, 200.0, 150.0, 350.0))
    car = Detection(label="car", confidence=0.92, bbox=(300.0, 200.0, 450.0, 320.0))

    violations = heuristic.evaluate(detections=[pedestrian, car])
    assert len(violations) == 0
