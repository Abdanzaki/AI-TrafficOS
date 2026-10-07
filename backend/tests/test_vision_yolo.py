"""Unit and integration tests for YOLOv8 vehicle detector and emergency heuristic.

Validates:
1. Model loading, parameter configuration, device auto-selection.
2. Input validation: rejection of None, empty arrays, corrupt bytes, NaNs, unsupported shapes/types.
3. Real inference on sample imagery with sane Detection fields and class filtering.
4. Non-vehicle class suppression (pedestrians, signs ignored).
5. Standalone and integrated EmergencyVehicleHeuristic behavior (livery ratios, temporal variance).
6. Schema adaptation to VehicleEventCreate.
"""

from datetime import datetime, timezone
import os
from pathlib import Path
import numpy as np
import pytest
from ultralytics.utils import ASSETS

from ai.common.schemas import Detection
from ai.cv.emergency_heuristic import EmergencyVehicleHeuristic
from ai.cv.exceptions import (
    CorruptFrameError,
    InvalidInputFrameError,
    ModelLoadError,
    UnsupportedInputFormatError,
)
from ai.cv.yolo_detector import DEFAULT_COCO_VEHICLE_MAP, YoloVehicleDetector
from app.vision.detectors import (
    detection_to_vehicle_event_create,
    get_vehicle_detector,
)


@pytest.fixture(scope="module")
def default_detector() -> YoloVehicleDetector:
    """Fixture providing an initialized YoloVehicleDetector."""
    return YoloVehicleDetector(conf_threshold=0.25, iou_threshold=0.45, imgsz=640)


class TestYoloVehicleDetectorInitialization:
    """Tests covering detector setup and hyperparameter configuration."""

    def test_default_initialization(self, default_detector: YoloVehicleDetector):
        """Verify default hyperparameter values and resolved model path."""
        assert default_detector.conf_threshold == 0.25
        assert default_detector.iou_threshold == 0.45
        assert default_detector.imgsz == 640
        assert default_detector.device in ("cpu", "cuda")
        assert default_detector.model_path.is_file()
        assert default_detector.class_mapping == DEFAULT_COCO_VEHICLE_MAP
        assert default_detector.enable_emergency_heuristic is True

    def test_custom_parameters(self):
        """Verify initialization with custom thresholds and mappings."""
        custom_map = {2: "car", 7: "truck"}
        det = YoloVehicleDetector(
            conf_threshold=0.50,
            iou_threshold=0.30,
            imgsz=320,
            device="cpu",
            class_mapping=custom_map,
            enable_emergency_heuristic=False,
        )
        assert det.conf_threshold == 0.50
        assert det.iou_threshold == 0.30
        assert det.imgsz == 320
        assert det.device == "cpu"
        assert det.class_mapping == custom_map
        assert det.enable_emergency_heuristic is False

    def test_missing_model_raises_model_load_error(self, tmp_path: Path):
        """Verify non-existent weights path raises ModelLoadError."""
        fake_path = tmp_path / "nonexistent_yolo.pt"
        with pytest.raises(ModelLoadError):
            YoloVehicleDetector(model_path=fake_path)


class TestInputValidation:
    """Tests covering typed exceptions for malformed, corrupt, or unsupported inputs."""

    def test_none_frame_raises(self, default_detector: YoloVehicleDetector):
        with pytest.raises(InvalidInputFrameError, match="cannot be None"):
            default_detector.detect(None)

    def test_empty_array_raises(self, default_detector: YoloVehicleDetector):
        empty = np.zeros((0, 0, 3), dtype=np.uint8)
        with pytest.raises(InvalidInputFrameError, match="empty"):
            default_detector.detect(empty)

    def test_zero_dimensions_raises(self, default_detector: YoloVehicleDetector):
        zero_dim = np.zeros((0, 640, 3), dtype=np.uint8)
        with pytest.raises(InvalidInputFrameError, match="empty|zero dimensions"):
            default_detector.detect(zero_dim)

    def test_nonexistent_file_raises(self, default_detector: YoloVehicleDetector):
        with pytest.raises(InvalidInputFrameError, match="does not exist"):
            default_detector.detect("/nonexistent/path/to/frame.jpg")

    def test_corrupt_bytes_raises(self, default_detector: YoloVehicleDetector):
        corrupt = b"this is not a valid jpeg or png binary stream"
        with pytest.raises(CorruptFrameError, match="corrupt or unreadable"):
            default_detector.detect(corrupt)

    def test_empty_bytes_raises(self, default_detector: YoloVehicleDetector):
        with pytest.raises(InvalidInputFrameError, match="empty"):
            default_detector.detect(b"")

    def test_nan_pixel_values_raise(self, default_detector: YoloVehicleDetector):
        nan_img = np.full((100, 100, 3), np.nan, dtype=np.float32)
        with pytest.raises(CorruptFrameError, match="NaN or infinite"):
            default_detector.detect(nan_img)

    def test_unsupported_type_raises(self, default_detector: YoloVehicleDetector):
        with pytest.raises(UnsupportedInputFormatError, match="Unsupported input frame type: int"):
            default_detector.detect(42)

    def test_unsupported_dimensions_raises(self, default_detector: YoloVehicleDetector):
        one_d = np.zeros((100,), dtype=np.uint8)
        with pytest.raises(UnsupportedInputFormatError, match="Unsupported frame dimensionality: 1"):
            default_detector.detect(one_d)


class TestYoloInference:
    """Tests covering real inference execution and detection schema compliance."""

    def test_detect_blank_image_returns_empty_list(self, default_detector: YoloVehicleDetector):
        """A blank black image contains no vehicles; should return empty list."""
        blank = np.zeros((640, 640, 3), dtype=np.uint8)
        detections = default_detector.detect(blank)
        assert isinstance(detections, list)
        assert len(detections) == 0

    def test_detect_real_bus_asset(self, default_detector: YoloVehicleDetector):
        """Execute real YOLO inference on standard ultralytics bus image asset."""
        bus_path = os.path.join(ASSETS, "bus.jpg")
        detections = default_detector.detect(bus_path)

        assert len(detections) >= 1
        labels = [d.label for d in detections]
        assert "bus" in labels

        for det in detections:
            assert isinstance(det, Detection)
            assert det.label in ("bus", "car", "truck", "motorcycle", "emergency_vehicle_heuristic")
            assert 0.0 <= det.confidence <= 1.0
            assert det.bbox is not None
            x1, y1, x2, y2 = det.bbox
            assert 0.0 <= x1 < x2
            assert 0.0 <= y1 < y2
            assert det.timestamp is not None

    def test_ignore_non_vehicle_coco_classes(self, default_detector: YoloVehicleDetector):
        """COCO class 0 (person) is present in bus.jpg but MUST be ignored."""
        bus_path = os.path.join(ASSETS, "bus.jpg")
        detections = default_detector.detect(bus_path)

        labels = [d.label for d in detections]
        assert "person" not in labels
        assert "traffic light" not in labels
        assert "stop sign" not in labels

    def test_programmatic_synthetic_vehicle_image(self, default_detector: YoloVehicleDetector):
        """Verify detector handles programmatic image buffer with vehicle crop."""
        import cv2

        canvas = np.zeros((640, 640, 3), dtype=np.uint8)
        canvas[:] = (80, 80, 80)
        bus_src = cv2.imread(os.path.join(ASSETS, "bus.jpg"))
        bus_crop = cv2.resize(bus_src[230:750, 30:800], (360, 260))
        canvas[200:460, 140:500] = bus_crop

        custom_ts = datetime(2026, 10, 7, 12, 0, 0, tzinfo=timezone.utc)
        detections = default_detector.detect(canvas, timestamp=custom_ts)

        assert len(detections) >= 1
        primary = detections[0]
        assert primary.label == "bus"
        assert primary.confidence > 0.80
        assert primary.timestamp == custom_ts
        x1, y1, x2, y2 = primary.bbox
        # Vehicle was placed at [200:460, 140:500]
        assert 120 <= x1 <= 160
        assert 180 <= y1 <= 220
        assert 480 <= x2 <= 520
        assert 440 <= y2 <= 480


class TestEmergencyVehicleHeuristic:
    """Tests verifying the rule-based visual heuristic layer."""

    def test_steady_civilian_crop_rejected(self):
        """Dark gray civilian vehicle crop does not trigger emergency heuristic."""
        heuristic = EmergencyVehicleHeuristic(min_confidence=0.40)
        civilian_crop = np.ones((100, 100, 3), dtype=np.uint8) * 80

        is_emerg, conf, metrics = heuristic.evaluate_crop(civilian_crop, vehicle_id="car_1")
        assert is_emerg is False
        assert conf < 0.10
        assert metrics["method"] == "heuristic_rule_based"

    def test_red_emergency_livery_crop_accepted(self):
        """Bright red emergency rescue livery triggers heuristic in single-frame mode."""
        heuristic = EmergencyVehicleHeuristic(min_confidence=0.40)
        # BGR: High red (R=220, G=30, B=30)
        emergency_crop = np.zeros((100, 100, 3), dtype=np.uint8)
        emergency_crop[:, :] = (30, 30, 220)

        is_emerg, conf, metrics = heuristic.evaluate_crop(emergency_crop)
        assert is_emerg is True
        assert conf >= 0.40
        assert metrics["red_ratio"] > 0.80
        assert metrics["livery_score"] > 0.80

    def test_temporal_flashing_variance_boosts_confidence(self):
        """Oscillating luminance in rooftop ROI triggers temporal variance."""
        heuristic = EmergencyVehicleHeuristic(
            history_window=10,
            min_temporal_frames=4,
            min_confidence=0.40,
        )

        for frame_idx in range(6):
            crop = np.zeros((100, 100, 3), dtype=np.uint8)
            # Body red livery
            crop[25:, :] = (30, 30, 220)
            # Alternating bright rooftop strobe (255 vs 20)
            roof_val = 250 if frame_idx % 2 == 0 else 20
            crop[0:25, :] = (roof_val, roof_val, roof_val)

            is_emerg, conf, metrics = heuristic.evaluate_crop(crop, vehicle_id="truck_99")

        assert is_emerg is True
        assert conf >= 0.85
        assert metrics["temporal_variance"] > 1000.0
        assert metrics["temporal_score"] > 0.80

    def test_heuristic_crop_validation(self):
        """Verify invalid crop handling in heuristic."""
        heuristic = EmergencyVehicleHeuristic()
        with pytest.raises(InvalidInputFrameError):
            heuristic.evaluate_crop(None)

        with pytest.raises(InvalidInputFrameError):
            heuristic.evaluate_crop(np.zeros((0, 0, 3), dtype=np.uint8))


class TestBackendIntegration:
    """Tests covering FastAPI backend helpers and schema conversion."""

    def test_detection_to_vehicle_event_create_adapter(self):
        """Verify conversion of normal vehicle detection to VehicleEventCreate."""
        ts = datetime.now(timezone.utc)
        det = Detection(
            label="car",
            confidence=0.92,
            bbox=(100.0, 150.0, 300.0, 350.0),
            timestamp=ts,
        )

        event = detection_to_vehicle_event_create(
            det,
            intersection_id=3,
            lane_id=12,
            speed_kmh=52.4,
            direction="southbound",
        )
        assert event.intersection_id == 3
        assert event.lane_id == 12
        assert event.event_type == "detection"
        assert event.vehicle_type == "car"
        assert event.confidence == 0.92
        assert event.speed_kmh == 52.4
        assert event.direction == "southbound"
        assert event.detected_at == ts

    def test_detection_to_emergency_event_adapter(self):
        """Verify emergency heuristic detection maps to emergency_preemption event_type."""
        ts = datetime.now(timezone.utc)
        det = Detection(
            label="emergency_vehicle_heuristic",
            confidence=0.78,
            bbox=(100.0, 150.0, 300.0, 350.0),
            timestamp=ts,
        )

        event = detection_to_vehicle_event_create(det, intersection_id=5)
        assert event.intersection_id == 5
        assert event.event_type == "emergency_preemption"
        assert event.vehicle_type == "emergency_vehicle_heuristic"
        assert event.confidence == 0.78

    def test_get_vehicle_detector_singleton(self):
        """Verify get_vehicle_detector returns a functional detector instance."""
        detector = get_vehicle_detector()
        assert isinstance(detector, YoloVehicleDetector)
        assert detector.conf_threshold == 0.25
