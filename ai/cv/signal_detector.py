"""Concrete YOLOv8 traffic signal detector with classical-CV state recognition.

Combines YOLOv8 deep learning localization restricted to COCO class 'traffic light' (id 9 / 10)
with the deterministic SignalStateHeuristic classical-CV layer for lamp state classification
(red / yellow / green / unknown).

Layout & Architecture Note:
---------------------------
Decoupled in `ai/cv/signal_detector.py` to maintain a framework-agnostic AI library
reusable by stream workers, edge devices, and Phase 5/6 services. The FastAPI backend
at `backend/app` re-exports it through `app.vision.detectors`.
"""

from datetime import datetime, timezone
import os
from pathlib import Path
from typing import Any
import numpy as np
import cv2
from ultralytics import YOLO

from ai.common.schemas import Detection, SignalDetection
from ai.cv.detectors import BaseDetector
from ai.cv.exceptions import (
    CorruptFrameError,
    InvalidInputFrameError,
    ModelLoadError,
    UnsupportedInputFormatError,
)
from ai.cv.signal_state_heuristic import SignalStateHeuristic, SignalStateResult
from ai.cv.yolo_detector import resolve_default_model_path, select_optimal_device

# Standard MS-COCO class ID for traffic light:
# Ultralytics 0-indexed: class 9 = 'traffic light'
# Standard 1-indexed COCO alias: class 10
DEFAULT_COCO_TRAFFIC_LIGHT_ID = 9


class TrafficSignalDetector(BaseDetector):
    """Production traffic signal detector and state recognition pipeline.

    Features:
    - Bounding box localization for traffic signal heads using YOLOv8 restricted to COCO class 9.
    - Deterministic classical-CV lamp state recognition (red / yellow / green / unknown)
      via SignalStateHeuristic.
    - Strict handling: returns empty list when no signal is visible (not an error).
    - Ambiguous or low-contrast crops yield state 'unknown' with low confidence.
    - Robust input validation rejecting invalid, corrupt, or empty frames.
    """

    def __init__(
        self,
        model_path: str | Path | None = None,
        conf_threshold: float = 0.20,
        iou_threshold: float = 0.45,
        imgsz: int | tuple[int, int] = 640,
        device: str | None = None,
        signal_class_id: int = DEFAULT_COCO_TRAFFIC_LIGHT_ID,
        heuristic: SignalStateHeuristic | None = None,
    ) -> None:
        """Initialize traffic signal detector and classical-CV state heuristic.

        Args:
            model_path: Path to yolov8n.pt weights. If None, auto-resolved.
            conf_threshold: Confidence threshold for signal head detection (default: 0.20).
                A 0.20 threshold maintains high recall for distant or small signal heads.
            iou_threshold: NMS IoU threshold (default: 0.45).
            imgsz: Inference input resolution (default: 640).
            device: Device target ('cpu', 'cuda', or None for auto-selection).
            signal_class_id: Target COCO class ID for traffic lights (default: 9, 10 supported as alias).
            heuristic: Custom SignalStateHeuristic instance, or None for default.

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
        self.heuristic = heuristic or SignalStateHeuristic()

        try:
            self._model = YOLO(str(self.model_path))
        except Exception as exc:
            raise ModelLoadError(f"Failed to initialize Ultralytics YOLO model from {self.model_path}: {exc}") from exc

        # Resolve COCO class ID:
        # In Ultralytics YOLOv8 names dict, search for "traffic light"
        resolved_id = None
        for cid, name in self._model.names.items():
            if "traffic" in name.lower() and "light" in name.lower():
                resolved_id = int(cid)
                break

        # Fallback to provided class ID (supporting 10 as alias for 9)
        if resolved_id is not None:
            self.signal_class_id = resolved_id
        elif signal_class_id == 10 and 9 in self._model.names:
            self.signal_class_id = 9
        else:
            self.signal_class_id = signal_class_id

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

        # Case 3: Numpy ndarray
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

            if frame.dtype != np.uint8:
                if np.issubdtype(frame.dtype, np.floating):
                    if frame.max() <= 1.0:
                        frame = (frame * 255.0).clip(0, 255).astype(np.uint8)
                    else:
                        frame = frame.clip(0, 255).astype(np.uint8)
                else:
                    frame = frame.clip(0, 255).astype(np.uint8)

            if frame.ndim == 2:
                return cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)

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

    def classify_crop(self, crop: np.ndarray) -> SignalStateResult:
        """Directly classify a cropped traffic signal head image using the heuristic.

        Args:
            crop: 3-channel uint8 BGR image crop of a signal head.

        Returns:
            SignalStateResult: State and confidence classification.
        """
        return self.heuristic.evaluate_crop(crop)

    def detect(
        self,
        frame: Any,
        timestamp: datetime | None = None,
    ) -> list[SignalDetection]:
        """Detect traffic signal heads and classify their illuminated states.

        Args:
            frame: Input video frame (numpy ndarray, filepath, or encoded bytes).
            timestamp: Capture timestamp. If None, current UTC timestamp is assigned.

        Returns:
            list[SignalDetection]: List of detected traffic signals with bounding boxes
                and classified states ('red', 'yellow', 'green', 'unknown'). Returns empty list
                when no traffic lights are present (not an error).

        Raises:
            InvalidInputFrameError: On invalid or empty frame.
            CorruptFrameError: On corrupted image data.
            UnsupportedInputFormatError: On invalid input types or shapes.
        """
        img_bgr = self._validate_and_normalize_frame(frame)
        det_timestamp = timestamp or datetime.now(timezone.utc)

        # Run YOLO inference restricted to traffic light class
        results = self._model.predict(
            source=img_bgr,
            conf=self.conf_threshold,
            iou=self.iou_threshold,
            imgsz=self.imgsz,
            device=self.device,
            classes=[self.signal_class_id],
            verbose=False,
        )

        detections: list[SignalDetection] = []
        if not results or len(results) == 0:
            return detections

        first_res = results[0]
        if first_res.boxes is None or len(first_res.boxes) == 0:
            return detections

        frame_h, frame_w = img_bgr.shape[:2]

        for box in first_res.boxes:
            conf = float(box.conf.item())
            xyxy = box.xyxy[0].tolist()

            # Coordinates clamped to frame boundaries
            x1 = max(0.0, float(xyxy[0]))
            y1 = max(0.0, float(xyxy[1]))
            x2 = min(float(frame_w), float(xyxy[2]))
            y2 = min(float(frame_h), float(xyxy[3]))
            bbox = (round(x1, 2), round(y1, 2), round(x2, 2), round(y2, 2))

            # Crop the detected signal head
            ix1, iy1, ix2, iy2 = int(round(x1)), int(round(y1)), int(round(x2)), int(round(y2))
            crop = img_bgr[iy1:iy2, ix1:ix2]

            # Apply classical-CV heuristic on the crop
            if crop.size > 0 and (ix2 - ix1 >= 4) and (iy2 - iy1 >= 4):
                state_result = self.heuristic.evaluate_crop(crop)
            else:
                state_result = SignalStateResult(
                    state="unknown",
                    confidence=0.0,
                    dominant_color="none",
                    margin=0.0,
                    details={"error": "crop_empty_or_too_small"},
                )

            detection = SignalDetection(
                label="traffic_light",
                confidence=round(conf, 4),
                bbox=bbox,
                timestamp=det_timestamp,
                state=state_result.state,
                state_confidence=round(state_result.confidence, 4),
                color_metrics=state_result.details,
            )
            detections.append(detection)

        return detections
