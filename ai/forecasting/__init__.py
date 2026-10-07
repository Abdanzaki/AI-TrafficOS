"""AI TrafficOS forecasting data layer and predictive modeling package.

Framework-free package providing synthetic telemetry generation,
temporal feature engineering, chronological data partitioning,
multi-target forecasting models, registry management, and training pipelines.
"""

from ai.forecasting.datasets import SplitResult, chronological_split
from ai.forecasting.exceptions import InsufficientDataError
from ai.forecasting.features import MIN_TRAINING_ROWS, build_feature_frame
from ai.forecasting.models import TrafficForecaster
from ai.forecasting.pipeline import load_latest_forecaster, train_pipeline
from ai.forecasting.registry import ModelRegistry
from ai.forecasting.synthetic import SyntheticTrafficGenerator

__all__ = [
    "InsufficientDataError",
    "SyntheticTrafficGenerator",
    "MIN_TRAINING_ROWS",
    "build_feature_frame",
    "chronological_split",
    "SplitResult",
    "TrafficForecaster",
    "ModelRegistry",
    "train_pipeline",
    "load_latest_forecaster",
]
