"""Temporal feature engineering and horizon target generation for traffic forecasting."""

from typing import Any

import numpy as np
import pandas as pd

MIN_TRAINING_ROWS: int = 500
"""Minimum chronological telemetry rows required for predictive model training.

Policy:
Reliable time-series forecasting requires at least 500 contiguous 5-minute telemetry records
(~41.6 hours) per intersection cohort. This threshold ensures sufficient diurnal cycle coverage,
enables stable lag-based feature representations up to 1-hour history (lag 12), and supports
chronological validation splits without data leakage. Telemetry datasets with fewer records
must trigger an InsufficientDataError or fall back to synthetic telemetry generation.
"""

FEATURE_NAMES: list[str] = [
    "hour_sin",
    "hour_cos",
    "day_of_week_sin",
    "day_of_week_cos",
    "is_weekend",
    "is_peak_hour",
    "vehicle_count_lag_1",
    "vehicle_count_lag_2",
    "vehicle_count_lag_3",
    "vehicle_count_lag_6",
    "vehicle_count_lag_12",
    "vehicle_count_rolling_mean_3",
    "vehicle_count_rolling_mean_6",
    "vehicle_count_rolling_mean_12",
    "congestion_level_rolling_mean_3",
    "congestion_level_rolling_mean_6",
    "congestion_level_rolling_mean_12",
    "avg_speed_kmh_lag_1",
    "incident_active_lag_1",
]


def build_feature_frame(
    records_df: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    """Engineer time-series features and multi-step forecasting targets.

    Sorts input telemetry by intersection_id and recorded_at, engineers temporal sin/cos
    encodings, peak hour flags, lag features, and rolling statistics per intersection,
    and constructs multi-horizon forecasting targets (H=6 steps / 30 minutes).

    Args:
        records_df: DataFrame matching traffic_records schema containing at least
            intersection_id, recorded_at, vehicle_count, and congestion_level,
            with optional avg_speed_kmh and incident_active columns.

    Returns:
        tuple (X, y, meta) where:
            X: Feature matrix DataFrame containing 19 engineered features.
            y: Target DataFrame with columns ['y_volume', 'y_congestion', 'y_queue'].
            meta: Dictionary with keys 'feature_names', 'horizon_steps' (6),
                'step_minutes' (5), and metadata helpers.
    """
    if records_df.empty or "intersection_id" not in records_df.columns:
        empty_x = pd.DataFrame(columns=FEATURE_NAMES)
        empty_y = pd.DataFrame(columns=["y_volume", "y_congestion", "y_queue"])
        meta = {
            "feature_names": FEATURE_NAMES,
            "horizon_steps": 6,
            "step_minutes": 5,
            "target_names": ["y_volume", "y_congestion", "y_queue"],
            "intersection_ids": [],
            "min_training_rows": MIN_TRAINING_ROWS,
        }
        return empty_x, empty_y, meta

    sorted_df = records_df.sort_values(by=["intersection_id", "recorded_at"]).copy()

    feature_subsets: list[pd.DataFrame] = []
    target_subsets: list[pd.DataFrame] = []
    meta_subsets: list[pd.DataFrame] = []

    for _, grp in sorted_df.groupby("intersection_id", sort=True):
        grp = grp.sort_values("recorded_at").copy()
        ts = pd.to_datetime(grp["recorded_at"], utc=True)

        hour_float = ts.dt.hour + ts.dt.minute / 60.0
        dow = ts.dt.dayofweek

        hour_sin = np.sin(2.0 * np.pi * hour_float / 24.0)
        hour_cos = np.cos(2.0 * np.pi * hour_float / 24.0)
        dow_sin = np.sin(2.0 * np.pi * dow / 7.0)
        dow_cos = np.cos(2.0 * np.pi * dow / 7.0)
        is_weekend = (dow >= 5).astype(int)
        is_peak_hour = (
            ((ts.dt.hour >= 8) & (ts.dt.hour < 10)) | ((ts.dt.hour >= 17) & (ts.dt.hour < 20))
        ).astype(int)

        vc = grp["vehicle_count"]
        cong = grp["congestion_level"]
        spd = (
            grp["avg_speed_kmh"]
            if "avg_speed_kmh" in grp.columns
            else pd.Series(np.nan, index=grp.index)
        )
        inc = (
            grp["incident_active"].astype(int)
            if "incident_active" in grp.columns
            else pd.Series(0, index=grp.index, dtype=int)
        )

        feat_df = pd.DataFrame(
            {
                "hour_sin": hour_sin,
                "hour_cos": hour_cos,
                "day_of_week_sin": dow_sin,
                "day_of_week_cos": dow_cos,
                "is_weekend": is_weekend,
                "is_peak_hour": is_peak_hour,
                "vehicle_count_lag_1": vc.shift(1),
                "vehicle_count_lag_2": vc.shift(2),
                "vehicle_count_lag_3": vc.shift(3),
                "vehicle_count_lag_6": vc.shift(6),
                "vehicle_count_lag_12": vc.shift(12),
                "vehicle_count_rolling_mean_3": vc.rolling(window=3).mean(),
                "vehicle_count_rolling_mean_6": vc.rolling(window=6).mean(),
                "vehicle_count_rolling_mean_12": vc.rolling(window=12).mean(),
                "congestion_level_rolling_mean_3": cong.rolling(window=3).mean(),
                "congestion_level_rolling_mean_6": cong.rolling(window=6).mean(),
                "congestion_level_rolling_mean_12": cong.rolling(window=12).mean(),
                "avg_speed_kmh_lag_1": spd.shift(1),
                "incident_active_lag_1": inc.shift(1),
            },
            index=grp.index,
        )

        # Targets with horizon H=6 steps (30 minutes ahead)
        y_volume = vc.shift(-6)
        y_congestion = cong.shift(-6)
        future_cong = pd.concat([cong.shift(-s) for s in range(1, 7)], axis=1)
        y_queue = future_cong.max(axis=1, skipna=False)

        target_df = pd.DataFrame(
            {
                "y_volume": y_volume,
                "y_congestion": y_congestion,
                "y_queue": y_queue,
            },
            index=grp.index,
        )

        meta_df = pd.DataFrame(
            {
                "intersection_id": grp["intersection_id"],
                "recorded_at": ts,
            },
            index=grp.index,
        )

        combined = pd.concat([feat_df, target_df, meta_df], axis=1).dropna()
        feature_subsets.append(combined[FEATURE_NAMES])
        target_subsets.append(combined[["y_volume", "y_congestion", "y_queue"]])
        meta_subsets.append(combined[["intersection_id", "recorded_at"]])

    if not feature_subsets:
        empty_x = pd.DataFrame(columns=FEATURE_NAMES)
        empty_y = pd.DataFrame(columns=["y_volume", "y_congestion", "y_queue"])
        meta = {
            "feature_names": FEATURE_NAMES,
            "horizon_steps": 6,
            "step_minutes": 5,
            "target_names": ["y_volume", "y_congestion", "y_queue"],
            "intersection_ids": sorted(records_df["intersection_id"].unique().tolist()),
            "min_training_rows": MIN_TRAINING_ROWS,
        }
        return empty_x, empty_y, meta

    x_out = pd.concat(feature_subsets, ignore_index=True)
    y_out = pd.concat(target_subsets, ignore_index=True)
    m_out = pd.concat(meta_subsets, ignore_index=True)

    meta = {
        "feature_names": FEATURE_NAMES,
        "horizon_steps": 6,
        "step_minutes": 5,
        "target_names": ["y_volume", "y_congestion", "y_queue"],
        "intersection_ids": sorted(records_df["intersection_id"].unique().tolist()),
        "min_training_rows": MIN_TRAINING_ROWS,
        "intersection_id": m_out["intersection_id"].to_numpy(),
        "recorded_at": m_out["recorded_at"].to_numpy(),
    }

    return x_out, y_out, meta
