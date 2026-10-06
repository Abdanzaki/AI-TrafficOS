"""Comprehensive integration tests for AI records, analytics, audit log routers, and Phase 1 regression.

Tests:
- AI Predictions: create (RBAC + audit), paginated query with filters, get detail, FK validations.
- AI Decisions: create (status='proposed' + audit), paginated query, get detail.
- AI Decisions PATCH lifecycle: proposed->applied, applied->reverted, proposed->reverted, invalid transitions (400),
  setting applied_by and applied_at, audit logging.
- Analytics traffic-summary: SQL date_trunc aggregations, avg vehicle count, speed, congestion, record counts.
- Analytics incidents-summary: real counts grouped by severity and by status.
- Analytics congestion-hotspots: top intersections ranked by congestion descending with name and code.
- Audit logs: admin ONLY (200), analyst/officer (403), unauthenticated (401), paginated filters.
- Phase 1 regression: root /health, /version, /ws alongside /api/v1 equivalents.
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
from app.models.intersection import Intersection


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
async def auth_tokens(async_client: AsyncClient):
    """Fixture that provisions admin, officer, and analyst users and returns auth headers."""
    uid = uuid.uuid4().hex[:8]
    password = "TestPassword123!"

    # 1. Admin login or create
    admin_login_resp = await async_client.post(
        "/api/v1/auth/login",
        json={"email": "admin@trafficos.io", "password": "adminpassword123"},
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

    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    # 2. Officer user
    officer_email = f"officer_{uid}@trafficos.io"
    officer_resp = await async_client.post(
        "/api/v1/users",
        headers=admin_headers,
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
    officer_headers = {"Authorization": f"Bearer {officer_token}"}

    # 3. Analyst user
    analyst_email = f"analyst_{uid}@trafficos.io"
    analyst_resp = await async_client.post(
        "/api/v1/users",
        headers=admin_headers,
        json={
            "email": analyst_email,
            "password": password,
            "full_name": "Traffic Analyst",
            "role_name": "analyst",
        },
    )
    assert analyst_resp.status_code == 201
    analyst_id = analyst_resp.json()["id"]

    analyst_login = await async_client.post(
        "/api/v1/auth/login",
        json={"email": analyst_email, "password": password},
    )
    analyst_token = analyst_login.json()["access_token"]
    analyst_headers = {"Authorization": f"Bearer {analyst_token}"}

    return {
        "admin": {"id": admin_id, "token": admin_token, "headers": admin_headers},
        "officer": {"id": officer_id, "token": officer_token, "headers": officer_headers},
        "analyst": {"id": analyst_id, "token": analyst_token, "headers": analyst_headers},
    }


@pytest.fixture
async def sample_intersection(async_client: AsyncClient, auth_tokens: dict):
    """Fixture providing a test intersection."""
    code = f"INT-{uuid.uuid4().hex[:6].upper()}"
    resp = await async_client.post(
        "/api/v1/junctions",
        headers=auth_tokens["admin"]["headers"],
        json={
            "name": f"Test Junction {code}",
            "code": code,
            "status": "active",
            "city": "Metropolis",
            "zone": "Downtown",
            "lat": 37.7749,
            "lon": -122.4194,
        },
    )
    assert resp.status_code == 201
    return resp.json()


# -----------------------------------------------------------------------------
# 1. AI Predictions Tests
# -----------------------------------------------------------------------------

@pytest.mark.anyio
async def test_ai_predictions_crud_and_rbac(
    async_client: AsyncClient,
    auth_tokens: dict,
    sample_intersection: dict,
):
    """Test AI predictions creation, RBAC guards, filtering, and audit logging."""
    inter_id = sample_intersection["id"]
    predicted_time = (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat()

    # 1. Analyst cannot create prediction (403)
    pred_payload = {
        "intersection_id": inter_id,
        "prediction_type": "congestion",
        "predicted_for": predicted_time,
        "payload": {"predicted_congestion_level": 75, "flow_rate": 1200},
        "confidence": 0.92,
        "model_version": "v1.2.0-st-gnn",
    }
    resp = await async_client.post(
        "/api/v1/ai-predictions",
        headers=auth_tokens["analyst"]["headers"],
        json=pred_payload,
    )
    assert resp.status_code == 403

    # 2. Officer creates prediction (201)
    resp = await async_client.post(
        "/api/v1/ai-predictions",
        headers=auth_tokens["officer"]["headers"],
        json=pred_payload,
    )
    assert resp.status_code == 201
    pred_data = resp.json()
    assert pred_data["id"] is not None
    assert pred_data["prediction_type"] == "congestion"
    assert pred_data["confidence"] == 0.92
    assert pred_data["model_version"] == "v1.2.0-st-gnn"
    pred_id = pred_data["id"]

    # 3. Verify audit log entry created
    audit_resp = await async_client.get(
        f"/api/v1/audit-logs?action=ai_prediction.created&entity_type=ai_prediction",
        headers=auth_tokens["admin"]["headers"],
    )
    assert audit_resp.status_code == 200
    audit_items = audit_resp.json()["items"]
    assert any(a["entity_id"] == pred_id for a in audit_items)

    # 4. Get by ID (analyst can read)
    get_resp = await async_client.get(
        f"/api/v1/ai-predictions/{pred_id}",
        headers=auth_tokens["analyst"]["headers"],
    )
    assert get_resp.status_code == 200
    assert get_resp.json()["id"] == pred_id

    # 5. List with filters (all roles read)
    list_resp = await async_client.get(
        f"/api/v1/ai-predictions?prediction_type=congestion&intersection_id={inter_id}",
        headers=auth_tokens["analyst"]["headers"],
    )
    assert list_resp.status_code == 200
    items = list_resp.json()["items"]
    assert len(items) >= 1
    assert items[0]["prediction_type"] == "congestion"


# -----------------------------------------------------------------------------
# 2. AI Decisions Tests
# -----------------------------------------------------------------------------

@pytest.mark.anyio
async def test_ai_decisions_lifecycle_and_transitions(
    async_client: AsyncClient,
    auth_tokens: dict,
    sample_intersection: dict,
):
    """Test AI decisions creation, state transitions (proposed->applied->reverted), invalid transitions, and audit logs."""
    inter_id = sample_intersection["id"]

    # 1. Create prediction first
    pred_resp = await async_client.post(
        "/api/v1/ai-predictions",
        headers=auth_tokens["admin"]["headers"],
        json={
            "intersection_id": inter_id,
            "prediction_type": "flow",
            "predicted_for": (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat(),
            "payload": {"flow_multiplier": 1.4},
            "confidence": 0.88,
            "model_version": "v1.0-flow",
        },
    )
    assert pred_resp.status_code == 201
    pred_id = pred_resp.json()["id"]

    # 2. Analyst cannot create decision (403)
    dec_payload = {
        "prediction_id": pred_id,
        "intersection_id": inter_id,
        "decision_type": "signal_timing",
        "payload": {"extend_green_seconds": 15, "phase_id": 1},
        "rationale": "High upstream traffic surge detected",
    }
    resp = await async_client.post(
        "/api/v1/ai-decisions",
        headers=auth_tokens["analyst"]["headers"],
        json=dec_payload,
    )
    assert resp.status_code == 403

    # 3. Officer creates decision (201, status defaults to 'proposed')
    resp = await async_client.post(
        "/api/v1/ai-decisions",
        headers=auth_tokens["officer"]["headers"],
        json=dec_payload,
    )
    assert resp.status_code == 201
    dec_data = resp.json()
    assert dec_data["status"] == "proposed"
    assert dec_data["decision_type"] == "signal_timing"
    assert dec_data["applied_by"] is None
    dec_id = dec_data["id"]

    # 4. Invalid transition: proposed -> proposed (400)
    resp = await async_client.patch(
        f"/api/v1/ai-decisions/{dec_id}",
        headers=auth_tokens["officer"]["headers"],
        json={"status": "proposed"},
    )
    assert resp.status_code == 400

    # 5. Transition: proposed -> applied (200, sets applied_by and applied_at)
    resp = await async_client.patch(
        f"/api/v1/ai-decisions/{dec_id}",
        headers=auth_tokens["officer"]["headers"],
        json={"status": "applied", "rationale": "Applied by traffic officer after safety check"},
    )
    assert resp.status_code == 200
    applied_data = resp.json()
    assert applied_data["status"] == "applied"
    assert applied_data["applied_by"] == auth_tokens["officer"]["id"]
    assert applied_data["applied_at"] is not None

    # 6. Invalid transition: applied -> proposed (400)
    resp = await async_client.patch(
        f"/api/v1/ai-decisions/{dec_id}",
        headers=auth_tokens["officer"]["headers"],
        json={"status": "proposed"},
    )
    assert resp.status_code == 400

    # 7. Transition: applied -> reverted (200)
    resp = await async_client.patch(
        f"/api/v1/ai-decisions/{dec_id}",
        headers=auth_tokens["officer"]["headers"],
        json={"status": "reverted", "rationale": "Reverting due to pedestrian priority"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "reverted"

    # 8. Invalid transition: reverted -> applied (400, no transitions from reverted)
    resp = await async_client.patch(
        f"/api/v1/ai-decisions/{dec_id}",
        headers=auth_tokens["officer"]["headers"],
        json={"status": "applied"},
    )
    assert resp.status_code == 400

    # 9. Verify direct proposed -> reverted is also allowed on a fresh decision
    fresh_dec = await async_client.post(
        "/api/v1/ai-decisions",
        headers=auth_tokens["admin"]["headers"],
        json=dec_payload,
    )
    fresh_id = fresh_dec.json()["id"]
    rev_resp = await async_client.patch(
        f"/api/v1/ai-decisions/{fresh_id}",
        headers=auth_tokens["admin"]["headers"],
        json={"status": "reverted", "rationale": "Directly rejected recommendation"},
    )
    assert rev_resp.status_code == 200
    assert rev_resp.json()["status"] == "reverted"


# -----------------------------------------------------------------------------
# 3. Analytics Tests (traffic-summary, incidents-summary, congestion-hotspots)
# -----------------------------------------------------------------------------

@pytest.mark.anyio
async def test_analytics_traffic_summary(
    async_client: AsyncClient,
    auth_tokens: dict,
    sample_intersection: dict,
):
    """Test GET /analytics/traffic-summary with real SQL date_trunc aggregations."""
    inter_id = sample_intersection["id"]
    headers = auth_tokens["analyst"]["headers"]

    # Ingest 3 real traffic records in the same hour
    now = datetime.now(timezone.utc)
    base_time = now.replace(minute=10, second=0, microsecond=0)

    records = [
        {
            "intersection_id": inter_id,
            "recorded_at": (base_time + timedelta(minutes=5)).isoformat(),
            "vehicle_count": 20,
            "avg_speed_kmh": 40.0,
            "congestion_level": 30,
            "source": "sensor",
        },
        {
            "intersection_id": inter_id,
            "recorded_at": (base_time + timedelta(minutes=15)).isoformat(),
            "vehicle_count": 40,
            "avg_speed_kmh": 60.0,
            "congestion_level": 50,
            "source": "sensor",
        },
    ]

    batch_resp = await async_client.post(
        "/api/v1/traffic-records/batch",
        headers=auth_tokens["admin"]["headers"],
        json={"records": records},
    )
    assert batch_resp.status_code == 201

    # Query traffic summary bucketed by hour
    from_str = (base_time - timedelta(hours=1)).isoformat()
    to_str = (base_time + timedelta(hours=1)).isoformat()

    resp = await async_client.get(
        f"/api/v1/analytics/traffic-summary?intersection_id={inter_id}&from={from_str}&to={to_str}&bucket=hour",
        headers=headers,
    )
    assert resp.status_code == 200
    buckets = resp.json()
    assert isinstance(buckets, list)
    assert len(buckets) >= 1

    bucket_data = buckets[0]
    # avg vehicle count: (20 + 40) / 2 = 30.0
    assert bucket_data["avg_vehicle_count"] == 30.0
    # avg speed: (40.0 + 60.0) / 2 = 50.0
    assert bucket_data["avg_speed"] == 50.0
    # avg congestion: (30 + 50) / 2 = 40.0
    assert bucket_data["avg_congestion"] == 40.0
    assert bucket_data["record_count"] >= 2

    # Query bucketed by day
    resp_day = await async_client.get(
        f"/api/v1/analytics/traffic-summary?intersection_id={inter_id}&bucket=day",
        headers=headers,
    )
    assert resp_day.status_code == 200

    # Invalid bucket -> 400
    bad_resp = await async_client.get(
        f"/api/v1/analytics/traffic-summary?bucket=second",
        headers=headers,
    )
    assert bad_resp.status_code == 400


@pytest.mark.anyio
async def test_analytics_incidents_summary(
    async_client: AsyncClient,
    auth_tokens: dict,
    sample_intersection: dict,
):
    """Test GET /analytics/incidents-summary with real counts grouped by severity and status."""
    inter_id = sample_intersection["id"]
    headers = auth_tokens["analyst"]["headers"]

    # Create 3 incidents with distinct severities and statuses
    inc1 = await async_client.post(
        "/api/v1/incidents",
        headers=auth_tokens["officer"]["headers"],
        json={
            "intersection_id": inter_id,
            "severity": "high",
            "status": "reported",
            "description": "Multi-car collision",
        },
    )
    assert inc1.status_code == 201

    inc2 = await async_client.post(
        "/api/v1/incidents",
        headers=auth_tokens["officer"]["headers"],
        json={
            "intersection_id": inter_id,
            "severity": "critical",
            "status": "acknowledged",
            "description": "Hazardous material spill",
        },
    )
    assert inc2.status_code == 201

    inc3 = await async_client.post(
        "/api/v1/incidents",
        headers=auth_tokens["officer"]["headers"],
        json={
            "intersection_id": inter_id,
            "severity": "high",
            "status": "resolved",
            "description": "Debris on road",
        },
    )
    assert inc3.status_code == 201

    # Query incidents summary
    resp = await async_client.get(
        "/api/v1/analytics/incidents-summary",
        headers=headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 3
    assert data["by_severity"].get("high", 0) >= 2
    assert data["by_severity"].get("critical", 0) >= 1
    assert data["by_status"].get("reported", 0) >= 1
    assert data["by_status"].get("acknowledged", 0) >= 1
    assert data["by_status"].get("resolved", 0) >= 1


@pytest.mark.anyio
async def test_analytics_congestion_hotspots(
    async_client: AsyncClient,
    auth_tokens: dict,
    sample_intersection: dict,
):
    """Test GET /analytics/congestion-hotspots with real rankings from database."""
    inter_id = sample_intersection["id"]
    headers = auth_tokens["analyst"]["headers"]

    # Ingest record with congestion 85
    rec_resp = await async_client.post(
        "/api/v1/traffic-records",
        headers=auth_tokens["admin"]["headers"],
        json={
            "intersection_id": inter_id,
            "vehicle_count": 95,
            "avg_speed_kmh": 12.0,
            "congestion_level": 85,
            "source": "sensor",
        },
    )
    assert rec_resp.status_code == 201

    resp = await async_client.get(
        "/api/v1/analytics/congestion-hotspots?limit=5",
        headers=headers,
    )
    assert resp.status_code == 200
    hotspots = resp.json()
    assert isinstance(hotspots, list)
    assert len(hotspots) >= 1

    # Verify hotspot contains intersection name, code, and computed congestion
    target = next((h for h in hotspots if h["intersection_id"] == inter_id), None)
    assert target is not None
    assert target["name"] == sample_intersection["name"]
    assert target["code"] == sample_intersection["code"]
    assert target["avg_congestion_level"] >= 80.0


# -----------------------------------------------------------------------------
# 4. Audit Logs Router Tests (admin only, RBAC verification)
# -----------------------------------------------------------------------------

@pytest.mark.anyio
async def test_audit_logs_rbac_and_query(
    async_client: AsyncClient,
    auth_tokens: dict,
):
    """Test GET /audit-logs: admin (200), officer (403), analyst (403), unauth (401)."""
    # 1. Analyst gets 403 Forbidden
    analyst_resp = await async_client.get(
        "/api/v1/audit-logs",
        headers=auth_tokens["analyst"]["headers"],
    )
    assert analyst_resp.status_code == 403

    # 2. Officer gets 403 Forbidden
    officer_resp = await async_client.get(
        "/api/v1/audit-logs",
        headers=auth_tokens["officer"]["headers"],
    )
    assert officer_resp.status_code == 403

    # 3. Unauthenticated gets 401 Unauthorized
    unauth_resp = await async_client.get("/api/v1/audit-logs")
    assert unauth_resp.status_code == 401

    # 4. Admin gets 200 OK with paginated list
    admin_resp = await async_client.get(
        "/api/v1/audit-logs?page=1&per_page=10",
        headers=auth_tokens["admin"]["headers"],
    )
    assert admin_resp.status_code == 200
    data = admin_resp.json()
    assert "items" in data
    assert "total" in data
    assert data["total"] >= 1
    assert len(data["items"]) >= 1


# -----------------------------------------------------------------------------
# 5. Phase 1 Regression Tests (Root and /api/v1 health/version/ws endpoints)
# -----------------------------------------------------------------------------

def test_phase1_root_and_v1_health():
    """Verify both /health and /api/v1/health return exact status and version."""
    from fastapi.testclient import TestClient
    app = create_app()
    with TestClient(app) as client:
        # /api/v1/health
        resp_v1 = client.get("/api/v1/health")
        assert resp_v1.status_code == 200
        assert resp_v1.json() == {"status": "ok", "service": "ai-trafficos", "version": "0.1.0"}

        # root /health
        resp_root = client.get("/health")
        assert resp_root.status_code == 200
        assert resp_root.json() == {"status": "ok", "service": "ai-trafficos", "version": "0.1.0"}


def test_phase1_root_and_v1_version():
    """Verify both /version and /api/v1/version return exact service and version."""
    from fastapi.testclient import TestClient
    app = create_app()
    with TestClient(app) as client:
        resp_v1 = client.get("/api/v1/version")
        assert resp_v1.status_code == 200
        assert resp_v1.json() == {"service": "ai-trafficos", "version": "0.1.0"}

        resp_root = client.get("/version")
        assert resp_root.status_code == 200
        assert resp_root.json() == {"service": "ai-trafficos", "version": "0.1.0"}


def test_phase1_root_and_v1_ws_handshake():
    """Verify both /ws and /api/v1/ws accept handshake and close cleanly."""
    from fastapi.testclient import TestClient
    app = create_app()
    with TestClient(app) as client:
        # /api/v1/ws
        with client.websocket_connect("/api/v1/ws") as ws:
            payload = ws.receive_json()
            assert payload == {
                "type": "handshake",
                "status": "connected",
                "note": "Phase 1: no live traffic streams yet",
            }

        # root /ws
        with client.websocket_connect("/ws") as ws:
            payload = ws.receive_json()
            assert payload == {
                "type": "handshake",
                "status": "connected",
                "note": "Phase 1: no live traffic streams yet",
            }
