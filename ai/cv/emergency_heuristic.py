"""Emergency vehicle visual heuristic analysis module.

IMPORTANT ARCHITECTURAL & ETHICAL DISCLAIMER:
=============================================
HEURISTIC LAYER ONLY — NOT A TRAINED DEEP LEARNING MODEL.
The standard MS-COCO dataset lacks dedicated emergency vehicle categories (e.g.,
ambulances, fire engines, emergency rescue vehicles). EmergencyVehicleHeuristic
is a secondary, rule-based visual cue analyzer designed to inspect vehicle bounding-box
crops produced by the primary YOLO detector.

Documented visual cues computed:
1. Red and white livery color ratios evaluated in HSV color space.
2. Flashing-light temporal luminance variance across successive video frames in the
   upper vehicle rooftop region of interest (ROI).

Honest heuristic limitations:
- Color livery cues produce false positives on civilian red cars, white delivery vans
  with red corporate logos, and commercial transport vehicles.
- Does not reliably generalize to regional emergency livery variations (e.g., European
  high-conspicuity yellow/green battenburg markings).
- Temporal flashing variance requires persistent multi-frame tracking; static single-frame
  evaluations lack flashing confirmation and carry lower confidence ceilings.
- NEVER present outputs of this class as a trained deep neural network model.
"""

from collections import deque
from datetime import datetime
from typing import Any
import numpy as np
import cv2

from ai.cv.exceptions import CorruptFrameError, InvalidInputFrameError


class EmergencyVehicleHeuristic:
    """Rule-based visual cue heuristic for identifying potential emergency vehicles.

    Evaluates vehicle crops using HSV livery color ratios and temporal lightbar
    flashing variance across video frames. Emits label 'emergency_vehicle_heuristic'
    with an associated heuristic confidence score.
    """

    def __init__(
        self,
        red_threshold: float = 0.12,
        white_threshold: float = 0.18,
        min_confidence: float = 0.40,
        history_window: int = 15,
        min_temporal_frames: int = 4,
    ) -> None:
        """Initialize heuristic parameters and temporal tracking history.

        Args:
            red_threshold: Minimum red pixel ratio for fire-engine livery cue.
            white_threshold: Minimum white pixel ratio for ambulance base livery cue.
            min_confidence: Minimum combined heuristic confidence to flag vehicle.
            history_window: Rolling frame buffer size for tracking lightbar variance.
            min_temporal_frames: Minimum historical observations before factoring
                temporal flashing-light variance into the composite score.
        """
        self.red_threshold = red_threshold
        self.white_threshold = white_threshold
        self.min_confidence = min_confidence
        self.history_window = history_window
        self.min_temporal_frames = min_temporal_frames

        # Mapping of vehicle_id/track_id -> deque of top-ROI intensity metrics
        self._temporal_history: dict[str, deque[float]] = {}

    def compute_livery_ratios(self, crop_bgr: np.ndarray) -> tuple[float, float, float]:
        """Compute red and white livery color ratios and static livery score.

        Evaluates pixels in HSV color space:
        - Red: wraps around 0 and 180 degrees (H: [0, 10] U [170, 180], S: [70, 255], V: [50, 255])
        - White: low saturation, high brightness (S: [0, 45], V: [180, 255])

        Args:
            crop_bgr: BGR vehicle image crop array.

        Returns:
            tuple[float, float, float]: (red_ratio, white_ratio, livery_score)
        """
        hsv = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2HSV)
        total_pixels = crop_bgr.shape[0] * crop_bgr.shape[1]
        if total_pixels == 0:
            return 0.0, 0.0, 0.0

        # Red mask in HSV (two split ranges for hue wrapping)
        lower_red_1 = np.array([0, 70, 50], dtype=np.uint8)
        upper_red_1 = np.array([10, 255, 255], dtype=np.uint8)
        lower_red_2 = np.array([170, 70, 50], dtype=np.uint8)
        upper_red_2 = np.array([180, 255, 255], dtype=np.uint8)

        mask_red_1 = cv2.inRange(hsv, lower_red_1, upper_red_1)
        mask_red_2 = cv2.inRange(hsv, lower_red_2, upper_red_2)
        mask_red = cv2.bitwise_or(mask_red_1, mask_red_2)

        # White mask in HSV
        lower_white = np.array([0, 0, 180], dtype=np.uint8)
        upper_white = np.array([180, 45, 255], dtype=np.uint8)
        mask_white = cv2.inRange(hsv, lower_white, upper_white)

        red_pixels = int(np.count_nonzero(mask_red))
        white_pixels = int(np.count_nonzero(mask_white))

        red_ratio = float(red_pixels / total_pixels)
        white_ratio = float(white_pixels / total_pixels)

        # Static livery heuristic formulas:
        # 1. Fire engine cue: predominant red paint
        fire_cue = min(red_ratio / max(self.red_threshold, 0.01), 1.0)

        # 2. Ambulance cue: predominant white body with red cross / chevron / stripe accents
        has_red_accent = min(red_ratio / 0.035, 1.0)
        has_white_body = min(white_ratio / max(self.white_threshold, 0.01), 1.0)
        ambulance_cue = has_white_body * has_red_accent

        livery_score = max(fire_cue, ambulance_cue)
        return red_ratio, white_ratio, float(livery_score)

    def compute_temporal_variance(
        self,
        crop_bgr: np.ndarray,
        vehicle_id: str | None = None,
    ) -> tuple[float, float]:
        """Compute rooftop lightbar temporal luminance variance across video frames.

        Inspects the upper 25% of the vehicle crop where roof lightbars/beacons
        are positioned, tracking luminance oscillations caused by strobe or LED lights.

        Args:
            crop_bgr: BGR vehicle image crop array.
            vehicle_id: Optional tracking identifier for multi-frame history tracking.

        Returns:
            tuple[float, float]: (raw_variance, normalized_temporal_score in [0.0, 1.0])
        """
        if vehicle_id is None:
            # Single-frame static evaluation has no temporal history
            return 0.0, 0.0

        h, w = crop_bgr.shape[:2]
        top_h = max(int(h * 0.25), 1)
        roof_roi = crop_bgr[0:top_h, :]

        # Calculate luminance (Y channel) intensity metric in roof ROI
        # Flashing strobes induce sharp peaks in 95th percentile luminance
        gray_roi = cv2.cvtColor(roof_roi, cv2.COLOR_BGR2GRAY)
        peak_intensity = float(np.percentile(gray_roi, 95))

        if vehicle_id not in self._temporal_history:
            self._temporal_history[vehicle_id] = deque(maxlen=self.history_window)

        hist = self._temporal_history[vehicle_id]
        hist.append(peak_intensity)

        if len(hist) < self.min_temporal_frames:
            return 0.0, 0.0

        # Compute sample variance across rolling intensity observations
        hist_array = np.array(hist, dtype=np.float32)
        raw_variance = float(np.var(hist_array))

        # Flashing emergency lights (1-4 Hz) typically produce variance > 250 in 8-bit scale
        # Normalized score saturates around variance of 500
        normalized_score = float(np.clip(raw_variance / 500.0, 0.0, 1.0))
        return raw_variance, normalized_score

    def evaluate_crop(
        self,
        crop_bgr: np.ndarray,
        vehicle_id: str | None = None,
        timestamp: datetime | None = None,
    ) -> tuple[bool, float, dict[str, Any]]:
        """Evaluate a vehicle crop using documented visual heuristics.

        Args:
            crop_bgr: BGR vehicle image crop array.
            vehicle_id: Optional tracking ID for temporal video frame analysis.
            timestamp: Optional capture timestamp.

        Returns:
            tuple[bool, float, dict]:
                - is_emergency: True if heuristic confidence meets min_confidence threshold.
                - confidence: Heuristic confidence score in [0.0, 1.0].
                - metrics: Dictionary of computed visual cue metrics.

        Raises:
            InvalidInputFrameError: If crop is empty or invalid.
            CorruptFrameError: If crop contains NaN or Inf values.
        """
        if crop_bgr is None:
            raise InvalidInputFrameError("Vehicle crop cannot be None.")
        if not isinstance(crop_bgr, np.ndarray):
            raise InvalidInputFrameError(f"Expected numpy ndarray for vehicle crop, got {type(crop_bgr).__name__}.")
        if crop_bgr.size == 0 or crop_bgr.shape[0] == 0 or crop_bgr.shape[1] == 0:
            raise InvalidInputFrameError("Vehicle crop is empty or has zero dimensions.")
        if np.isnan(crop_bgr).any() or np.isinf(crop_bgr).any():
            raise CorruptFrameError("Vehicle crop contains NaN or infinite values.")

        red_ratio, white_ratio, livery_score = self.compute_livery_ratios(crop_bgr)
        raw_variance, temporal_score = self.compute_temporal_variance(crop_bgr, vehicle_id=vehicle_id)

        # Honest composite scoring:
        # If multi-frame temporal data is available, weight flashing lights heavily (55%).
        # If static single-frame, rely on livery color cues with a conservative ceiling (max 0.60)
        # to honestly reflect the absence of flashing confirmation.
        if vehicle_id is not None and len(self._temporal_history.get(vehicle_id, [])) >= self.min_temporal_frames:
            confidence = float(np.clip(0.45 * livery_score + 0.55 * temporal_score, 0.0, 1.0))
        else:
            # Single-frame static confidence cap: max 0.60
            confidence = float(np.clip(livery_score * 0.60, 0.0, 0.60))

        is_emergency = confidence >= self.min_confidence

        metrics = {
            "red_ratio": round(red_ratio, 4),
            "white_ratio": round(white_ratio, 4),
            "livery_score": round(livery_score, 4),
            "temporal_variance": round(raw_variance, 4),
            "temporal_score": round(temporal_score, 4),
            "heuristic_confidence": round(confidence, 4),
            "is_emergency_heuristic": is_emergency,
            "method": "heuristic_rule_based",
        }

        return is_emergency, confidence, metrics

    def reset_history(self, vehicle_id: str | None = None) -> None:
        """Clear temporal lightbar tracking history.

        Args:
            vehicle_id: Specific vehicle ID to reset, or None to clear all tracking buffers.
        """
        if vehicle_id is not None:
            self._temporal_history.pop(vehicle_id, None)
        else:
            self._temporal_history.clear()
