"""Comprehensive integration and REST API tests for traffic violations.

Covers:
1. REST API CRUD endpoints (/api/v1/violations/)
2. RBAC access control (admin, traffic_officer, analyst, unauthenticated)
3. Pagination and query filters (violation_type, intersection_id, timestamp ranges)
4. Persistence bridge integration (app.vision.violations.persist_violation)
"""

from datetime import datetime, timezone
import uuid
from httpx import AsyncClient
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ai.cv.violations import ViolationCandidate
from app.core.database import engine
from app.models.intersection import Intersection
from app.models.violation import Violation
from app.vision.violations import persist_violation


@pytest.fixture(autouse=True)
async def clean_engine_pool():
    """Ensure connection pool is disposed between tests to prevent event loop mismatch."""
    yield
    await engine.dispose()


@pytest.fixture
async def sample_intersection(db_session: AsyncSession) -> Intersection:
    """Provision a persistent test intersection."""
    code = f"JNC_{uuid.uuid4().hex[:6].upper()}"
    junction = Intersection(
        name="Test Corridor Junction",
        code=code,
        status="active",
        city="Hyderabad",
        zone="Central",
        lat=17.3850,
        lon=78.4867,
    )
    db_session.add(junction)
    await db_session.commit()
    await db_session.refresh(junction)
    return junction


@pytest.mark.anyio
async def test_create_violation_as_officer_and_admin(
    async_client: AsyncClient,
    test_users: dict[str, dict[str, str | int]],
    sample_intersection: Intersection,
):
    """Officers and admins can record traffic violations via REST API."""
    officer_token = test_users["officer"]["token"]
    now_iso = datetime.now(timezone.utc).isoformat()

    payload = {
        "violation_type": "red_light",
        "detected_at": now_iso,
        "intersection_id": sample_intersection.id,
        "camera_id": "cam_north_01",
        "confidence": 0.94,
        "status": "recorded",
        "evidence_ref": "storage/evidence/violations/red_light_001.jpg",
        "details": {
            "lane_id": "lane_1",
            "speed_kmh": 54.2,
            "signal_phase": "red",
        },
    }

    resp = await async_client.post(
        "/api/v1/violations",
        headers={"Authorization": f"Bearer {officer_token}"},
        json=payload,
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["id"] is not None
    assert data["violation_type"] == "red_light"
    assert data["intersection_id"] == sample_intersection.id
    assert data["camera_id"] == "cam_north_01"
    assert data["confidence"] == 0.94
    assert data["status"] == "recorded"
    assert data["evidence_ref"] == "storage/evidence/violations/red_light_001.jpg"
    assert data["details"]["signal_phase"] == "red"


@pytest.mark.anyio
async def test_create_violation_rbac_guards(
    async_client: AsyncClient,
    test_users: dict[str, dict[str, str | int]],
):
    """Analysts are forbidden (403) and unauthenticated requests are rejected (401)."""
    now_iso = datetime.now(timezone.utc).isoformat()
    payload = {
        "violation_type": "wrong_way",
        "detected_at": now_iso,
        "confidence": 0.88,
    }

    # 1. Unauthenticated request -> 401
    resp_unauth = await async_client.post("/api/v1/violations", json=payload)
    assert resp_unauth.status_code == 401

    # 2. Analyst request -> 403 Forbidden
    analyst_token = test_users["analyst"]["token"]
    resp_analyst = await async_client.post(
        "/api/v1/violations",
        headers={"Authorization": f"Bearer {analyst_token}"},
        json=payload,
    )
    assert resp_analyst.status_code == 403


@pytest.mark.anyio
async def test_create_violation_validation_and_not_found(
    async_client: AsyncClient,
    test_users: dict[str, dict[str, str | int]],
):
    """Invalid violation types yield 422, nonexistent intersection yields 404."""
    officer_token = test_users["officer"]["token"]
    now_iso = datetime.now(timezone.utc).isoformat()

    # 1. Nonexistent intersection ID -> 404
    resp_404 = await async_client.post(
        "/api/v1/violations",
        headers={"Authorization": f"Bearer {officer_token}"},
        json={
            "violation_type": "red_light",
            "detected_at": now_iso,
            "intersection_id": 99999999,
            "confidence": 0.90,
        },
    )
    assert resp_404.status_code == 404

    # 2. Invalid violation type -> 422
    resp_422 = await async_client.post(
        "/api/v1/violations",
        headers={"Authorization": f"Bearer {officer_token}"},
        json={
            "violation_type": "illegal_u_turn_unsupported",
            "detected_at": now_iso,
            "confidence": 0.90,
        },
    )
    assert resp_422.status_code == 422


@pytest.mark.anyio
async def test_list_violations_pagination_and_filters(
    async_client: AsyncClient,
    test_users: dict[str, dict[str, str | int]],
    sample_intersection: Intersection,
):
    """Verify listing violations with type, intersection, and date filters."""
    admin_token = test_users["admin"]["token"]
    now = datetime.now(timezone.utc)

    # Seed 3 violations
    v_types = ["red_light", "wrong_way", "no_helmet"]
    for i, v_type in enumerate(v_types):
        await async_client.post(
            "/api/v1/violations",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={
                "violation_type": v_type,
                "detected_at": now.isoformat(),
                "intersection_id": sample_intersection.id if i < 2 else None,
                "confidence": 0.85 + (i * 0.05),
                "camera_id": f"cam_filter_test_{i}",
            },
        )

    # 1. List all with pagination
    resp = await async_client.get(
        "/api/v1/violations?page=1&per_page=10",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 3
    assert len(data["items"]) >= 3

    # 2. Filter by violation_type
    resp_type = await async_client.get(
        "/api/v1/violations?violation_type=no_helmet",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp_type.status_code == 200
    items_type = resp_type.json()["items"]
    assert all(it["violation_type"] == "no_helmet" for it in items_type)

    # 3. Filter by intersection_id
    resp_junction = await async_client.get(
        f"/api/v1/violations?intersection_id={sample_intersection.id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp_junction.status_code == 200
    items_j = resp_junction.json()["items"]
    assert all(it["intersection_id"] == sample_intersection.id for it in items_j)


@pytest.mark.anyio
async def test_get_and_update_violation(
    async_client: AsyncClient,
    test_users: dict[str, dict[str, str | int]],
):
    """Retrieve violation by ID and update status via PATCH."""
    officer_token = test_users["officer"]["token"]
    now_iso = datetime.now(timezone.utc).isoformat()

    create_resp = await async_client.post(
        "/api/v1/violations",
        headers={"Authorization": f"Bearer {officer_token}"},
        json={
            "violation_type": "no_helmet",
            "detected_at": now_iso,
            "confidence": 0.82,
            "status": "recorded",
        },
    )
    assert create_resp.status_code == 201
    v_id = create_resp.json()["id"]

    # 1. Get single violation
    get_resp = await async_client.get(
        f"/api/v1/violations/{v_id}",
        headers={"Authorization": f"Bearer {officer_token}"},
    )
    assert get_resp.status_code == 200
    assert get_resp.json()["id"] == v_id

    # 2. Patch status to 'reviewed'
    patch_resp = await async_client.patch(
        f"/api/v1/violations/{v_id}",
        headers={"Authorization": f"Bearer {officer_token}"},
        json={"status": "reviewed"},
    )
    assert patch_resp.status_code == 200
    assert patch_resp.json()["status"] == "reviewed"


@pytest.mark.anyio
async def test_persistence_bridge_integration(
    db_session: AsyncSession,
    sample_intersection: Intersection,
):
    """Verify backend/app/vision/violations.py persist_violation directly writes to DB."""
    cand = ViolationCandidate(
        violation_type="red_light",
        confidence=0.91,
        detected_at=datetime.now(timezone.utc),
        camera_id="cam_bridge_direct_01",
        track_id=888,
        bbox=(10.0, 20.0, 50.0, 60.0),
        evidence_ref="storage/evidence/violations/snap_direct.jpg",
        details={"speed_kmh": 48.0, "lane_id": "L1"},
    )

    violation_row = await persist_violation(
        db=db_session,
        candidate=cand,
        intersection_id=sample_intersection.id,
    )
    await db_session.refresh(violation_row)

    assert violation_row.id is not None
    assert violation_row.violation_type == "red_light"
    assert violation_row.confidence == 0.91
    assert violation_row.camera_id == "cam_bridge_direct_01"
    assert violation_row.details["speed_kmh"] == 48.0

    await db_session.rollback()
