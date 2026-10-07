"""Verification script for Phase 5 Prompt 2: Forecasting models, registry, and pipeline."""

import shutil
from pathlib import Path
from ai.forecasting import (
    InsufficientDataError,
    ModelRegistry,
    SyntheticTrafficGenerator,
    load_latest_forecaster,
    train_pipeline,
)

def main() -> None:
    print("=== AI TrafficOS Forecasting Pipeline Verification ===")
    artifacts_dir = Path("ai/forecasting/artifacts")
    # Clean previous artifacts for a fresh verification run
    if artifacts_dir.exists():
        shutil.rmtree(artifacts_dir)

    generator = SyntheticTrafficGenerator(seed=42)

    # Step 1: Generate 21 days of synthetic data for 3 intersections
    print("\n--- Step 1: Generating 21 days of synthetic data for 3 intersections ---")
    df_21d = generator.generate(intersection_ids=[1, 2, 3], days=21, seed=42)
    print(f"Generated {len(df_21d)} records across {df_21d['intersection_id'].nunique()} intersections.")

    # Step 2: Run train_pipeline (first run -> v1)
    print("\n--- Step 2: Running train_pipeline (Run 1) ---")
    report1 = train_pipeline(df_21d, notes="Initial 21-day model training")
    v1 = report1["version"]
    rmse_vol1 = report1["metrics"]["y_volume"]["test"]["rmse"]
    rmse_cong1 = report1["metrics"]["y_congestion"]["test"]["rmse"]
    rmse_queue1 = report1["metrics"]["y_queue"]["test"]["rmse"]

    # Step 3: Print version and test-split RMSE for y_volume and y_congestion
    print(f"Registered Version: {v1}")
    print(f"Test-split RMSE y_volume:     {rmse_vol1:.4f}")
    print(f"Test-split RMSE y_congestion: {rmse_cong1:.4f}")
    print(f"Test-split RMSE y_queue:      {rmse_queue1:.4f}")
    print(f"Test-split MAE  y_volume:     {report1['metrics']['y_volume']['test']['mae']:.4f}")
    print(f"Test-split MAE  y_congestion: {report1['metrics']['y_congestion']['test']['mae']:.4f}")
    print(f"Test-split R2   y_volume:     {report1['metrics']['y_volume']['test']['r2']}")
    print(f"Test-split R2   y_congestion: {report1['metrics']['y_congestion']['test']['r2']}")

    # Step 4: Train a second time -> v2
    print("\n--- Step 3: Running train_pipeline (Run 2) ---")
    report2 = train_pipeline(df_21d, notes="Retrained second model")
    v2 = report2["version"]
    rmse_vol2 = report2["metrics"]["y_volume"]["test"]["rmse"]
    rmse_cong2 = report2["metrics"]["y_congestion"]["test"]["rmse"]
    print(f"Second Registered Version: {v2}")
    print(f"Test-split RMSE y_volume:     {rmse_vol2:.4f}")
    print(f"Test-split RMSE y_congestion: {rmse_cong2:.4f}")

    # Confirm list_versions shows v1 and v2 both present
    registry = ModelRegistry()
    versions = registry.list_versions()
    version_ids = [m["version"] for m in versions]
    print(f"\nRegistry versions listed: {version_ids}")
    assert "v1" in version_ids, "v1 missing from registry list_versions!"
    assert "v2" in version_ids, "v2 missing from registry list_versions!"
    assert len(version_ids) == 2, f"Expected 2 versions, found {len(version_ids)}"
    print("Confirmed: list_versions shows both v1 and v2 present.")

    # Confirm get_version('v1') still loads
    m1_loaded, meta1 = registry.get_version("v1")
    assert meta1["version"] == "v1", f"Expected version v1 in metadata, got {meta1['version']}"
    assert m1_loaded.is_fitted_, "Loaded v1 model is not fitted!"
    print(f"Confirmed: get_version('v1') successfully loaded model and metadata (trained_at: {meta1['trained_at']}).")

    # Confirm load_latest_forecaster returns v2
    m_latest, meta_latest = load_latest_forecaster()
    assert meta_latest["version"] == "v2", f"Expected latest version v2, got {meta_latest['version']}"
    print("Confirmed: load_latest_forecaster loaded v2 model.")

    # Step 5: Verify that train_pipeline on only 5 days of data for 1 intersection raises InsufficientDataError
    print("\n--- Step 4: Verifying InsufficientDataError on 5 days of data for 1 intersection ---")
    df_5d = generator.generate(intersection_ids=[1], days=5, seed=42)
    print(f"Generated 5-day dataset: {len(df_5d)} records.")
    try:
        train_pipeline(df_5d)
        print("ERROR: train_pipeline did NOT raise InsufficientDataError!")
        raise RuntimeError("Verification failed: InsufficientDataError was not raised.")
    except InsufficientDataError as e:
        print(f"SUCCESS: Caught expected InsufficientDataError: {e}")
        print(f"  rows_found:    {e.rows_found}")
        print(f"  rows_required: {e.rows_required}")

    print("\n=== ALL VERIFICATION CHECKS PASSED SUCCESSFULLY ===")

if __name__ == "__main__":
    main()
