"""Classical Computer Vision heuristic for traffic signal lamp state recognition.

DOCUMENTED ARCHITECTURAL NOTE:
-------------------------------
This module implements a deterministic classical-CV heuristic layer (SignalStateHeuristic).
It is explicitly NOT a trained deep learning or machine learning classifier.

Justification:
1. Standard object detection datasets (e.g. MS-COCO) provide bounding boxes for "traffic light"
   (COCO class 9), but do NOT annotate which lamp is currently illuminated (red, yellow, or green).
2. Traffic control and safety-critical preemption require deterministic, auditable decisions.
   Classical HSV color masking with spatial zone analysis and dominance margin calculation
   provides full mathematical explainability and eliminates silent neural hallucination.
3. Transparent confidence: confidence is derived directly from the color dominance margin
   (difference between the top lit color and the runner-up). When color dominance is ambiguous
   or no lamp meets activation thresholds, the heuristic strictly emits state 'unknown' with
   low confidence—never forcing a statistical guess.

Physical & Optical Limitations:
-------------------------------
- Nighttime bloom: high-intensity LED lamps produce flare across adjacent dark lenses.
- Direct sunlight / glare: low-angle sunlight hitting signal lenses (sun phantom effect) can illuminate unlit lenses.
- Occlusion & perspective: partially occluded signal heads or extreme viewing angles distort vertical lamp order.
- Non-standard configurations: doghouse (5-section) clusters, horizontal signals, and turn arrows require custom spatial layouts.
"""

from dataclasses import dataclass, field
from typing import Any
import numpy as np
import cv2


@dataclass(frozen=True)
class SignalStateResult:
    """Immutable result payload produced by SignalStateHeuristic."""

    state: str  # "red", "yellow", "green", or "unknown"
    confidence: float  # [0.0, 1.0] derived from color dominance margin & spatial alignment
    dominant_color: str  # "red", "yellow", "green", or "none"
    margin: float  # Margin of separation between winning and runner-up color scores [0.0, 1.0]
    details: dict[str, Any] = field(default_factory=dict)


class SignalStateHeuristic:
    """Classical Computer Vision heuristic for traffic signal state recognition.

    Analyzes cropped traffic light images in HSV color space combined with
    vertical spatial lamp partitioning (top=red, middle=yellow, bottom=green)
    and brightest lamp position analysis.
    """

    def __init__(
        self,
        min_pixel_count: int = 8,
        min_pixel_ratio: float = 0.008,
        ambiguity_margin_threshold: float = 0.20,
        min_saturation: int = 55,
        min_value: int = 55,
    ) -> None:
        """Initialize the signal state heuristic with color and margin thresholds.

        Args:
            min_pixel_count: Minimum active color pixels required to consider any lamp lit.
            min_pixel_ratio: Minimum active color pixel ratio relative to crop area.
            ambiguity_margin_threshold: Minimum dominance margin required between the top
                color and runner-up color. Margins below this trigger state 'unknown'.
            min_saturation: Minimum HSV Saturation threshold for active colored light.
            min_value: Minimum HSV Value (brightness) threshold for active colored light.
        """
        self.min_pixel_count = min_pixel_count
        self.min_pixel_ratio = min_pixel_ratio
        self.ambiguity_margin_threshold = ambiguity_margin_threshold
        self.min_saturation = min_saturation
        self.min_value = min_value

    def evaluate_crop(self, crop_bgr: np.ndarray) -> SignalStateResult:
        """Classify the illuminated lamp state of a cropped traffic signal head.

        Args:
            crop_bgr: 3-channel uint8 BGR image crop of a detected traffic signal head.

        Returns:
            SignalStateResult: Recognized state ('red', 'yellow', 'green', 'unknown')
                with dominance-derived confidence and detailed metrics.
        """
        if crop_bgr is None or not isinstance(crop_bgr, np.ndarray):
            return SignalStateResult(
                state="unknown",
                confidence=0.0,
                dominant_color="none",
                margin=0.0,
                details={"error": "invalid_input_none_or_not_array"},
            )

        if crop_bgr.size == 0 or crop_bgr.ndim != 3:
            return SignalStateResult(
                state="unknown",
                confidence=0.0,
                dominant_color="none",
                margin=0.0,
                details={"error": "empty_crop_or_invalid_dimensions"},
            )

        height, width = crop_bgr.shape[:2]
        if height < 4 or width < 4:
            return SignalStateResult(
                state="unknown",
                confidence=0.0,
                dominant_color="none",
                margin=0.0,
                details={"error": "crop_too_small", "shape": (height, width)},
            )

        area = float(height * width)

        # Convert to HSV color space
        hsv = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2HSV)
        sat = self.min_saturation
        val = self.min_value

        # 1. Color Segmentation Masks in HSV
        # Red spans 0-10 and 160-180 in OpenCV 8-bit hue
        r_mask1 = cv2.inRange(hsv, np.array([0, sat, val], dtype=np.uint8), np.array([10, 255, 255], dtype=np.uint8))
        r_mask2 = cv2.inRange(hsv, np.array([160, sat, val], dtype=np.uint8), np.array([180, 255, 255], dtype=np.uint8))
        mask_red = cv2.bitwise_or(r_mask1, r_mask2)

        # Yellow / Amber spans 11-35 hue
        mask_yellow = cv2.inRange(hsv, np.array([11, sat, val], dtype=np.uint8), np.array([35, 255, 255], dtype=np.uint8))

        # Green spans 36-95 hue (pure green through traffic teal)
        mask_green = cv2.inRange(hsv, np.array([36, max(45, sat - 10), max(45, val - 10)], dtype=np.uint8), np.array([95, 255, 255], dtype=np.uint8))

        cnt_red = int(np.count_nonzero(mask_red))
        cnt_yellow = int(np.count_nonzero(mask_yellow))
        cnt_green = int(np.count_nonzero(mask_green))

        ratio_red = cnt_red / area
        ratio_yellow = cnt_yellow / area
        ratio_green = cnt_green / area

        # 2. Vertical Spatial Lamp Partitioning
        # Standard vertical signal heads: Top = Red, Middle = Yellow, Bottom = Green
        y_top_boundary = int(height * 0.42)
        y_bottom_boundary = int(height * 0.58)

        # Red spatial consistency: fraction of red pixels in upper half
        spatial_red = (
            float(np.count_nonzero(mask_red[:y_top_boundary, :])) / cnt_red
            if cnt_red > 0
            else 0.0
        )
        # Yellow spatial consistency: fraction of yellow pixels in middle band
        spatial_yellow = (
            float(np.count_nonzero(mask_yellow[int(height * 0.20) : int(height * 0.80), :])) / cnt_yellow
            if cnt_yellow > 0
            else 0.0
        )
        # Green spatial consistency: fraction of green pixels in lower half
        spatial_green = (
            float(np.count_nonzero(mask_green[y_bottom_boundary:, :])) / cnt_green
            if cnt_green > 0
            else 0.0
        )

        # 3. Brightest Core Lamp Detection (V channel)
        v_chan = hsv[:, :, 2]
        v_blur = cv2.GaussianBlur(v_chan, (5, 5), 0)
        _, max_v, _, max_loc = cv2.minMaxLoc(v_blur)
        brightest_y_ratio = max_loc[1] / float(max(1, height))

        # 4. Composite Scoring per Color
        # Score blends raw active pixel count with spatial alignment
        score_red = cnt_red * (0.65 + 0.35 * spatial_red)
        score_yellow = cnt_yellow * (0.65 + 0.35 * spatial_yellow)
        score_green = cnt_green * (0.65 + 0.35 * spatial_green)

        scores = [
            ("red", score_red, cnt_red, ratio_red, spatial_red),
            ("yellow", score_yellow, cnt_yellow, ratio_yellow, spatial_yellow),
            ("green", score_green, cnt_green, ratio_green, spatial_green),
        ]
        scores.sort(key=lambda item: item[1], reverse=True)

        top_color, top_score, top_cnt, top_ratio, top_spatial = scores[0]
        second_color, second_score, second_cnt, _, _ = scores[1]

        details: dict[str, Any] = {
            "crop_shape": (height, width),
            "pixel_counts": {"red": cnt_red, "yellow": cnt_yellow, "green": cnt_green},
            "pixel_ratios": {
                "red": round(ratio_red, 4),
                "yellow": round(ratio_yellow, 4),
                "green": round(ratio_green, 4),
            },
            "spatial_consistencies": {
                "red": round(spatial_red, 4),
                "yellow": round(spatial_yellow, 4),
                "green": round(spatial_green, 4),
            },
            "scores": {
                "red": round(score_red, 2),
                "yellow": round(score_yellow, 2),
                "green": round(score_green, 2),
            },
            "brightest_pixel_value": float(max_v),
            "brightest_y_ratio": round(brightest_y_ratio, 3),
        }

        # Case A: Insufficient color activation -> No lamp illuminated
        if top_cnt < self.min_pixel_count or top_ratio < self.min_pixel_ratio:
            return SignalStateResult(
                state="unknown",
                confidence=0.0,
                dominant_color="none",
                margin=0.0,
                details=details,
            )

        # Case B: Dominance Margin Analysis
        margin = float((top_score - second_score) / (top_score + 1e-6))
        details["margin"] = round(margin, 4)

        # If the margin is too narrow (e.g. both red and green lit, or low-contrast ambiguity)
        if margin < self.ambiguity_margin_threshold:
            # Ambiguous state: strictly emit 'unknown' with low confidence
            ambiguous_conf = float(round(min(0.35, max(0.05, margin * 0.5)), 4))
            return SignalStateResult(
                state="unknown",
                confidence=ambiguous_conf,
                dominant_color=top_color,
                margin=round(margin, 4),
                details=details,
            )

        # Case C: Confident State Classification
        # Confidence derived from color dominance margin, spatial alignment, and brightness
        norm_v = min(1.0, max_v / 255.0)
        raw_conf = 0.50 * margin + 0.30 * top_spatial + 0.20 * norm_v
        final_conf = float(round(min(0.99, max(0.40, raw_conf)), 4))

        return SignalStateResult(
            state=top_color,
            confidence=final_conf,
            dominant_color=top_color,
            margin=round(margin, 4),
            details=details,
        )
