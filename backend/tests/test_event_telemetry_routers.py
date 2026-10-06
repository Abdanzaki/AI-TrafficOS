"""Comprehensive integration tests for event and telemetry REST routers.

Tests vehicle_events, incidents, emergency_events, traffic_records, notifications.
Validates real DB operations, batch ingests, RBAC guards, FK validations,
lifecycle status transitions, auto-suggest preemption, and audit logging.
"""

from datetime import datetime, timedelta, timezone
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
    """Fixture that provisions admin, officer, and analyst users and returns their tokens."""
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


@pytest.fixture
async def test_infrastructure(async_client: AsyncClient, test_users: dict):
    """Fixture creating a test intersection, road, and lane."""
    uid = uuid.uuid4().hex[:6]
    admin_headers = {"Authorization": f"Bearer {test_users['admin']['token']}"}

    # Create junction
    junc_resp = await async_client.post(
        "/api/v1/junctions",
        headers=admin_headers,
        json={
            "name": f"Event Test Junction {uid}",
            "code": f"ETJ-{uid.upper()}",
            "status": "active",
            "city": "Metropolis",
            "zone": "Downtown",
            "lat": 37.7749,
            "lon": -122.4194,
        },
    )
    assert junc_resp.status_code == 201
    junction = junc_resp.json()

    # Create road
    road_resp = await async_client.post(
        "/api/v1/roads",
        headers=admin_headers,
        json={
            "name": f"Event Test Ave {uid}",
            "road_type": "arterial",
            "speed_limit_kmh": 50,
        },
    )
    assert road_resp.status_code == 201
    road = road_resp.json()

    # Create lane
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
    assert lane_resp.status_code == 201
    lane = lane_resp.json()

    return {
        "junction": junction,
        "road": road,
        "lane": lane,
    }


# =====================================================================
# 1. Vehicle Events Tests
# =====================================================================

@pytest.mark.anyio
async def test_vehicle_events_single_and_batch_ingest(
    async_client: AsyncClient,
    test_users: dict,
    test_infrastructure: dict,
):
    """Test single and batch ingest of vehicle events, including 100-event batch, filters, RBAC."""
    officer_headers = {"Authorization": f"Bearer {test_users['officer']['token']}"}
    analyst_headers = {"Authorization": f"Bearer {test_users['analyst']['token']}"}
    junction_id = test_infrastructure["junction"]["id"]
    lane_id = test_infrastructure["lane"]["id"]

    # 1. Analyst cannot ingest single vehicle event (403)
    resp = await async_client.post(
        "/api/v1/vehicle-events",
        headers=analyst_headers,
        json={
            "intersection_id": junction_id,
            "lane_id": lane_id,
            "vehicle_type": "car",
            "speed_kmh": 45.2,
            "direction": "northbound",
        },
    )
    assert resp.status_code == 403

    # 2. Officer ingests single vehicle event (201)
    single_resp = await async_client.post(
        "/api/v1/vehicle-events",
        headers=officer_headers,
        json={
            "intersection_id": junction_id,
            "lane_id": lane_id,
            "event_type": "detection",
            "vehicle_type": "car",
            "speed_kmh": 48.5,
            "direction": "northbound",
            "confidence": 0.98,
        },
    )
    assert single_resp.status_code == 201
    single_data = single_resp.json()
    assert single_data["intersection_id"] == junction_id
    assert single_data["lane_id"] == lane_id
    assert single_data["speed_kmh"] == 48.5
    single_id = single_data["id"]

    # 3. Analyst cannot batch ingest (403)
    resp = await async_client.post(
        "/api/v1/vehicle-events/batch",
        headers=analyst_headers,
        json={"events": [{"vehicle_type": "car"}]},
    )
    assert resp.status_code == 403

    # 4. Officer batch ingests 100 vehicle events -> 201 fast
    batch_events = [
        {
            "intersection_id": junction_id,
            "lane_id": lane_id,
            "event_type": "detection",
            "vehicle_type": "car" if i % 2 == 0 else "bus",
            "speed_kmh": 30.0 + (i % 20),
            "direction": "northbound",
            "confidence": 0.95,
        }
        for i in range(100)
    ]
    batch_resp = await async_client.post(
        "/api/v1/vehicle-events/batch",
        headers=officer_headers,
        json={"events": batch_events},
    )
    assert batch_resp.status_code == 201
    batch_data = batch_resp.json()
    assert batch_data["inserted"] == 100

    # 5. Query with time-range filter -> 200
    now = datetime.now(timezone.utc)
    from_time = (now - timedelta(minutes=5)).isoformat()
    to_time = (now + timedelta(minutes=5)).isoformat()

    query_resp = await async_client.get(
        f"/api/v1/vehicle-events?intersection_id={junction_id}&detected_from={from_time}&detected_to={to_time}&per_page=100",
        headers=analyst_headers,
    )
    assert query_resp.status_code == 200
    query_data = query_resp.json()
    assert query_data["total"] >= 101
    assert len(query_data["items"]) == 100

    # 6. Verify single event read
    get_single = await async_client.get(
        f"/api/v1/vehicle-events/{single_id}",
        headers=analyst_headers,
    )
    assert get_single.status_code == 200
    assert get_single.json()["id"] == single_id

    # 7. Check FK validation
    invalid_fk_resp = await async_client.post(
        "/api/v1/vehicle-events",
        headers=officer_headers,
        json={
            "intersection_id": 9999999,
            "vehicle_type": "truck",
        },
    )
    assert invalid_fk_resp.status_code == 404


# =====================================================================
# 2. Incidents Tests
# =====================================================================

@pytest.mark.anyio
async def test_incident_full_lifecycle_and_rbac(
    async_client: AsyncClient,
    test_users: dict,
    test_infrastructure: dict,
):
    """Test incident lifecycle (reported -> acknowledged -> resolved), invalid transitions, and RBAC."""
    admin_headers = {"Authorization": f"Bearer {test_users['admin']['token']}"}
    officer_headers = {"Authorization": f"Bearer {test_users['officer']['token']}"}
    analyst_headers = {"Authorization": f"Bearer {test_users['analyst']['token']}"}
    junction_id = test_infrastructure["junction"]["id"]

    # 1. Analyst cannot create incident (403)
    resp = await async_client.post(
        "/api/v1/incidents",
        headers=analyst_headers,
        json={"description": "Analyst hazard report"},
    )
    assert resp.status_code == 403

    # 2. Officer creates incident (201)
    create_resp = await async_client.post(
        "/api/v1/incidents",
        headers=officer_headers,
        json={
            "intersection_id": junction_id,
            "severity": "high",
            "status": "reported",
            "description": "Multi-car collision blocking right lane",
            "lat": 37.7750,
            "lon": -122.4190,
        },
    )
    assert create_resp.status_code == 201
    incident = create_resp.json()
    incident_id = incident["id"]
    assert incident["status"] == "reported"
    assert incident["severity"] == "high"
    assert incident["reported_by"] == test_users["officer"]["id"]
    assert incident["resolved_at"] is None

    # 3. Lifecycle step 1: reported -> acknowledged (200)
    ack_resp = await async_client.patch(
        f"/api/v1/incidents/{incident_id}",
        headers=officer_headers,
        json={"status": "acknowledged"},
    )
    assert ack_resp.status_code == 200
    assert ack_resp.json()["status"] == "acknowledged"

    # 4. Lifecycle step 2: acknowledged -> resolved (200, resolved_at auto-populated)
    resolve_resp = await async_client.patch(
        f"/api/v1/incidents/{incident_id}",
        headers=officer_headers,
        json={"status": "resolved"},
    )
    assert resolve_resp.status_code == 200
    resolved_data = resolve_resp.json()
    assert resolved_data["status"] == "resolved"
    assert resolved_data["resolved_at"] is not None

    # 5. Invalid transition: cannot go resolved -> reported (400)
    invalid_resp = await async_client.patch(
        f"/api/v1/incidents/{incident_id}",
        headers=officer_headers,
        json={"status": "reported"},
    )
    assert invalid_resp.status_code == 400
    assert "cannot transition incident from resolved to reported" in invalid_resp.json()["detail"].lower()

    # 6. Query with filters (status, severity, intersection_id, from/to)
    now = datetime.now(timezone.utc)
    from_date = (now - timedelta(minutes=5)).isoformat()
    to_date = (now + timedelta(minutes=5)).isoformat()

    get_resp = await async_client.get(
        f"/api/v1/incidents?status=resolved&severity=high&intersection_id={junction_id}&from={from_date}&to={to_date}",
        headers=analyst_headers,
    )
    assert get_resp.status_code == 200
    items = get_resp.json()["items"]
    assert any(i["id"] == incident_id for i in items)

    # 7. Analyst cannot update incident (403)
    analyst_patch = await async_client.patch(
        f"/api/v1/incidents/{incident_id}",
        headers=analyst_headers,
        json={"severity": "low"},
    )
    assert analyst_patch.status_code == 403

    # 8. Officer cannot delete incident (403, admin only)
    officer_del = await async_client.delete(
        f"/api/v1/incidents/{incident_id}",
        headers=officer_headers,
    )
    assert officer_del.status_code == 403

    # 9. Admin deletes incident (204)
    admin_del = await async_client.delete(
        f"/api/v1/incidents/{incident_id}",
        headers=admin_headers,
    )
    assert admin_del.status_code == 204

    # 10. Verify 404 after deletion
    not_found_resp = await async_client.get(
        f"/api/v1/incidents/{incident_id}",
        headers=analyst_headers,
    )
    assert not_found_resp.status_code == 404


# =====================================================================
# 3. Emergency Events Tests
# =====================================================================

@pytest.mark.anyio
async def test_emergency_events_auto_suggest_and_lifecycle(
    async_client: AsyncClient,
    test_users: dict,
    test_infrastructure: dict,
):
    """Test emergency event creation linked to incident, auto-suggesting intersection, and status/priority updates."""
    officer_headers = {"Authorization": f"Bearer {test_users['officer']['token']}"}
    analyst_headers = {"Authorization": f"Bearer {test_users['analyst']['token']}"}
    junction_id = test_infrastructure["junction"]["id"]

    # Create an incident first
    inc_resp = await async_client.post(
        "/api/v1/incidents",
        headers=officer_headers,
        json={
            "intersection_id": junction_id,
            "severity": "critical",
            "status": "reported",
            "description": "Ambulance transit required for medical emergency",
        },
    )
    assert inc_resp.status_code == 201
    incident_id = inc_resp.json()["id"]

    # 1. Analyst cannot create emergency event (403)
    resp = await async_client.post(
        "/api/v1/emergency-events",
        headers=analyst_headers,
        json={"vehicle_type": "ambulance", "priority": 1},
    )
    assert resp.status_code == 403

    # 2. Officer creates emergency event linked to incident without specifying intersection_id
    # Auto-suggest should copy intersection_id from the incident!
    em_resp = await async_client.post(
        "/api/v1/emergency-events",
        headers=officer_headers,
        json={
            "incident_id": incident_id,
            "vehicle_type": "ambulance",
            "priority": 1,
            "status": "active",
        },
    )
    assert em_resp.status_code == 201
    em_data = em_resp.json()
    em_id = em_data["id"]
    assert em_data["incident_id"] == incident_id
    assert em_data["intersection_id"] == junction_id
    assert em_data["vehicle_type"] == "ambulance"
    assert em_data["priority"] == 1
    assert em_data["status"] == "active"

    # 3. Officer updates status and priority
    patch_resp = await async_client.patch(
        f"/api/v1/emergency-events/{em_id}",
        headers=officer_headers,
        json={
            "status": "resolved",
            "priority": 2,
        },
    )
    assert patch_resp.status_code == 200
    patched = patch_resp.json()
    assert patched["status"] == "resolved"
    assert patched["priority"] == 2
    assert patched["cleared_at"] is not None

    # 4. Analyst can read emergency events with filters
    list_resp = await async_client.get(
        f"/api/v1/emergency-events?status=resolved&priority=2",
        headers=analyst_headers,
    )
    assert list_resp.status_code == 200
    items = list_resp.json()["items"]
    assert any(e["id"] == em_id for e in items)

    # 5. Analyst cannot update emergency event (403)
    analyst_patch = await async_client.patch(
        f"/api/v1/emergency-events/{em_id}",
        headers=analyst_headers,
        json={"priority": 1},
    )
    assert analyst_patch.status_code == 403


# =====================================================================
# 4. Traffic Records Tests
# =====================================================================

@pytest.mark.anyio
async def test_traffic_records_single_and_batch_ingest(
    async_client: AsyncClient,
    test_users: dict,
    test_infrastructure: dict,
):
    """Test single and batch ingest of traffic records, queries with filters, and RBAC."""
    officer_headers = {"Authorization": f"Bearer {test_users['officer']['token']}"}
    analyst_headers = {"Authorization": f"Bearer {test_users['analyst']['token']}"}
    junction_id = test_infrastructure["junction"]["id"]
    lane_id = test_infrastructure["lane"]["id"]

    # 1. Analyst cannot ingest traffic records (403)
    resp = await async_client.post(
        "/api/v1/traffic-records",
        headers=analyst_headers,
        json={
            "intersection_id": junction_id,
            "vehicle_count": 10,
        },
    )
    assert resp.status_code == 403

    # 2. Officer ingests single traffic record (201)
    single_resp = await async_client.post(
        "/api/v1/traffic-records",
        headers=officer_headers,
        json={
            "intersection_id": junction_id,
            "lane_id": lane_id,
            "vehicle_count": 42,
            "avg_speed_kmh": 41.5,
            "congestion_level": 35,
            "source": "sensor",
        },
    )
    assert single_resp.status_code == 201
    rec = single_resp.json()
    assert rec["intersection_id"] == junction_id
    assert rec["lane_id"] == lane_id
    assert rec["vehicle_count"] == 42
    assert rec["congestion_level"] == 35

    # 3. Officer batch ingests traffic records (201)
    batch_records = [
        {
            "intersection_id": junction_id,
            "lane_id": lane_id,
            "vehicle_count": 20 + i,
            "avg_speed_kmh": 35.0,
            "congestion_level": 20,
            "source": "camera",
        }
        for i in range(25)
    ]
    batch_resp = await async_client.post(
        "/api/v1/traffic-records/batch",
        headers=officer_headers,
        json={"records": batch_records},
    )
    assert batch_resp.status_code == 201
    assert batch_resp.json()["inserted"] == 25

    # 4. Analyst queries traffic records with filters (source, intersection_id, lane_id)
    query_resp = await async_client.get(
        f"/api/v1/traffic-records?intersection_id={junction_id}&lane_id={lane_id}&source=camera&per_page=50",
        headers=analyst_headers,
    )
    assert query_resp.status_code == 200
    data = query_resp.json()
    assert data["total"] == 25
    assert len(data["items"]) == 25


# =====================================================================
# 5. Notifications Tests
# =====================================================================

@pytest.mark.anyio
async def test_notifications_broadcast_targeted_and_read(
    async_client: AsyncClient,
    test_users: dict,
):
    """Test broadcast notifications as admin, targeted alerts, me query, and read marking."""
    admin_headers = {"Authorization": f"Bearer {test_users['admin']['token']}"}
    officer_headers = {"Authorization": f"Bearer {test_users['officer']['token']}"}
    analyst_headers = {"Authorization": f"Bearer {test_users['analyst']['token']}"}
    analyst_id = test_users["analyst"]["id"]
    officer_id = test_users["officer"]["id"]

    # 1. Officer cannot broadcast notification (403, admin only)
    resp = await async_client.post(
        "/api/v1/notifications/broadcast",
        headers=officer_headers,
        json={
            "title": "Unauthorized broadcast",
            "message": "Should fail with 403",
        },
    )
    assert resp.status_code == 403

    # 2. Admin broadcasts notification -> 201
    broadcast_resp = await async_client.post(
        "/api/v1/notifications/broadcast",
        headers=admin_headers,
        json={
            "title": "System-wide Amber Alert",
            "message": "High congestion reported across central corridor",
            "severity": "warning",
        },
    )
    assert broadcast_resp.status_code == 201
    broadcast_data = broadcast_resp.json()
    broadcast_id = broadcast_data["id"]
    assert broadcast_data["user_id"] is None
    assert broadcast_data["is_read"] is False

    # 3. Analyst sees broadcast notification in /notifications/me -> 200
    my_notifs_resp = await async_client.get(
        "/api/v1/notifications/me",
        headers=analyst_headers,
    )
    assert my_notifs_resp.status_code == 200
    my_items = my_notifs_resp.json()["items"]
    assert any(n["id"] == broadcast_id for n in my_items)

    # 4. Analyst marks broadcast notification read -> 200
    mark_read_resp = await async_client.patch(
        f"/api/v1/notifications/{broadcast_id}/read",
        headers=analyst_headers,
    )
    assert mark_read_resp.status_code == 200
    assert mark_read_resp.json()["is_read"] is True

    # 5. Admin sends targeted notification to analyst
    targeted_resp = await async_client.post(
        "/api/v1/notifications",
        headers=admin_headers,
        json={
            "user_id": analyst_id,
            "title": "Shift briefing update",
            "message": "Review latest junction telemetry report",
            "severity": "info",
        },
    )
    assert targeted_resp.status_code == 201
    targeted_id = targeted_resp.json()["id"]

    # 6. Officer attempts to mark analyst's targeted notification as read -> 403 Forbidden!
    forbidden_read = await async_client.patch(
        f"/api/v1/notifications/{targeted_id}/read",
        headers=officer_headers,
    )
    assert forbidden_read.status_code == 403

    # 7. Analyst marks own targeted notification as read -> 200
    analyst_read = await async_client.patch(
        f"/api/v1/notifications/{targeted_id}/read",
        headers=analyst_headers,
    )
    assert analyst_read.status_code == 200
    assert analyst_read.json()["is_read"] is True


# =====================================================================
# 6. Audit Trail Verification
# =====================================================================

@pytest.mark.anyio
async def test_audit_logs_recorded(
    async_client: AsyncClient,
    test_users: dict,
):
    """Verify state-changing actions write to audit_logs."""
    async with AsyncSessionLocal() as db:
        res = await db.execute(select(AuditLog.action).order_by(AuditLog.id.desc()).limit(20))
        actions = res.scalars().all()
        # Verify actions like incident.created, emergency.created, notification.broadcast are logged
        assert any("incident" in a or "emergency" in a or "notification" in a or "vehicle_event" in a for a in actions)
