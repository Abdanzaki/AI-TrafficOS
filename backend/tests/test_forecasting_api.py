"""Integration tests for traffic forecasting REST API endpoints (/api/v1/forecasting).

Validates:
- POST /forecasting/train:
  - 401 unauthenticated
  - 403 for analyst role (restricted to admin)
  - 200 for admin role with version and metrics report
  - Persists MLModel record in PostgreSQL database
- POST /forecasting/predict:
  - 200 for officer role returning multi-target predictions
  - Predictions contain value, confidence in [0, 1], and model_version
  - Persists AIPrediction records in PostgreSQL database
  - Returns intersections with insufficient telemetry under 'insufficient' list
  - Never writes AIPrediction rows for insufficient intersections
- GET /forecasting/models/latest:
  - 200 for analyst role returning latest model metadata and metrics
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path
import shutil
import uuid
from httpx import AsyncClient
import pytest
from sqlalchemy import delete, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from ai.forecasting.registry import DEFAULT_ARTIFACTS_DIR, ModelRegistry
from app.models.ai import AIPrediction
from app.models.intersection import Intersection
from app.models.ml import MLModel
from app.models.traffic import TrafficRecord

pytestmark = pytest.mark.anyio


@pytest.fixture(scope="module", autouse=True)
def clean_test_artifacts():
    """Ensure artifacts directory is cleaned after all tests in module finish."""
    yield
    if DEFAULT_ARTIFACTS_DIR.exists():
        shutil.rmtree(DEFAULT_ARTIFACTS_DIR, ignore_errors=True)


@pytest.fixture
async def forecasting_test_data(db_session: AsyncSession):
    """Seed test intersections and 9 days of synthetic 5-minute traffic records."""
    uid = uuid.uuid4().hex[:6]
    int_1 = Intersection(
        name=f"Forecast Int 1 {uid}",
        code=f"FC-1-{uid.upper()}",
        status="active",
        lat=37.7749,
        lon=-122.4194,
    )
    int_2 = Intersection(
        name=f"Forecast Int 2 {uid}",
        code=f"FC-2-{uid.upper()}",
        status="active",
        lat=37.7849,
        lon=-122.4094,
    )
    int_empty = Intersection(
        name=f"Forecast Empty {uid}",
        code=f"FC-E-{uid.upper()}",
        status="active",
        lat=37.7949,
        lon=-122.3994,
    )
    db_session.add_all([int_1, int_2, int_empty])
    await db_session.commit()
    await db_session.refresh(int_1)
    await db_session.refresh(int_2)
    await db_session.refresh(int_empty)

    # 9 days of 5-min intervals: 9 * 288 = 2592 intervals per intersection
    # Total = 5184 records (well above 2000 MIN_PIPELINE_ROWS)
    now = datetime.now(timezone.utc)
    records: list[dict] = []
    total_intervals = 9 * 288

    for i in range(total_intervals):
        ts = now - timedelta(minutes=5 * (total_intervals - 1 - i))
        hour = ts.hour
        is_rush = 1 if (7 <= hour <= 9 or 16 <= hour <= 19) else 0

        v1 = 30 + 25 * is_rush + (i % 7)
        c1 = 20 + 35 * is_rush + (i % 5)
        v2 = 25 + 20 * is_rush + (i % 6)
        c2 = 15 + 30 * is_rush + (i % 4)

        records.append({
            "intersection_id": int_1.id,
            "recorded_at": ts,
            "vehicle_count": v1,
            "avg_speed_kmh": round(50.0 - (c1 * 0.3), 1),
            "congestion_level": c1,
            "source": "synthetic",
        })
        records.append({
            "intersection_id": int_2.id,
            "recorded_at": ts,
            "vehicle_count": v2,
            "avg_speed_kmh": round(52.0 - (c2 * 0.3), 1),
            "congestion_level": c2,
            "source": "synthetic",
        })

    await db_session.execute(insert(TrafficRecord).values(records))
    await db_session.commit()

    yield {
        "int_1": int_1,
        "int_2": int_2,
        "int_empty": int_empty,
        "intersection_ids": [int_1.id, int_2.id],
    }

    # Teardown database rows
    await db_session.execute(
        delete(TrafficRecord).where(
            TrafficRecord.intersection_id.in_([int_1.id, int_2.id, int_empty.id])
        )
    )
    await db_session.execute(
        delete(AIPrediction).where(
            AIPrediction.intersection_id.in_([int_1.id, int_2.id, int_empty.id])
        )
    )
    await db_session.execute(
        delete(Intersection).where(
            Intersection.id.in_([int_1.id, int_2.id, int_empty.id])
        )
    )
    await db_session.commit()


async def _ensure_model_trained(async_client: AsyncClient, test_users: dict) -> dict:
    """Helper ensuring at least one model exists in the registry."""
    reg = ModelRegistry()
    try:
        _, meta = reg.get_latest()
        return meta
    except FileNotFoundError:
        admin_headers = {"Authorization": f"Bearer {test_users['admin']['token']}"}
        resp = await async_client.post(
            "/api/v1/forecasting/train",
            headers=admin_headers,
            json={"days": 14, "notes": "Test setup model"},
        )
        assert resp.status_code == 200, resp.text
        return resp.json()


async def test_forecasting_train_auth_and_permissions(
    async_client: AsyncClient,
    test_users: dict,
):
    """Verify RBAC on POST /api/v1/forecasting/train: 401 unauth, 403 analyst."""
    # 1. Unauthenticated request
    resp_unauth = await async_client.post(
        "/api/v1/forecasting/train",
        json={"days": 14},
    )
    assert resp_unauth.status_code == 401

    # 2. Analyst request (insufficient role)
    analyst_headers = {"Authorization": f"Bearer {test_users['analyst']['token']}"}
    resp_analyst = await async_client.post(
        "/api/v1/forecasting/train",
        headers=analyst_headers,
        json={"days": 14},
    )
    assert resp_analyst.status_code == 403


async def test_forecasting_train_as_admin(
    async_client: AsyncClient,
    test_users: dict,
    db_session: AsyncSession,
    forecasting_test_data: dict,
):
    """Verify POST /api/v1/forecasting/train succeeds as admin and creates MLModel row."""
    admin_headers = {"Authorization": f"Bearer {test_users['admin']['token']}"}
    resp = await async_client.post(
        "/api/v1/forecasting/train",
        headers=admin_headers,
        json={"days": 14, "notes": "Admin integration test training"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()

    assert "version" in data
    assert "metrics" in data
    assert "n_train_rows" in data
    assert data["n_train_rows"] > 0
    version = data["version"]

    # Verify ml_models DB row
    stmt = select(MLModel).where(MLModel.version == version)
    res = await db_session.execute(stmt)
    ml_row = res.scalar_one_or_none()
    assert ml_row is not None
    assert ml_row.version == version
    assert ml_row.name == "traffic_forecaster"
    assert ml_row.notes == "Admin integration test training"


async def test_forecasting_predict_as_officer(
    async_client: AsyncClient,
    test_users: dict,
    db_session: AsyncSession,
    forecasting_test_data: dict,
):
    """Verify POST /api/v1/forecasting/predict generates and stores predictions."""
    await _ensure_model_trained(async_client, test_users)

    int_1_id = forecasting_test_data["int_1"].id
    int_2_id = forecasting_test_data["int_2"].id

    officer_headers = {"Authorization": f"Bearer {test_users['officer']['token']}"}
    resp = await async_client.post(
        "/api/v1/forecasting/predict",
        headers=officer_headers,
        json={"intersection_ids": [int_1_id, int_2_id]},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()

    predictions = data["predictions"]
    assert len(predictions) == 2

    for pred in predictions:
        assert pred["status"] == "predicted"
        assert pred["model_version"] is not None
        assert pred["intersection_id"] in [int_1_id, int_2_id]

        # Flow target
        flow = pred["flow"]
        assert "value" in flow
        assert isinstance(flow["value"], (int, float))
        assert "confidence" in flow
        assert 0.0 <= flow["confidence"] <= 1.0

        # Congestion target
        congestion = pred["congestion"]
        assert "value" in congestion
        assert isinstance(congestion["value"], (int, float))
        assert "confidence" in congestion
        assert 0.0 <= congestion["confidence"] <= 1.0

    # Verify ai_predictions rows exist in DB
    stmt = select(AIPrediction).where(
        AIPrediction.intersection_id.in_([int_1_id, int_2_id])
    )
    res = await db_session.execute(stmt)
    ai_preds = res.scalars().all()
    # At least 2 predictions (flow, congestion) per intersection
    assert len(ai_preds) >= 4
    for ap in ai_preds:
        assert ap.confidence is not None
        assert 0.0 <= ap.confidence <= 1.0
        assert ap.model_version is not None
        assert ap.prediction_type in ["flow", "congestion"]


async def test_forecasting_predict_insufficient_data(
    async_client: AsyncClient,
    test_users: dict,
    db_session: AsyncSession,
    forecasting_test_data: dict,
):
    """Verify predict returns insufficient intersections and writes NO prediction rows."""
    await _ensure_model_trained(async_client, test_users)

    int_empty_id = forecasting_test_data["int_empty"].id

    officer_headers = {"Authorization": f"Bearer {test_users['officer']['token']}"}
    resp = await async_client.post(
        "/api/v1/forecasting/predict",
        headers=officer_headers,
        json={"intersection_ids": [int_empty_id]},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()

    assert len(data["predictions"]) == 0
    assert len(data["insufficient"]) == 1

    item = data["insufficient"][0]
    assert item["intersection_id"] == int_empty_id
    assert item["status"] == "insufficient_data"
    assert item["rows_found"] == 0
    assert item["rows_required"] == 20

    # Guarantee NO prediction row is written for the empty intersection
    stmt = select(AIPrediction).where(AIPrediction.intersection_id == int_empty_id)
    res = await db_session.execute(stmt)
    assert len(res.scalars().all()) == 0


async def test_forecasting_models_latest_as_analyst(
    async_client: AsyncClient,
    test_users: dict,
    forecasting_test_data: dict,
):
    """Verify GET /api/v1/forecasting/models/latest as analyst returns 200 with metrics."""
    await _ensure_model_trained(async_client, test_users)

    analyst_headers = {"Authorization": f"Bearer {test_users['analyst']['token']}"}
    resp = await async_client.get(
        "/api/v1/forecasting/models/latest",
        headers=analyst_headers,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()

    assert "version" in data
    assert data["version"] != ""
    assert "metrics" in data
    assert isinstance(data["metrics"], dict)
    assert "y_volume" in data["metrics"] or "val" in data["metrics"]
