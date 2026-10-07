"""Unit tests for ai.forecasting data layer."""

import pytest
import pandas as pd
import numpy as np

from ai.forecasting import (
    InsufficientDataError,
    MIN_TRAINING_ROWS,
    SyntheticTrafficGenerator,
    build_feature_frame,
    chronological_split,
)
from ai.forecasting.datasets import SplitResult


def test_synthetic_traffic_generator_schema_and_reproducibility():
    generator = SyntheticTrafficGenerator(seed=42)
    df1 = generator.generate(intersection_ids=[1, 2], days=2, seed=42)
    df2 = generator.generate(intersection_ids=[1, 2], days=2, seed=42)

    assert len(df1) == 2 * 2 * 288  # 1152 rows
    assert list(df1.columns) == [
        "intersection_id",
        "lane_id",
        "recorded_at",
        "vehicle_count",
        "avg_speed_kmh",
        "congestion_level",
        "source",
        "incident_active",
    ]
    assert (df1["source"] == "synthetic").all()
    assert (df1["vehicle_count"] >= 0).all()
    assert (df1["congestion_level"] >= 0).all() and (df1["congestion_level"] <= 100).all()
    assert df1["recorded_at"].dt.tz is not None
    assert (df1["lane_id"].isna()).all()

    # Reproducibility check
    pd.testing.assert_frame_equal(df1, df2)


def test_build_feature_frame_engineering():
    generator = SyntheticTrafficGenerator(seed=42)
    raw_df = generator.generate(intersection_ids=[10, 20], days=3)

    X, y, meta = build_feature_frame(raw_df)

    assert meta["horizon_steps"] == 6
    assert meta["step_minutes"] == 5
    assert len(meta["feature_names"]) == 19
    assert list(y.columns) == ["y_volume", "y_congestion", "y_queue"]
    assert len(X) == len(y)
    assert not X.isna().any().any()
    assert not y.isna().any().any()

    # Lags drop 12 rows at beginning and 6 rows at end per intersection
    per_intersection_steps = 3 * 288
    expected_rows_per_intersection = per_intersection_steps - 12 - 6
    assert len(X) == expected_rows_per_intersection * 2


def test_build_feature_frame_tolerates_missing_incident_active():
    generator = SyntheticTrafficGenerator(seed=42)
    raw_df = generator.generate(intersection_ids=[1], days=3)
    raw_df_no_incident = raw_df.drop(columns=["incident_active"])

    X, y, meta = build_feature_frame(raw_df_no_incident)
    assert "incident_active_lag_1" in X.columns
    assert (X["incident_active_lag_1"] == 0).all()


def test_chronological_split_success_and_order():
    generator = SyntheticTrafficGenerator(seed=42)
    raw_df = generator.generate(intersection_ids=[1], days=7)
    X, y, meta = build_feature_frame(raw_df)

    split = chronological_split(X, y, train_ratio=0.7, val_ratio=0.15)
    assert isinstance(split, SplitResult)

    n = len(X)
    train_n = int(n * 0.7)
    val_n = int(n * 0.85) - train_n
    test_n = n - int(n * 0.85)

    assert len(split.X_train) == train_n
    assert len(split.y_train) == train_n
    assert len(split.X_val) == val_n
    assert len(split.y_val) == val_n
    assert len(split.X_test) == test_n
    assert len(split.y_test) == test_n

    # Unpacking style 1 (pairs):
    X_tr, y_tr, X_v, y_v, X_te, y_te = split
    assert len(X_tr) == train_n
    assert len(y_tr) == train_n

    # Unpacking style 2 (all X then all y):
    X_train, X_val, X_test, y_train, y_val, y_test = split
    assert len(X_train) == train_n
    assert len(X_val) == val_n
    assert len(X_test) == test_n
    assert len(y_train) == train_n


def test_chronological_split_insufficient_data():
    X_small = pd.DataFrame({"feat": np.arange(100)})
    y_small = pd.DataFrame({"target": np.arange(100)})

    with pytest.raises(InsufficientDataError) as exc_info:
        chronological_split(X_small, y_small)

    err = exc_info.value
    assert err.rows_found == 100
    assert err.rows_required == MIN_TRAINING_ROWS
