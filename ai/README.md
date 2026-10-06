# AI TrafficOS - AI & Perception Architecture

Perception and predictive analytics architectural foundation for AI TrafficOS.

## Design Philosophy

In accordance with Phase 1 architectural requirements, this package defines clean contracts, interfaces, and shared data schemas without fake models or simulated detections. Real machine learning pipelines, tensor runtimes, and model weights arrive in dedicated subsequent phases.

## Feature Mapping & Implementation Roadmap

| Feature Category | Specific AI Feature | Stub File / Interface | Implementing Phase | Scope & Description |
| :--- | :--- | :--- | :--- | :--- |
| **Perception (CV)** | Vehicle Detection | `ai/cv/detectors.py` (`BaseDetector`) | **Phase 4** | Multiclass vehicle localization and counting (cars, buses, trucks, motorcycles, bicycles). |
| **Perception (CV)** | Signal State Classification | `ai/cv/detectors.py` (`BaseDetector`) | **Phase 4** | Real-time classification of traffic signal aspect heads (red, yellow, green, turn arrows). |
| **Perception (CV)** | Emergency Vehicle Detection | `ai/cv/detectors.py` (`BaseDetector`) | **Phase 4** | Priority vehicle identification (sirens, light bar patterns) for emergency preemption. |
| **Forecasting** | Traffic Flow Forecasting | `ai/prediction/base.py` (`BasePredictor`) | **Phase 5** | Spatial-temporal forecasting of lane volume and flow rates at 5 to 30 minute horizons. |
| **Forecasting** | Congestion & Bottleneck Prediction | `ai/prediction/base.py` (`BasePredictor`) | **Phase 5** | Queuing delay estimation, spillback hazard forecasting, and gridlock alerts. |

## Data Schemas

Shared data contracts are located in `ai/common/schemas.py`:
- `Detection`: Frozen dataclass containing bounding box coordinates (`bbox`), class label (`label`), confidence score (`confidence`), and timestamp.
- `TrafficSnapshot`: Frozen dataclass containing aggregated intersection telemetry (`intersection_id`, `vehicle_count`, `timestamp`, `raw`).
