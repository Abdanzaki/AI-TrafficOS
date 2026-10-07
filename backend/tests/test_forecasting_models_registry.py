"""Unit and integration tests for TrafficForecaster, ModelRegistry, and train_pipeline."""

from pathlib import Path
import tempfile
import pytest
import numpy as np
import pandas as pd
from sklearn.exceptions import NotFittedError

from ai.forecasting import (
    InsufficientDataError,
    ModelRegistry,
    SyntheticTrafficGenerator,
    TrafficForecaster,
    load_latest_forecaster,
    train_pipeline,
)


def test_traffic_forecaster_fit_predict_and_confidence():
    # Setup synthetic dataset
    rng = np.random.default_rng(42)
    n_samples = 600
    n_features = 19
    feature_cols = [f"f_{i}" for i in range(n_features)]

    X = pd.DataFrame(rng.normal(size=(n_samples, n_features)), columns=feature_cols)
    y = pd.DataFrame({
        "y_volume": rng.uniform(10, 100, size=n_samples),
        "y_congestion": rng.uniform(0, 100, size=n_samples),
        "y_queue": rng.uniform(0, 100, size=n_samples),
    })

    model = TrafficForecaster(random_state=42, model_params={"max_iter": 20})
    assert not model.is_fitted_

    with pytest.raises(NotFittedError):
        model.predict(X)

    model.fit(X, y)
    assert model.is_fitted_
    assert set(model.residual_stds_.keys()) == {"y_volume", "y_congestion", "y_queue"}
    for std_val in model.residual_stds_.values():
        assert std_val >= 0.0

    # Predict point estimates
    preds = model.predict(X.iloc[:10])
    assert set(preds.keys()) == {"y_volume", "y_congestion", "y_queue"}
    assert preds["y_volume"].shape == (10,)
    assert preds["y_congestion"].shape == (10,)
    assert preds["y_queue"].shape == (10,)

    # Predict with confidence
    preds_conf = model.predict_with_confidence(X.iloc[:10])
    for target in ["y_volume", "y_congestion", "y_queue"]:
        assert "value" in preds_conf[target]
        assert "confidence" in preds_conf[target]
        assert preds_conf[target]["value"].shape == (10,)
        conf_arr = preds_conf[target]["confidence"]
        assert conf_arr.shape == (10,)
        assert (conf_arr >= 0.0).all() and (conf_arr <= 1.0).all()


def test_traffic_forecaster_save_and_load(tmp_path: Path):
    rng = np.random.default_rng(42)
    X = pd.DataFrame(rng.normal(size=(600, 19)))
    y = pd.DataFrame({
        "y_volume": rng.uniform(10, 50, size=600),
        "y_congestion": rng.uniform(0, 50, size=600),
        "y_queue": rng.uniform(0, 50, size=600),
    })

    model = TrafficForecaster(random_state=42, model_params={"max_iter": 15})
    model.fit(X, y)
    model.meta = {"horizon_steps": 6, "step_minutes": 5}

    save_path = tmp_path / "test_model.joblib"
    model.save(save_path)
    assert save_path.exists()

    loaded_model = TrafficForecaster.load(save_path)
    assert isinstance(loaded_model, TrafficForecaster)
    assert loaded_model.is_fitted_
    assert loaded_model.meta["horizon_steps"] == 6

    # Compare predictions
    orig_preds = model.predict(X.iloc[:5])
    loaded_preds = loaded_model.predict(X.iloc[:5])
    for target in ["y_volume", "y_congestion", "y_queue"]:
        np.testing.assert_allclose(orig_preds[target], loaded_preds[target])


def test_model_registry_lifecycle_and_versioning(tmp_path: Path):
    registry = ModelRegistry(root=tmp_path / "artifacts")

    # Empty registry checks
    with pytest.raises(FileNotFoundError) as exc_info:
        registry.get_latest()
    assert "No forecasting models registered" in str(exc_info.value)

    with pytest.raises(FileNotFoundError):
        registry.get_version("v1")

    assert registry.list_versions() == []

    # Mock model
    rng = np.random.default_rng(42)
    X = pd.DataFrame(rng.normal(size=(600, 19)))
    y = pd.DataFrame({
        "y_volume": rng.uniform(10, 50, size=600),
        "y_congestion": rng.uniform(0, 50, size=600),
        "y_queue": rng.uniform(0, 50, size=600),
    })
    model1 = TrafficForecaster(random_state=42, model_params={"max_iter": 10})
    model1.fit(X, y)
    model1.meta = {"horizon_steps": 6, "step_minutes": 5}

    metrics1 = {
        "val": {"y_volume": {"mae": 3.2, "rmse": 4.1, "r2": 0.85}},
        "test": {"y_volume": {"mae": 3.4, "rmse": 4.3, "r2": 0.83}},
    }
    summary1 = {"n_rows": 600, "n_intersections": 1, "source_mix": {"synthetic": 600}}

    v1 = registry.register(model1, metrics=metrics1, data_summary=summary1, notes="baseline")
    assert v1 == "v1"

    # Register second model
    model2 = TrafficForecaster(random_state=42, model_params={"max_iter": 15})
    model2.fit(X, y)
    model2.meta = {"horizon_steps": 6, "step_minutes": 5}
    v2 = registry.register(model2, metrics=metrics1, data_summary=summary1, notes="v2 update")
    assert v2 == "v2"

    # Inspect list_versions
    versions = registry.list_versions()
    assert len(versions) == 2
    assert versions[0]["version"] == "v1"
    assert versions[1]["version"] == "v2"
    assert versions[0]["notes"] == "baseline"
    assert versions[1]["notes"] == "v2 update"

    # Inspect get_version
    m1_loaded, meta1 = registry.get_version("v1")
    assert isinstance(m1_loaded, TrafficForecaster)
    assert meta1["version"] == "v1"

    # Inspect get_latest
    latest_m, latest_meta = registry.get_latest()
    assert latest_meta["version"] == "v2"


def test_train_pipeline_insufficient_data():
    gen = SyntheticTrafficGenerator(seed=42)
    # 5 days of 1 intersection = 1440 rows < 2000 rows minimum pipeline policy
    df_small = gen.generate(intersection_ids=[1], days=5)

    with pytest.raises(InsufficientDataError) as exc_info:
        train_pipeline(df_small)

    err = exc_info.value
    assert err.rows_found == 1440
    assert err.rows_required == 2000
