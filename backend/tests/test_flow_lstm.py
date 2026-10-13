"""Tests for PyTorch Flow LSTM forecasting model, registry, and inference API.

Validates:
- Deterministic synthetic frame generation and fast CPU training.
- ModelRegistry persistence with architecture='lstm', training_rows, training_data_provenance.
- PostgreSQL MLModel catalog registration.
- POST /api/v1/forecasting/lstm/predict:
  - 200 for officer/admin role.
  - Response contains model_name, provenance, prediction_horizon, confidence, uncertainty, prediction_interval.
  - Insufficient-data path returns diagnostic row counts without fabricating predictions.
- RBAC permissions (401 unauthenticated, 403 analyst for training).
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path
import shutil
import uuid

from httpx import AsyncClient
import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ai.forecasting.lstm import FlowLSTM, DEFAULT_SEQUENCE_LENGTH
from ai.forecasting.registry import DEFAULT_ARTIFACTS_DIR, ModelRegistry
from app.core.database import AsyncSessionLocal, engine
from app.models.ai import AIPrediction
from app.models.intersection import Intersection
from app.models.ml import MLModel
from app.models.traffic import TrafficRecord
from app.services.flow_lstm import (
    DEFAULT_LSTM_ARTIFACTS_DIR,
    predict_flow_lstm,
    train_and_register_flow_lstm,
)

pytestmark = pytest.mark.anyio


@pytest.fixture(autouse=True)
async def dispose_engine_per_test():
    """Ensure SQLAlchemy connection pool does not leak across anyio test event loops."""
    yield
    await engine.dispose()


@pytest.fixture(scope="module", autouse=True)
def clean_lstm_artifacts():
    """Ensure test artifacts directory is cleaned after tests finish."""
    yield
    test_root = DEFAULT_ARTIFACTS_DIR / "flow_lstm_test"
    if test_root.exists():
        shutil.rmtree(test_root, ignore_errors=True)


@pytest.fixture
async def lstm_test_data():
    """Seed test intersections and sequential 5-minute traffic records using isolated session."""
    uid = uuid.uuid4().hex[:6]
    async with AsyncSessionLocal() as db:
        int_sufficient = Intersection(
            name=f"LSTM Sufficient Int {uid}",
            code=f"LSTM-OK-{uid.upper()}",
            status="active",
            lat=37.7749,
            lon=-122.4194,
        )
        int_insufficient = Intersection(
            name=f"LSTM Insufficient Int {uid}",
            code=f"LSTM-FEW-{uid.upper()}",
            status="active",
            lat=37.7849,
            lon=-122.4094,
        )
        db.add_all([int_sufficient, int_insufficient])
        await db.commit()
        await db.refresh(int_sufficient)
        await db.refresh(int_insufficient)

        sufficient_id = int_sufficient.id
        insufficient_id = int_insufficient.id

        now = datetime.now(timezone.utc)

        # 1. Sufficient intersection has 30 records (> DEFAULT_SEQUENCE_LENGTH 12)
        records: list[TrafficRecord] = []
        for i in range(30):
            ts = now - timedelta(minutes=5 * (29 - i))
            records.append(
                TrafficRecord(
                    intersection_id=sufficient_id,
                    recorded_at=ts,
                    vehicle_count=25 + (i % 8),
                    avg_speed_kmh=48.0,
                    congestion_level=20 + (i % 5),
                    source="sensor",
                )
            )

        # 2. Insufficient intersection has only 4 records (< 12)
        for i in range(4):
            ts = now - timedelta(minutes=5 * (3 - i))
            records.append(
                TrafficRecord(
                    intersection_id=insufficient_id,
                    recorded_at=ts,
                    vehicle_count=10,
                    avg_speed_kmh=50.0,
                    congestion_level=10,
                    source="sensor",
                )
            )

        db.add_all(records)
        await db.commit()

    yield {
        "sufficient_id": sufficient_id,
        "insufficient_id": insufficient_id,
    }

    # Teardown
    async with AsyncSessionLocal() as db:
        await db.execute(delete(TrafficRecord).where(TrafficRecord.intersection_id.in_([sufficient_id, insufficient_id])))
        await db.execute(delete(AIPrediction).where(AIPrediction.intersection_id.in_([sufficient_id, insufficient_id])))
        await db.execute(delete(Intersection).where(Intersection.id.in_([sufficient_id, insufficient_id])))
        await db.commit()


async def test_flow_lstm_unit_fit_and_mc_uncertainty():
    """Verify PyTorch FlowLSTM fits on sequence frame and outputs valid MC uncertainty."""
    import pandas as pd

    now = datetime.now(timezone.utc)
    data = [
        {
            "recorded_at": now - timedelta(minutes=5 * (50 - i)),
            "intersection_id": 1,
            "vehicle_count": 30 + (i % 10),
            "avg_speed_kmh": 45.0,
            "congestion_level": 25,
        }
        for i in range(50)
    ]
    df = pd.DataFrame(data)

    model = FlowLSTM(sequence_length=12, horizon_steps=6, hidden_size=32, num_layers=1)
    metrics = model.fit(df, epochs=3, batch_size=32)

    assert "mae" in metrics
    assert "rmse" in metrics
    assert metrics["sequence_count"] > 0

    pred = model.predict_with_uncertainty(df.tail(12), num_mc_samples=10)
    assert "predicted_flow" in pred
    assert pred["predicted_flow"] >= 0.0
    assert "uncertainty" in pred
    assert pred["uncertainty"] >= 0.0
    assert 0.0 <= pred["confidence"] <= 1.0
    assert len(pred["prediction_interval"]) == 2
    assert pred["prediction_interval"][0] <= pred["prediction_interval"][1]


async def test_train_and_register_flow_lstm(tmp_path: Path):
    """Verify train_and_register_flow_lstm catalogs model with architecture='lstm' and provenance."""
    custom_root = tmp_path / "lstm_artifacts"

    async with AsyncSessionLocal() as session:
        report = await train_and_register_flow_lstm(
            db=session,
            days=7,
            force_synthetic=True,
            seed=42,
            epochs=2,
            registry_root=custom_root,
            notes="PyTest automated LSTM registration",
        )

        assert report["architecture"] == "lstm"
        assert report["name"] == "flow_lstm"
        assert report["version"].startswith("v")
        assert report["training_data_provenance"] == "synthetic-deterministic-seed-42"
        assert report["training_rows"] > 0
        assert "mae" in report["metrics"]

        # Verify disk ModelRegistry metadata
        reg = ModelRegistry(root=custom_root)
        model, metadata = reg.get_latest()
        assert isinstance(model, FlowLSTM)
        assert metadata["architecture"] == "lstm"
        assert metadata["training_data_provenance"] == "synthetic-deterministic-seed-42"
        assert metadata["training_rows"] == report["training_rows"]

        # Verify PostgreSQL MLModel record
        stmt = select(MLModel).where(MLModel.id == report["id"])
        res = await session.execute(stmt)
        ml_row = res.scalar_one_or_none()
        assert ml_row is not None
        assert ml_row.name == "flow_lstm"
        assert ml_row.version == report["version"]
        assert ml_row.data_summary["architecture"] == "lstm"


async def test_predict_flow_lstm_service(lstm_test_data: dict, tmp_path: Path):
    """Verify predict_flow_lstm service evaluates sufficient vs insufficient intersections."""
    custom_root = tmp_path / "lstm_artifacts_pred"

    async with AsyncSessionLocal() as session:
        # Train and register first
        await train_and_register_flow_lstm(
            db=session,
            days=7,
            force_synthetic=True,
            seed=42,
            epochs=2,
            registry_root=custom_root,
        )

        res = await predict_flow_lstm(
            db=session,
            intersection_ids=[lstm_test_data["sufficient_id"], lstm_test_data["insufficient_id"]],
            horizon_minutes=30,
            registry_root=custom_root,
        )

        predictions = res["predictions"]
        insufficient = res["insufficient"]

        # 1. Sufficient intersection produces valid prediction
        assert len(predictions) == 1
        p = predictions[0]
        assert p["intersection_id"] == lstm_test_data["sufficient_id"]
        assert p["model_name"] == "flow_lstm"
        assert p["prediction_horizon"] == 30
        assert p["provenance"] == "synthetic-deterministic-seed-42"
        assert p["predicted_flow"] >= 0.0
        assert 0.0 <= p["confidence"] <= 1.0
        assert p["uncertainty"] >= 0.0
        assert len(p["prediction_interval"]) == 2

        # 2. Insufficient intersection has diagnostic row counts
        assert len(insufficient) == 1
        ins = insufficient[0]
        assert ins["intersection_id"] == lstm_test_data["insufficient_id"]
        assert ins["status"] == "insufficient_data"
        assert ins["rows_found"] == 4
        assert ins["rows_required"] == DEFAULT_SEQUENCE_LENGTH
        assert "minimum 12" in ins["message"].lower() or "minimum" in ins["message"].lower()

        # 3. Check AIPrediction row was stored for the successful prediction
        stmt = select(AIPrediction).where(
            AIPrediction.intersection_id == lstm_test_data["sufficient_id"],
            AIPrediction.prediction_type == "flow_lstm",
        )
        db_pred = (await session.execute(stmt)).scalar_one_or_none()
        assert db_pred is not None
        assert db_pred.payload["model_name"] == "flow_lstm"
        assert db_pred.payload["confidence"] == p["confidence"]


async def test_lstm_predict_api_endpoint(
    async_client: AsyncClient,
    test_users: dict,
    lstm_test_data: dict,
):
    """Test POST /api/v1/forecasting/lstm/predict endpoint."""
    async with AsyncSessionLocal() as session:
        # Ensure a model is registered in the default flow_lstm registry
        await train_and_register_flow_lstm(
            db=session,
            days=7,
            force_synthetic=True,
            seed=42,
            epochs=2,
        )

    officer_headers = {"Authorization": f"Bearer {test_users['officer']['token']}"}

    payload = {
        "intersection_ids": [lstm_test_data["sufficient_id"], lstm_test_data["insufficient_id"]],
        "horizon_minutes": 30,
    }

    resp = await async_client.post(
        "/api/v1/forecasting/lstm/predict",
        json=payload,
        headers=officer_headers,
    )
    assert resp.status_code == 200
    body = resp.json()

    assert "predictions" in body
    assert "insufficient" in body
    assert len(body["predictions"]) == 1
    assert len(body["insufficient"]) == 1

    item = body["predictions"][0]
    assert item["model_name"] == "flow_lstm"
    assert "provenance" in item
    assert item["prediction_horizon"] == 30
    assert "confidence" in item
    assert "uncertainty" in item
    assert "prediction_interval" in item
    assert item["status"] == "predicted"


async def test_lstm_api_rbac(
    async_client: AsyncClient,
    test_users: dict,
    lstm_test_data: dict,
):
    """Test RBAC restrictions for LSTM prediction and training endpoints."""
    analyst_headers = {"Authorization": f"Bearer {test_users['analyst']['token']}"}
    admin_headers = {"Authorization": f"Bearer {test_users['admin']['token']}"}

    # 1. 401 for unauthenticated request
    resp = await async_client.post(
        "/api/v1/forecasting/lstm/predict",
        json={"intersection_ids": [lstm_test_data["sufficient_id"]]},
    )
    assert resp.status_code == 401

    # 2. Analyst is forbidden from training (admin only)
    train_resp = await async_client.post(
        "/api/v1/forecasting/lstm/train",
        json={"days": 14, "notes": "analyst attempt"},
        headers=analyst_headers,
    )
    assert train_resp.status_code == 403

    # 3. Admin can train via API
    admin_train_resp = await async_client.post(
        "/api/v1/forecasting/lstm/train",
        json={"days": 14, "notes": "admin training test"},
        headers=admin_headers,
    )
    assert admin_train_resp.status_code == 200
    assert admin_train_resp.json()["architecture"] == "lstm"
