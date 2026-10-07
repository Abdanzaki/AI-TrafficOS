"""End-to-end model training, evaluation, and registration pipeline for traffic forecasting."""

from pathlib import Path
from typing import Any, Optional, Union

import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

from ai.forecasting.datasets import chronological_split
from ai.forecasting.exceptions import InsufficientDataError
from ai.forecasting.features import MIN_TRAINING_ROWS, build_feature_frame
from ai.forecasting.models import TrafficForecaster
from ai.forecasting.registry import ModelRegistry

MIN_PIPELINE_ROWS: int = 2000
"""Minimum raw telemetry records required for production pipeline training.

While individual feature transformations require a baseline of 500 rows, end-to-end
model training, three-way chronological partitioning (70/15/15), and weekly
seasonality representations require at least 2000 records (~7 full days of 5-minute intervals).
"""


def _compute_metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, Any]:
    """Compute MAE, RMSE, and variance-guarded R2 regression metrics."""
    mae = float(mean_absolute_error(y_true, y_pred))
    rmse = float(np.sqrt(mean_squared_error(y_true, y_pred)))
    variance = float(np.var(y_true))
    if variance == 0.0 or len(np.unique(y_true)) <= 1:
        r2 = None
    else:
        r2 = float(r2_score(y_true, y_pred))
    return {
        "mae": round(mae, 4),
        "rmse": round(rmse, 4),
        "r2": round(r2, 4) if r2 is not None else None,
    }


def train_pipeline(
    records_df: pd.DataFrame,
    notes: str = "",
    registry_root: Optional[Union[Path, str]] = None,
    model_params: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Execute end-to-end traffic forecasting model training and registry publication.

    Workflow:
    1. Validate minimum dataset volume and engineer temporal lag features.
    2. Chronologically split partitions into train (70%), validation (15%), and test (15%).
       Propagates InsufficientDataError if telemetry records do not meet the minimum threshold.
    3. Fit multi-target TrafficForecaster on the training partition.
    4. Evaluate out-of-sample performance on validation and test partitions,
       calculating MAE, RMSE, and R2 (with zero-variance safety checks).
    5. Register trained model and metadata in ModelRegistry under an incremented version.

    Args:
        records_df: Raw traffic telemetry records DataFrame matching traffic_records schema.
        notes: Optional descriptive notes or experiment tag.
        registry_root: Optional custom artifacts storage path for ModelRegistry.
        model_params: Optional dictionary of hyperparameters passed to regressor models.

    Returns:
        Report dictionary containing:
            - 'version': The newly registered version identifier (e.g. 'v1').
            - 'metrics': Multi-target evaluation metrics across validation and test splits.
            - 'n_train_rows': Number of training partition rows used for model fitting.
            - 'data_summary': Telemetry provenance summary (row count, time range, sources).
            - 'feature_names': List of 19 engineered feature column names.
            - 'horizon_info': Horizon step count and duration details.
            - 'model': The fitted TrafficForecaster instance.

    Raises:
        InsufficientDataError: When records_df contains fewer rows than required for
            reliable forecasting and chronological validation splits.
    """
    if len(records_df) < MIN_PIPELINE_ROWS:
        raise InsufficientDataError(
            rows_found=len(records_df),
            rows_required=MIN_PIPELINE_ROWS,
            message=(
                f"Insufficient telemetry data for training pipeline: found {len(records_df)} rows, "
                f"but a minimum of {MIN_PIPELINE_ROWS} rows (~7 days of 5-minute telemetry) is required."
            ),
        )

    # 1. Feature Engineering
    X, y, meta = build_feature_frame(records_df)

    # 2. Chronological Split (lets InsufficientDataError propagate if len(X) < MIN_TRAINING_ROWS)
    split = chronological_split(X, y, train_ratio=0.7, val_ratio=0.15)
    X_train, y_train = split.X_train, split.y_train
    X_val, y_val = split.X_val, split.y_val
    X_test, y_test = split.X_test, split.y_test

    # 3. Model Training
    forecaster = TrafficForecaster(random_state=42, model_params=model_params)
    forecaster.meta.update(meta)
    forecaster.fit(X_train, y_train)

    # 4. Out-of-sample Evaluation
    val_preds = forecaster.predict(X_val)
    test_preds = forecaster.predict(X_test)

    metrics_by_target: dict[str, dict[str, Any]] = {}
    metrics_by_split: dict[str, dict[str, dict[str, Any]]] = {"val": {}, "test": {}}

    for target in forecaster.target_names:
        if isinstance(y_val, pd.DataFrame) and target in y_val.columns:
            y_val_t = y_val[target].to_numpy(dtype=float)
        else:
            y_val_t = np.asarray(y_val[target], dtype=float)

        if isinstance(y_test, pd.DataFrame) and target in y_test.columns:
            y_test_t = y_test[target].to_numpy(dtype=float)
        else:
            y_test_t = np.asarray(y_test[target], dtype=float)

        val_m = _compute_metrics(y_val_t, val_preds[target])
        test_m = _compute_metrics(y_test_t, test_preds[target])

        metrics_by_split["val"][target] = val_m
        metrics_by_split["test"][target] = test_m

        metrics_by_target[target] = {
            "val": val_m,
            "test": test_m,
            "val_mae": val_m["mae"],
            "val_rmse": val_m["rmse"],
            "val_r2": val_m["r2"],
            "test_mae": test_m["mae"],
            "test_rmse": test_m["rmse"],
            "test_r2": test_m["r2"],
        }

    metrics: dict[str, Any] = {
        **metrics_by_target,
        "val": metrics_by_split["val"],
        "test": metrics_by_split["test"],
    }

    # 5. Data Summary
    min_recorded_at: Optional[str] = None
    max_recorded_at: Optional[str] = None
    if "recorded_at" in records_df.columns and not records_df["recorded_at"].isna().all():
        ts_col = pd.to_datetime(records_df["recorded_at"])
        min_recorded_at = ts_col.min().isoformat()
        max_recorded_at = ts_col.max().isoformat()

    source_mix: dict[str, int] = {}
    if "source" in records_df.columns:
        source_mix = {str(k): int(v) for k, v in records_df["source"].value_counts().items()}
    else:
        source_mix = {"unknown": int(len(records_df))}

    data_summary: dict[str, Any] = {
        "n_rows": int(len(records_df)),
        "n_intersections": (
            int(records_df["intersection_id"].nunique())
            if "intersection_id" in records_df.columns
            else 0
        ),
        "min_recorded_at": min_recorded_at,
        "max_recorded_at": max_recorded_at,
        "source_mix": source_mix,
    }

    # 6. Artifact Registration
    registry = ModelRegistry(root=registry_root)
    version = registry.register(
        model=forecaster,
        metrics=metrics,
        data_summary=data_summary,
        notes=notes,
    )

    horizon_info = {
        "steps": int(meta.get("horizon_steps", 6)),
        "step_minutes": int(meta.get("step_minutes", 5)),
        "duration_minutes": int(meta.get("horizon_steps", 6) * meta.get("step_minutes", 5)),
    }

    report: dict[str, Any] = {
        "version": version,
        "metrics": metrics,
        "n_train_rows": int(len(X_train)),
        "data_summary": data_summary,
        "feature_names": list(forecaster.feature_names),
        "horizon_info": horizon_info,
        "horizon": horizon_info,
        "model": forecaster,
    }

    return report


def load_latest_forecaster(
    registry_root: Optional[Union[Path, str]] = None,
) -> tuple[TrafficForecaster, dict[str, Any]]:
    """Retrieve the latest registered TrafficForecaster model and its metadata.

    Args:
        registry_root: Optional custom path for the ModelRegistry artifacts directory.

    Returns:
        tuple (forecaster, metadata) where forecaster is a fitted TrafficForecaster
        and metadata is the model's provenance dictionary.

    Raises:
        FileNotFoundError: When no models exist in the registry.
    """
    registry = ModelRegistry(root=registry_root)
    return registry.get_latest()
