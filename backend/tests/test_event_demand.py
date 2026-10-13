"""Tests for Event Demand Uplift Forecasting (Feature 2).

Validates:
1. Mathematical accuracy of transparent parametric gravity heuristic against documented formula.
2. Baseline flow extraction from real TrafficRecord telemetry.
3. Empty-baseline handling with explicit notes (no invented measurements or zeros).
4. Request validations (attendance <= 0 -> 422, past starts_at -> 422, missing location -> 422).
5. Response metadata: provenance='parametric-heuristic', confidence intervals, assumptions list.
"""

from datetime import datetime, timedelta, timezone
import uuid
from httpx import AsyncClient
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import engine
from app.models.intersection import Intersection
from app.models.traffic import TrafficRecord
from app.services.event_demand import (
    calculate_peak_vehicles,
    calculate_spatial_weights,
    haversine_distance_km,
)


@pytest.fixture(autouse=True)
async def clean_engine_pool():
    """Ensure connection pool is disposed between tests."""
    yield
    await engine.dispose()


@pytest.fixture
async def event_junctions(db_session: AsyncSession) -> tuple[Intersection, Intersection]:
    """Provision two test intersections: one with telemetry, one without."""
    uid = uuid.uuid4().hex[:6].upper()
    base_lat = 25.0 + (int(uid[:4], 16) % 500) * 0.05
    j1 = Intersection(
        name=f"Host Stadium Junction {uid}",
        code=f"HOST_{uid}",
        status="active",
        city="Hyderabad",
        zone="Stadium Corridor",
        lat=base_lat,
        lon=78.4500,
    )
    j2 = Intersection(
        name=f"Neighbor Junction {uid}",
        code=f"NEIGH_{uid}",
        status="active",
        city="Hyderabad",
        zone="Stadium Corridor",
        lat=base_lat + 0.009,  # ~1.0 km north
        lon=78.4500,
    )
    db_session.add_all([j1, j2])
    await db_session.flush()

    # Seed baseline telemetry only for j1 (known average vehicle_count = 150)
    now = datetime.now(timezone.utc)
    t1 = TrafficRecord(
        intersection_id=j1.id,
        vehicle_count=140,
        avg_speed_kmh=45.0,
        congestion_level=30,
        source="sensor",
        recorded_at=now - timedelta(hours=2),
    )
    t2 = TrafficRecord(
        intersection_id=j1.id,
        vehicle_count=160,
        avg_speed_kmh=42.0,
        congestion_level=35,
        source="sensor",
        recorded_at=now - timedelta(hours=1),
    )
    db_session.add_all([t1, t2])
    await db_session.commit()
    await db_session.refresh(j1)
    await db_session.refresh(j2)

    return j1, j2


@pytest.mark.anyio
async def test_pure_formula_math():
    """Unit tests verifying transparent parametric formula equations directly."""
    attendance = 12000

    # 1. Peak vehicles math
    # Low: 12000 * (0.35 / 1.8) * 0.60 = 1400
    # Base: 12000 * (0.50 / 1.5) * 0.75 = 3000
    # High: 12000 * (0.65 / 1.2) * 0.90 = 5850
    v = calculate_peak_vehicles(attendance)
    assert v["low"] == 1400
    assert v["base"] == 3000
    assert v["high"] == 5850

    # 2. Spatial gravity weight decay
    # Distances: 0.0 km and 1.0 km
    # w0 = 1 / (0.0 + 0.5)^2 = 4.0
    # w1 = 1 / (1.0 + 0.5)^2 = 1 / 2.25 = 0.4444444
    # Total = 4.4444444
    # share0 = 4.0 / 4.4444444 = 0.90
    # share1 = 0.4444444 / 4.4444444 = 0.10
    shares = calculate_spatial_weights([0.0, 1.0])
    assert pytest.approx(shares[0], abs=1e-3) == 0.90
    assert pytest.approx(shares[1], abs=1e-3) == 0.10
    assert pytest.approx(sum(shares), abs=1e-5) == 1.0


@pytest.mark.anyio
async def test_event_demand_forecast_api_and_baseline(
    async_client: AsyncClient,
    test_users: dict[str, dict[str, str | int]],
    event_junctions: tuple[Intersection, Intersection],
):
    """End-to-end POST /api/v1/events/forecast with observed baseline and empty baseline handling."""
    j1, j2 = event_junctions
    token = test_users["analyst"]["token"]

    future_start = (datetime.now(timezone.utc) + timedelta(days=3, hours=4)).isoformat()
    payload = {
        "name": "Championship Derby",
        "junction_id": j1.id,
        "starts_at": future_start,
        "expected_attendance": 10000,
        "k_nearest": 2,
    }

    resp = await async_client.post(
        "/api/v1/events/forecast",
        headers={"Authorization": f"Bearer {token}"},
        json=payload,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()

    assert data["event_name"] == "Championship Derby"
    assert data["expected_attendance"] == 10000
    assert data["provenance"] == "parametric-heuristic"
    assert data["model_type"] == "parametric-heuristic"
    assert "Parametric heuristic model" in data["documentation"]

    # Verify peak vehicle demand totals
    # Low: 10000 * (0.35/1.8) * 0.60 = 1167
    # Base: 10000 * (0.50/1.5) * 0.75 = 2500
    # High: 10000 * (0.65/1.2) * 0.90 = 4875
    totals = data["total_peak_vehicles"]
    assert totals["low"] == 1167
    assert totals["base"] == 2500
    assert totals["high"] == 4875

    # Verify assumptions list present
    assumptions = data["assumptions"]
    assert len(assumptions) >= 4
    param_keys = [a["parameter"] for a in assumptions]
    assert "mode_share" in param_keys
    assert "vehicle_occupancy" in param_keys
    assert "peak_arrival_share" in param_keys
    assert "spatial_gravity_distribution" in param_keys

    # Verify junction results
    junctions = data["junctions"]
    assert len(junctions) == 2

    # Junction 1: Host junction with real baseline (avg of 140 and 160 = 150.0)
    host_res = next(j for j in junctions if j["junction_id"] == j1.id)
    assert host_res["baseline_status"] == "observed"
    assert host_res["baseline_flow"] == 150.0
    assert host_res["distance_km"] == 0.0

    # Scenarios for host junction
    base_sc = host_res["scenarios"]["base"]
    assert base_sc["uplift_vehicles"] > 0
    assert base_sc["projected_total_flow"] == 150.0 + base_sc["uplift_vehicles"]
    assert base_sc["uplift_percentage"] is not None

    # Confidence interval [low, high]
    ci = host_res["confidence_interval"]
    assert len(ci) == 2
    assert ci[0] == host_res["scenarios"]["low"]["uplift_vehicles"]
    assert ci[1] == host_res["scenarios"]["high"]["uplift_vehicles"]
    assert ci[0] <= base_sc["uplift_vehicles"] <= ci[1]

    # Junction 2: Empty baseline telemetry
    neigh_res = next(j for j in junctions if j["junction_id"] == j2.id)
    assert neigh_res["baseline_status"] == "no_baseline_data"
    assert neigh_res["baseline_flow"] is None
    assert neigh_res["baseline_note"] is not None
    assert "Baseline flow cannot be determined" in neigh_res["baseline_note"]
    # Projected total flow is None (never 0 presented as measurement!)
    assert neigh_res["scenarios"]["base"]["projected_total_flow"] is None
    assert neigh_res["scenarios"]["base"]["uplift_percentage"] is None


@pytest.mark.anyio
async def test_event_demand_forecast_validation(
    async_client: AsyncClient,
    test_users: dict[str, dict[str, str | int]],
    event_junctions: tuple[Intersection, Intersection],
):
    """Validation rejections: negative attendance, past date, and missing location."""
    j1, _ = event_junctions
    token = test_users["admin"]["token"]
    future_time = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
    past_time = (datetime.now(timezone.utc) - timedelta(hours=5)).isoformat()

    # 1. Negative attendance -> 422
    resp_neg = await async_client.post(
        "/api/v1/events/forecast",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "name": "Negative Test",
            "junction_id": j1.id,
            "starts_at": future_time,
            "expected_attendance": -500,
        },
    )
    assert resp_neg.status_code == 422

    # 2. Zero attendance -> 422
    resp_zero = await async_client.post(
        "/api/v1/events/forecast",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "name": "Zero Test",
            "junction_id": j1.id,
            "starts_at": future_time,
            "expected_attendance": 0,
        },
    )
    assert resp_zero.status_code == 422

    # 3. Past starts_at -> 422
    resp_past = await async_client.post(
        "/api/v1/events/forecast",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "name": "Past Event Test",
            "junction_id": j1.id,
            "starts_at": past_time,
            "expected_attendance": 5000,
        },
    )
    assert resp_past.status_code == 422

    # 4. Missing both junction_id and (lat, lng) -> 422
    resp_no_loc = await async_client.post(
        "/api/v1/events/forecast",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "name": "No Location Test",
            "starts_at": future_time,
            "expected_attendance": 5000,
        },
    )
    assert resp_no_loc.status_code == 422

    # 5. Non-existent junction_id -> 404
    resp_not_found = await async_client.post(
        "/api/v1/events/forecast",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "name": "404 Junction Test",
            "junction_id": 99999999,
            "starts_at": future_time,
            "expected_attendance": 5000,
        },
    )
    assert resp_not_found.status_code == 404
