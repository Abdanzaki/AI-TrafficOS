"""Tests for end-to-end traffic forecasting pipeline execution and version registration."""

from pathlib import Path
import pytest

from ai.forecasting import (
    InsufficientDataError,
    ModelRegistry,
    SyntheticTrafficGenerator,
    train_pipeline,
)


def test_train_pipeline_multi_target_evaluation_and_versioning(tmp_path: Path):
    """Test full pipeline workflow: 21-day training, versioning, and retrieval."""
    generator = SyntheticTrafficGenerator(seed=42)
    df_21d = generator.generate(intersection_ids=[1, 2, 3], days=21, seed=42)
    tmp_registry = tmp_path / "artifacts"

    # 1. First pipeline run -> v1
    report1 = train_pipeline(
        df_21d,
        notes="Initial pipeline test run",
        registry_root=tmp_registry,
    )

    assert report1["version"] == "v1"
    assert report1["n_train_rows"] > 0
    assert "metrics" in report1

    targets = ["y_volume", "y_congestion", "y_queue"]
    splits = ["val", "test"]

    # Verify metrics structure across targets and splits
    for split in splits:
        assert split in report1["metrics"]
        for target in targets:
            target_metrics = report1["metrics"][split][target]
            assert "mae" in target_metrics
            assert "rmse" in target_metrics
            assert "r2" in target_metrics
            assert isinstance(target_metrics["mae"], float)
            assert isinstance(target_metrics["rmse"], float)
            assert isinstance(target_metrics["r2"], float)
            assert target_metrics["mae"] >= 0.0
            assert target_metrics["rmse"] >= 0.0

    # Sanity bound: Synthetic traffic volume contains strong temporal patterns (R2 > 0.5)
    r2_volume_test = report1["metrics"]["test"]["y_volume"]["r2"]
    assert r2_volume_test is not None
    assert r2_volume_test > 0.5, f"Expected test R2 for y_volume > 0.5, got {r2_volume_test}"

    # 2. Second pipeline run -> v2
    report2 = train_pipeline(
        df_21d,
        notes="Second pipeline test run",
        registry_root=tmp_registry,
    )
    assert report2["version"] == "v2"

    # Verify v1 is still preserved and matches original metrics
    registry = ModelRegistry(root=tmp_registry)
    model_v1, meta_v1 = registry.get_version("v1")
    assert meta_v1["version"] == "v1"
    assert meta_v1["metrics"] == report1["metrics"]
    assert model_v1.is_fitted_

    model_v2, meta_v2 = registry.get_version("v2")
    assert meta_v2["version"] == "v2"
    assert model_v2.is_fitted_


def test_train_pipeline_insufficient_data_error(tmp_path: Path):
    """Verify that training pipeline enforces minimum telemetry thresholds."""
    generator = SyntheticTrafficGenerator(seed=42)
    # 5 days for 1 intersection yields 1,440 rows < 2,000 required
    df_5d = generator.generate(intersection_ids=[1], days=5, seed=42)
    tmp_registry = tmp_path / "artifacts"

    with pytest.raises(InsufficientDataError) as exc_info:
        train_pipeline(df_5d, registry_root=tmp_registry)

    assert exc_info.value.rows_found == 1440
    assert exc_info.value.rows_required == 2000
    assert "Insufficient telemetry data for training pipeline" in str(exc_info.value)
