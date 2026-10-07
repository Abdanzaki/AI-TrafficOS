"""Multi-target traffic forecasting model implementation using gradient boosted regression."""

from pathlib import Path
from typing import Any, Optional, Union

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.exceptions import NotFittedError

from ai.forecasting.features import FEATURE_NAMES
from ai.prediction.base import BasePredictor

DEFAULT_TARGETS: list[str] = ["y_volume", "y_congestion", "y_queue"]


class TrafficForecaster(BasePredictor):
    """Multi-output traffic flow, congestion, and queue forecaster.

    Implements BasePredictor by training independent HistGradientBoostingRegressor
    models for each horizon target ('y_volume', 'y_congestion', 'y_queue').
    Provides point estimates and dispersion-based confidence intervals derived
    from training residual variance.
    """

    def __init__(
        self,
        random_state: int = 42,
        model_params: Optional[dict[str, Any]] = None,
    ) -> None:
        """Initialize multi-target forecasting ensemble.

        Args:
            random_state: Seed for reproducible tree splitting and bootstrapping.
            model_params: Optional hyperparameter dictionary passed to underlying
                HistGradientBoostingRegressor instances (e.g., max_iter, learning_rate).
        """
        self.random_state: int = random_state
        self.model_params: dict[str, Any] = dict(model_params) if model_params is not None else {}
        self.target_names: list[str] = list(DEFAULT_TARGETS)
        self.feature_names: list[str] = list(FEATURE_NAMES)
        self.meta: dict[str, Any] = {}
        self.models_: dict[str, HistGradientBoostingRegressor] = {}
        self.residual_stds_: dict[str, float] = {}
        self.is_fitted_: bool = False

    def fit(
        self,
        X_train: Union[pd.DataFrame, np.ndarray],
        y_train: Union[pd.DataFrame, np.ndarray, dict[str, Any]],
    ) -> "TrafficForecaster":
        """Fit one HistGradientBoostingRegressor per target and compute training residuals.

        Args:
            X_train: Training feature matrix (pd.DataFrame with 19 engineered features
                or 2D numpy array matching FEATURE_NAMES column layout).
            y_train: Training target frame containing columns ['y_volume', 'y_congestion', 'y_queue'],
                or corresponding target dictionary / 2D numpy array.

        Returns:
            self: The fitted TrafficForecaster instance.
        """
        if isinstance(X_train, pd.DataFrame):
            self.feature_names = list(X_train.columns)
            X_mat = X_train.to_numpy(dtype=float)
        else:
            X_mat = np.asarray(X_train, dtype=float)

        self.models_ = {}
        self.residual_stds_ = {}

        for i, target in enumerate(self.target_names):
            if isinstance(y_train, pd.DataFrame):
                if target in y_train.columns:
                    y_vec = y_train[target].to_numpy(dtype=float)
                else:
                    y_vec = y_train.iloc[:, i].to_numpy(dtype=float)
            elif isinstance(y_train, dict):
                y_vec = np.asarray(y_train[target], dtype=float)
            elif isinstance(y_train, np.ndarray):
                y_vec = y_train[:, i].astype(float) if y_train.ndim > 1 else y_train.astype(float)
            else:
                y_vec = np.asarray(y_train, dtype=float)

            reg_kwargs: dict[str, Any] = {"random_state": self.random_state}
            target_overrides = self.model_params.get(target)
            if isinstance(target_overrides, dict):
                reg_kwargs.update(self.model_params)
                reg_kwargs.update(target_overrides)
                reg_kwargs.pop(target, None)
            else:
                reg_kwargs.update(self.model_params)

            regressor = HistGradientBoostingRegressor(**reg_kwargs)
            regressor.fit(X_mat, y_vec)

            train_preds = regressor.predict(X_mat)
            residuals = y_vec - train_preds
            residual_std = float(np.std(residuals))

            self.models_[target] = regressor
            self.residual_stds_[target] = residual_std

        self.is_fitted_ = True
        return self

    def _ensure_fitted(self) -> None:
        """Validate model fitting status before inference."""
        if not self.is_fitted_ or not self.models_:
            raise NotFittedError(
                "TrafficForecaster is not fitted yet. Call 'fit' before executing inference."
            )

    def _prepare_features(self, X: Union[pd.DataFrame, np.ndarray]) -> np.ndarray:
        """Align input features with training schema."""
        if isinstance(X, pd.DataFrame):
            if all(col in X.columns for col in self.feature_names):
                return X[self.feature_names].to_numpy(dtype=float)
            return X.to_numpy(dtype=float)
        return np.asarray(X, dtype=float)

    def predict(self, X: Union[pd.DataFrame, np.ndarray], *args: Any, **kwargs: Any) -> dict[str, np.ndarray]:
        """Execute predictive inference over input feature representations.

        Args:
            X: Input feature DataFrame or 2D numpy array.
            *args: Additional positional arguments (accepted for BasePredictor compatibility).
            **kwargs: Additional keyword parameters (accepted for BasePredictor compatibility).

        Returns:
            Dictionary mapping each target name ('y_volume', 'y_congestion', 'y_queue')
            to 1D numpy array of point predictions.
        """
        self._ensure_fitted()
        X_mat = self._prepare_features(X)

        predictions: dict[str, np.ndarray] = {}
        for target, model in self.models_.items():
            predictions[target] = model.predict(X_mat)

        return predictions

    def predict_with_confidence(
        self,
        X: Union[pd.DataFrame, np.ndarray],
    ) -> dict[str, dict[str, np.ndarray]]:
        """Predict horizon target values alongside dispersion-based confidence estimates.

        Note:
            The confidence metric returned here is a heuristic dispersion score
            derived from training residual standard deviation relative to prediction
            magnitude:
                confidence = 1 / (1 + residual_std / (|pred| + 1))
            This reflects model stability and relative error scale on in-sample data.
            It is a dispersion-based heuristic, NOT a calibrated Bayesian or conformal
            probability.

        Args:
            X: Input feature DataFrame or 2D numpy array.

        Returns:
            Dictionary mapping target name to a dictionary containing:
                - 'value': 1D numpy array of point predictions.
                - 'confidence': 1D numpy array of float confidence scores in [0.0, 1.0].
        """
        self._ensure_fitted()
        point_predictions = self.predict(X)

        result: dict[str, dict[str, np.ndarray]] = {}
        for target, preds in point_predictions.items():
            residual_std = self.residual_stds_.get(target, 0.0)
            conf = 1.0 / (1.0 + residual_std / (np.abs(preds) + 1.0))
            conf = np.clip(conf, 0.0, 1.0).astype(float)
            result[target] = {
                "value": preds,
                "confidence": conf,
            }

        return result

    def save(self, path: Union[str, Path]) -> None:
        """Persist fitted forecasting models, feature metadata, and residual statistics.

        Args:
            path: Target file path (.joblib format).
        """
        target_path = Path(path).resolve()
        target_path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(self, target_path)

    @classmethod
    def load(cls, path: Union[str, Path]) -> "TrafficForecaster":
        """Load persisted TrafficForecaster from disk.

        Args:
            path: Source file path containing serialized forecaster or artifact bundle.

        Returns:
            TrafficForecaster instance ready for inference or fine-tuning.
        """
        source_path = Path(path).resolve()
        if not source_path.exists():
            raise FileNotFoundError(f"Forecasting model file not found: {source_path}")

        loaded = joblib.load(source_path)
        if isinstance(loaded, cls):
            return loaded

        if isinstance(loaded, dict):
            instance = cls(
                random_state=loaded.get("random_state", 42),
                model_params=loaded.get("model_params"),
            )
            instance.models_ = loaded.get("models", {})
            instance.feature_names = loaded.get("feature_names", list(FEATURE_NAMES))
            instance.residual_stds_ = loaded.get("residual_stds", {})
            instance.meta = loaded.get("meta", {})
            instance.target_names = loaded.get("target_names", list(DEFAULT_TARGETS))
            instance.is_fitted_ = loaded.get("is_fitted", True)
            return instance

        raise TypeError(f"Unrecognized serialized model object type: {type(loaded)}")
