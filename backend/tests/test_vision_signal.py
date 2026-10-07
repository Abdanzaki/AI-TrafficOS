"""Unit and integration tests for traffic signal detection, state heuristic, and storage.

Validates:
1. Classical-CV heuristic (SignalStateHeuristic) on programmatically generated synthetic fixtures:
   - Lit RED lamp correctly classified with high confidence and dominance margin.
   - Lit YELLOW lamp correctly classified with high confidence and dominance margin.
   - Lit GREEN lamp correctly classified with high confidence and dominance margin.
   - Ambiguous inputs (conflicting red+green, unlit/dark head, diffuse white glare) strictly
     classified as 'unknown' with low/zero confidence (never a forced guess).
   - Graceful handling of invalid, empty, or miniature crops.
2. End-to-end TrafficSignalDetector:
   - Frame without signals returns an empty list (not an error).
   - Frame with multiple signals (red, yellow, green) localizes bounding boxes and classifies each.
   - Typed exception hierarchy for invalid frames (None, empty, corrupt, zero-dim).
3. Database Storage Path:
   - Base.metadata columns exist on 'signals' table (observed_state, observed_confidence, observed_at).
   - Async SQLAlchemy session writes real observation records to the signals table.
   - Querying the database verifies persisted camera observation fields.
"""

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
import numpy as np
import cv2
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ai.common.schemas import Detection, SignalDetection
from ai.cv.exceptions import (
    CorruptFrameError,
    InvalidInputFrameError,
    ModelLoadError,
    UnsupportedInputFormatError,
)
from ai.cv.signal_detector import DEFAULT_COCO_TRAFFIC_LIGHT_ID, TrafficSignalDetector
from ai.cv.signal_state_heuristic import SignalStateHeuristic, SignalStateResult
from app.core.database import Base
from app.models.intersection import Intersection
from app.models.signal import Signal
from app.schemas.signal import SignalObservationUpdate, SignalResponse
from app.vision.detectors import (
    get_signal_detector,
    record_signal_observation,
)


# ==============================================================================
# Synthetic Fixture Generators
# ==============================================================================


def create_synthetic_signal_crop(
    lit: str = "red",
    width: int = 50,
    height: int = 150,
    housing_color: tuple[int, int, int] = (30, 30, 30),
    unlit_color: tuple[int, int, int] = (45, 45, 45),
) -> np.ndarray:
    """Programmatically generate a synthetic 3-lamp vertical traffic signal head crop.

    Top lamp = Red, Middle lamp = Yellow, Bottom lamp = Green.

    Args:
        lit: Which lamp is active ('red', 'yellow', 'green', 'none', 'both_red_green', 'glare').
        width: Pixel width of crop.
        height: Pixel height of crop.
        housing_color: BGR color of signal housing background.
        unlit_color: BGR color of inactive lamps.

    Returns:
        np.ndarray: 3-channel uint8 BGR image crop.
    """
    crop = np.full((height, width, 3), housing_color, dtype=np.uint8)

    lamp_radius = int(width * 0.28)
    cx = width // 2
    cy_red = int(height * 0.20)
    cy_yel = int(height * 0.50)
    cy_grn = int(height * 0.80)

    # Standard colors in BGR
    c_red = (0, 0, 255) if lit in ("red", "both_red_green") else unlit_color
    c_yel = (0, 235, 255) if lit == "yellow" else unlit_color
    c_grn = (0, 255, 0) if lit in ("green", "both_red_green") else unlit_color

    if lit == "glare":
        # Diffuse desaturated white glare over all lamps
        c_red = (220, 220, 220)
        c_yel = (220, 220, 220)
        c_grn = (220, 220, 220)

    cv2.circle(crop, (cx, cy_red), lamp_radius, c_red, -1)
    cv2.circle(crop, (cx, cy_yel), lamp_radius, c_yel, -1)
    cv2.circle(crop, (cx, cy_grn), lamp_radius, c_grn, -1)

    return crop


def create_synthetic_scene_with_signals(
    signals_config: list[tuple[int, str]],
    width: int = 900,
    height: int = 640,
) -> np.ndarray:
    """Generate a realistic canvas containing multiple traffic signals on poles for YOLO.

    Args:
        signals_config: List of (x_center, lit_state) tuples.
        width: Frame width.
        height: Frame height.

    Returns:
        np.ndarray: 3-channel uint8 BGR image frame.
    """
    canvas = np.full((height, width, 3), 195, dtype=np.uint8)  # Daylight gray-sky backdrop

    head_w = 70
    head_h = 200
    y_top = 120

    for x_center, lit in signals_config:
        x1 = x_center - head_w // 2
        x2 = x_center + head_w // 2

        # Draw mounting pole
        cv2.rectangle(canvas, (x_center - 4, y_top + head_h), (x_center + 4, y_top + head_h + 200), (80, 80, 80), -1)

        # Draw signal head housing with dark border
        cv2.rectangle(canvas, (x1, y_top), (x2, y_top + head_h), (35, 35, 35), -1)
        cv2.rectangle(canvas, (x1 - 3, y_top - 3), (x2 + 3, y_top + head_h + 3), (20, 20, 20), 2)

        lamp_r = head_w // 4
        cx = x_center
        cy_red = y_top + head_h // 6
        cy_yel = y_top + head_h // 2
        cy_grn = y_top + 5 * head_h // 6

        # Draw visor arcs over each lamp
        for cy in (cy_red, cy_yel, cy_grn):
            cv2.ellipse(canvas, (cx, cy - lamp_r), (lamp_r + 2, 6), 0, 180, 360, (15, 15, 15), -1)

        c_red = (0, 0, 255) if lit == "red" else (40, 40, 40)
        c_yel = (0, 230, 255) if lit == "yellow" else (40, 40, 40)
        c_grn = (0, 255, 0) if lit == "green" else (40, 40, 40)

        cv2.circle(canvas, (cx, cy_red), lamp_r, c_red, -1)
        cv2.circle(canvas, (cx, cy_yel), lamp_r, c_yel, -1)
        cv2.circle(canvas, (cx, cy_grn), lamp_r, c_grn, -1)

    return canvas


# ==============================================================================
# 1. Classical-CV SignalStateHeuristic Unit Tests
# ==============================================================================


class TestSignalStateHeuristic:
    """Tests covering classical-CV lamp state classification logic."""

    @pytest.fixture
    def heuristic(self) -> SignalStateHeuristic:
        return SignalStateHeuristic()

    def test_classify_lit_red_lamp(self, heuristic: SignalStateHeuristic):
        """Verify illuminated red lamp produces state 'red' with high dominance margin."""
        crop = create_synthetic_signal_crop(lit="red")
        res = heuristic.evaluate_crop(crop)

        assert res.state == "red"
        assert res.dominant_color == "red"
        assert res.confidence >= 0.70
        assert res.margin >= 0.80
        assert res.details["pixel_counts"]["red"] > 0
        assert res.details["pixel_counts"]["green"] == 0
        assert res.details["spatial_consistencies"]["red"] > 0.80

    def test_classify_lit_yellow_lamp(self, heuristic: SignalStateHeuristic):
        """Verify illuminated yellow/amber lamp produces state 'yellow' with high margin."""
        crop = create_synthetic_signal_crop(lit="yellow")
        res = heuristic.evaluate_crop(crop)

        assert res.state == "yellow"
        assert res.dominant_color == "yellow"
        assert res.confidence >= 0.70
        assert res.margin >= 0.80
        assert res.details["pixel_counts"]["yellow"] > 0
        assert res.details["pixel_counts"]["red"] == 0

    def test_classify_lit_green_lamp(self, heuristic: SignalStateHeuristic):
        """Verify illuminated green lamp produces state 'green' with high margin."""
        crop = create_synthetic_signal_crop(lit="green")
        res = heuristic.evaluate_crop(crop)

        assert res.state == "green"
        assert res.dominant_color == "green"
        assert res.confidence >= 0.70
        assert res.margin >= 0.80
        assert res.details["pixel_counts"]["green"] > 0
        assert res.details["pixel_counts"]["yellow"] == 0

    def test_ambiguous_both_red_and_green_lit(self, heuristic: SignalStateHeuristic):
        """Verify conflicting simultaneous lamps produce state 'unknown' with low confidence."""
        crop = create_synthetic_signal_crop(lit="both_red_green")
        res = heuristic.evaluate_crop(crop)

        assert res.state == "unknown"
        # Narrow margin prevents forced guess; confidence must be strictly low
        assert res.confidence <= 0.35
        assert res.margin < heuristic.ambiguity_margin_threshold

    def test_ambiguous_all_lamps_off(self, heuristic: SignalStateHeuristic):
        """Verify dark/unlit signal head yields state 'unknown' with 0.0 confidence."""
        crop = create_synthetic_signal_crop(lit="none")
        res = heuristic.evaluate_crop(crop)

        assert res.state == "unknown"
        assert res.confidence == 0.0
        assert res.dominant_color == "none"

    def test_ambiguous_diffuse_sun_glare(self, heuristic: SignalStateHeuristic):
        """Verify desaturated white sunlight glare yields state 'unknown'."""
        crop = create_synthetic_signal_crop(lit="glare")
        res = heuristic.evaluate_crop(crop)

        assert res.state == "unknown"
        assert res.confidence == 0.0

    def test_invalid_input_crops_handled_safely(self, heuristic: SignalStateHeuristic):
        """Verify None, empty, and miniature inputs return 'unknown' without crashing."""
        res_none = heuristic.evaluate_crop(None)
        assert res_none.state == "unknown"
        assert res_none.confidence == 0.0

        empty = np.zeros((0, 0, 3), dtype=np.uint8)
        res_empty = heuristic.evaluate_crop(empty)
        assert res_empty.state == "unknown"

        tiny = np.zeros((2, 2, 3), dtype=np.uint8)
        res_tiny = heuristic.evaluate_crop(tiny)
        assert res_tiny.state == "unknown"


# ==============================================================================
# 2. End-to-End TrafficSignalDetector Tests
# ==============================================================================


class TestTrafficSignalDetector:
    """Tests covering YOLO signal-head detection combined with heuristic classification."""

    @pytest.fixture(scope="module")
    def signal_detector(self) -> TrafficSignalDetector:
        return TrafficSignalDetector(conf_threshold=0.15)

    def test_initialization_defaults(self, signal_detector: TrafficSignalDetector):
        """Verify default parameters and model loading."""
        assert signal_detector.conf_threshold == 0.15
        assert signal_detector.iou_threshold == 0.45
        assert signal_detector.device in ("cpu", "cuda")
        assert signal_detector.signal_class_id in (9, 10)
        assert isinstance(signal_detector.heuristic, SignalStateHeuristic)

    def test_missing_weights_raises_model_load_error(self, tmp_path: Path):
        """Verify non-existent weights path raises ModelLoadError."""
        fake_path = tmp_path / "nonexistent_model.pt"
        with pytest.raises(ModelLoadError):
            TrafficSignalDetector(model_path=fake_path)

    def test_no_signal_present_returns_empty_list(self, signal_detector: TrafficSignalDetector):
        """Verify scenes without traffic lights return empty list rather than error."""
        blank_canvas = np.full((640, 640, 3), 180, dtype=np.uint8)
        detections = signal_detector.detect(blank_canvas)

        assert isinstance(detections, list)
        assert len(detections) == 0

    def test_detect_and_classify_multiple_signals(self, signal_detector: TrafficSignalDetector):
        """Verify scene with 3 traffic lights detects heads and classifies red, yellow, green."""
        scene = create_synthetic_scene_with_signals(
            signals_config=[
                (160, "red"),
                (440, "yellow"),
                (720, "green"),
            ],
            width=900,
            height=640,
        )

        detections = signal_detector.detect(scene)

        # Assert all 3 signal heads are located
        assert len(detections) == 3

        # Sort detections by horizontal coordinate (left to right)
        detections.sort(key=lambda d: d.bbox[0])

        det_red, det_yel, det_grn = detections

        # Verify Red signal
        assert det_red.label == "traffic_light"
        assert det_red.state == "red"
        assert det_red.confidence > 0.20
        assert det_red.state_confidence > 0.60
        assert det_red.bbox[0] < det_red.bbox[2]
        assert det_red.bbox[1] < det_red.bbox[3]

        # Verify Yellow signal
        assert det_yel.label == "traffic_light"
        assert det_yel.state == "yellow"
        assert det_yel.confidence > 0.20
        assert det_yel.state_confidence > 0.60

        # Verify Green signal
        assert det_grn.label == "traffic_light"
        assert det_grn.state == "green"
        assert det_grn.confidence >= 0.15
        assert det_grn.state_confidence > 0.60

    def test_input_frame_validation(self, signal_detector: TrafficSignalDetector):
        """Verify typed exceptions for invalid, empty, or corrupt input frames."""
        with pytest.raises(InvalidInputFrameError, match="cannot be None"):
            signal_detector.detect(None)

        empty_arr = np.zeros((0, 0, 3), dtype=np.uint8)
        with pytest.raises(InvalidInputFrameError, match="empty"):
            signal_detector.detect(empty_arr)

        nan_arr = np.full((100, 100, 3), np.nan, dtype=np.float32)
        with pytest.raises(CorruptFrameError, match="NaN"):
            signal_detector.detect(nan_arr)

        with pytest.raises(InvalidInputFrameError, match="does not exist"):
            signal_detector.detect("/nonexistent/image/path.jpg")


# ==============================================================================
# 3. Database Storage Path Tests
# ==============================================================================


async def create_test_db():
    """Create isolated in-memory SQLite async engine and session factory."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    return engine, session_factory


class TestSignalObservationStorage:
    """Tests covering persistence of CV optical observations to the signals table."""

    def test_signals_table_metadata_columns(self):
        """Verify observed_state, observed_confidence, and observed_at columns in metadata."""
        cols = Base.metadata.tables["signals"].columns
        assert "observed_state" in cols
        assert "observed_confidence" in cols
        assert "observed_at" in cols
        assert "status" in cols  # Verify hardware status column remains intact

    @pytest.mark.anyio
    async def test_record_signal_observation_writes_to_real_db(self):
        """Verify record_signal_observation updates real database row with observation data."""
        engine, session_factory = await create_test_db()
        async with session_factory() as async_db_session:
            # 1. Seed Intersection
            inter = Intersection(
                name="Market & 4th",
                code="INT_MKT_4TH",
                status="active",
                city="San Francisco",
            )
            async_db_session.add(inter)
            await async_db_session.flush()

            # 2. Seed Signal (commanded state lives in phases, status is hardware health)
            signal = Signal(
                intersection_id=inter.id,
                code="SIG_MKT_4TH_01",
                status="active",
                observed_state=None,
                observed_confidence=None,
                observed_at=None,
            )
            async_db_session.add(signal)
            await async_db_session.commit()
            signal_id = signal.id

            # 3. Store CV camera observation
            now = datetime.now(timezone.utc)
            updated = await record_signal_observation(
                db=async_db_session,
                signal_id=signal_id,
                observed_state="red",
                confidence=0.942,
                observed_at=now,
            )
            await async_db_session.commit()

            assert updated is not None
            assert updated.id == signal_id
            assert updated.observed_state == "red"
            assert abs(updated.observed_confidence - 0.942) < 1e-4

            # 4. Query back using fresh select
            stmt = select(Signal).where(Signal.id == signal_id)
            res = await async_db_session.execute(stmt)
            queried = res.scalar_one()

            assert queried.observed_state == "red"
            assert abs(queried.observed_confidence - 0.942) < 1e-4
            assert queried.observed_at is not None
            assert queried.status == "active"  # Hardware status remains unchanged

        await engine.dispose()

    @pytest.mark.anyio
    async def test_record_signal_observation_nonexistent_returns_none(self):
        """Verify writing an observation for an unknown signal_id returns None safely."""
        engine, session_factory = await create_test_db()
        async with session_factory() as async_db_session:
            res = await record_signal_observation(
                db=async_db_session,
                signal_id=999999,
                observed_state="green",
                confidence=0.88,
            )
            assert res is None
        await engine.dispose()


    def test_pydantic_schema_serialization(self):
        """Verify Pydantic schema serialization for SignalResponse and SignalObservationUpdate."""
        obs_update = SignalObservationUpdate(
            observed_state="yellow",
            observed_confidence=0.85,
            observed_at=datetime.now(timezone.utc),
        )
        assert obs_update.observed_state == "yellow"
        assert obs_update.observed_confidence == 0.85

        sig_resp = SignalResponse(
            id=1,
            intersection_id=10,
            code="SIG_01",
            status="active",
            observed_state="green",
            observed_confidence=0.91,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        assert sig_resp.observed_state == "green"
        assert sig_resp.observed_confidence == 0.91
