# Predictive AI Architecture & Traffic Forecasting (Phase 5)

This document provides complete technical specifications, architectural layout justifications, feature engineering formulations, empirical evaluation benchmarks, and operational limitations for the Predictive AI and Traffic Forecasting subsystem in **AI TrafficOS**.

---

## 1. Architectural Layout & Modular Design

The predictive AI subsystem is structured into two cleanly decoupled layers: a framework-agnostic core forecasting library (`ai/forecasting/`) and a production FastAPI service/API layer (`backend/app/services/forecasting.py`, `backend/app/api/v1/forecasting.py`, and `backend/app/services/routing/forecast_adapter.py`).

```
AI-TrafficOS/
├── ai/
│   ├── forecasting/
│   │   ├── __init__.py             # Public exports (forecaster, registry, pipeline)
│   │   ├── exceptions.py           # Typed forecasting exceptions (InsufficientDataError)
│   │   ├── datasets.py             # Chronological train/val/test splitter
│   │   ├── synthetic.py            # SyntheticTrafficGenerator for bootstrapping
│   │   ├── features.py             # 19 engineered lag, cyclic, and rolling features
│   │   ├── models.py               # TrafficForecaster multi-target ensemble
│   │   ├── registry.py             # Filesystem ModelRegistry (joblib + metadata.json)
│   │   ├── pipeline.py             # train_pipeline orchestrator & load_latest_forecaster
│   │   └── artifacts/              # Local model storage (.gitignored)
│   └── prediction/
│       └── base.py                 # Abstract BasePredictor interface
├── backend/app/
│   ├── models/
│   │   ├── ml.py                   # MLModel SQLAlchemy catalog entity
│   │   └── ai.py                   # AIPrediction database model
│   ├── schemas/
│   │   └── forecasting.py          # Pydantic schemas (TrainRequest, PredictRequest, etc.)
│   ├── services/
│   │   ├── forecasting.py          # Telemetry loading, training orchestration, prediction persistence
│   │   └── routing/
│   │       └── forecast_adapter.py # Phase 6 routing seam (blend_predicted_congestion, apply_predictions_to_costs)
│   └── api/v1/
│       └── forecasting.py          # REST endpoints (/train, /predict, /models, /models/latest)
└── docs/
    └── PREDICTIVE_AI.md            # Architecture, metrics, limits, and seam specifications
```

### Module Responsibilities

1. **`ai.forecasting.synthetic` (`SyntheticTrafficGenerator`)**:
   - Generates realistic, diurnal 5-minute traffic telemetry matching the `traffic_records` table schema.
   - Embeds morning (07:00–09:00) and evening (16:00–19:00) peak rush hour curves, weekday vs. weekend multipliers, Poisson/Gaussian sensor noise, and stochastic incident perturbations.

2. **`ai.forecasting.features` (`build_feature_frame`)**:
   - Maps raw time-series telemetry into a 19-dimensional tabular feature matrix $X$ and multi-target matrix $y$ for a 30-minute forward horizon ($H = 6$ intervals of 5 minutes).

3. **`ai.forecasting.datasets` (`chronological_split`)**:
   - Partitions time-ordered feature rows into 70% train, 15% validation, and 15% test splits without shuffling.

4. **`ai.forecasting.models` (`TrafficForecaster`)**:
   - Implements `BasePredictor` by wrapping three independent `HistGradientBoostingRegressor` models for volume, congestion, and queue risk.
   - Computes point forecasts and dispersion-based confidence intervals.

5. **`ai.forecasting.registry` (`ModelRegistry`)**:
   - Manages versioned artifact persistence (`v1`, `v2`, ...) containing `model.joblib` and `metadata.json`.
   - Sanitizes NumPy, Pandas, and timestamp types for clean JSON storage.

6. **`ai.forecasting.pipeline` (`train_pipeline`)**:
   - Coordinates end-to-end training, out-of-sample evaluation across validation and test splits, and registry publication.

7. **`backend.app.services.forecasting`**:
   - Bridges PostgreSQL `traffic_records` with the forecasting pipeline, manages artifact records in `ml_models`, and writes multi-target predictions into `ai_predictions`.

8. **`backend.app.services.routing.forecast_adapter`**:
   - Architectural seam providing pure functions to blend real-time sensor measurements with 30-minute predictive forecasts for route cost calculation.

9. **`backend.app.api.v1.forecasting`**:
   - Role-guarded REST endpoints supporting admin model training, officer/admin forward predictions, and public/analyst model catalog inspection.

---

## 2. Model Specification

### Algorithm Choice: Histogram-Based Gradient Boosting

The core model ensemble utilizes `sklearn.ensemble.HistGradientBoostingRegressor` with one dedicated regressor per forecast target:
- `y_volume`: Vehicular flow count at horizon $t + 30\text{ min}$.
- `y_congestion`: Congestion saturation percentage ($0.0$ to $100.0$) at $t + 30\text{ min}$.
- `y_queue`: Queue spillback risk percentage ($0.0$ to $100.0$) at $t + 30\text{ min}$.

### Justification
1. **CPU-Friendly & Ultra-Fast**: Histogram binning (256 discrete bins) groups continuous features into integer bins, reducing split-finding complexity from $O(N \log N)$ to $O(N)$. Training over 18,000 observations takes less than 3 seconds on commodity CPUs, and single-row inference executes in $< 1\text{ ms}$.
2. **Handles Non-Linear Thresholds**: Traffic dynamics exhibit severe non-linearities (e.g., phase transitions from free-flow to gridlock when volume surpasses critical lane capacity). Tree-based ensembles model these step-function phase changes significantly better than linear or autoregressive moving-average models (ARIMA).
3. **No GPU Required**: Eliminates heavy deep learning dependencies (PyTorch/CUDA runtime overhead), dramatically reducing Docker image sizes, cloud compute costs, and deployment friction for municipal traffic control hardware.
4. **Outlier & Monotonicity Robustness**: Gradient boosted decision trees do not require feature scaling or normalization and are intrinsically resilient to sensor spikes.

### Hyperparameter Configuration
All three regressors are trained with reproducible hyperparameters:
```python
{
    "random_state": 42,
    "loss": "squared_error",
    "max_iter": 100,
    "learning_rate": 0.1,
    "max_leaf_nodes": 31,
    "min_samples_leaf": 20,
    "l2_regularization": 0.0,
}
```

---

## 3. Feature Engineering & Prediction Horizon

### 30-Minute Lookahead Horizon ($H = 6$)
The operational planning horizon is defined as **30 minutes forward**:
$$\text{Horizon Steps } H = 6 \quad (\text{at } 5\text{-minute telemetry intervals})$$
$$t_{\text{pred}} = t_{\text{current}} + (6 \times 5\text{ min}) = t_{\text{current}} + 30\text{ min}$$

### 19 Engineered Features
The feature matrix $X$ consists of 19 engineered features capturing temporal rhythm, recent inertia, and moving momentum:

| Feature Index | Feature Name | Category | Description |
|---|---|---|---|
| 0 | `hour_sin` | Cyclic Time | $\sin(2\pi \cdot \text{hour} / 24)$ encoding continuous time-of-day |
| 1 | `hour_cos` | Cyclic Time | $\cos(2\pi \cdot \text{hour} / 24)$ encoding continuous time-of-day |
| 2 | `day_of_week_sin` | Cyclic Time | $\sin(2\pi \cdot \text{dow} / 7)$ encoding weekly schedule progression |
| 3 | `day_of_week_cos` | Cyclic Time | $\cos(2\pi \cdot \text{dow} / 7)$ encoding weekly schedule progression |
| 4 | `is_weekend` | Calendar | Binary indicator ($1$ for Saturday/Sunday, $0$ for Monday–Friday) |
| 5 | `is_peak_hour` | Calendar | Binary indicator ($1$ during 07:00–09:00 or 16:00–19:00 rush hours) |
| 6 | `vehicle_count_lag_1` | Autoregressive | Volume observed $1$ step ago ($t - 5\text{ min}$) |
| 7 | `vehicle_count_lag_2` | Autoregressive | Volume observed $2$ steps ago ($t - 10\text{ min}$) |
| 8 | `vehicle_count_lag_3` | Autoregressive | Volume observed $3$ steps ago ($t - 15\text{ min}$) |
| 9 | `vehicle_count_lag_6` | Autoregressive | Volume observed $6$ steps ago ($t - 30\text{ min}$) |
| 10 | `vehicle_count_lag_12` | Autoregressive | Volume observed $12$ steps ago ($t - 60\text{ min}$) |
| 11 | `vehicle_count_rolling_mean_3` | Rolling Aggregate | Rolling mean volume over previous 15 minutes ($k=3$) |
| 12 | `vehicle_count_rolling_mean_6` | Rolling Aggregate | Rolling mean volume over previous 30 minutes ($k=6$) |
| 13 | `vehicle_count_rolling_mean_12` | Rolling Aggregate | Rolling mean volume over previous 60 minutes ($k=12$) |
| 14 | `congestion_level_rolling_mean_3` | Rolling Aggregate | Rolling mean congestion over previous 15 minutes ($k=3$) |
| 15 | `congestion_level_rolling_mean_6` | Rolling Aggregate | Rolling mean congestion over previous 30 minutes ($k=6$) |
| 16 | `congestion_level_rolling_mean_12` | Rolling Aggregate | Rolling mean congestion over previous 60 minutes ($k=12$) |
| 17 | `avg_speed_kmh_lag_1` | Telemetry Lag | Observed vehicular velocity at $t - 5\text{ min}$ |
| 18 | `incident_active_lag_1` | Incident Indicator | Binary indicator if an incident was active at $t - 5\text{ min}$ |

---

## 4. Training Procedure & Validation Split

### Strict Chronological Partitioning (No Shuffling)
Standard $k$-fold cross-validation or random train-test splitting introduces **lookahead bias** (temporal leakage), where future observations contaminate past training weights.

To guarantee zero lookahead bias:
1. All telemetry records are sorted strictly by `(intersection_id, recorded_at ASC)`.
2. Lags and rolling aggregates are computed per intersection.
3. Partitions are sliced chronologically:
   - **Training Set (70%)**: Historical baseline $[t_0, t_{0.70})$.
   - **Validation Set (15%)**: Out-of-sample hyperparameter and variance tuning $[t_{0.70}, t_{0.85})$.
   - **Test Set (15%)**: Final hold-out evaluation simulating future live operations $[t_{0.85}, t_{1.00}]$.

```
Telemetry Timeline:
|==================== Train (70%) ====================|====== Val (15%) ======|====== Test (15%) ======|
t=0                                                  t=70%                  t=85%                   t=100%
```

### Two-Tier Insufficient Data Policy
1. **Pipeline Tier (`MIN_PIPELINE_ROWS = 2000`)**:
   - `train_pipeline` requires at least 2,000 raw telemetry rows (~7 full days of 5-minute intervals). If fewer rows exist, it raises `InsufficientDataError(rows_found, rows_required=2000)`.
2. **Feature Frame Tier (`MIN_TRAINING_ROWS = 500`)**:
   - Because $12$ lag steps and $6$ horizon steps are dropped at the series boundaries ($18$ dropped rows per intersection), `chronological_split` enforces a secondary guard requiring at least 500 valid feature rows.

---

## 5. Measured Evaluation Metrics

The following metrics are **measured empirical results** from running `train_pipeline` on the standard 21-day, 3-intersection synthetic traffic benchmark dataset (18,144 records total; seed=42):

### Test-Split Hold-Out Performance (Final 15% Unseen Future Window)

| Target Variable | Target Description | Test MAE | Test RMSE | Test $R^2$ Score | Performance Interpretation |
|---|---|---|---|---|---|
| `y_volume` | 30-min Vehicular Volume (veh/5min) | **3.1779** | **4.0201** | **0.9457** | Excellent diurnal tracking ($R^2 > 0.94$); captures morning and evening peak curves accurately. |
| `y_congestion` | 30-min Congestion Index (0–100%) | **3.7225** | **6.3597** | **0.7655** | Strong predictive fidelity ($R^2 > 0.76$); average absolute error $< 3.8\%$. |
| `y_queue` | 30-min Queue Spillback Risk (0–100%) | **3.3897** | **6.8455** | **0.7594** | High sensitivity to bottleneck formation ($R^2 > 0.75$); average error $< 3.4\%$. |

### Validation-Split Performance (Intermediate 15% Window)

| Target Variable | Validation MAE | Validation RMSE | Validation $R^2$ Score |
|---|---|---|---|
| `y_volume` | 3.1021 | 3.9272 | 0.9424 |
| `y_congestion` | 3.9904 | 7.4360 | 0.6767 |
| `y_queue` | 3.8886 | 8.5332 | 0.6403 |

> [!NOTE]
> The test-split $R^2$ of **0.9457** for `y_volume` comfortably exceeds the project sanity bound ($R^2 > 0.50$), proving the engineered lag and cyclic features learn synthetic diurnal rhythms effectively.

---

## 6. Phase 6 Routing Seam (`forecast_adapter`)

Phase 3 established deterministic graph shortest-path routing (Dijkstra and $A^*$). Phase 6 (Autonomous Routing & Dynamic Corridors) will invoke `backend.app.services.routing.forecast_adapter` immediately before graph evaluation to blend live telemetry with 30-minute predictive lookahead.

### Convex Combination Formula
To prevent vehicle "herding" onto corridors that are currently clear but impending gridlock:
$$\text{blended\_congestion} = (1.0 - \alpha) \cdot \text{base\_congestion} + \alpha \cdot \text{predicted\_congestion}$$

- $\alpha = 0.0$: Purely reactive routing (uses current sensor observation only).
- $\alpha = 0.5$: Balanced predictive routing (equal blend of live state and 30-min forecast).
- $\alpha = 1.0$: Fully predictive routing (routes based solely on expected conditions).
- Clamped strictly within $[0.0, 100.0]$.

### Traversal Cost Scaling Function
`apply_predictions_to_costs(edge_costs, predictions, alpha=0.5)` adjusts edge travel times according to impending corridor saturation:
$$\text{multiplier} = 1.0 + \left(\frac{\text{blended\_congestion}}{100.0}\right) \times 2.0$$
$$\text{cost}_{\text{adjusted}} = \text{cost}_{\text{base}} \times \text{multiplier}$$

Corridors forecasted to reach 100% congestion experience a $3.0\times$ impedance penalty, dynamically redirecting Dijkstra/$A^*$ path selection away from bottlenecks.

---

## 7. Insufficient Data Policy

The platform strictly prohibits fabricating synthetic predictions when telemetry is missing:

| Operation | Condition | System Behavior |
|---|---|---|
| **Model Training** (`POST /forecasting/train`) | Total telemetry $< 2,000$ rows | Fails immediately with HTTP 422 (`error: "insufficient_data"`), reporting exact `rows_found` and `rows_required`. |
| **Model Training** (`POST /forecasting/train`) | Real + synthetic data mix | If real camera/sensor rows $\ge 2,000$, trains exclusively on real data. If real rows $< 2,000$, retains synthetic records to prevent starvation. |
| **Inference** (`POST /forecasting/predict`) | Intersection has $< 20$ records in last 24h | Marked as `status: "insufficient_data"`. Returned in the response `insufficient` list with diagnostic row counts (`rows_found`, `rows_required=20`). **Zero rows written to `ai_predictions`**. |
| **Inference** (`POST /forecasting/predict`) | No model registered | Returns HTTP 404 (`error: "No forecasting models found in registry"`). |

---

## 8. Honest Limitations & Operational Boundaries

1. **Synthetic Telemetry Baseline**:
   - Initial training relies on synthetic traffic data generated by `SyntheticTrafficGenerator`. While realistic (incorporating diurnal cycles, weekend dips, and stochastic incidents), synthetic distributions cannot perfectly mirror municipal real-world edge cases (extreme weather, construction detours, mass sporting events). The model must be scheduled for automated retraining once real telemetry accumulates.
2. **Dispersion-Based Confidence Heuristic**:
   - Model confidence scores ($0.0$ to $1.0$) are derived from training residual standard deviations ($\sigma_{\text{res}}$):
     $$\text{dispersion} = \min(1.0, \frac{\sigma_{\text{res}}}{\text{scale}}), \quad \text{confidence} = \max(0.1, 1.0 - \text{dispersion})$$
     This reflects residual spread, **not a calibrated Bayesian posterior probability**.
3. **Telemetry Dependency**:
   - Predictions assume continuous 5-minute sampling. Sensor dropouts or network partitions will reduce feature accuracy.
4. **Inherited Vision Perception Bounds**:
   - Ingested camera telemetry inherits Phase 4 perception bounds (lens occlusion, severe glare, field-of-view limits). Low-quality input counts propagate forward into downstream predictions.
