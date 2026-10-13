"""Tests for predictive-maintenance signal health scoring service and REST API.

Validates:
- Crafted telemetry history scoring:
  - Flapping signal -> low score, status degraded/at-risk, explanation mentions flapping.
  - Healthy signal -> high score (>=80), status healthy, nominal explanation.
  - Stale heartbeat -> penalty applied, explanation mentions stale/heartbeat.
  - Anomalous dwell time -> penalty applied, explanation mentions dwell.
  - Hardware fault -> heavy penalty, status at-risk.
- Strictly honest provenance='heuristic'.
- GET /api/v1/signals/health:
  - 200 OK returning SignalHealthListResponse.
- GET /api/v1/signals/{id}/health:
  - 200 OK returning SignalHealthResponse.
  - 404 for non-existent signal ID.
- RBAC validation (401 unauthenticated, 200 for authenticated roles).
"""

from datetime import datetime, timedelta, timezone
import uuid

from httpx import AsyncClient
import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.models.intersection import Intersection
from app.models.signal import Signal, SignalPhase
from app.services.signal_health import (
    PROVENANCE,
    TelemetrySample,
    compute_signal_health,
    get_all_signals_health,
    get_signal_health,
)

pytestmark = pytest.mark.anyio


def _create_mock_signal(
    signal_id: int = 1,
    code: str = "SIG-TEST-01",
    intersection_id: int = 10,
    status: str = "active",
    observed_state: str = "green",
    observed_at: datetime = None,
    phases: list[SignalPhase] = None,
) -> Signal:
    """Helper creating an in-memory Signal instance."""
    sig = Signal(
        id=signal_id,
        code=code,
        intersection_id=intersection_id,
        status=status,
        observed_state=observed_state,
        observed_at=observed_at or datetime.now(timezone.utc),
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    if phases is None:
        p1 = SignalPhase(
            id=1,
            signal_id=signal_id,
            name="Phase 1 Green",
            phase_order=1,
            duration_seconds=30,
            state="green",
            is_active=True,
        )
        p2 = SignalPhase(
            id=2,
            signal_id=signal_id,
            name="Phase 2 Yellow",
            phase_order=2,
            duration_seconds=5,
            state="yellow",
            is_active=False,
        )
        p3 = SignalPhase(
            id=3,
            signal_id=signal_id,
            name="Phase 3 Red",
            phase_order=3,
            duration_seconds=25,
            state="red",
            is_active=False,
        )
        sig.phases = [p1, p2, p3]
    else:
        sig.phases = phases
    return sig


# ---------------------------------------------------------------------------
# Unit Tests with Crafted Telemetry Histories
# ---------------------------------------------------------------------------

def test_signal_health_healthy_fixture():
    """Verify healthy telemetry produces high score (>=80), healthy band, and clean factors."""
    now = datetime.now(timezone.utc)
    sig = _create_mock_signal(status="active", observed_at=now - timedelta(seconds=10))

    # Steady, regular 30s cadence (no flapping, fresh timestamps, nominal dwell)
    telemetry = [
        TelemetrySample(timestamp=now - timedelta(seconds=90), state="green", duration_seconds=30),
        TelemetrySample(timestamp=now - timedelta(seconds=60), state="yellow", duration_seconds=5),
        TelemetrySample(timestamp=now - timedelta(seconds=55), state="red", duration_seconds=25),
        TelemetrySample(timestamp=now - timedelta(seconds=30), state="green", duration_seconds=30),
    ]

    result = compute_signal_health(sig, telemetry, now=now)

    assert result["score"] >= 80
    assert result["status_band"] == "healthy"
    assert result["provenance"] == "heuristic"
    assert "healthy" in result["explanation"].lower()
    for factor in result["factors"]:
        assert factor["penalty"] == 0.0
        assert factor["status"] == "normal"


def test_signal_health_flapping_fixture():
    """Verify rapid phase-flapping triggers penalty and explanation mentions flapping."""
    now = datetime.now(timezone.utc)
    sig = _create_mock_signal(status="active", observed_at=now - timedelta(seconds=5))

    # Flapping telemetry: multiple state changes within <5 seconds
    telemetry = [
        TelemetrySample(timestamp=now - timedelta(seconds=15), state="green", duration_seconds=30),
        TelemetrySample(timestamp=now - timedelta(seconds=13), state="red", duration_seconds=2),   # dt = 2s (<5s)
        TelemetrySample(timestamp=now - timedelta(seconds=11), state="green", duration_seconds=2), # dt = 2s (<5s)
        TelemetrySample(timestamp=now - timedelta(seconds=9), state="red", duration_seconds=2),   # dt = 2s (<5s)
        TelemetrySample(timestamp=now - timedelta(seconds=7), state="green", duration_seconds=2), # dt = 2s (<5s)
        TelemetrySample(timestamp=now - timedelta(seconds=5), state="red", duration_seconds=2),   # dt = 2s (<5s)
    ]

    result = compute_signal_health(sig, telemetry, now=now)

    assert result["score"] < 80
    assert result["status_band"] in ("degraded", "at-risk")
    assert "flapping" in result["explanation"].lower()

    flapping_factor = next(f for f in result["factors"] if f["name"] == "phase_flapping")
    assert flapping_factor["penalty"] > 0
    assert flapping_factor["status"] in ("warning", "critical")
    assert "flapping" in flapping_factor["description"].lower()


def test_signal_health_stale_heartbeat_fixture():
    """Verify missed heartbeats / stale updates degrade health and explanation mentions staleness."""
    now = datetime.now(timezone.utc)
    # Signal last updated 40 minutes ago
    stale_time = now - timedelta(minutes=40)
    sig = _create_mock_signal(status="active", observed_at=stale_time)

    telemetry = [
        TelemetrySample(timestamp=stale_time, state="green", duration_seconds=30),
    ]

    result = compute_signal_health(sig, telemetry, now=now)

    assert result["score"] <= 75
    assert "stale" in result["explanation"].lower() or "heartbeat" in result["explanation"].lower()

    staleness_factor = next(f for f in result["factors"] if f["name"] == "heartbeat_staleness")
    assert staleness_factor["penalty"] >= 20.0
    assert staleness_factor["status"] == "critical"


def test_signal_health_anomalous_dwell_fixture():
    """Verify anomalous dwell times trigger penalty and explanation mentions dwell."""
    now = datetime.now(timezone.utc)
    sig = _create_mock_signal(status="active", observed_at=now - timedelta(seconds=10))

    # Phase stuck for 180 seconds (when expected is ~20-30s, >3x anomaly)
    telemetry = [
        TelemetrySample(timestamp=now - timedelta(seconds=200), state="red", duration_seconds=180),
        TelemetrySample(timestamp=now - timedelta(seconds=20), state="green", duration_seconds=200),
    ]

    result = compute_signal_health(sig, telemetry, now=now)

    dwell_factor = next(f for f in result["factors"] if f["name"] == "anomalous_dwell")
    assert dwell_factor["penalty"] > 0
    assert "dwell" in result["explanation"].lower()


def test_signal_health_hardware_fault_fixture():
    """Verify hardware controller fault drops score into at-risk band (<50)."""
    now = datetime.now(timezone.utc)
    sig = _create_mock_signal(status="fault", observed_at=now - timedelta(seconds=10))

    result = compute_signal_health(sig, [], now=now)

    assert result["score"] < 50
    assert result["status_band"] == "at-risk"
    assert "fault" in result["explanation"].lower()


def test_signal_health_provenance_strictly_heuristic():
    """Verify provenance is strictly 'heuristic' across all evaluations."""
    sig = _create_mock_signal()
    result = compute_signal_health(sig)
    assert result["provenance"] == "heuristic"
    assert PROVENANCE == "heuristic"


# ---------------------------------------------------------------------------
# Integration and Endpoint Tests
# ---------------------------------------------------------------------------

@pytest.fixture
async def signal_health_db_data():
    """Seed test intersection and physical signal controller records with isolated session."""
    uid = uuid.uuid4().hex[:6]
    async with AsyncSessionLocal() as db:
        junc = Intersection(
            name=f"Health Test Junction {uid}",
            code=f"HTJ-{uid.upper()}",
            status="active",
            lat=37.7749,
            lon=-122.4194,
        )
        db.add(junc)
        await db.commit()
        await db.refresh(junc)

        now = datetime.now(timezone.utc)
        sig_healthy = Signal(
            intersection_id=junc.id,
            code=f"SIG-HLTH-{uid.upper()}-1",
            status="active",
            observed_state="green",
            observed_confidence=0.98,
            observed_at=now - timedelta(seconds=15),
        )
        sig_faulty = Signal(
            intersection_id=junc.id,
            code=f"SIG-FLT-{uid.upper()}-2",
            status="fault",
            observed_state="unknown",
            observed_confidence=0.10,
            observed_at=now - timedelta(hours=2),
        )
        db.add_all([sig_healthy, sig_faulty])
        await db.commit()
        await db.refresh(sig_healthy)
        await db.refresh(sig_faulty)

        p1 = SignalPhase(
            signal_id=sig_healthy.id,
            name="Main Green",
            phase_order=1,
            duration_seconds=35,
            state="green",
            is_active=True,
        )
        p2 = SignalPhase(
            signal_id=sig_faulty.id,
            name="Side Red",
            phase_order=1,
            duration_seconds=30,
            state="red",
            is_active=True,
        )
        db.add_all([p1, p2])
        await db.commit()

        junc_id = junc.id
        healthy_id = sig_healthy.id
        faulty_id = sig_faulty.id

    yield {
        "intersection_id": junc_id,
        "healthy_signal_id": healthy_id,
        "faulty_signal_id": faulty_id,
    }

    async with AsyncSessionLocal() as db:
        await db.execute(delete(SignalPhase).where(SignalPhase.signal_id.in_([healthy_id, faulty_id])))
        await db.execute(delete(Signal).where(Signal.id.in_([healthy_id, faulty_id])))
        await db.execute(delete(Intersection).where(Intersection.id == junc_id))
        await db.commit()


async def test_get_all_signals_health_endpoint(
    async_client: AsyncClient,
    test_users: dict,
    signal_health_db_data: dict,
):
    """Test GET /api/v1/signals/health endpoint returns structured list and honest provenance."""
    officer_headers = {"Authorization": f"Bearer {test_users['officer']['token']}"}

    resp = await async_client.get(
        f"/api/v1/signals/health?intersection_id={signal_health_db_data['intersection_id']}",
        headers=officer_headers,
    )
    assert resp.status_code == 200
    data = resp.json()

    assert data["provenance"] == "heuristic"
    assert data["total"] >= 2
    assert "healthy_count" in data
    assert "at_risk_count" in data
    assert len(data["items"]) >= 2

    # Verify item schema
    item = data["items"][0]
    assert "score" in item
    assert 0 <= item["score"] <= 100
    assert item["status_band"] in ("healthy", "degraded", "at-risk")
    assert "explanation" in item
    assert "factors" in item
    assert len(item["factors"]) == 4
    assert item["provenance"] == "heuristic"


async def test_get_single_signal_health_endpoint(
    async_client: AsyncClient,
    test_users: dict,
    signal_health_db_data: dict,
):
    """Test GET /api/v1/signals/{id}/health endpoint for individual signal."""
    officer_headers = {"Authorization": f"Bearer {test_users['officer']['token']}"}
    sig_id = signal_health_db_data["healthy_signal_id"]

    resp = await async_client.get(
        f"/api/v1/signals/{sig_id}/health",
        headers=officer_headers,
    )
    assert resp.status_code == 200
    item = resp.json()

    assert item["signal_id"] == sig_id
    assert item["score"] >= 80
    assert item["status_band"] == "healthy"
    assert item["provenance"] == "heuristic"
    assert len(item["factors"]) == 4


async def test_get_single_signal_health_not_found(
    async_client: AsyncClient,
    test_users: dict,
):
    """Test GET /api/v1/signals/{id}/health returns 404 for non-existent signal."""
    officer_headers = {"Authorization": f"Bearer {test_users['officer']['token']}"}

    resp = await async_client.get(
        "/api/v1/signals/9999999/health",
        headers=officer_headers,
    )
    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"].lower()


async def test_signals_health_rbac(
    async_client: AsyncClient,
    test_users: dict,
    signal_health_db_data: dict,
):
    """Test RBAC access permissions for signal health endpoints."""
    sig_id = signal_health_db_data["healthy_signal_id"]

    # 1. 401 unauthenticated
    resp_unauth = await async_client.get("/api/v1/signals/health")
    assert resp_unauth.status_code == 401

    resp_single_unauth = await async_client.get(f"/api/v1/signals/{sig_id}/health")
    assert resp_single_unauth.status_code == 401

    # 2. Analyst role can inspect signal health (read-only monitoring)
    analyst_headers = {"Authorization": f"Bearer {test_users['analyst']['token']}"}
    resp_analyst = await async_client.get(
        f"/api/v1/signals/{sig_id}/health",
        headers=analyst_headers,
    )
    assert resp_analyst.status_code == 200
    assert resp_analyst.json()["status_band"] == "healthy"
