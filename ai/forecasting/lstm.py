"""Deep-learning traffic flow forecasting model using PyTorch LSTM.

Provides a sequence-to-scalar LSTM neural network predicting near-term per-junction
traffic volume (flow) from historical TrafficRecord sequences.

Uncertainty Quantification:
    Uses Monte Carlo Dropout (MC Dropout, Gal & Ghahramani 2016). Multiple stochastic
    forward passes are evaluated with active dropout during inference to compute the
    predictive mean, empirical standard deviation (epistemic + dispersion uncertainty),
    and a 95% confidence interval.
    The confidence metric is derived directly from dispersion:
        confidence = 1 / (1 + uncertainty / (mean + 1.0))
    This provides an honest, transparent uncertainty estimate without fabricating
    calibrated Bayesian posteriors.
"""

from datetime import datetime, timezone
import math
from pathlib import Path
from typing import Any, Optional, Union

import joblib
import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from torch.utils.data import DataLoader, TensorDataset

LSTM_FEATURE_NAMES: list[str] = [
    "vehicle_count",
    "avg_speed_kmh",
    "congestion_level",
    "sin_hour",
    "cos_hour",
    "is_weekend",
]
DEFAULT_SEQUENCE_LENGTH: int = 12  # 12 x 5-minute intervals = 1 hour history
DEFAULT_HORIZON_STEPS: int = 6     # 6 x 5-minute intervals = 30 minutes forward


class FlowLSTMNet(nn.Module):
    """PyTorch recurrent architecture with LSTM layer and Monte Carlo dropout head."""

    def __init__(
        self,
        input_size: int = len(LSTM_FEATURE_NAMES),
        hidden_size: int = 32,
        num_layers: int = 1,
        dropout: float = 0.15,
    ) -> None:
        super().__init__()
        self.input_size = input_size
        self.hidden_size = hidden_size
        self.num_layers = num_layers
        self.dropout_rate = dropout

        self.lstm = nn.LSTM(
            input_size=input_size,
            hidden_size=hidden_size,
            num_layers=num_layers,
            batch_first=True,
            dropout=dropout if num_layers > 1 else 0.0,
        )
        self.dropout = nn.Dropout(p=dropout)
        self.fc = nn.Sequential(
            nn.Linear(hidden_size, 16),
            nn.ReLU(),
            nn.Dropout(p=dropout),
            nn.Linear(16, 1),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """Standard forward pass."""
        lstm_out, _ = self.lstm(x)
        last_hidden = lstm_out[:, -1, :]
        dropped = self.dropout(last_hidden)
        out = self.fc(dropped)
        return out.squeeze(-1)

    def forward_mc(self, x: torch.Tensor) -> torch.Tensor:
        """Forward pass with dropout forced active for Monte Carlo sampling."""
        lstm_out, _ = self.lstm(x)
        last_hidden = lstm_out[:, -1, :]
        # Force dropout even in eval mode
        dropped = nn.functional.dropout(last_hidden, p=self.dropout_rate, training=True)
        h = self.fc[0](dropped)
        h = self.fc[1](h)
        h = nn.functional.dropout(h, p=self.dropout_rate, training=True)
        out = self.fc[3](h)
        return out.squeeze(-1)


class FlowLSTM:
    """End-to-end wrapper for LSTM sequence flow forecasting with uncertainty estimation."""

    def __init__(
        self,
        sequence_length: int = DEFAULT_SEQUENCE_LENGTH,
        horizon_steps: int = DEFAULT_HORIZON_STEPS,
        hidden_size: int = 32,
        num_layers: int = 1,
        dropout: float = 0.15,
        random_state: int = 42,
    ) -> None:
        self.sequence_length = sequence_length
        self.horizon_steps = horizon_steps
        self.hidden_size = hidden_size
        self.num_layers = num_layers
        self.dropout = dropout
        self.random_state = random_state

        self.architecture = "lstm"
        self.feature_names = list(LSTM_FEATURE_NAMES)
        self.target_names = ["vehicle_count"]
        self.meta: dict[str, Any] = {
            "architecture": "lstm",
            "sequence_length": sequence_length,
            "horizon_steps": horizon_steps,
            "step_minutes": 5,
            "duration_minutes": horizon_steps * 5,
        }

        self.net_: Optional[FlowLSTMNet] = None
        self.scaler_mean_: Optional[np.ndarray] = None
        self.scaler_std_: Optional[np.ndarray] = None
        self.target_mean_: float = 0.0
        self.target_std_: float = 1.0
        self.is_fitted_: bool = False

    @staticmethod
    def extract_features(df: pd.DataFrame) -> pd.DataFrame:
        """Engineer cyclical time and normalize features for raw telemetry frame."""
        df_feat = df.copy()
        if not pd.api.types.is_datetime64_any_dtype(df_feat["recorded_at"]):
            df_feat["recorded_at"] = pd.to_datetime(df_feat["recorded_at"], utc=True)

        hours = df_feat["recorded_at"].dt.hour + df_feat["recorded_at"].dt.minute / 60.0
        df_feat["sin_hour"] = np.sin(2.0 * math.pi * hours / 24.0)
        df_feat["cos_hour"] = np.cos(2.0 * math.pi * hours / 24.0)
        df_feat["is_weekend"] = (df_feat["recorded_at"].dt.dayofweek >= 5).astype(float)

        if "avg_speed_kmh" not in df_feat.columns:
            df_feat["avg_speed_kmh"] = 50.0
        else:
            df_feat["avg_speed_kmh"] = df_feat["avg_speed_kmh"].fillna(50.0)

        if "congestion_level" not in df_feat.columns:
            df_feat["congestion_level"] = 0.0
        else:
            df_feat["congestion_level"] = df_feat["congestion_level"].fillna(0.0)

        return df_feat

    def _build_sequences(
        self,
        df: pd.DataFrame,
    ) -> tuple[np.ndarray, np.ndarray]:
        """Construct sliding sequences per intersection: X (N, seq_len, F), y (N,)."""
        df_feat = self.extract_features(df)
        df_sorted = df_feat.sort_values(by=["intersection_id", "recorded_at"]).reset_index(drop=True)

        X_list: list[np.ndarray] = []
        y_list: list[float] = []

        feature_cols = self.feature_names

        for _, group in df_sorted.groupby("intersection_id"):
            vals = group[feature_cols].to_numpy(dtype=np.float32)
            targets = group["vehicle_count"].to_numpy(dtype=np.float32)
            n_rows = len(group)

            for i in range(n_rows - self.sequence_length - self.horizon_steps + 1):
                seq_x = vals[i : i + self.sequence_length]
                target_idx = i + self.sequence_length + self.horizon_steps - 1
                y_val = targets[target_idx]
                X_list.append(seq_x)
                y_list.append(y_val)

        if not X_list:
            return np.empty((0, self.sequence_length, len(feature_cols)), dtype=np.float32), np.empty((0,), dtype=np.float32)

        return np.asarray(X_list, dtype=np.float32), np.asarray(y_list, dtype=np.float32)

    def fit(
        self,
        df: pd.DataFrame,
        epochs: int = 5,
        batch_size: int = 64,
        lr: float = 0.005,
    ) -> dict[str, Any]:
        """Fit LSTM sequence model on historical telemetry dataframe.

        Args:
            df: Historical telemetry containing recorded_at, intersection_id, vehicle_count.
            epochs: Number of training epochs (kept small for fast CPU execution).
            batch_size: Minibatch size.
            lr: Learning rate for Adam optimizer.

        Returns:
            Dictionary with training metrics (mae, rmse, final_loss, sample_count).
        """
        torch.manual_seed(self.random_state)
        np.random.seed(self.random_state)

        X_raw, y_raw = self._build_sequences(df)
        if len(X_raw) == 0:
            raise ValueError("Insufficient sequential observations to construct LSTM training sequences.")

        # Compute scaling parameters
        # Flatten across samples and timesteps to get global feature mean and std
        flat_X = X_raw.reshape(-1, X_raw.shape[-1])
        self.scaler_mean_ = np.mean(flat_X, axis=0, keepdims=True)
        self.scaler_std_ = np.std(flat_X, axis=0, keepdims=True)
        self.scaler_std_[self.scaler_std_ == 0.0] = 1.0

        self.target_mean_ = float(np.mean(y_raw))
        self.target_std_ = float(np.std(y_raw))
        if self.target_std_ == 0.0:
            self.target_std_ = 1.0

        # Scale features and targets
        X_scaled = (X_raw - self.scaler_mean_) / self.scaler_std_
        y_scaled = (y_raw - self.target_mean_) / self.target_std_

        dataset = TensorDataset(
            torch.from_numpy(X_scaled).float(),
            torch.from_numpy(y_scaled).float(),
        )
        loader = DataLoader(dataset, batch_size=batch_size, shuffle=True)

        self.net_ = FlowLSTMNet(
            input_size=len(self.feature_names),
            hidden_size=self.hidden_size,
            num_layers=self.num_layers,
            dropout=self.dropout,
        )

        optimizer = torch.optim.Adam(self.net_.parameters(), lr=lr)
        criterion = nn.MSELoss()

        self.net_.train()
        final_loss = 0.0
        for _ in range(epochs):
            total_loss = 0.0
            for bx, by in loader:
                optimizer.zero_grad()
                pred = self.net_(bx)
                loss = criterion(pred, by)
                loss.backward()
                optimizer.step()
                total_loss += loss.item() * len(bx)
            final_loss = total_loss / len(dataset)

        # In-sample validation metrics
        self.net_.eval()
        with torch.no_grad():
            preds_scaled = self.net_(torch.from_numpy(X_scaled).float()).numpy()
            preds_unscaled = preds_scaled * self.target_std_ + self.target_mean_
            preds_unscaled = np.maximum(0.0, preds_unscaled)
            mae = float(np.mean(np.abs(preds_unscaled - y_raw)))
            rmse = float(np.sqrt(np.mean((preds_unscaled - y_raw) ** 2)))

        self.is_fitted_ = True

        metrics = {
            "mae": round(mae, 3),
            "rmse": round(rmse, 3),
            "final_train_loss": round(final_loss, 4),
            "sequence_count": len(X_raw),
            "epochs": epochs,
        }
        return metrics

    def predict_with_uncertainty(
        self,
        sequence_df_or_array: Union[pd.DataFrame, np.ndarray],
        num_mc_samples: int = 10,
    ) -> dict[str, Any]:
        """Generate near-term flow forecast with Monte Carlo dropout uncertainty.

        Args:
            sequence_df_or_array: Sequence of observations (DataFrame of >= sequence_length rows
                or numpy array of shape (sequence_length, num_features)).
            num_mc_samples: Number of stochastic forward passes for uncertainty estimation.

        Returns:
            Dictionary containing:
                - 'predicted_flow': Expected vehicle count (float >= 0.0)
                - 'uncertainty': Standard deviation of predictions (spread)
                - 'confidence': Heuristic confidence score in [0.0, 1.0]
                - 'prediction_interval': tuple (lower_bound, upper_bound)
                - 'method': 'mc_dropout'
        """
        if not self.is_fitted_ or self.net_ is None:
            raise RuntimeError("FlowLSTM is not fitted. Train or load weights before predicting.")

        if isinstance(sequence_df_or_array, pd.DataFrame):
            df_feat = self.extract_features(sequence_df_or_array)
            if len(df_feat) < self.sequence_length:
                raise ValueError(
                    f"Expected at least {self.sequence_length} sequence rows, received {len(df_feat)}"
                )
            # Take the latest sequence_length observations
            seq = df_feat.iloc[-self.sequence_length :][self.feature_names].to_numpy(dtype=np.float32)
        else:
            seq = np.asarray(sequence_df_or_array, dtype=np.float32)
            if seq.ndim == 2:
                seq = seq[-self.sequence_length :]

        # Normalize sequence
        seq_scaled = (seq - self.scaler_mean_) / self.scaler_std_
        input_tensor = torch.from_numpy(seq_scaled).float().unsqueeze(0)  # Shape (1, seq_len, features)

        # Run MC dropout stochastic passes
        self.net_.eval()
        samples: list[float] = []
        with torch.no_grad():
            for _ in range(num_mc_samples):
                out_scaled = self.net_.forward_mc(input_tensor).item()
                out_unscaled = out_scaled * self.target_std_ + self.target_mean_
                samples.append(max(0.0, float(out_unscaled)))

        arr = np.array(samples, dtype=float)
        mean_flow = float(np.mean(arr))
        std_flow = float(np.std(arr)) if len(arr) > 1 else 1.0

        # Heuristic confidence: dispersion relative to predicted magnitude
        conf = 1.0 / (1.0 + std_flow / (mean_flow + 1.0))
        conf = float(np.clip(conf, 0.0, 1.0))

        interval_low = max(0.0, round(mean_flow - 1.96 * std_flow, 2))
        interval_high = round(mean_flow + 1.96 * std_flow, 2)

        return {
            "predicted_flow": round(mean_flow, 2),
            "uncertainty": round(std_flow, 4),
            "confidence": round(conf, 4),
            "prediction_interval": (interval_low, interval_high),
            "mc_samples": num_mc_samples,
            "method": "mc_dropout_uncertainty",
        }

    def save(self, path: Union[str, Path]) -> None:
        """Persist model bundle to disk."""
        target_path = Path(path).resolve()
        target_path.parent.mkdir(parents=True, exist_ok=True)

        bundle = {
            "sequence_length": self.sequence_length,
            "horizon_steps": self.horizon_steps,
            "hidden_size": self.hidden_size,
            "num_layers": self.num_layers,
            "dropout": self.dropout,
            "random_state": self.random_state,
            "architecture": "lstm",
            "feature_names": self.feature_names,
            "target_names": self.target_names,
            "meta": self.meta,
            "scaler_mean": self.scaler_mean_,
            "scaler_std": self.scaler_std_,
            "target_mean": self.target_mean_,
            "target_std": self.target_std_,
            "is_fitted": self.is_fitted_,
            "state_dict": self.net_.state_dict() if self.net_ is not None else None,
        }
        joblib.dump(bundle, target_path)

    @classmethod
    def load(cls, path: Union[str, Path]) -> "FlowLSTM":
        """Load persisted FlowLSTM model bundle from disk."""
        source_path = Path(path).resolve()
        if not source_path.exists():
            raise FileNotFoundError(f"LSTM model file not found: {source_path}")

        loaded = joblib.load(source_path)
        if isinstance(loaded, cls):
            return loaded

        if not isinstance(loaded, dict):
            raise TypeError(f"Unrecognized serialized model object type: {type(loaded)}")

        instance = cls(
            sequence_length=loaded.get("sequence_length", DEFAULT_SEQUENCE_LENGTH),
            horizon_steps=loaded.get("horizon_steps", DEFAULT_HORIZON_STEPS),
            hidden_size=loaded.get("hidden_size", 32),
            num_layers=loaded.get("num_layers", 1),
            dropout=loaded.get("dropout", 0.15),
            random_state=loaded.get("random_state", 42),
        )
        instance.architecture = loaded.get("architecture", "lstm")
        instance.feature_names = loaded.get("feature_names", list(LSTM_FEATURE_NAMES))
        instance.target_names = loaded.get("target_names", ["vehicle_count"])
        instance.meta = loaded.get("meta", {})
        instance.scaler_mean_ = loaded.get("scaler_mean")
        instance.scaler_std_ = loaded.get("scaler_std")
        instance.target_mean_ = loaded.get("target_mean", 0.0)
        instance.target_std_ = loaded.get("target_std", 1.0)
        instance.is_fitted_ = loaded.get("is_fitted", False)

        state_dict = loaded.get("state_dict")
        if state_dict is not None:
            instance.net_ = FlowLSTMNet(
                input_size=len(instance.feature_names),
                hidden_size=instance.hidden_size,
                num_layers=instance.num_layers,
                dropout=instance.dropout,
            )
            instance.net_.load_state_dict(state_dict)
            instance.net_.eval()

        return instance
