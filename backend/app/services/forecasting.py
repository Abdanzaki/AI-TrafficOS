"""Traffic forecasting service module.

Coordinates telemetry dataset assembly, model training via ai.forecasting.pipeline,
artifact cataloging in ml_models, inference execution, and persistent storage
of multi-target predictions in ai_predictions.
"""

from datetime import datetime, timedelta, timezone
import logging
from pathlib import Path
from typing import Any, Optional, Union

import pandas as pd
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ai.forecasting.exceptions import InsufficientDataError
from ai.forecasting.features import build_feature_frame
from ai.forecasting.pipeline import load_latest_forecaster, train_pipeline
from ai.forecasting.registry import DEFAULT_ARTIFACTS_DIR, ModelRegistry
from app.models.ai import AIPrediction
from app.models.ml import MLModel
from app.models.traffic import TrafficRecord

logger = logging.getLogger(__name__)


class ForecastingInsufficientDataError(Exception):
    """Raised when telemetry data is insufficient for model training or feature generation."""

    def __init__(
        self,
        rows_found: int,
        rows_required: int,
        message: Optional[str] = None,
        intersection_id: Optional[int] = None,
    ) -> None:
        self.rows_found: int = int(rows_found)
        self.rows_required: int = int(rows_required)
        self.intersection_id: Optional[int] = intersection_id
        if message is None:
            message = (
                f"Insufficient telemetry data for forecasting model: found {self.rows_found} rows, "
                f"but a minimum of {self.rows_required} rows is required."
            )
        self.message: str = message
        super().__init__(message)


class ForecastingModelNotFoundError(Exception):
    """Raised when no trained forecasting model exists in the registry."""

    def __init__(self, message: Optional[str] = None) -> None:
        if message is None:
            message = "No forecasting models found in registry. Train a model first."
        super().__init__(message)


async def load_training_frame(
    db: AsyncSession,
    intersection_ids: Optional[list[int]] = None,
    days: int = 21,
) -> pd.DataFrame:
    """Query traffic_records for the designated window and map to feature frame schema.

    Args:
        db: Active asynchronous SQLAlchemy session.
        intersection_ids: Optional list of target intersection IDs. If None, queries
            records for all intersections present in the window.
        days: Historical lookback duration in days.

    Returns:
        pandas DataFrame conforming to the forecasting feature frame contract
        (recorded_at, intersection_id, vehicle_count, avg_speed_kmh, congestion_level, lane_id=None).
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    stmt = (
        select(TrafficRecord)
        .where(TrafficRecord.recorded_at >= cutoff)
        .order_by(TrafficRecord.intersection_id, TrafficRecord.recorded_at.asc())
    )

    if intersection_ids:
        stmt = stmt.where(TrafficRecord.intersection_id.in_(intersection_ids))

    res = await db.execute(stmt)
    records = res.scalars().all()

    if not records:
        return pd.DataFrame(
            columns=[
                "recorded_at",
                "intersection_id",
                "vehicle_count",
                "avg_speed_kmh",
                "congestion_level",
                "lane_id",
                "source",
            ]
        )

    data = [
        {
            "recorded_at": r.recorded_at,
            "intersection_id": r.intersection_id,
            "vehicle_count": r.vehicle_count,
            "avg_speed_kmh": r.avg_speed_kmh if r.avg_speed_kmh is not None else 50.0,
            "congestion_level": r.congestion_level,
            "lane_id": None,
            "source": r.source,
        }
        for r in records
    ]

    return pd.DataFrame(data)


async def train_and_register(
    db: AsyncSession,
    intersection_ids: Optional[list[int]] = None,
    days: int = 21,
    notes: Optional[str] = None,
    registry_root: Optional[Union[Path, str]] = None,
) -> dict[str, Any]:
    """Load historical telemetry, fit multi-target forecaster, and record in ml_models.

    Workflow:
    1. Query database traffic_records over the lookback window.
    2. Filter synthetic telemetry rows if real sensor/camera sources exist in the dataset.
    3. Invoke ai.forecasting.pipeline.train_pipeline.
    4. Persist model registration record in ml_models table.
    5. Return training report dictionary including newly created database model ID.

    Raises:
        ForecastingInsufficientDataError: If telemetry volume is below pipeline minimum.
    """
    df = await load_training_frame(db, intersection_ids, days)

    # If the frame has a 'source' mix, prioritize real rows if volume meets pipeline threshold
    if "source" in df.columns:
        sources = set(df["source"].dropna().unique())
        has_real = any(s != "synthetic" for s in sources)
        has_synthetic = "synthetic" in sources
        if has_real and has_synthetic:
            real_df = df[df["source"] != "synthetic"]
            if len(real_df) >= 2000:
                df = real_df.copy()

    try:
        report = train_pipeline(
            records_df=df,
            notes=notes or "",
            registry_root=registry_root,
        )
    except InsufficientDataError as exc:
        raise ForecastingInsufficientDataError(
            rows_found=exc.rows_found,
            rows_required=exc.rows_required,
            message=str(exc),
        ) from exc

    # Determine artifact storage directory
    reg = ModelRegistry(root=registry_root)
    artifact_path = str(reg.root / report["version"])

    stmt = select(MLModel).where(
        MLModel.name == "traffic_forecaster",
        MLModel.version == report["version"],
    )
    res = await db.execute(stmt)
    ml_model = res.scalar_one_or_none()

    if ml_model is None:
        ml_model = MLModel(
            name="traffic_forecaster",
            version=report["version"],
            artifact_path=artifact_path,
            metrics=report.get("metrics", {}),
            data_summary=report.get("data_summary"),
            feature_names=report.get("feature_names"),
            horizon_steps=report.get("horizon_info", {}).get("steps", 6),
            notes=notes,
        )
        db.add(ml_model)
    else:
        ml_model.artifact_path = artifact_path
        ml_model.metrics = report.get("metrics", {})
        ml_model.data_summary = report.get("data_summary")
        ml_model.feature_names = report.get("feature_names")
        ml_model.horizon_steps = report.get("horizon_info", {}).get("steps", 6)
        ml_model.notes = notes

    await db.flush()
    await db.commit()

    report["id"] = ml_model.id
    report["db_id"] = ml_model.id

    logger.info(
        "Model successfully registered: version=%s, db_id=%d, test_r2=%s",
        ml_model.version,
        ml_model.id,
        report.get("metrics", {}).get("y_congestion", {}).get("test_r2"),
    )

    return report


async def predict_and_store(
    db: AsyncSession,
    intersection_ids: list[int],
    registry_root: Optional[Union[Path, str]] = None,
) -> list[dict[str, Any]]:
    """Execute predictive inference on latest 24h telemetry and persist AIPrediction records.

    For each intersection:
    - Loads the most recent 24h of traffic_records.
    - Requires at least 20 contiguous observations to engineer temporal lag features.
    - If data is deficient, marks intersection 'insufficient_data' with row counts.
    - Never fabricates synthetic predictions for under-sampled intersections.
    - Constructs feature representations and takes the final row for inference.
    - Evaluates point predictions and dispersion confidence intervals.
    - Persists two AIPrediction records:
        1. 'flow' prediction for vehicular volume (y_volume).
        2. 'congestion' prediction for saturation and queue risk (y_congestion, y_queue).
    - Returns structured list of results.

    Raises:
        ForecastingModelNotFoundError: If no models exist in ModelRegistry.
    """
    try:
        forecaster, metadata = load_latest_forecaster(registry_root=registry_root)
    except FileNotFoundError as exc:
        raise ForecastingModelNotFoundError(
            "No forecasting models registered in registry. Train a model before requesting predictions."
        ) from exc

    version = metadata.get("version", "unknown")
    now = datetime.now(timezone.utc)
    cutoff_24h = now - timedelta(hours=24)
    predicted_for = now + timedelta(minutes=30)

    results: list[dict[str, Any]] = []

    for iid in intersection_ids:
        stmt = (
            select(TrafficRecord)
            .where(
                TrafficRecord.intersection_id == iid,
                TrafficRecord.recorded_at >= cutoff_24h,
            )
            .order_by(TrafficRecord.recorded_at.asc())
        )
        res = await db.execute(stmt)
        records = res.scalars().all()
        count = len(records)

        # Require at least ~20 rows to build lag features; else mark that intersection 'insufficient_data'
        if count < 20:
            results.append({
                "intersection_id": iid,
                "status": "insufficient_data",
                "rows_found": count,
                "rows_required": 20,
                "message": (
                    f"Intersection {iid} has {count} telemetry records in the last 24 hours. "
                    "A minimum of 20 contiguous records is required to engineer temporal lag features."
                ),
            })
            continue

        df_recent = pd.DataFrame([
            {
                "recorded_at": r.recorded_at,
                "intersection_id": r.intersection_id,
                "vehicle_count": r.vehicle_count,
                "avg_speed_kmh": r.avg_speed_kmh if r.avg_speed_kmh is not None else 50.0,
                "congestion_level": r.congestion_level,
                "lane_id": None,
                "source": r.source,
            }
            for r in records
        ])

        X, _, _ = build_feature_frame(df_recent)
        if X.empty:
            results.append({
                "intersection_id": iid,
                "status": "insufficient_data",
                "rows_found": count,
                "rows_required": 20,
                "message": (
                    f"Intersection {iid} could not produce lag feature matrix from {count} records."
                ),
            })
            continue

        inference_input = X.iloc[[-1]]
        preds_dict = forecaster.predict_with_confidence(inference_input)

        vol_val = max(0.0, float(preds_dict["y_volume"]["value"][0]))
        vol_conf = max(0.0, min(1.0, float(preds_dict["y_volume"]["confidence"][0])))
        cong_val = max(0.0, min(100.0, float(preds_dict["y_congestion"]["value"][0])))
        cong_conf = max(0.0, min(1.0, float(preds_dict["y_congestion"]["confidence"][0])))
        queue_val = max(0.0, min(100.0, float(preds_dict["y_queue"]["value"][0])))
        queue_conf = max(0.0, min(1.0, float(preds_dict["y_queue"]["confidence"][0])))

        flow_payload = {
            "target": "y_volume",
            "value": round(vol_val, 2),
            "confidence": round(vol_conf, 4),
            "horizon_minutes": 30,
            "intersection_id": iid,
            "model_version": version,
        }
        cong_payload = {
            "target": "congestion",
            "value": round(cong_val, 2),
            "congestion": round(cong_val, 2),
            "queue": round(queue_val, 2),
            "confidence": round(cong_conf, 4),
            "queue_confidence": round(queue_conf, 4),
            "horizon_minutes": 30,
            "intersection_id": iid,
            "model_version": version,
        }

        flow_pred = AIPrediction(
            intersection_id=iid,
            prediction_type="flow",
            predicted_for=predicted_for,
            payload=flow_payload,
            confidence=round(vol_conf, 4),
            model_version=version,
        )
        cong_pred = AIPrediction(
            intersection_id=iid,
            prediction_type="congestion",
            predicted_for=predicted_for,
            payload=cong_payload,
            confidence=round(cong_conf, 4),
            model_version=version,
        )

        db.add(flow_pred)
        db.add(cong_pred)
        await db.flush()

        results.append({
            "intersection_id": iid,
            "status": "predicted",
            "predicted_for": predicted_for.isoformat(),
            "model_version": version,
            "flow": {
                "prediction_id": flow_pred.id,
                "prediction_type": "flow",
                "value": round(vol_val, 2),
                "confidence": round(vol_conf, 4),
                "payload": flow_payload,
            },
            "congestion": {
                "prediction_id": cong_pred.id,
                "prediction_type": "congestion",
                "value": round(cong_val, 2),
                "confidence": round(cong_conf, 4),
                "queue": round(queue_val, 2),
                "payload": cong_payload,
            },
            "prediction_ids": [flow_pred.id, cong_pred.id],
        })

    await db.commit()
    return results
