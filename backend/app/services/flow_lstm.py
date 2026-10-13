"""Traffic flow deep-learning prediction service using PyTorch LSTM.

Coordinates sequence dataset preparation from TrafficRecord history, deterministic
synthetic bootstrapping when observed records are insufficient, model training,
artifact cataloging via ModelRegistry and ml_models, and predictive inference with
honest Monte Carlo dropout uncertainty quantification.
"""

from datetime import datetime, timedelta, timezone
import logging
from pathlib import Path
from typing import Any, Optional, Union

import pandas as pd
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ai.forecasting.lstm import FlowLSTM, DEFAULT_SEQUENCE_LENGTH, DEFAULT_HORIZON_STEPS
from ai.forecasting.registry import DEFAULT_ARTIFACTS_DIR, ModelRegistry
from ai.forecasting.synthetic import SyntheticTrafficGenerator
from app.models.ai import AIPrediction
from app.models.ml import MLModel
from app.models.traffic import TrafficRecord
from app.services.forecasting import (
    ForecastingInsufficientDataError,
    ForecastingModelNotFoundError,
    load_training_frame,
)

logger = logging.getLogger(__name__)

DEFAULT_LSTM_ARTIFACTS_DIR: Path = DEFAULT_ARTIFACTS_DIR / "flow_lstm"
MIN_LSTM_TRAIN_ROWS: int = 100


async def train_and_register_flow_lstm(
    db: AsyncSession,
    intersection_ids: Optional[list[int]] = None,
    days: int = 21,
    notes: Optional[str] = None,
    epochs: int = 5,
    force_synthetic: bool = False,
    seed: int = 42,
    registry_root: Optional[Union[Path, str]] = None,
) -> dict[str, Any]:
    """Train PyTorch LSTM sequence forecaster and catalog artifact in ModelRegistry & PostgreSQL.

    Data Provenance Policy:
    - Queries database traffic_records over the lookback window.
    - If total records are below MIN_LSTM_TRAIN_ROWS or force_synthetic is True,
      bootstraps a DETERMINISTIC synthetic dataset using SyntheticTrafficGenerator
      with a documented fixed random seed.
    - Provenance is explicitly labeled:
        * 'observed' when sufficient real/observed records are utilized.
        * 'synthetic-deterministic-seed-N' when synthetic generation is triggered.
    - Training runs swiftly on CPU with small hidden size and small epoch count.

    Args:
        db: Active asynchronous SQLAlchemy session.
        intersection_ids: Optional target intersection IDs.
        days: Historical lookback duration in days.
        notes: Optional descriptive notes.
        epochs: Training epochs (default 5, fast on CPU).
        force_synthetic: Force deterministic synthetic training dataset generation.
        seed: Random seed for deterministic generation and weight initialization.
        registry_root: Custom root directory for artifact persistence.

    Returns:
        Structured training report dictionary.
    """
    df = await load_training_frame(db, intersection_ids, days)
    data_provenance = "observed"

    if force_synthetic or len(df) < MIN_LSTM_TRAIN_ROWS:
        target_ids = intersection_ids or [1, 2, 3]
        gen = SyntheticTrafficGenerator(seed=seed)
        df = gen.generate(intersection_ids=target_ids, days=max(7, days), seed=seed)
        data_provenance = f"synthetic-deterministic-seed-{seed}"
        logger.info(
            "Bootstrapped deterministic synthetic training set for LSTM flow model: %d rows, seed=%d",
            len(df),
            seed,
        )
    else:
        # Check source column if mixed
        if "source" in df.columns:
            sources = set(df["source"].dropna().unique())
            if sources == {"synthetic"}:
                data_provenance = f"synthetic-deterministic-seed-{seed}"
            elif "synthetic" in sources:
                data_provenance = "mixed-observed-synthetic"
            else:
                data_provenance = "observed"

    model = FlowLSTM(
        sequence_length=DEFAULT_SEQUENCE_LENGTH,
        horizon_steps=DEFAULT_HORIZON_STEPS,
        hidden_size=32,
        num_layers=1,
        dropout=0.15,
        random_state=seed,
    )

    metrics = model.fit(df, epochs=epochs, batch_size=64)

    effective_root = Path(registry_root).resolve() if registry_root else DEFAULT_LSTM_ARTIFACTS_DIR
    reg = ModelRegistry(root=effective_root)

    unique_intersections = sorted([int(x) for x in df["intersection_id"].unique()])
    data_summary = {
        "total_rows": len(df),
        "training_rows": len(df),
        "sequence_count": metrics.get("sequence_count", 0),
        "intersections": unique_intersections,
        "provenance": data_provenance,
        "training_data_provenance": data_provenance,
        "architecture": "lstm",
        "horizon_steps": DEFAULT_HORIZON_STEPS,
        "step_minutes": 5,
        "sequence_length": DEFAULT_SEQUENCE_LENGTH,
    }

    version = reg.register(
        model=model,
        metrics=metrics,
        data_summary=data_summary,
        notes=notes or "PyTorch LSTM sequence flow forecaster",
        architecture="lstm",
    )
    artifact_path = str(reg.root / version)

    # Persist or update MLModel catalog entry
    stmt = select(MLModel).where(
        MLModel.name == "flow_lstm",
        MLModel.version == version,
    )
    res = await db.execute(stmt)
    ml_model = res.scalar_one_or_none()

    if ml_model is None:
        ml_model = MLModel(
            name="flow_lstm",
            version=version,
            artifact_path=artifact_path,
            metrics=metrics,
            data_summary=data_summary,
            feature_names=model.feature_names,
            horizon_steps=DEFAULT_HORIZON_STEPS,
            notes=notes,
        )
        db.add(ml_model)
    else:
        ml_model.artifact_path = artifact_path
        ml_model.metrics = metrics
        ml_model.data_summary = data_summary
        ml_model.feature_names = model.feature_names
        ml_model.horizon_steps = DEFAULT_HORIZON_STEPS
        ml_model.notes = notes

    await db.flush()
    await db.commit()

    report: dict[str, Any] = {
        "id": ml_model.id,
        "db_id": ml_model.id,
        "name": "flow_lstm",
        "version": version,
        "architecture": "lstm",
        "training_rows": len(df),
        "training_data_provenance": data_provenance,
        "metrics": metrics,
        "data_summary": data_summary,
        "artifact_path": artifact_path,
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "notes": notes,
    }
    return report


async def predict_flow_lstm(
    db: AsyncSession,
    intersection_ids: list[int],
    horizon_minutes: int = 30,
    registry_root: Optional[Union[Path, str]] = None,
) -> dict[str, Any]:
    """Execute LSTM predictive inference for target intersections with MC dropout uncertainty.

    Requires at least DEFAULT_SEQUENCE_LENGTH (12) contiguous historical records
    in the past 24-hour window. Intersections with fewer records are marked
    as 'insufficient_data' with exact row counts; never fabricates predictions.

    Args:
        db: Active asynchronous SQLAlchemy session.
        intersection_ids: Target intersection IDs for flow inference.
        horizon_minutes: Prediction horizon (defaults to 30 minutes).
        registry_root: Optional custom registry directory.

    Returns:
        Dictionary containing 'predictions' and 'insufficient' lists.

    Raises:
        ForecastingModelNotFoundError: When no trained LSTM models exist in the registry.
    """
    effective_root = Path(registry_root).resolve() if registry_root else DEFAULT_LSTM_ARTIFACTS_DIR
    reg = ModelRegistry(root=effective_root)

    try:
        model, metadata = reg.get_latest()
    except FileNotFoundError as exc:
        raise ForecastingModelNotFoundError(
            "No flow LSTM models registered in registry. Train an LSTM model before requesting predictions."
        ) from exc

    version = metadata.get("version", "unknown")
    model_provenance = (
        metadata.get("training_data_provenance")
        or metadata.get("data_summary", {}).get("training_data_provenance")
        or "synthetic"
    )

    now = datetime.now(timezone.utc)
    cutoff_24h = now - timedelta(hours=24)
    predicted_for = now + timedelta(minutes=horizon_minutes)

    predictions: list[dict[str, Any]] = []
    insufficient: list[dict[str, Any]] = []

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

        if count < DEFAULT_SEQUENCE_LENGTH:
            insufficient.append({
                "intersection_id": iid,
                "status": "insufficient_data",
                "rows_found": count,
                "rows_required": DEFAULT_SEQUENCE_LENGTH,
                "message": (
                    f"Intersection {iid} has {count} telemetry records in the last 24 hours. "
                    f"A minimum of {DEFAULT_SEQUENCE_LENGTH} contiguous records is required for LSTM sequence forecasting."
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
            }
            for r in records
        ])

        try:
            uncertainty_output = model.predict_with_uncertainty(
                df_recent.iloc[-DEFAULT_SEQUENCE_LENGTH :],
                num_mc_samples=10,
            )
        except Exception as pred_err:
            logger.warning("Inference failed for intersection %d: %s", iid, pred_err)
            insufficient.append({
                "intersection_id": iid,
                "status": "insufficient_data",
                "rows_found": count,
                "rows_required": DEFAULT_SEQUENCE_LENGTH,
                "message": f"Inference failed on sequential telemetry: {pred_err}",
            })
            continue

        pred_val = float(uncertainty_output["predicted_flow"])
        unc_val = float(uncertainty_output["uncertainty"])
        conf_val = float(uncertainty_output["confidence"])
        interval = list(uncertainty_output["prediction_interval"])

        payload = {
            "model_name": "flow_lstm",
            "model_version": version,
            "provenance": model_provenance,
            "prediction_horizon": horizon_minutes,
            "predicted_flow": pred_val,
            "uncertainty": unc_val,
            "confidence": conf_val,
            "prediction_interval": interval,
            "uncertainty_method": "mc_dropout",
            "intersection_id": iid,
        }

        # Persist AIPrediction record
        ai_pred = AIPrediction(
            intersection_id=iid,
            prediction_type="flow_lstm",
            predicted_for=predicted_for,
            payload=payload,
            confidence=conf_val,
            model_version=version,
        )
        db.add(ai_pred)
        await db.flush()

        predictions.append({
            "intersection_id": iid,
            "model_name": "flow_lstm",
            "model_version": version,
            "provenance": model_provenance,
            "predicted_for": predicted_for.isoformat(),
            "prediction_horizon": horizon_minutes,
            "predicted_flow": pred_val,
            "confidence": conf_val,
            "uncertainty": unc_val,
            "prediction_interval": interval,
            "status": "predicted",
            "payload": payload,
            "prediction_id": ai_pred.id,
        })

    await db.commit()
    return {
        "predictions": predictions,
        "insufficient": insufficient,
    }
