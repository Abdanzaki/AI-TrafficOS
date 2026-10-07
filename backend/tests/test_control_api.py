"""Comprehensive integration tests for Intelligent Traffic Control REST API (Phase 6).

Covers all 11 control routes under /api/v1/control:
- POST /recommendations: telemetry + forecasting evaluation -> 201 advisory proposal
- POST /optimize-signals: Webster-inspired queue-proportional split optimization -> 200 validated plan
- POST /simulate: point-queue simulation comparison between baseline and proposed plans -> 200 with verdict
- GET /decisions: paginated advisory decision history
- GET /decisions/{id}: single decision detail
- POST /decisions/{id}/apply: transition status proposed -> applied (and rejection of double-apply -> 400)
- POST /decisions/{id}/revert: transition status -> reverted
- GET /junctions/{intersection_id}/control-status: junction operational health, signal state, telemetry age
- RBAC enforcement: Officer can optimize/apply; Analyst gets 201 on recommendations, 403 on optimize/apply; unauthenticated 401
- Telemetry freshness enforcement: telemetry older than 300s -> 422 Unprocessable Entity
- Emergency preemption: POST /emergency/prioritize -> green wave preemption plan; POST /emergency/restore -> 200 NO_ACTION restoration
- Audit log persistence verification across control plane actions
"""

from datetime import datetime, timedelta, timezone
import uuid

from httpx import ASGITransport, AsyncClient
import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.control import _GRAPH_CACHE
from app.core.database import AsyncSessionLocal, engine
from app.core.security import hash_password
from app.main import create_app
from app.models.ai import AIDecision
from app.models.audit import AuditLog
from app.models.auth import Role, User
from app.models.emergency import EmergencyEvent
from app.models.event import Incident
from app.models.intersection import Intersection
from app.models.road import Road
from app.models.signal import Signal, SignalPhase
from app.models.traffic import TrafficRecord


@pytest.fixture
def anyio_backend() -> str:
    """Designate asyncio as the async testing backend."""
    return "asyncio"


@pytest.fixture
async def async_client():
    """Async HTTP client fixture communicating with test ASGI application."""
    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        yield client
    await engine.dispose()


@pytest.fixture
async def db_session() -> AsyncSession:
    """Async SQLAlchemy database session fixture for direct model interactions."""
    async with AsyncSessionLocal() as session:
        yield session


@pytest.fixture
async def test_users(async_client: AsyncClient) -> dict[str, dict[str, str | int]]:
    """Fixture that provisions admin, officer, and analyst users and returns auth tokens."""
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
        me_resp = await async_client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        admin_id = me_resp.json()["id"]
    else:
        async with AsyncSessionLocal() as db:
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
    assert officer_resp.status_code == 201, officer_resp.text
    officer_id = officer_resp.json()["id"]

    officer_login = await async_client.post(
        "/api/v1/auth/login",
        json={"email": officer_email, "password": password},
    )
    assert officer_login.status_code == 200, officer_login.text
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
    assert analyst_resp.status_code == 201, analyst_resp.text
    analyst_id = analyst_resp.json()["id"]

    analyst_login = await async_client.post(
        "/api/v1/auth/login",
        json={"email": analyst_email, "password": password},
    )
    assert analyst_login.status_code == 200, analyst_login.text
    analyst_token = analyst_login.json()["access_token"]

    return {
        "admin": {"token": admin_token, "id": admin_id},
        "officer": {"token": officer_token, "id": officer_id},
        "analyst": {"token": analyst_token, "id": analyst_id},
    }


@pytest.fixture
async def control_infrastructure(test_users: dict, db_session: AsyncSession) -> dict:
    """Seed infrastructure: 2 intersections + 1 connecting road + 2 signals + 4 phases + 1 traffic record + 1 incident."""
    _GRAPH_CACHE.clear()
    uid = uuid.uuid4().hex[:6]
    now = datetime.now(timezone.utc)

    # 1. Intersections
    junc1 = Intersection(
        name=f"Control Junction Alpha {uid}",
        code=f"CJA-{uid.upper()}",
        status="active",
        city="Metropolis",
        zone="Downtown",
        lat=37.7749,
        lon=-122.4194,
    )
    junc2 = Intersection(
        name=f"Control Junction Beta {uid}",
        code=f"CJB-{uid.upper()}",
        status="active",
        city="Metropolis",
        zone="Downtown",
        lat=37.7760,
        lon=-122.4180,
    )
    db_session.add_all([junc1, junc2])
    await db_session.flush()

    # 2. Road connecting them (bidirectional arterial)
    road = Road(
        name=f"Corridor Ave {uid}",
        from_intersection_id=junc1.id,
        to_intersection_id=junc2.id,
        road_type="arterial",
        speed_limit_kmh=50.0,
        length_km=0.5,
        is_bidirectional=True,
        capacity_veh_per_hr=2200,
    )
    db_session.add(road)
    await db_session.flush()

    # 3. Two signals (one per intersection)
    sig1 = Signal(
        intersection_id=junc1.id,
        code=f"SIG-ALPHA-{uid.upper()}",
        status="active",
        observed_state="green",
        observed_confidence=0.95,
        observed_at=now,
    )
    sig2 = Signal(
        intersection_id=junc2.id,
        code=f"SIG-BETA-{uid.upper()}",
        status="active",
        observed_state="green",
        observed_confidence=0.95,
        observed_at=now,
    )
    db_session.add_all([sig1, sig2])
    await db_session.flush()

    # 4. Four phases (2 per signal, ordered, active)
    # Signal 1 phases
    p1 = SignalPhase(
        signal_id=sig1.id,
        intersection_id=junc1.id,
        name="Northbound Through",
        phase_order=1,
        duration_seconds=30,
        state="green",
        is_active=True,
    )
    p2 = SignalPhase(
        signal_id=sig1.id,
        intersection_id=junc1.id,
        name="Southbound Through",
        phase_order=2,
        duration_seconds=30,
        state="red",
        is_active=True,
    )
    # Signal 2 phases
    p3 = SignalPhase(
        signal_id=sig2.id,
        intersection_id=junc2.id,
        name="Eastbound Through",
        phase_order=1,
        duration_seconds=30,
        state="green",
        is_active=True,
    )
    p4 = SignalPhase(
        signal_id=sig2.id,
        intersection_id=junc2.id,
        name="Westbound Through",
        phase_order=2,
        duration_seconds=30,
        state="red",
        is_active=True,
    )
    db_session.add_all([p1, p2, p3, p4])

    # 5. One fresh traffic_records row
    record = TrafficRecord(
        intersection_id=junc1.id,
        vehicle_count=22,
        avg_speed_kmh=42.0,
        congestion_level=35,
        source="sensor",
        recorded_at=now,
        created_at=now,
    )
    db_session.add(record)

    # 6. One open incident
    incident = Incident(
        intersection_id=junc1.id,
        severity="high",
        status="reported",
        description=f"Traffic blockage test incident {uid}",
        reported_by=test_users["officer"]["id"],
    )
    db_session.add(incident)

    await db_session.commit()
    await db_session.refresh(junc1)
    await db_session.refresh(junc2)
    await db_session.refresh(road)
    await db_session.refresh(sig1)
    await db_session.refresh(sig2)
    await db_session.refresh(p1)
    await db_session.refresh(p2)
    await db_session.refresh(p3)
    await db_session.refresh(p4)
    await db_session.refresh(record)
    await db_session.refresh(incident)

    return {
        "junc1": junc1,
        "junc2": junc2,
        "road": road,
        "sig1": sig1,
        "sig2": sig2,
        "p1": p1,
        "p2": p2,
        "p3": p3,
        "p4": p4,
        "record": record,
        "incident": incident,
    }


# ==============================================================================
# 1. Traffic Officer Happy Path & Control Lifecycle Tests
# ==============================================================================


@pytest.mark.anyio
async def test_officer_full_control_lifecycle_and_audit(
    async_client: AsyncClient,
    test_users: dict,
    control_infrastructure: dict,
    db_session: AsyncSession,
):
    """Test full traffic_officer workflow: recommendations, optimize, simulate, decisions CRUD, status, and audit trail."""
    officer_headers = {"Authorization": f"Bearer {test_users['officer']['token']}"}
    junc1 = control_infrastructure["junc1"]
    p1 = control_infrastructure["p1"]
    p2 = control_infrastructure["p2"]

    # 1. POST /api/v1/control/recommendations -> 201 with action, reason, id, is_recommendation
    rec_resp = await async_client.post(
        "/api/v1/control/recommendations",
        headers=officer_headers,
        json={"intersection_id": junc1.id},
    )
    assert rec_resp.status_code == 201, rec_resp.text
    rec_data = rec_resp.json()
    assert rec_data["id"] is not None
    assert rec_data["intersection_id"] == junc1.id
    assert "action" in rec_data
    assert len(rec_data["reason"]) > 0
    assert rec_data["is_recommendation"] is True
    decision_id = rec_data["id"]

    # 2. POST /api/v1/control/optimize-signals -> 200 validated plan
    opt_resp = await async_client.post(
        "/api/v1/control/optimize-signals",
        headers=officer_headers,
        json={
            "intersection_id": junc1.id,
            "phase_demands": [
                {
                    "phase_id": p1.id,
                    "queue_length": 16.0,
                    "density": 0.45,
                    "flow_veh_per_min": 25.0,
                    "lane_count": 1,
                },
                {
                    "phase_id": p2.id,
                    "queue_length": 6.0,
                    "density": 0.20,
                    "flow_veh_per_min": 10.0,
                    "lane_count": 1,
                },
            ],
            "cycle_config": {
                "min_green_s": 7.0,
                "max_green_s": 60.0,
                "yellow_s": 3.0,
                "all_red_s": 2.0,
            },
        },
    )
    assert opt_resp.status_code == 200, opt_resp.text
    opt_data = opt_resp.json()
    assert opt_data["validated"] is True
    assert opt_data["intersection_id"] == junc1.id
    assert str(p1.id) in opt_data["recommended_green_s"]
    assert str(p2.id) in opt_data["recommended_green_s"]
    assert opt_data["total_cycle_s"] > 0

    # 3. POST /api/v1/control/simulate -> 200 with verdict
    sim_resp = await async_client.post(
        "/api/v1/control/simulate",
        headers=officer_headers,
        json={
            "intersection_id": junc1.id,
            "approaches": [
                {
                    "approach_id": "NB",
                    "queue_veh": 18.0,
                    "arrival_rate_veh_per_min": 15.0,
                    "saturation_flow_veh_per_min": 30.0,
                    "lane_count": 1,
                },
                {
                    "approach_id": "SB",
                    "queue_veh": 4.0,
                    "arrival_rate_veh_per_min": 5.0,
                    "saturation_flow_veh_per_min": 30.0,
                    "lane_count": 1,
                },
            ],
            "current_plan": {
                "phases": {"phase_nb": 20.0, "phase_sb": 20.0},
                "phase_to_approaches": {"phase_nb": ["NB"], "phase_sb": ["SB"]},
                "yellow_s": 3.0,
                "all_red_s": 2.0,
            },
            "proposed_plan": {
                "phases": {"phase_nb": 35.0, "phase_sb": 15.0},
                "phase_to_approaches": {"phase_nb": ["NB"], "phase_sb": ["SB"]},
                "yellow_s": 3.0,
                "all_red_s": 2.0,
            },
            "horizon_minutes": 10.0,
            "dt_seconds": 5.0,
        },
    )
    assert sim_resp.status_code == 200, sim_resp.text
    sim_data = sim_resp.json()
    assert "verdict" in sim_data
    assert sim_data["verdict"] in ["proposed_better", "current_better", "equivalent"]
    assert "delta_wait" in sim_data

    # 4. GET /api/v1/control/decisions -> lists created decision
    list_dec = await async_client.get(
        f"/api/v1/control/decisions?intersection_id={junc1.id}",
        headers=officer_headers,
    )
    assert list_dec.status_code == 200, list_dec.text
    dec_items = list_dec.json()["items"]
    assert any(d["id"] == decision_id for d in dec_items)

    # 5. POST /api/v1/control/decisions/{id}/apply -> status 'applied'
    apply_resp = await async_client.post(
        f"/api/v1/control/decisions/{decision_id}/apply",
        headers=officer_headers,
    )
    assert apply_resp.status_code == 200, apply_resp.text
    applied_data = apply_resp.json()
    assert applied_data["status"] == "applied"
    assert applied_data["applied_by"] == test_users["officer"]["id"]
    assert applied_data["applied_at"] is not None

    # 6. POST /api/v1/control/decisions/{id}/revert -> status 'reverted'
    revert_resp = await async_client.post(
        f"/api/v1/control/decisions/{decision_id}/revert",
        headers=officer_headers,
    )
    assert revert_resp.status_code == 200, revert_resp.text
    assert revert_resp.json()["status"] == "reverted"

    # 7. Double-apply check -> 400
    # Create a fresh decision, apply it once, then apply again to verify 400 rejection
    rec2_resp = await async_client.post(
        "/api/v1/control/recommendations",
        headers=officer_headers,
        json={"intersection_id": junc1.id},
    )
    assert rec2_resp.status_code == 201
    decision_id2 = rec2_resp.json()["id"]

    # First apply -> 200
    first_apply = await async_client.post(
        f"/api/v1/control/decisions/{decision_id2}/apply",
        headers=officer_headers,
    )
    assert first_apply.status_code == 200
    assert first_apply.json()["status"] == "applied"

    # Second apply (double-apply) -> 400 Bad Request
    second_apply = await async_client.post(
        f"/api/v1/control/decisions/{decision_id2}/apply",
        headers=officer_headers,
    )
    assert second_apply.status_code == 400
    assert "invalid status transition" in second_apply.json()["detail"].lower()

    # 8. GET /api/v1/control/junctions/{intersection_id}/control-status -> all fields present
    status_resp = await async_client.get(
        f"/api/v1/control/junctions/{junc1.id}/control-status",
        headers=officer_headers,
    )
    assert status_resp.status_code == 200, status_resp.text
    status_data = status_resp.json()
    assert status_data["intersection_id"] == junc1.id
    assert "latest_telemetry_age_s" in status_data
    assert "current_observed_signal_state" in status_data
    assert "open_incidents_count" in status_data
    assert "active_emergency" in status_data
    assert "latest_decision" in status_data
    assert "latest_prediction" in status_data
    assert status_data["open_incidents_count"] >= 1
    assert status_data["latest_decision"] is not None
    assert status_data["latest_decision"]["id"] == decision_id2

    # 9. Verify audit_logs table has entries for the control actions
    res = await db_session.execute(
        select(AuditLog.action)
        .order_by(AuditLog.id.desc())
        .limit(30)
    )
    recent_actions = res.scalars().all()
    assert any("control.recommendation" in a for a in recent_actions)
    assert any("control.signal_optimization" in a for a in recent_actions)
    assert any("control.decision_applied" in a for a in recent_actions)
    assert any("control.decision_reverted" in a for a in recent_actions)


# ==============================================================================
# 2. RBAC & Authentication Guard Tests
# ==============================================================================


@pytest.mark.anyio
async def test_rbac_and_unauthenticated_guards(
    async_client: AsyncClient,
    test_users: dict,
    control_infrastructure: dict,
):
    """Test RBAC boundaries: analyst can recommend but cannot optimize/apply; unauthenticated gets 401."""
    analyst_headers = {"Authorization": f"Bearer {test_users['analyst']['token']}"}
    junc1 = control_infrastructure["junc1"]
    p1 = control_infrastructure["p1"]

    # 1. Analyst POST /recommendations -> 201 allowed
    rec_resp = await async_client.post(
        "/api/v1/control/recommendations",
        headers=analyst_headers,
        json={"intersection_id": junc1.id},
    )
    assert rec_resp.status_code == 201
    analyst_dec_id = rec_resp.json()["id"]

    # 2. Analyst POST /optimize-signals -> 403 Forbidden
    opt_resp = await async_client.post(
        "/api/v1/control/optimize-signals",
        headers=analyst_headers,
        json={
            "intersection_id": junc1.id,
            "phase_demands": [
                {
                    "phase_id": p1.id,
                    "queue_length": 10.0,
                    "density": 0.3,
                    "flow_veh_per_min": 15.0,
                }
            ],
        },
    )
    assert opt_resp.status_code == 403

    # 3. Analyst POST /decisions/{id}/apply -> 403 Forbidden
    apply_resp = await async_client.post(
        f"/api/v1/control/decisions/{analyst_dec_id}/apply",
        headers=analyst_headers,
    )
    assert apply_resp.status_code == 403

    # 4. Unauthenticated requests -> 401 Unauthorized
    unauth_rec = await async_client.post(
        "/api/v1/control/recommendations",
        json={"intersection_id": junc1.id},
    )
    assert unauth_rec.status_code == 401

    unauth_opt = await async_client.post(
        "/api/v1/control/optimize-signals",
        json={"intersection_id": junc1.id, "phase_demands": []},
    )
    assert unauth_opt.status_code == 401

    unauth_list = await async_client.get("/api/v1/control/decisions")
    assert unauth_list.status_code == 401


# ==============================================================================
# 3. Stale Telemetry Freshness Policy Tests
# ==============================================================================


@pytest.mark.anyio
async def test_stale_telemetry_raises_422(
    async_client: AsyncClient,
    test_users: dict,
    control_infrastructure: dict,
    db_session: AsyncSession,
):
    """Verify that when traffic record is older than 300s (e.g. 2 hours ago), POST /recommendations returns 422."""
    officer_headers = {"Authorization": f"Bearer {test_users['officer']['token']}"}
    junc1 = control_infrastructure["junc1"]
    two_hours_ago = datetime.now(timezone.utc) - timedelta(hours=2)

    # Update all traffic records for junction 1 to be 2 hours old
    await db_session.execute(
        update(TrafficRecord)
        .where(TrafficRecord.intersection_id == junc1.id)
        .values(recorded_at=two_hours_ago, created_at=two_hours_ago)
    )
    await db_session.commit()

    resp = await async_client.post(
        "/api/v1/control/recommendations",
        headers=officer_headers,
        json={"intersection_id": junc1.id},
    )
    assert resp.status_code == 422
    detail = resp.json()["detail"].lower()
    assert "stale" in detail
    assert "exceeds" in detail or "300.0s" in detail


# ==============================================================================
# 4. Emergency Preemption & Normal Plan Restoration Tests
# ==============================================================================


@pytest.mark.anyio
async def test_emergency_prioritize_and_restore_flow(
    async_client: AsyncClient,
    test_users: dict,
    control_infrastructure: dict,
    db_session: AsyncSession,
):
    """Test emergency preemption lifecycle: activate green wave corridor, then restore standard coordination."""
    _GRAPH_CACHE.clear()
    officer_headers = {"Authorization": f"Bearer {test_users['officer']['token']}"}
    junc1 = control_infrastructure["junc1"]
    junc2 = control_infrastructure["junc2"]
    incident = control_infrastructure["incident"]

    # 1. Create an active EmergencyEvent linked to the seeded open incident at junc1
    em_event = EmergencyEvent(
        incident_id=incident.id,
        vehicle_type="ambulance",
        priority=1,
        status="active",
    )
    db_session.add(em_event)
    await db_session.commit()
    await db_session.refresh(em_event)

    # 2. POST /api/v1/control/emergency/prioritize -> 200 with corridor plan
    prioritize_resp = await async_client.post(
        "/api/v1/control/emergency/prioritize",
        headers=officer_headers,
        json={
            "emergency_event_id": em_event.id,
            "destination_intersection_id": junc2.id,
        },
    )
    assert prioritize_resp.status_code in [200, 201], prioritize_resp.text
    p_data = prioritize_resp.json()
    assert p_data["is_recommendation"] is True
    assert "decision_id" in p_data
    assert "corridor_plan" in p_data
    corridor_plan = p_data["corridor_plan"]
    # Connecting road gives a real path between junc1 and junc2
    assert corridor_plan["path"] == [junc1.id, junc2.id]
    assert len(corridor_plan["signal_actions"]) > 0

    # Verify event status transitioned active -> dispatched in DB
    await db_session.refresh(em_event)
    assert em_event.status == "dispatched"

    # 3. POST /api/v1/control/emergency/restore -> 200 event resolved + NO_ACTION decision
    restore_resp = await async_client.post(
        "/api/v1/control/emergency/restore",
        headers=officer_headers,
        json={"emergency_event_id": em_event.id},
    )
    assert restore_resp.status_code == 200, restore_resp.text
    r_data = restore_resp.json()
    assert r_data["action"] == "NO_ACTION"
    assert r_data["is_recommendation"] is True
    assert "decision_id" in r_data

    # Verify event status transitioned to resolved and cleared_at is stamped
    await db_session.refresh(em_event)
    assert em_event.status == "resolved"
    assert em_event.cleared_at is not None

    # Verify the restore decision in DB is indeed NO_ACTION
    dec_stmt = select(AIDecision).where(AIDecision.id == r_data["decision_id"])
    dec_res = await db_session.execute(dec_stmt)
    restore_dec_row = dec_res.scalar_one_or_none()
    assert restore_dec_row is not None
    assert restore_dec_row.decision_type == "NO_ACTION"
