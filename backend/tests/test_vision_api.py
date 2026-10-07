"""Integration tests for computer vision API endpoints (/api/v1/vision).

Validates:
- POST /vision/analyze-image:
  - 200 on valid image upload
  - Persists TrafficRecord aggregate (source='camera') in real PostgreSQL
  - Optional VehicleEvents persistence with persist_events=True
  - 415 on unsupported media type
  - 413 on oversize payload
  - 403 for analyst role (restricted to officer & admin)
  - 404 on nonexistent intersection FK
- POST /vision/analyze-video:
  - 200 on valid video upload with strided evaluation
  - Persists windowed TrafficRecords and heuristic Incidents
  - 415 on wrong content-type
  - 413 on oversize video
  - 403 for analyst role
- GET /vision/signal-observations:
  - 200 for any authenticated role (analyst, officer, admin)
  - Returns paginated items joining Signal and Intersection
  - Filtering by observed_state
  - 401 on unauthenticated access
"""

from datetime import datetime, timezone
import io
from pathlib import Path
import tempfile
import uuid

import cv2
from httpx import ASGITransport, AsyncClient
import numpy as np
import pytest
from sqlalchemy import select

from app.core.database import AsyncSessionLocal, engine
from app.main import create_app
from app.models.event import Incident, VehicleEvent
from app.models.intersection import Intersection
from app.models.road import Lane, Road
from app.models.signal import Signal
from app.models.traffic import TrafficRecord


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def async_client():
    """Async client fixture communicating with test application."""
    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        yield client
    await engine.dispose()


@pytest.fixture
def synthetic_jpeg_bytes() -> bytes:
    """Generate a clean in-memory JPEG image with geometric patterns."""
    canvas = np.full((320, 320, 3), 50, dtype=np.uint8)
    # Draw simulated vehicle shape
    cv2.rectangle(canvas, (60, 60), (140, 160), (0, 200, 0), -1)
    # Draw simulated traffic light box
    cv2.rectangle(canvas, (200, 40), (240, 120), (30, 30, 30), -1)
    cv2.circle(canvas, (220, 60), 12, (0, 0, 255), -1)  # Red light
    success, encoded = cv2.imencode(".jpg", canvas)
    assert success, "Failed to encode synthetic JPEG"
    return encoded.tobytes()


@pytest.fixture
def synthetic_mp4_bytes() -> bytes:
    """Generate a valid in-memory MP4 video file with moving shapes."""
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
        tmp_path = Path(tmp.name)

    try:
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        writer = cv2.VideoWriter(str(tmp_path), fourcc, 10.0, (160, 120))
        for i in range(12):
            canvas = np.full((120, 160, 3), 40, dtype=np.uint8)
            x = int(20 + i * 8)
            cv2.rectangle(canvas, (x, 40), (x + 30, 70), (0, 220, 0), -1)
            writer.write(canvas)
        writer.release()

        with open(tmp_path, "rb") as f:
            data = f.read()
        return data
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


@pytest.fixture
async def test_infrastructure(async_client: AsyncClient, test_users: dict):
    """Fixture creating test intersection, road, lane, and signal."""
    uid = uuid.uuid4().hex[:6]
    admin_headers = {"Authorization": f"Bearer {test_users['admin']['token']}"}

    # 1. Intersection
    junc_resp = await async_client.post(
        "/api/v1/junctions",
        headers=admin_headers,
        json={
            "name": f"Vision Test Junction {uid}",
            "code": f"VTJ-{uid.upper()}",
            "status": "active",
            "city": "Metro",
            "zone": "Central",
            "lat": 37.7749,
            "lon": -122.4194,
        },
    )
    assert junc_resp.status_code == 201, junc_resp.text
    junction = junc_resp.json()

    # 2. Road
    road_resp = await async_client.post(
        "/api/v1/roads",
        headers=admin_headers,
        json={
            "name": f"Vision Test Road {uid}",
            "road_type": "arterial",
            "speed_limit_kmh": 50,
        },
    )
    assert road_resp.status_code == 201, road_resp.text
    road = road_resp.json()

    # 3. Lane
    lane_resp = await async_client.post(
        "/api/v1/lanes",
        headers=admin_headers,
        json={
            "road_id": road["id"],
            "intersection_id": junction["id"],
            "lane_number": 1,
            "direction": "northbound",
            "lane_type": "through",
        },
    )
    assert lane_resp.status_code == 201, lane_resp.text
    lane = lane_resp.json()

    # 4. Signal
    sig_resp = await async_client.post(
        "/api/v1/signals",
        headers=admin_headers,
        json={
            "intersection_id": junction["id"],
            "code": f"SIG-VT-{uid.upper()}",
            "status": "active",
        },
    )
    assert sig_resp.status_code == 201, sig_resp.text
    signal = sig_resp.json()

    return {
        "intersection": junction,
        "road": road,
        "lane": lane,
        "signal": signal,
    }


# ==============================================================================
# POST /vision/analyze-image Tests
# ==============================================================================


@pytest.mark.anyio
async def test_analyze_image_valid_upload_persists_traffic_record(
    async_client: AsyncClient,
    test_users: dict,
    test_infrastructure: dict,
    synthetic_jpeg_bytes: bytes,
):
    """Verify valid image upload returns structured metrics and creates TrafficRecord in DB."""
    officer_headers = {"Authorization": f"Bearer {test_users['officer']['token']}"}
    intersection_id = test_infrastructure["intersection"]["id"]
    lane_id = test_infrastructure["lane"]["id"]

    files = {"file": ("traffic_sample.jpg", synthetic_jpeg_bytes, "image/jpeg")}
    data = {
        "intersection_id": str(intersection_id),
        "lane_id": str(lane_id),
    }

    resp = await async_client.post(
        "/api/v1/vision/analyze-image",
        headers=officer_headers,
        files=files,
        data=data,
    )
    assert resp.status_code == 200, resp.text
    payload = resp.json()

    # Verify structured perception response fields
    assert "vehicle_count" in payload
    assert "traffic_density" in payload
    assert "density_per_100k_px" in payload
    assert "congestion_level" in payload
    assert 0 <= payload["congestion_level"] <= 100
    assert payload["congestion_status"] in ("free_flow", "moderate", "heavy", "severe")
    assert isinstance(payload["detections"], list)
    assert isinstance(payload["signal_observations"], list)
    assert payload["traffic_record_id"] is not None

    # Verify real database row was created
    async with AsyncSessionLocal() as session:
        tr = await session.get(TrafficRecord, payload["traffic_record_id"])
        assert tr is not None
        assert tr.intersection_id == intersection_id
        assert tr.lane_id == lane_id
        assert tr.source == "camera"
        assert tr.congestion_level == payload["congestion_level"]
        assert tr.vehicle_count == payload["vehicle_count"]


@pytest.mark.anyio
async def test_analyze_image_with_persist_events(
    async_client: AsyncClient,
    test_users: dict,
    test_infrastructure: dict,
    synthetic_jpeg_bytes: bytes,
):
    """Verify persist_events=True persists VehicleEvents to DB."""
    officer_headers = {"Authorization": f"Bearer {test_users['officer']['token']}"}
    intersection_id = test_infrastructure["intersection"]["id"]

    files = {"file": ("traffic.jpg", synthetic_jpeg_bytes, "image/jpeg")}
    data = {
        "intersection_id": str(intersection_id),
        "persist_events": "true",
    }

    resp = await async_client.post(
        "/api/v1/vision/analyze-image",
        headers=officer_headers,
        files=files,
        data=data,
    )
    assert resp.status_code == 200, resp.text
    payload = resp.json()

    assert payload["events_persisted"] == len(payload["detections"])
    if payload["events_persisted"] > 0:
        async with AsyncSessionLocal() as session:
            events_stmt = select(VehicleEvent).where(VehicleEvent.intersection_id == intersection_id)
            res = await session.execute(events_stmt)
            events = res.scalars().all()
            assert len(events) >= payload["events_persisted"]


@pytest.mark.anyio
async def test_analyze_image_wrong_content_type_returns_415(
    async_client: AsyncClient,
    test_users: dict,
    test_infrastructure: dict,
):
    """Verify non-image content-type is rejected with explicit HTTP 415."""
    officer_headers = {"Authorization": f"Bearer {test_users['officer']['token']}"}

    files = {"file": ("document.txt", b"plain text data", "text/plain")}
    resp = await async_client.post(
        "/api/v1/vision/analyze-image",
        headers=officer_headers,
        files=files,
    )
    assert resp.status_code == 415
    assert "Unsupported media type" in resp.json()["detail"]


@pytest.mark.anyio
async def test_analyze_image_oversize_returns_413(
    async_client: AsyncClient,
    test_users: dict,
    test_infrastructure: dict,
    synthetic_jpeg_bytes: bytes,
    monkeypatch,
):
    """Verify uploaded image exceeding size limit is rejected with explicit HTTP 413."""
    officer_headers = {"Authorization": f"Bearer {test_users['officer']['token']}"}

    # Monkeypatch MAX_IMAGE_SIZE_BYTES to a tiny limit (20 bytes)
    monkeypatch.setattr("app.api.v1.vision.MAX_IMAGE_SIZE_BYTES", 20)

    files = {"file": ("large_image.jpg", synthetic_jpeg_bytes, "image/jpeg")}
    resp = await async_client.post(
        "/api/v1/vision/analyze-image",
        headers=officer_headers,
        files=files,
    )
    assert resp.status_code == 413
    assert "exceeds maximum allowable limit" in resp.json()["detail"]


@pytest.mark.anyio
async def test_analyze_image_analyst_role_forbidden_403(
    async_client: AsyncClient,
    test_users: dict,
    synthetic_jpeg_bytes: bytes,
):
    """Verify analyst role is forbidden from triggering vision inference (HTTP 403)."""
    analyst_headers = {"Authorization": f"Bearer {test_users['analyst']['token']}"}

    files = {"file": ("traffic.jpg", synthetic_jpeg_bytes, "image/jpeg")}
    resp = await async_client.post(
        "/api/v1/vision/analyze-image",
        headers=analyst_headers,
        files=files,
    )
    assert resp.status_code == 403


@pytest.mark.anyio
async def test_analyze_image_nonexistent_intersection_404(
    async_client: AsyncClient,
    test_users: dict,
    synthetic_jpeg_bytes: bytes,
):
    """Verify 404 is returned when specified intersection_id does not exist."""
    officer_headers = {"Authorization": f"Bearer {test_users['officer']['token']}"}

    files = {"file": ("traffic.jpg", synthetic_jpeg_bytes, "image/jpeg")}
    data = {"intersection_id": "999999"}
    resp = await async_client.post(
        "/api/v1/vision/analyze-image",
        headers=officer_headers,
        files=files,
        data=data,
    )
    assert resp.status_code == 404


# ==============================================================================
# POST /vision/analyze-video Tests
# ==============================================================================


@pytest.mark.anyio
async def test_analyze_video_valid_upload_persists_traffic_records(
    async_client: AsyncClient,
    test_users: dict,
    test_infrastructure: dict,
    synthetic_mp4_bytes: bytes,
):
    """Verify valid video upload processes frames and creates windowed TrafficRecords."""
    officer_headers = {"Authorization": f"Bearer {test_users['officer']['token']}"}
    intersection_id = test_infrastructure["intersection"]["id"]
    lane_id = test_infrastructure["lane"]["id"]

    files = {"file": ("traffic_stream.mp4", synthetic_mp4_bytes, "video/mp4")}
    data = {
        "intersection_id": str(intersection_id),
        "lane_id": str(lane_id),
        "frame_stride": "2",
    }

    resp = await async_client.post(
        "/api/v1/vision/analyze-video",
        headers=officer_headers,
        files=files,
        data=data,
    )
    assert resp.status_code == 200, resp.text
    payload = resp.json()

    assert payload["frames_processed"] > 0
    assert payload["total_frames_sampled"] > 0
    assert payload["traffic_records_created"] >= 1
    assert "average_congestion_level" in payload
    assert "average_vehicle_count" in payload
    assert "incidents_created" in payload

    # Verify TrafficRecord in DB
    async with AsyncSessionLocal() as session:
        records_stmt = select(TrafficRecord).where(
            TrafficRecord.intersection_id == intersection_id,
            TrafficRecord.source == "camera",
        )
        res = await session.execute(records_stmt)
        records = res.scalars().all()
        assert len(records) >= payload["traffic_records_created"]


@pytest.mark.anyio
async def test_analyze_video_wrong_content_type_returns_415(
    async_client: AsyncClient,
    test_users: dict,
):
    """Verify non-video content-type is rejected with explicit HTTP 415."""
    officer_headers = {"Authorization": f"Bearer {test_users['officer']['token']}"}

    files = {"file": ("data.csv", b"col1,col2\n1,2\n", "text/csv")}
    resp = await async_client.post(
        "/api/v1/vision/analyze-video",
        headers=officer_headers,
        files=files,
    )
    assert resp.status_code == 415
    assert "Unsupported media type" in resp.json()["detail"]


@pytest.mark.anyio
async def test_analyze_video_oversize_returns_413(
    async_client: AsyncClient,
    test_users: dict,
    synthetic_mp4_bytes: bytes,
    monkeypatch,
):
    """Verify video payload exceeding size limit is rejected with HTTP 413."""
    officer_headers = {"Authorization": f"Bearer {test_users['officer']['token']}"}

    monkeypatch.setattr("app.api.v1.vision.MAX_VIDEO_SIZE_BYTES", 50)

    files = {"file": ("large_video.mp4", synthetic_mp4_bytes, "video/mp4")}
    resp = await async_client.post(
        "/api/v1/vision/analyze-video",
        headers=officer_headers,
        files=files,
    )
    assert resp.status_code == 413
    assert "exceeds maximum allowable limit" in resp.json()["detail"]


@pytest.mark.anyio
async def test_analyze_video_analyst_role_forbidden_403(
    async_client: AsyncClient,
    test_users: dict,
    synthetic_mp4_bytes: bytes,
):
    """Verify analyst role is forbidden from triggering video analysis (HTTP 403)."""
    analyst_headers = {"Authorization": f"Bearer {test_users['analyst']['token']}"}

    files = {"file": ("video.mp4", synthetic_mp4_bytes, "video/mp4")}
    resp = await async_client.post(
        "/api/v1/vision/analyze-video",
        headers=analyst_headers,
        files=files,
    )
    assert resp.status_code == 403


# ==============================================================================
# GET /vision/signal-observations Tests
# ==============================================================================


@pytest.mark.anyio
async def test_signal_observations_endpoint_and_pagination(
    async_client: AsyncClient,
    test_users: dict,
    test_infrastructure: dict,
):
    """Verify signal observations endpoint returns rows, joins Intersection, and paginates."""
    intersection_id = test_infrastructure["intersection"]["id"]
    signal_id = test_infrastructure["signal"]["id"]

    # 1. Update signal directly in DB with camera observation
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as session:
        sig = await session.get(Signal, signal_id)
        assert sig is not None
        sig.observed_state = "green"
        sig.observed_confidence = 0.94
        sig.observed_at = now
        await session.commit()

    # 2. Query as analyst user (allowed for any authenticated user)
    analyst_headers = {"Authorization": f"Bearer {test_users['analyst']['token']}"}
    resp = await async_client.get(
        "/api/v1/vision/signal-observations",
        headers=analyst_headers,
    )
    assert resp.status_code == 200, resp.text
    payload = resp.json()

    assert payload["total"] >= 1
    assert payload["page"] == 1
    assert "items" in payload

    # Find the observed signal in the items
    matched = [item for item in payload["items"] if item["signal_id"] == signal_id]
    assert len(matched) == 1
    obs_item = matched[0]
    assert obs_item["observed_state"] == "green"
    assert obs_item["observed_confidence"] == pytest.approx(0.94, abs=0.01)
    assert obs_item["intersection_id"] == intersection_id
    assert obs_item["intersection_code"] == test_infrastructure["intersection"]["code"]

    # 3. Filter by observed_state
    filter_green = await async_client.get(
        "/api/v1/vision/signal-observations?observed_state=green",
        headers=analyst_headers,
    )
    assert filter_green.status_code == 200
    assert any(it["signal_id"] == signal_id for it in filter_green.json()["items"])

    filter_red = await async_client.get(
        "/api/v1/vision/signal-observations?observed_state=red",
        headers=analyst_headers,
    )
    assert filter_red.status_code == 200
    assert not any(it["signal_id"] == signal_id for it in filter_red.json()["items"])


@pytest.mark.anyio
async def test_signal_observations_unauthenticated_401(
    async_client: AsyncClient,
):
    """Verify signal observations endpoint requires authentication (HTTP 401)."""
    resp = await async_client.get("/api/v1/vision/signal-observations")
    assert resp.status_code == 401
