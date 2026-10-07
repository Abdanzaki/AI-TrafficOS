"""Concrete YOLOv8 vehicle detector for AI TrafficOS perception pipeline.

Implements YoloVehicleDetector inheriting from BaseDetector using Ultralytics YOLOv8.
Performs real multiclass vehicle localization and includes an honest secondary visual
heuristic layer for emergency vehicle identification.

Layout & Architecture Note:
---------------------------
This detector is housed in `ai/cv/yolo_detector.py` to maintain a framework-agnostic
AI/perception library reusable by streaming workers, batch inference jobs, and Phase 5/6
services. The FastAPI application at `backend/app` imports and re-exports it through
`app.vision.detectors`, ensuring clean modular separation between ML runtime and HTTP routing.
"""

from datetime import datetime, timezone
import os
from pathlib import Path
from typing import Any
import numpy as np
import cv2
import torch
from ultralytics import YOLO

from ai.common.schemas import Detection
from ai.cv.detectors import BaseDetector
from ai.cv.emergency_heuristic import EmergencyVehicleHeuristic
from ai.cv.exceptions import (
    CorruptFrameError,
    InvalidInputFrameError,
    ModelLoadError,
    UnsupportedInputFormatError,
)

# Standard MS-COCO class IDs mapped to AI TrafficOS database vehicle_type values:
# COCO Class 2: car        -> DB vehicle_type: 'car'
# COCO Class 3: motorcycle -> DB vehicle_type: 'motorcycle'
# COCO Class 5: bus        -> DB vehicle_type: 'bus'
# COCO Class 7: truck      -> DB vehicle_type: 'truck'
# Non-vehicle classes (person, stop sign, traffic light, bicycle, etc.) are ignored.
DEFAULT_COCO_VEHICLE_MAP: dict[int, str] = {
    2: "car",
    3: "motorcycle",
    5: "bus",
    7: "truck",
}


def resolve_default_model_path() -> Path:
    """Resolve the default YOLOv8 weights path across repo and app directory structures.

    Returns:
        Path: Absolute or verified path to yolov8n.pt.

    Raises:
        ModelLoadError: If weights file cannot be located.
    """
    env_path = os.getenv("YOLO_MODEL_PATH")
    if env_path:
        p = Path(env_path)
        if p.is_file():
            return p.resolve()
        raise ModelLoadError(f"YOLO_MODEL_PATH environment variable specified nonexistent file: {env_path}")

    # Search known candidate paths relative to this file and current working directory
    current_file_dir = Path(__file__).resolve().parent
    candidates = [
        # Relative to ai/cv/ (2 levels up to repo root, then backend/app/ml/models/)
        current_file_dir.parents[1] / "backend" / "app" / "ml" / "models" / "yolov8n.pt",
        # Relative to current working directory (running from repo root)
        Path.cwd() / "backend" / "app" / "ml" / "models" / "yolov8n.pt",
        # Relative to current working directory (running from backend/)
        Path.cwd() / "app" / "ml" / "models" / "yolov8n.pt",
        # Fallback direct path
        Path("/home/hatch/workspace/AI-TrafficOS/backend/app/ml/models/yolov8n.pt"),
    ]

    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()

    raise ModelLoadError(
        f"Unable to locate YOLO weights file yolov8n.pt. Searched candidates: {[str(c) for c in candidates]}"
    )


def select_optimal_device(requested_device: str | None = None) -> str:
    """Auto-select the optimal execution device (CUDA GPU if available, else CPU).

    Args:
        requested_device: Explicit device string ("cpu", "cuda", "cuda:0") or None for auto.

    Returns:
        str: Validated PyTorch / Ultralytics device string.
    """
    if requested_device and requested_device.lower() != "auto":
        return requested_device.lower()

    if torch.cuda.is_available():
        return "cuda"
    return "cpu"


class YoloVehicleDetector(BaseDetector):
    """Production YOLOv8 vehicle detector implementing BaseDetector.

    Features:
    - Real multiclass vehicle detection (car, motorcycle, bus, truck) using YOLOv8n.
    - Configurable confidence threshold, NMS IoU threshold, image size, and device.
    - Robust input validation rejecting invalid, corrupt, or unsupported frames.
    - Integrated secondary EmergencyVehicleHeuristic layer emitting candidate
      'emergency_vehicle_heuristic' detections.
    """

    def __init__(
        self,
        model_path: str | Path | None = None,
        conf_threshold: float = 0.25,
        iou_threshold: float = 0.45,
        imgsz: int | tuple[int, int] = 640,
        device: str | None = None,
        class_mapping: dict[int, str] | None = None,
        enable_emergency_heuristic: bool = True,
        emergency_heuristic: EmergencyVehicleHeuristic | None = None,
    ) -> None:
        """Initialize YOLO vehicle detector with weights and runtime hyperparameters.

        Args:
            model_path: Path to yolov8n.pt weights. If None, auto-resolved.
            conf_threshold: Detection confidence threshold (default: 0.25).
                Justification: 0.25 balances recall and precision in traffic perception,
                detecting distant or occluded vehicles (e.g. small motorcycles) while
                suppressing low-confidence noise. Downstream tracking smooths false alarms.
            iou_threshold: Non-Maximum Suppression IoU threshold (default: 0.45).
                Prevents duplicate detections of elongated vehicles (buses/trucks) without
                suppressing adjacent vehicles in tightly queued lanes.
            imgsz: Inference input resolution (default: 640).
            device: Execution target ('cuda', 'cpu', or None for auto-selection).
            class_mapping: COCO class ID to database vehicle_type dictionary.
            enable_emergency_heuristic: Enable secondary visual cue heuristic analysis.
            emergency_heuristic: Custom EmergencyVehicleHeuristic instance.

        Raises:
            ModelLoadError: If model weights cannot be located or loaded.
        """
        resolved_path = Path(model_path) if model_path else resolve_default_model_path()
        if not resolved_path.is_file():
            raise ModelLoadError(f"Model weights file not found: {resolved_path}")

        self.model_path = resolved_path
        self.conf_threshold = float(conf_threshold)
        self.iou_threshold = float(iou_threshold)
        self.imgsz = imgsz
        self.device = select_optimal_device(device)
        self.class_mapping = class_mapping or DEFAULT_COCO_VEHICLE_MAP
        self.target_coco_classes = sorted(list(self.class_mapping.keys()))

        self.enable_emergency_heuristic = enable_emergency_heuristic
        self.emergency_heuristic = emergency_heuristic or EmergencyVehicleHeuristic()

        try:
            self._model = YOLO(str(self.model_path))
        except Exception as exc:
            raise ModelLoadError(f"Failed to initialize Ultralytics YOLO model from {self.model_path}: {exc}") from exc

    def _validate_and_normalize_frame(self, frame: Any) -> np.ndarray:
        """Validate input payload and normalize into a 3-channel BGR numpy ndarray.

        Args:
            frame: Input payload (numpy ndarray, filepath string/Path, or encoded bytes).

        Returns:
            np.ndarray: Validated 3-channel uint8 BGR image array.

        Raises:
            InvalidInputFrameError: On None, empty, zero-dimensioned, or missing inputs.
            CorruptFrameError: On unreadable/corrupted files, undecodable bytes, or NaN/Inf.
            UnsupportedInputFormatError: On unsupported types or tensor shapes.
        """
        if frame is None:
            raise InvalidInputFrameError("Input frame cannot be None.")

        # Case 1: Filepath string or Path object
        if isinstance(frame, (str, Path)):
            file_path = Path(frame)
            if not file_path.is_file():
                raise InvalidInputFrameError(f"Input image file does not exist: {file_path}")
            img = cv2.imread(str(file_path))
            if img is None:
                raise CorruptFrameError(f"Failed to read/decode corrupt or unsupported image file: {file_path}")
            return img

        # Case 2: Raw encoded image bytes or bytearray
        if isinstance(frame, (bytes, bytearray)):
            if len(frame) == 0:
                raise InvalidInputFrameError("Input image byte buffer is empty.")
            byte_arr = np.frombuffer(frame, dtype=np.uint8)
            img = cv2.imdecode(byte_arr, cv2.IMREAD_COLOR)
            if img is None:
                raise CorruptFrameError("Failed to decode corrupt or unreadable image bytes buffer.")
            return img

        # Case 3: Numpy ndarray (standard OpenCV frame buffer)
        if isinstance(frame, np.ndarray):
            if frame.size == 0:
                raise InvalidInputFrameError("Input frame numpy array is empty (size 0).")
            if frame.ndim not in (2, 3):
                raise UnsupportedInputFormatError(
                    f"Unsupported frame dimensionality: {frame.ndim}. Expected 2D or 3D numpy array."
                )
            if frame.shape[0] == 0 or frame.shape[1] == 0:
                raise InvalidInputFrameError(f"Input frame has zero dimensions: shape={frame.shape}.")
            if np.isnan(frame).any() or np.isinf(frame).any():
                raise CorruptFrameError("Input frame contains NaN or infinite pixel values.")

            # Ensure uint8 dtype
            if frame.dtype != np.uint8:
                if np.issubdtype(frame.dtype, np.floating):
                    # Check range and convert
                    if frame.max() <= 1.0:
                        frame = (frame * 255.0).clip(0, 255).astype(np.uint8)
                    else:
                        frame = frame.clip(0, 255).astype(np.uint8)
                else:
                    frame = frame.clip(0, 255).astype(np.uint8)

            # Convert 2D grayscale to 3-channel BGR
            if frame.ndim == 2:
                return cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)

            # Convert 3D with channel dimensions
            channels = frame.shape[2]
            if channels == 3:
                return frame
            if channels == 1:
                return cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
            if channels == 4:
                return cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)

            raise UnsupportedInputFormatError(
                f"Unsupported number of image channels: {channels}. Expected 1, 3, or 4 channels."
            )

        raise UnsupportedInputFormatError(
            f"Unsupported input frame type: {type(frame).__name__}. "
            "Supported types are numpy.ndarray, bytes, bytearray, str, and pathlib.Path."
        )

    def detect(
        self,
        frame: Any,
        timestamp: datetime | None = None,
        vehicle_ids: list[str | None] | None = None,
    ) -> list[Detection]:
        """Execute YOLOv8 vehicle detection over an input video frame.

        Performs real tensor inference using Ultralytics YOLOv8, extracts bounding
        boxes, maps COCO class IDs to database vehicle categories (car, motorcycle,
        bus, truck), and optionally runs the secondary EmergencyVehicleHeuristic.

        Args:
            frame: Input image (numpy ndarray, filepath, or encoded bytes).
            timestamp: Capture timestamp. If None, current UTC timestamp is assigned.
            vehicle_ids: Optional list of tracker IDs for multi-frame heuristic tracking.

        Returns:
            list[Detection]: List of real Detection dataclass instances.

        Raises:
            InvalidInputFrameError: On invalid or empty frame.
            CorruptFrameError: On corrupted image data.
            UnsupportedInputFormatError: On invalid input types or shapes.
        """
        img_bgr = self._validate_and_normalize_frame(frame)
        det_timestamp = timestamp or datetime.now(timezone.utc)

        # Run real Ultralytics inference
        results = self._model.predict(
            source=img_bgr,
            conf=self.conf_threshold,
            iou=self.iou_threshold,
            imgsz=self.imgsz,
            device=self.device,
            classes=self.target_coco_classes,
            verbose=False,
        )

        detections: list[Detection] = []
        if not results or len(results) == 0:
            return detections

        first_res = results[0]
        if first_res.boxes is None or len(first_res.boxes) == 0:
            return detections

        frame_h, frame_w = img_bgr.shape[:2]

        for i, box in enumerate(first_res.boxes):
            cls_id = int(box.cls.item())
            if cls_id not in self.class_mapping:
                # Strictly ignore non-vehicle classes
                continue

            traffic_label = self.class_mapping[cls_id]
            conf = float(box.conf.item())
            xyxy = box.xyxy[0].tolist()

            # Coordinates clamped to frame boundaries
            x1 = max(0.0, float(xyxy[0]))
            y1 = max(0.0, float(xyxy[1]))
            x2 = min(float(frame_w), float(xyxy[2]))
            y2 = min(float(frame_h), float(xyxy[3]))
            bbox = (round(x1, 2), round(y1, 2), round(x2, 2), round(y2, 2))

            primary_detection = Detection(
                label=traffic_label,
                confidence=round(conf, 4),
                bbox=bbox,
                timestamp=det_timestamp,
            )
            detections.append(primary_detection)

            # Secondary Emergency Vehicle Heuristic layer
            if self.enable_emergency_heuristic and (x2 - x1 >= 12.0) and (y2 - y1 >= 12.0):
                ix1, iy1, ix2, iy2 = int(round(x1)), int(round(y1)), int(round(x2)), int(round(y2))
                crop = img_bgr[iy1:iy2, ix1:ix2]
                if crop.size > 0:
                    vid = vehicle_ids[i] if (vehicle_ids and i < len(vehicle_ids)) else None
                    is_emerg, emerg_conf, _ = self.emergency_heuristic.evaluate_crop(
                        crop_bgr=crop,
                        vehicle_id=vid,
                        timestamp=det_timestamp,
                    )
                    if is_emerg:
                        detections.append(
                            Detection(
                                label="emergency_vehicle_heuristic",
                                confidence=round(emerg_conf, 4),
                                bbox=bbox,
                                timestamp=det_timestamp,
                            )
                        )

        return detections
