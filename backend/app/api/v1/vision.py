"""Computer Vision API router for AI TrafficOS.

Provides high-performance perception endpoints:
1. POST /vision/analyze-image:
   Multipart image upload -> YOLO vehicle detection + traffic metrics + signal detection
   -> persists TrafficRecord aggregate (source='camera') and optional VehicleEvents.
2. POST /vision/analyze-video:
   Multipart video upload -> strided frame evaluation + MultiObjectTracker + incident heuristics
   -> persists windowed TrafficRecords and heuristic candidate Incidents.
3. GET /vision/signal-observations:
   Paginated queries of physical Signal controllers with camera-observed optical states.
"""

from datetime import datetime, timezone
import math
import os
from pathlib import Path
import tempfile
import time
from typing import Any, Optional

import cv2
from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)
import numpy as np
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_current_user, require_roles
from app.core.database import get_db
from app.models.auth import User
from app.models.event import Incident, VehicleEvent
from app.models.intersection import Intersection
from app.models.road import Lane
from app.models.signal import Signal
from app.models.traffic import TrafficRecord
from app.schemas.vision import (
    DetectionSummaryItem,
    ImageAnalysisResponse,
    PaginatedSignalObservations,
    SignalObservationItem,
    SignalObservationResult,
    VideoAnalysisResponse,
)
from app.vision.congestion import compute_congestion_score
from app.vision.detectors import (
    CorruptFrameError,
    InvalidInputFrameError,
    UnsupportedInputFormatError,
    detection_to_vehicle_event_create,
    get_signal_detector,
    get_vehicle_detector,
    record_signal_observation,
)
from app.vision.incidents import IncidentCandidate, get_incident_detector
from app.vision.metrics import compute_frame_metrics
from app.vision.processor import (
    CorruptVideoError,
    EmptyVideoError,
    UnsupportedVideoFormatError,
    VideoOpenError,
    VideoProcessor,
)
from app.vision.storage import (
    record_congestion_observation,
    record_incident_candidates,
)

router = APIRouter(
    prefix="/vision",
    tags=["vision"],
)

# Documented Operational Limits
MAX_IMAGE_SIZE_BYTES: int = 10 * 1024 * 1024   # 10 MB limit
MAX_VIDEO_SIZE_BYTES: int = 50 * 1024 * 1024   # 50 MB limit
MAX_VIDEO_DURATION_SECONDS: float = 60.0       # 60s max video duration
DEFAULT_FRAME_STRIDE: int = 5                  # Process every 5th frame
DEFAULT_PROCESSING_TIMEOUT_SECONDS: float = 30.0

ALLOWED_IMAGE_TYPES: set[str] = {
    "image/jpeg",
    "image/jpg",
    "image/png",
    "image/webp",
}

ALLOWED_VIDEO_TYPES: set[str] = {
    "video/mp4",
    "video/avi",
    "video/x-msvideo",
    "video/quicktime",
    "video/x-matroska",
    "video/webm",
}


def _classify_congestion_status(level: int) -> str:
    """Map integer congestion percentage [0, 100] to operational category."""
    if level <= 25:
        return "free_flow"
    if level <= 50:
        return "moderate"
    if level <= 75:
        return "heavy"
    return "severe"


@router.post(
    "/analyze-image",
    response_model=ImageAnalysisResponse,
    status_code=status.HTTP_200_OK,
    summary="Analyze single image with YOLO, metrics, and signal detection (officer and admin only)",
)
async def analyze_image(
    request: Request,
    file: UploadFile = File(...),
    intersection_id: Optional[int] = Form(None),
    lane_id: Optional[int] = Form(None),
    signal_id: Optional[int] = Form(None),
    persist_events: bool = Form(False),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles("admin", "traffic_officer")),
) -> ImageAnalysisResponse:
    """Analyze a single uploaded image with vehicle perception and optical signal heuristic.

    Operational Specifications:
    - Content-type validation with explicit HTTP 415 error.
    - Size validation with explicit HTTP 413 error (10MB default limit).
    - Persists aggregate `TrafficRecord` with source='camera' when intersection_id is given.
    - Optionally persists individual `VehicleEvent` records when persist_events=True.
    - Always cleans up temporary files on disk.
    """
    # Fallback to query params if omitted in Form body
    if intersection_id is None and "intersection_id" in request.query_params:
        try:
            intersection_id = int(request.query_params["intersection_id"])
        except ValueError:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid intersection_id")
    if lane_id is None and "lane_id" in request.query_params:
        try:
            lane_id = int(request.query_params["lane_id"])
        except ValueError:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid lane_id")
    if signal_id is None and "signal_id" in request.query_params:
        try:
            signal_id = int(request.query_params["signal_id"])
        except ValueError:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid signal_id")
    if not persist_events and "persist_events" in request.query_params:
        persist_events = request.query_params["persist_events"].lower() in ("true", "1")

    # 1. Validate Content-Type (HTTP 415)
    content_type = (file.content_type or "").lower().strip()
    if content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=(
                f"Unsupported media type: '{file.content_type}'. "
                f"Allowed image types are: {sorted(list(ALLOWED_IMAGE_TYPES))}"
            ),
        )

    # 2. Read contents and validate size (HTTP 413)
    content = await file.read()
    if len(content) > MAX_IMAGE_SIZE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=(
                f"Uploaded image size ({len(content)} bytes) exceeds "
                f"maximum allowable limit of {MAX_IMAGE_SIZE_BYTES} bytes."
            ),
        )

    # 3. Foreign key validations
    if intersection_id is not None:
        intersection = await db.get(Intersection, intersection_id)
        if not intersection:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Intersection with id {intersection_id} not found",
            )

    if lane_id is not None:
        lane = await db.get(Lane, lane_id)
        if not lane:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Lane with id {lane_id} not found",
            )

    if signal_id is not None:
        sig = await db.get(Signal, signal_id)
        if not sig:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Signal with id {signal_id} not found",
            )

    # 4. Write to temp file and guarantee cleanup
    ext = Path(file.filename or "image.jpg").suffix or ".jpg"
    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp_file:
        tmp_path = Path(tmp_file.name)
        tmp_file.write(content)

    try:
        # 5. Read image with OpenCV
        img_bgr = cv2.imread(str(tmp_path))
        if img_bgr is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Failed to decode image data; file may be corrupt or invalid.",
            )

        now_utc = datetime.now(timezone.utc)

        # 6. Run vehicle detection & metrics
        vehicle_detector = get_vehicle_detector()
        vehicle_detections = vehicle_detector.detect(img_bgr, timestamp=now_utc)
        metrics = compute_frame_metrics(detections=vehicle_detections, frame_shape=img_bgr.shape)
        congestion = compute_congestion_score(
            metrics=metrics,
            detections=vehicle_detections,
            frame_shape=img_bgr.shape,
        )

        # 7. Run traffic signal detection & state heuristic
        signal_detector = get_signal_detector()
        signal_detections = signal_detector.detect(img_bgr, timestamp=now_utc)

        # 8. Persist TrafficRecord aggregate if intersection_id is provided
        traffic_record_id: Optional[int] = None
        if intersection_id is not None:
            tr = await record_congestion_observation(
                db=db,
                intersection_id=intersection_id,
                congestion_result=congestion,
                vehicle_count=metrics.total_vehicles,
                lane_id=lane_id,
                recorded_at=now_utc,
            )
            traffic_record_id = tr.id

        # 9. Optionally persist individual VehicleEvents (opt-in to prevent DB flooding)
        events_persisted = 0
        if persist_events and intersection_id is not None:
            for det in vehicle_detections:
                ev_data = detection_to_vehicle_event_create(
                    detection=det,
                    intersection_id=intersection_id,
                    lane_id=lane_id,
                )
                db_event = VehicleEvent(
                    intersection_id=ev_data.intersection_id,
                    lane_id=ev_data.lane_id,
                    event_type=ev_data.event_type or "detection",
                    vehicle_type=ev_data.vehicle_type,
                    speed_kmh=ev_data.speed_kmh,
                    direction=ev_data.direction,
                    confidence=ev_data.confidence,
                    detected_at=ev_data.detected_at,
                )
                db.add(db_event)
                events_persisted += 1

        # 10. Update Signal controller if observation exists
        if signal_detections:
            best_sig = max(signal_detections, key=lambda s: s.confidence)
            target_signal_id = signal_id
            if target_signal_id is None and intersection_id is not None:
                # Resolve primary signal at intersection
                sig_stmt = select(Signal).where(Signal.intersection_id == intersection_id).limit(1)
                sig_res = await db.execute(sig_stmt)
                matching_signal = sig_res.scalars().first()
                if matching_signal is not None:
                    target_signal_id = matching_signal.id

            if target_signal_id is not None:
                await record_signal_observation(
                    db=db,
                    signal_id=target_signal_id,
                    observed_state=best_sig.state,
                    confidence=best_sig.state_confidence,
                    observed_at=best_sig.timestamp or now_utc,
                )

        if intersection_id is not None or signal_id is not None:
            await db.commit()

        # 11. Format response summary
        detection_summaries = [
            DetectionSummaryItem(
                label=d.label,
                confidence=round(d.confidence, 4),
                bbox=list(d.bbox) if d.bbox else None,
                vehicle_type=d.label,
            )
            for d in vehicle_detections
        ]

        signal_summaries = [
            SignalObservationResult(
                signal_id=signal_id,
                state=s.state,
                confidence=round(s.state_confidence, 4),
                bbox=list(s.bbox) if s.bbox else None,
            )
            for s in signal_detections
        ]

        return ImageAnalysisResponse(
            vehicle_count=metrics.total_vehicles,
            vehicle_counts_by_type=metrics.counts_by_class,
            traffic_density=round(metrics.density_per_100k_px / 100000.0, 6),
            density_per_100k_px=round(metrics.density_per_100k_px, 2),
            lane_occupancy=metrics.lane_occupancy,
            queue_lengths=metrics.queue_lengths,
            congestion_level=congestion.congestion_level,
            congestion_status=_classify_congestion_status(congestion.congestion_level),
            detections=detection_summaries,
            signal_observations=signal_summaries,
            traffic_record_id=traffic_record_id,
            events_persisted=events_persisted,
            processed_at=datetime.now(timezone.utc),
        )

    except (CorruptFrameError, InvalidInputFrameError, UnsupportedInputFormatError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Computer vision frame decoding error: {exc}",
        )
    finally:
        # Guarantee disk cleanup
        if tmp_path.exists():
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


@router.post(
    "/analyze-video",
    response_model=VideoAnalysisResponse,
    status_code=status.HTTP_200_OK,
    summary="Analyze video upload with tracking and incident heuristics (officer and admin only)",
)
async def analyze_video(
    request: Request,
    file: UploadFile = File(...),
    intersection_id: Optional[int] = Form(None),
    lane_id: Optional[int] = Form(None),
    frame_stride: int = Form(DEFAULT_FRAME_STRIDE),
    timeout_seconds: float = Form(DEFAULT_PROCESSING_TIMEOUT_SECONDS),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles("admin", "traffic_officer")),
) -> VideoAnalysisResponse:
    """Process a recorded traffic video file using strided multi-object tracking and heuristics.

    Operational Specifications:
    - Content-type validation with explicit HTTP 415 error.
    - Size validation with explicit HTTP 413 error (50MB default limit).
    - Maximum duration check (60s default limit) preventing resource exhaustion.
    - Honest timeout checking (HTTP 504 if elapsed time exceeds timeout).
    - Persists aggregated TrafficRecord per sampled window.
    - Persists heuristic incident candidates as Incidents (status='reported').
    - Always cleans up temporary files on disk.
    """
    # Fallback to query params if omitted in Form body
    if intersection_id is None and "intersection_id" in request.query_params:
        try:
            intersection_id = int(request.query_params["intersection_id"])
        except ValueError:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid intersection_id")
    if lane_id is None and "lane_id" in request.query_params:
        try:
            lane_id = int(request.query_params["lane_id"])
        except ValueError:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid lane_id")
    if "frame_stride" in request.query_params and frame_stride == DEFAULT_FRAME_STRIDE:
        try:
            frame_stride = int(request.query_params["frame_stride"])
        except ValueError:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid frame_stride")
    if "timeout_seconds" in request.query_params and timeout_seconds == DEFAULT_PROCESSING_TIMEOUT_SECONDS:
        try:
            timeout_seconds = float(request.query_params["timeout_seconds"])
        except ValueError:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid timeout_seconds")

    # 1. Validate Content-Type (HTTP 415)
    content_type = (file.content_type or "").lower().strip()
    if content_type not in ALLOWED_VIDEO_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=(
                f"Unsupported media type: '{file.content_type}'. "
                f"Allowed video types are: {sorted(list(ALLOWED_VIDEO_TYPES))}"
            ),
        )

    # 2. Read contents and validate size (HTTP 413)
    content = await file.read()
    if len(content) > MAX_VIDEO_SIZE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=(
                f"Uploaded video size ({len(content)} bytes) exceeds "
                f"maximum allowable limit of {MAX_VIDEO_SIZE_BYTES} bytes."
            ),
        )

    # 3. Foreign key validations
    if intersection_id is not None:
        intersection = await db.get(Intersection, intersection_id)
        if not intersection:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Intersection with id {intersection_id} not found",
            )

    if lane_id is not None:
        lane = await db.get(Lane, lane_id)
        if not lane:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Lane with id {lane_id} not found",
            )

    # 4. Write to temp file and guarantee cleanup
    ext = Path(file.filename or "video.mp4").suffix or ".mp4"
    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp_file:
        tmp_path = Path(tmp_file.name)
        tmp_file.write(content)

    try:
        # 5. Open video with OpenCV to check duration and validity
        cap = cv2.VideoCapture(str(tmp_path))
        if not cap.isOpened():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Failed to open or decode video container.",
            )

        fps = float(cap.get(cv2.CAP_PROP_FPS) or 25.0)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        duration_seconds = float(total_frames / fps) if fps > 0 and total_frames > 0 else 0.0
        cap.release()

        if duration_seconds > MAX_VIDEO_DURATION_SECONDS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Video duration ({duration_seconds:.1f}s) exceeds "
                    f"maximum allowed limit of {MAX_VIDEO_DURATION_SECONDS:.1f}s."
                ),
            )

        # 6. Initialize pipeline components
        start_mono = time.monotonic()
        processor = VideoProcessor(
            detector=get_vehicle_detector(),
            frame_stride=max(1, frame_stride),
        )
        incident_detector = get_incident_detector()
        incident_detector.reset()

        sampled_results = []
        raw_candidates: list[IncidentCandidate] = []
        window_size = 10  # frames per persistence aggregation window
        window_metrics: list[int] = []
        window_congestion: list[int] = []
        traffic_records_created = 0

        # 7. Process video with strict timeout check
        for frame_res in processor.process_video(tmp_path):
            # Honest timeout guard
            if (time.monotonic() - start_mono) > timeout_seconds:
                raise HTTPException(
                    status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                    detail=f"Video processing timed out after {timeout_seconds:.1f} seconds.",
                )

            sampled_results.append(frame_res)
            c_score = compute_congestion_score(metrics=frame_res.metrics)
            window_metrics.append(frame_res.metrics.total_vehicles)
            window_congestion.append(c_score.congestion_level)

            # Evaluate incident heuristics on active tracked vehicles
            candidates = incident_detector.detect_incidents(
                tracks=frame_res.tracks,
                timestamp=frame_res.timestamp,
            )
            raw_candidates.extend(candidates)

            # Persist windowed TrafficRecord
            if len(window_metrics) >= window_size and intersection_id is not None:
                avg_count = int(round(float(np.mean(window_metrics))))
                avg_c = int(round(float(np.mean(window_congestion))))
                await record_congestion_observation(
                    db=db,
                    intersection_id=intersection_id,
                    congestion_result=avg_c,
                    vehicle_count=avg_count,
                    lane_id=lane_id,
                    recorded_at=frame_res.timestamp,
                )
                traffic_records_created += 1
                window_metrics.clear()
                window_congestion.clear()

        # Flush final remaining partial window
        if window_metrics and intersection_id is not None:
            avg_count = int(round(float(np.mean(window_metrics))))
            avg_c = int(round(float(np.mean(window_congestion))))
            last_timestamp = sampled_results[-1].timestamp if sampled_results else datetime.now(timezone.utc)
            await record_congestion_observation(
                db=db,
                intersection_id=intersection_id,
                congestion_result=avg_c,
                vehicle_count=avg_count,
                lane_id=lane_id,
                recorded_at=last_timestamp,
            )
            traffic_records_created += 1

        # 8. Deduplicate incident candidates by (track_id, event_type)
        deduped_candidates: dict[tuple[int, str], IncidentCandidate] = {}
        for c in raw_candidates:
            key = (c.track_id, c.event_type)
            if key not in deduped_candidates or c.confidence > deduped_candidates[key].confidence:
                deduped_candidates[key] = c

        incidents_to_persist = list(deduped_candidates.values())
        created_incidents: list[Incident] = []
        if incidents_to_persist:
            created_incidents = await record_incident_candidates(
                db=db,
                candidates=incidents_to_persist,
                intersection_id=intersection_id,
            )

        if intersection_id is not None or created_incidents:
            await db.commit()

        # 9. Compute global summary values
        mean_veh = float(np.mean([r.metrics.total_vehicles for r in sampled_results])) if sampled_results else 0.0
        mean_cong = float(np.mean([compute_congestion_score(r.metrics).congestion_level for r in sampled_results])) if sampled_results else 0.0

        incident_summaries = [
            {
                "id": inc.id,
                "severity": inc.severity,
                "status": inc.status,
                "description": inc.description,
            }
            for inc in created_incidents
        ]

        return VideoAnalysisResponse(
            frames_processed=len(sampled_results) * max(1, frame_stride),
            total_frames_sampled=len(sampled_results),
            duration_seconds=round(duration_seconds, 2),
            fps=round(fps, 2),
            average_vehicle_count=round(mean_veh, 2),
            average_congestion_level=round(mean_cong, 2),
            traffic_records_created=traffic_records_created,
            incidents_created=len(created_incidents),
            incident_details=incident_summaries,
            processed_at=datetime.now(timezone.utc),
        )

    except (CorruptVideoError, EmptyVideoError, UnsupportedVideoFormatError, VideoOpenError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Video processing error: {exc}",
        )
    finally:
        # Guarantee disk cleanup
        if tmp_path.exists():
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


@router.get(
    "/signal-observations",
    response_model=PaginatedSignalObservations,
    status_code=status.HTTP_200_OK,
    summary="List traffic signals with camera-observed optical states (any authenticated user)",
)
async def list_signal_observations(
    intersection_id: Optional[int] = Query(None, description="Filter by intersection ID"),
    observed_state: Optional[str] = Query(None, description="Filter by observed lamp state ('red', 'yellow', 'green', 'unknown')"),
    page: int = Query(1, ge=1, description="Page number"),
    per_page: int = Query(20, ge=1, le=100, description="Items per page"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PaginatedSignalObservations:
    """Retrieve paginated list of traffic signals possessing optical camera observations.

    Joins `Signal.intersection` to return associated intersection details.
    Accessible to any authenticated user role (admin, traffic_officer, analyst).
    """
    conditions = [Signal.observed_state.is_not(None)]

    if intersection_id is not None:
        conditions.append(Signal.intersection_id == intersection_id)
    if observed_state is not None:
        conditions.append(Signal.observed_state == observed_state.lower().strip())

    count_stmt = select(func.count(Signal.id)).where(*conditions)
    total_result = await db.execute(count_stmt)
    total = total_result.scalar() or 0

    offset = (page - 1) * per_page
    stmt = (
        select(Signal)
        .options(selectinload(Signal.intersection))
        .where(*conditions)
        .order_by(Signal.observed_at.desc().nullslast(), Signal.id.desc())
        .offset(offset)
        .limit(per_page)
    )

    result = await db.execute(stmt)
    signals = list(result.scalars().all())

    items: list[SignalObservationItem] = [
        SignalObservationItem(
            signal_id=sig.id,
            intersection_id=sig.intersection_id,
            intersection_name=sig.intersection.name if sig.intersection else None,
            intersection_code=sig.intersection.code if sig.intersection else None,
            signal_code=sig.code,
            status=sig.status,
            observed_state=sig.observed_state or "unknown",
            observed_confidence=sig.observed_confidence or 0.0,
            observed_at=sig.observed_at,
            created_at=sig.created_at,
            updated_at=sig.updated_at,
        )
        for sig in signals
    ]

    pages = math.ceil(total / per_page) if total > 0 else 1

    return PaginatedSignalObservations(
        items=items,
        total=total,
        page=page,
        per_page=per_page,
        pages=pages,
    )
