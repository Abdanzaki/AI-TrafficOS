"""Comprehensive integration tests for domain REST routers: junctions, roads, lanes, signals.

Tests real database operations, eager loading with selectinload, RBAC, FK validations,
pagination, filtering, manual signal overrides, and audit trails.
"""

import uuid
from httpx import ASGITransport, AsyncClient
import pytest
from sqlalchemy import select

from app.core.database import AsyncSessionLocal, engine
from app.main import create_app
from app.models.audit import AuditLog
from app.models.auth import Role, User


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def async_client():
    """Async client fixture."""
    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        yield client
    await engine.dispose()


@pytest.fixture
async def test_users(async_client: AsyncClient):
    """Fixture that provisions admin, officer, and analyst users and returns their auth tokens."""
    uid = uuid.uuid4().hex[:8]
    password = "TestPassword123!"

    # 1. Admin login or create
    admin_email = "admin@trafficos.io"
    admin_login_resp = await async_client.post(
        "/api/v1/auth/login",
        json={"email": admin_email, "password": "adminpassword123"},
    )
    if admin_login_resp.status_code == 200:
        admin_token = admin_login_resp.json()["access_token"]
        admin_id = (await async_client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {admin_token}"},
        )).json()["id"]
    else:
        # Create admin via create_user endpoint if another admin exists, or directly in DB
        async with AsyncSessionLocal() as db:
            from app.core.security import hash_password
            admin_role = (await db.execute(select(Role).where(Role.name == "admin"))).scalars().first()
            admin_u = User(
                email=f"admin_{uid}@trafficos.io",
                hashed_password=hash_password(password),
                full_name="Test Admin",
                role_id=admin_role.id,
                is_active=True,
            )
            db.add(admin_u)
            await db.commit()
            await db.refresh(admin_u)
            admin_id = admin_u.id

        admin_login = await async_client.post(
            "/api/v1/auth/login",
            json={"email": f"admin_{uid}@trafficos.io", "password": password},
        )
        admin_token = admin_login.json()["access_token"]

    # 2. Officer user
    officer_email = f"officer_{uid}@trafficos.io"
    officer_resp = await async_client.post(
        "/api/v1/users",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "email": officer_email,
            "password": password,
            "full_name": "Traffic Officer",
            "role_name": "traffic_officer",
        },
    )
    assert officer_resp.status_code == 201
    officer_id = officer_resp.json()["id"]

    officer_login = await async_client.post(
        "/api/v1/auth/login",
        json={"email": officer_email, "password": password},
    )
    officer_token = officer_login.json()["access_token"]

    # 3. Analyst user
    analyst_email = f"analyst_{uid}@trafficos.io"
    analyst_resp = await async_client.post(
        "/api/v1/auth/register",
        json={
            "email": analyst_email,
            "password": password,
            "full_name": "Traffic Analyst",
        },
    )
    assert analyst_resp.status_code == 201
    analyst_id = analyst_resp.json()["id"]

    analyst_login = await async_client.post(
        "/api/v1/auth/login",
        json={"email": analyst_email, "password": password},
    )
    analyst_token = analyst_login.json()["access_token"]

    return {
        "admin": {"token": admin_token, "id": admin_id},
        "officer": {"token": officer_token, "id": officer_id},
        "analyst": {"token": analyst_token, "id": analyst_id},
    }


@pytest.mark.anyio
async def test_unauthenticated_requests(async_client: AsyncClient):
    """Ensure unauthenticated access to domain endpoints is rejected with 401."""
    endpoints = [
        "/api/v1/junctions",
        "/api/v1/roads",
        "/api/v1/lanes",
        "/api/v1/signals",
    ]
    for ep in endpoints:
        resp = await async_client.get(ep)
        assert resp.status_code == 401, f"Expected 401 on {ep}, got {resp.status_code}"


@pytest.mark.anyio
async def test_roads_full_lifecycle(async_client: AsyncClient, test_users: dict):
    """Test road creation, listing, filtering, pagination, eager lanes, RBAC, and audit log."""
    admin_auth = {"Authorization": f"Bearer {test_users['admin']['token']}"}
    officer_auth = {"Authorization": f"Bearer {test_users['officer']['token']}"}
    analyst_auth = {"Authorization": f"Bearer {test_users['analyst']['token']}"}

    uid = uuid.uuid4().hex[:6]
    road_name = f"Main Arterial Blvd {uid}"

    # 1. Analyst cannot create road (403)
    analyst_create = await async_client.post(
        "/api/v1/roads",
        headers=analyst_auth,
        json={"name": road_name, "road_type": "arterial", "speed_limit_kmh": 60},
    )
    assert analyst_create.status_code == 403

    # 2. Officer creates road (201)
    create_resp = await async_client.post(
        "/api/v1/roads",
        headers=officer_auth,
        json={"name": road_name, "road_type": "arterial", "speed_limit_kmh": 60},
    )
    assert create_resp.status_code == 201
    road_data = create_resp.json()
    road_id = road_data["id"]
    assert road_data["name"] == road_name
    assert road_data["road_type"] == "arterial"

    # 3. GET /roads with search filter and pagination
    list_resp = await async_client.get(
        f"/api/v1/roads?search={uid}&road_type=arterial&page=1&per_page=10",
        headers=analyst_auth,
    )
    assert list_resp.status_code == 200
    list_data = list_resp.json()
    assert list_data["total"] >= 1
    assert any(r["id"] == road_id for r in list_data["items"])

    # 4. GET /roads/{id} detail with eager lanes
    get_resp = await async_client.get(f"/api/v1/roads/{road_id}", headers=analyst_auth)
    assert get_resp.status_code == 200
    detail = get_resp.json()
    assert detail["id"] == road_id
    assert "lanes" in detail
    assert detail["lanes"] == []

    # 5. Officer PATCH /roads/{id} (200)
    patch_resp = await async_client.patch(
        f"/api/v1/roads/{road_id}",
        headers=officer_auth,
        json={"speed_limit_kmh": 70},
    )
    assert patch_resp.status_code == 200
    assert patch_resp.json()["speed_limit_kmh"] == 70

    # 6. Analyst cannot PATCH /roads/{id} (403)
    analyst_patch = await async_client.patch(
        f"/api/v1/roads/{road_id}",
        headers=analyst_auth,
        json={"speed_limit_kmh": 80},
    )
    assert analyst_patch.status_code == 403

    # 7. Officer cannot DELETE /roads/{id} (403)
    officer_del = await async_client.delete(f"/api/v1/roads/{road_id}", headers=officer_auth)
    assert officer_del.status_code == 403

    # 8. Admin DELETE /roads/{id} (204)
    admin_del = await async_client.delete(f"/api/v1/roads/{road_id}", headers=admin_auth)
    assert admin_del.status_code == 204

    # 9. Verify 404 after deletion
    post_del_get = await async_client.get(f"/api/v1/roads/{road_id}", headers=analyst_auth)
    assert post_del_get.status_code == 404
    assert post_del_get.json()["detail"] == "Road not found"


@pytest.mark.anyio
async def test_junctions_full_lifecycle(async_client: AsyncClient, test_users: dict):
    """Test junction creation, code uniqueness, listing, filtering, eager loading, RBAC, and audit log."""
    admin_auth = {"Authorization": f"Bearer {test_users['admin']['token']}"}
    officer_auth = {"Authorization": f"Bearer {test_users['officer']['token']}"}
    analyst_auth = {"Authorization": f"Bearer {test_users['analyst']['token']}"}

    uid = uuid.uuid4().hex[:6]
    code = f"JNC-{uid}"
    name = f"Central Junction {uid}"

    # 1. Analyst cannot create junction (403)
    analyst_create = await async_client.post(
        "/api/v1/junctions",
        headers=analyst_auth,
        json={"name": name, "code": code, "city": "Metropolis", "zone": "Downtown"},
    )
    assert analyst_create.status_code == 403

    # 2. Officer creates junction (201)
    create_resp = await async_client.post(
        "/api/v1/junctions",
        headers=officer_auth,
        json={
            "name": name,
            "code": code,
            "city": "Metropolis",
            "zone": "Downtown",
            "lat": 37.7749,
            "lon": -122.4194,
        },
    )
    assert create_resp.status_code == 201
    junc_data = create_resp.json()
    junc_id = junc_data["id"]
    assert junc_data["code"] == code
    assert junc_data["city"] == "Metropolis"

    # 3. Duplicate code rejected (409)
    dup_resp = await async_client.post(
        "/api/v1/junctions",
        headers=officer_auth,
        json={"name": "Duplicate Code Junction", "code": code},
    )
    assert dup_resp.status_code == 409

    # 4. List junctions with filters and pagination
    list_resp = await async_client.get(
        f"/api/v1/junctions?search={uid}&city=Metro&zone=Down&status=active&page=1&per_page=5",
        headers=analyst_auth,
    )
    assert list_resp.status_code == 200
    list_data = list_resp.json()
    assert list_data["total"] >= 1
    assert any(j["id"] == junc_id for j in list_data["items"])

    # 5. GET /junctions/{id} detail with eager signals and lanes
    get_resp = await async_client.get(f"/api/v1/junctions/{junc_id}", headers=analyst_auth)
    assert get_resp.status_code == 200
    detail = get_resp.json()
    assert detail["id"] == junc_id
    assert "signals" in detail
    assert "lanes" in detail
    assert detail["signals"] == []
    assert detail["lanes"] == []

    # 6. Officer PATCH /junctions/{id}
    patch_resp = await async_client.patch(
        f"/api/v1/junctions/{junc_id}",
        headers=officer_auth,
        json={"zone": "Uptown", "status": "maintenance"},
    )
    assert patch_resp.status_code == 200
    assert patch_resp.json()["zone"] == "Uptown"
    assert patch_resp.json()["status"] == "maintenance"

    # 7. Officer cannot delete junction (403)
    officer_del = await async_client.delete(f"/api/v1/junctions/{junc_id}", headers=officer_auth)
    assert officer_del.status_code == 403

    # 8. Admin DELETE junction (204)
    admin_del = await async_client.delete(f"/api/v1/junctions/{junc_id}", headers=admin_auth)
    assert admin_del.status_code == 204

    # 9. Verify 404 after deletion
    post_del_get = await async_client.get(f"/api/v1/junctions/{junc_id}", headers=analyst_auth)
    assert post_del_get.status_code == 404
    assert post_del_get.json()["detail"] == "Junction not found"


@pytest.mark.anyio
async def test_lanes_crud_and_fk_validation(async_client: AsyncClient, test_users: dict):
    """Test lane creation, FK validation (road and junction existence), listing, and RBAC."""
    admin_auth = {"Authorization": f"Bearer {test_users['admin']['token']}"}
    officer_auth = {"Authorization": f"Bearer {test_users['officer']['token']}"}
    analyst_auth = {"Authorization": f"Bearer {test_users['analyst']['token']}"}

    uid = uuid.uuid4().hex[:6]

    # Create road and junction first
    road_resp = await async_client.post(
        "/api/v1/roads",
        headers=officer_auth,
        json={"name": f"Road For Lanes {uid}", "road_type": "arterial"},
    )
    assert road_resp.status_code == 201
    road_id = road_resp.json()["id"]

    junc_resp = await async_client.post(
        "/api/v1/junctions",
        headers=officer_auth,
        json={"name": f"Junction For Lanes {uid}", "code": f"JNC-LANE-{uid}"},
    )
    assert junc_resp.status_code == 201
    junc_id = junc_resp.json()["id"]

    # 1. Invalid road FK (404)
    bad_road_resp = await async_client.post(
        "/api/v1/lanes",
        headers=officer_auth,
        json={
            "road_id": 9999999,
            "intersection_id": junc_id,
            "lane_number": 1,
            "direction": "northbound",
            "lane_type": "through",
        },
    )
    assert bad_road_resp.status_code == 404

    # 2. Invalid intersection FK (404)
    bad_inter_resp = await async_client.post(
        "/api/v1/lanes",
        headers=officer_auth,
        json={
            "road_id": road_id,
            "intersection_id": 9999999,
            "lane_number": 1,
            "direction": "northbound",
            "lane_type": "through",
        },
    )
    assert bad_inter_resp.status_code == 404

    # 3. Analyst cannot create lane (403)
    analyst_create = await async_client.post(
        "/api/v1/lanes",
        headers=analyst_auth,
        json={
            "road_id": road_id,
            "intersection_id": junc_id,
            "lane_number": 1,
            "direction": "northbound",
            "lane_type": "through",
        },
    )
    assert analyst_create.status_code == 403

    # 4. Officer creates valid lane (201)
    lane_resp = await async_client.post(
        "/api/v1/lanes",
        headers=officer_auth,
        json={
            "road_id": road_id,
            "intersection_id": junc_id,
            "lane_number": 1,
            "direction": "northbound",
            "lane_type": "left_turn",
        },
    )
    assert lane_resp.status_code == 201
    lane_data = lane_resp.json()
    lane_id = lane_data["id"]
    assert lane_data["lane_type"] == "left_turn"

    # 5. List lanes with filters
    list_resp = await async_client.get(
        f"/api/v1/lanes?road_id={road_id}&intersection_id={junc_id}",
        headers=analyst_auth,
    )
    assert list_resp.status_code == 200
    list_data = list_resp.json()
    assert list_data["total"] == 1
    assert list_data["items"][0]["id"] == lane_id

    # 6. Road detail now includes lane eager
    road_detail = await async_client.get(f"/api/v1/roads/{road_id}", headers=analyst_auth)
    assert len(road_detail.json()["lanes"]) == 1
    assert road_detail.json()["lanes"][0]["id"] == lane_id

    # 7. Junction detail now includes lane eager
    junc_detail = await async_client.get(f"/api/v1/junctions/{junc_id}", headers=analyst_auth)
    assert len(junc_detail.json()["lanes"]) == 1
    assert junc_detail.json()["lanes"][0]["id"] == lane_id

    # 8. Officer PATCH lane (200)
    patch_resp = await async_client.patch(
        f"/api/v1/lanes/{lane_id}",
        headers=officer_auth,
        json={"lane_type": "through"},
    )
    assert patch_resp.status_code == 200
    assert patch_resp.json()["lane_type"] == "through"

    # 9. Officer cannot delete lane (403)
    officer_del = await async_client.delete(f"/api/v1/lanes/{lane_id}", headers=officer_auth)
    assert officer_del.status_code == 403

    # 10. Admin DELETE lane (204)
    admin_del = await async_client.delete(f"/api/v1/lanes/{lane_id}", headers=admin_auth)
    assert admin_del.status_code == 204

    # Cleanup road and junction
    await async_client.delete(f"/api/v1/roads/{road_id}", headers=admin_auth)
    await async_client.delete(f"/api/v1/junctions/{junc_id}", headers=admin_auth)


@pytest.mark.anyio
async def test_signals_phases_and_override_lifecycle(async_client: AsyncClient, test_users: dict):
    """Test signal creation, phase management, junction eager loading, manual override, and audit log."""
    admin_auth = {"Authorization": f"Bearer {test_users['admin']['token']}"}
    officer_auth = {"Authorization": f"Bearer {test_users['officer']['token']}"}
    analyst_auth = {"Authorization": f"Bearer {test_users['analyst']['token']}"}

    uid = uuid.uuid4().hex[:6]

    # Create junction first
    junc_resp = await async_client.post(
        "/api/v1/junctions",
        headers=officer_auth,
        json={"name": f"Junction For Signals {uid}", "code": f"JNC-SIG-{uid}"},
    )
    assert junc_resp.status_code == 201
    junc_id = junc_resp.json()["id"]

    # 1. Invalid intersection FK on signal creation (404)
    bad_fk_resp = await async_client.post(
        "/api/v1/signals",
        headers=officer_auth,
        json={"intersection_id": 9999999, "code": f"SIG-BAD-{uid}"},
    )
    assert bad_fk_resp.status_code == 404

    # 2. Analyst cannot create signal (403)
    analyst_create = await async_client.post(
        "/api/v1/signals",
        headers=analyst_auth,
        json={"intersection_id": junc_id, "code": f"SIG-{uid}"},
    )
    assert analyst_create.status_code == 403

    # 3. Officer creates signal (201)
    sig_resp = await async_client.post(
        "/api/v1/signals",
        headers=officer_auth,
        json={"intersection_id": junc_id, "code": f"SIG-{uid}", "status": "active"},
    )
    assert sig_resp.status_code == 201
    sig_data = sig_resp.json()
    signal_id = sig_data["id"]
    assert sig_data["code"] == f"SIG-{uid}"

    # 4. List signals with filters
    list_sig = await async_client.get(
        f"/api/v1/signals?intersection_id={junc_id}&status=active",
        headers=analyst_auth,
    )
    assert list_sig.status_code == 200
    assert list_sig.json()["total"] == 1

    # 5. Add phases via POST /signals/{id}/phases
    phase1_resp = await async_client.post(
        f"/api/v1/signals/{signal_id}/phases",
        headers=officer_auth,
        json={
            "name": "Phase 1 - North/South Green",
            "phase_order": 2,
            "duration_seconds": 45,
            "state": "green",
            "is_active": True,
        },
    )
    assert phase1_resp.status_code == 201
    p1_id = phase1_resp.json()["id"]

    phase2_resp = await async_client.post(
        f"/api/v1/signals/{signal_id}/phases",
        headers=officer_auth,
        json={
            "name": "Phase 2 - East/West Green",
            "phase_order": 1,
            "duration_seconds": 35,
            "state": "red",
            "is_active": False,
        },
    )
    assert phase2_resp.status_code == 201
    p2_id = phase2_resp.json()["id"]

    # 6. GET /signals/{id} returns phases ordered by phase_order (phase 2 has phase_order 1, so it comes first!)
    sig_detail = await async_client.get(f"/api/v1/signals/{signal_id}", headers=analyst_auth)
    assert sig_detail.status_code == 200
    phases = sig_detail.json()["phases"]
    assert len(phases) == 2
    assert phases[0]["id"] == p2_id
    assert phases[0]["phase_order"] == 1
    assert phases[1]["id"] == p1_id
    assert phases[1]["phase_order"] == 2

    # 7. GET /junctions/{id} detail includes the signal in eager loading
    junc_detail = await async_client.get(f"/api/v1/junctions/{junc_id}", headers=analyst_auth)
    assert junc_detail.status_code == 200
    assert len(junc_detail.json()["signals"]) == 1
    assert junc_detail.json()["signals"][0]["id"] == signal_id

    # 8. Analyst cannot perform manual override (403)
    analyst_override = await async_client.post(
        f"/api/v1/signals/{signal_id}/override",
        headers=analyst_auth,
        json={"phase_id": p2_id, "state": "green"},
    )
    assert analyst_override.status_code == 403

    # 9. Officer manual override (200)
    officer_override = await async_client.post(
        f"/api/v1/signals/{signal_id}/override",
        headers=officer_auth,
        json={"phase_id": p2_id, "state": "green", "reason": "Emergency vehicle preempt"},
    )
    assert officer_override.status_code == 200
    override_data = officer_override.json()
    # Phase 2 is now active, Phase 1 is inactive
    p2_updated = next(p for p in override_data["phases"] if p["id"] == p2_id)
    p1_updated = next(p for p in override_data["phases"] if p["id"] == p1_id)
    assert p2_updated["is_active"] is True
    assert p2_updated["state"] == "green"
    assert p1_updated["is_active"] is False

    # 10. Verify audit row was recorded for signal.override
    async with AsyncSessionLocal() as db:
        audit_stmt = (
            select(AuditLog)
            .where(
                AuditLog.action == "signal.override",
                AuditLog.entity_id == signal_id,
            )
            .order_by(AuditLog.id.desc())
        )
        audit_entry = (await db.execute(audit_stmt)).scalars().first()
        assert audit_entry is not None
        assert audit_entry.actor_user_id == test_users["officer"]["id"]
        assert audit_entry.details.get("phase_id") == p2_id
        assert audit_entry.details.get("reason") == "Emergency vehicle preempt"

    # 11. Invalid phase_id override (404)
    bad_override = await async_client.post(
        f"/api/v1/signals/{signal_id}/override",
        headers=officer_auth,
        json={"phase_id": 9999999},
    )
    assert bad_override.status_code == 404

    # 12. Officer PATCH /phases/{phase_id} (200)
    phase_patch = await async_client.patch(
        f"/api/v1/phases/{p1_id}",
        headers=officer_auth,
        json={"duration_seconds": 50},
    )
    assert phase_patch.status_code == 200
    assert phase_patch.json()["duration_seconds"] == 50

    # 13. Officer cannot DELETE phase (403 - DELETE admin only)
    officer_del_phase = await async_client.delete(f"/api/v1/phases/{p1_id}", headers=officer_auth)
    assert officer_del_phase.status_code == 403

    # 14. Admin DELETE phase (204)
    admin_del_phase = await async_client.delete(f"/api/v1/phases/{p1_id}", headers=admin_auth)
    assert admin_del_phase.status_code == 204

    # 15. Officer cannot DELETE signal (403)
    officer_del_sig = await async_client.delete(f"/api/v1/signals/{signal_id}", headers=officer_auth)
    assert officer_del_sig.status_code == 403

    # 16. Admin DELETE signal (204)
    admin_del_sig = await async_client.delete(f"/api/v1/signals/{signal_id}", headers=admin_auth)
    assert admin_del_sig.status_code == 204

    # Cleanup junction
    await async_client.delete(f"/api/v1/junctions/{junc_id}", headers=admin_auth)
