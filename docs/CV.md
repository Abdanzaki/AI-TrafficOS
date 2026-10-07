# Computer Vision & Perception Architecture (Phase 4)

This document provides technical specifications, architectural layout justifications, performance benchmarks, and limitations for the Computer Vision perception subsystems in **AI TrafficOS**.

---

## 1. Architectural Layout & Modular Design

To support modular reuse across edge video workers, streaming ingestion nodes, and downstream Phase 5 (Traffic Flow Forecasting) and Phase 6 (Traffic Signal Control & Preemption), the vision subsystem is divided into two decoupled layers:

```
AI-TrafficOS/
├── ai/
│   ├── common/
│   │   └── schemas.py              # Detection dataclass, SignalDetection
│   └── cv/
│       ├── detectors.py            # BaseDetector ABC interface
│       ├── exceptions.py           # Typed exception hierarchy (VisionDetectorError, etc.)
│       ├── emergency_heuristic.py  # EmergencyVehicleHeuristic rule-based layer
│       ├── yolo_detector.py        # Concrete YoloVehicleDetector implementing BaseDetector
│       ├── signal_state_heuristic.py # Classical-CV SignalStateHeuristic (HSV + spatial margin)
│       ├── signal_detector.py      # TrafficSignalDetector (YOLO COCO traffic light + heuristic)
│       ├── metrics.py              # FrameMetrics, PolygonROI, density, occupancy, queue length
│       ├── tracking.py             # MultiObjectTracker, TrackedVehicle, speed estimation
│       ├── congestion.py           # Congestion scoring (0-100) & far-field traffic-ahead
│       ├── incidents.py            # Stopped-vehicle & wrong-way heuristics
│       └── video_processor.py      # VideoProcessor pipeline with stride sampling & typed errors
└── backend/app/
    ├── ml/models/
    │   └── yolov8n.pt              # Ultralytics YOLOv8 Nano model weights
    └── vision/
        ├── __init__.py             # Vision package exports
        ├── detectors.py            # FastAPI dependency injection, adapters & signal storage
        ├── metrics.py              # Provider functions for metrics computation
        ├── tracking.py             # Provider functions for multi-object tracking
        ├── congestion.py           # Provider functions for congestion scoring
        ├── incidents.py            # Provider functions for incident heuristics
        ├── storage.py              # Async DB persistence for TrafficRecord & Incident
        └── processor.py            # Provider functions for video processing pipeline
```

### Layout Justification

1. **Decoupled AI Core (`ai/cv/`):**
   - The detector implementations (`YoloVehicleDetector`, `TrafficSignalDetector`), heuristic layers (`EmergencyVehicleHeuristic`, `SignalStateHeuristic`), metrics algorithms (`ai/cv/metrics.py`), tracking engine (`ai/cv/tracking.py`), and video pipeline (`ai/cv/video_processor.py`) reside strictly within `ai/cv/`.
   - This keeps the perception algorithms decoupled from the web framework. Standalone streaming processes (e.g., RTSP frame pullers, Celery tasks, Kafka consumers) can run vision inference headlessly without importing FastAPI or web server dependencies.


2. **FastAPI Backend Integration (`backend/app/vision/`):**
   - The FastAPI backend accesses vision subsystems through modular providers:
     - `get_vehicle_detector()`: A thread-safe, cached singleton provider for dependency injection across FastAPI route handlers.
     - `get_vehicle_tracker()`: Provider instantiating multi-object tracking sessions.
     - `get_metrics_calculator()`: Provider returning callable frame metrics computation.
     - `get_video_processor()`: Provider wiring detector, tracker, and metrics into a video stream processor.
     - `detection_to_vehicle_event_create()`: A data adapter translating raw `Detection` dataclasses into validated Pydantic schemas (`VehicleEventCreate`) consumed by `/api/v1/vehicle-events`.

---

## 2. Model Specification

- **Architecture:** Ultralytics YOLOv8 Nano (`yolov8n`)
- **Weights File:** `backend/app/ml/models/yolov8n.pt` (6.3 MB)
- **Parameters:** ~3.2 million
- **Inference Precision:** FP32 (CPU) / FP16 (CUDA enabled)
- **Input Resolutions:**
  - Standard: `640x640` (balanced latency and spatial resolution)
  - Low-latency edge mode: `320x320` (optimized for constrained CPU environments)

---

## 3. Class Mapping & Filtering Strategy

Standard MS-COCO contains 80 classes. The traffic perception engine strictly targets vehicle categories relevant to traffic management, mapping them directly to database `VehicleEvent.vehicle_type` values:

| COCO Class ID | COCO Class Name | Database `vehicle_type` | Traffic Monitoring Role |
| :---: | :---: | :---: | :---: |
| **2** | `car` | `car` | Passenger automobiles, sedans, SUVs, taxis |
| **3** | `motorcycle` | `motorcycle` | Two-wheeled motorized vehicles, scooters |
| **5** | `bus` | `bus` | Transit buses, coaches, school buses |
| **7** | `truck` | `truck` | Commercial delivery trucks, semi-trailers, freight |

### Suppression of Non-Vehicle Classes
Non-vehicle COCO classes (including class 0 `person`, class 9 `traffic light`, class 11 `stop sign`, animals, backpacks, etc.) are strictly filtered out during inference via the YOLO `classes=[2, 3, 5, 7]` argument. They are never ingested as vehicle events.

---

## 4. Hyperparameter Settings & Justifications

### Confidence Threshold (`conf_threshold = 0.25`)
- **Justification:** In traffic monitoring, missing a vehicle (false negative) causes volume and queue length underestimation. A threshold of `0.25` provides high recall for distant, partially occluded, or low-contrast vehicles (such as smaller motorcycles and queued cars). Downstream tracking algorithms filter out transient low-confidence false positives.

### Non-Maximum Suppression IoU Threshold (`iou_threshold = 0.45`)
- **Justification:** Large vehicles (buses and trucks) often generate multiple overlapping candidate proposals. An IoU threshold of `0.45` prevents duplicate bounding boxes on the same vehicle while avoiding the suppression of distinct, closely spaced vehicles waiting at dense intersection stop bars.

---

## 5. Device Strategy & Execution Targets

The detector implements automatic device selection via `select_optimal_device()`:

```python
if requested_device and requested_device.lower() != "auto":
    return requested_device.lower()
if torch.cuda.is_available():
    return "cuda"
return "cpu"
```

- **CUDA:** Selected automatically when NVIDIA GPU hardware and CUDA drivers are available.
- **CPU:** Default fallback when running in standard cloud containers or developer environments without dedicated GPU accelerators.
- **Explicit Override:** Callers may explicitly pass `device="cpu"`, `device="cuda"`, or `device="cuda:0"`.

---

## 6. Measured CPU Latency & Benchmarks

Measured on standard Linux x86_64 host utilizing PyTorch 2.14.1+cpu:

| Input Resolution | Measured Mean Latency | Latency Range (Min - Max) | Throughput (FPS) |
| :---: | :---: | :---: | :---: |
| **640 x 640** | **~180 - 245 ms** | 173 ms - 269 ms | **~4.1 - 5.5 FPS** |
| **320 x 320** | **~65 ms** | 56 ms - 74 ms | **~15.4 FPS** |

*Note: For real-time 30 FPS video streaming at 640x640 resolution, deployment on a CUDA-enabled GPU (e.g., NVIDIA T4, RTX, or Jetson Orin) or TensorRT export is recommended.*

---

## 7. Emergency Vehicle Heuristic Layer

Because the standard MS-COCO dataset has no category for emergency vehicles (ambulances, fire engines, police units), a dedicated secondary layer—`EmergencyVehicleHeuristic`—is implemented.

### Documented Visual Cues

1. **HSV Color Livery Cues:**
   - Evaluates red pixel ratio in HSV space (`H in [0, 10] U [170, 180], S in [70, 255], V in [50, 255]`).
   - Evaluates white pixel ratio in HSV space (`S in [0, 45], V in [180, 255]`).
   - Computes:
     - Fire Engine cue: predominant red livery (`red_ratio >= 0.12`).
     - Ambulance cue: high white base with red accent decals (`white_ratio >= 0.18` and `red_ratio >= 0.035`).

2. **Flashing-Light Temporal Luminance Variance:**
   - Isolates the upper 25% of the vehicle bounding-box crop (rooftop lightbar ROI).
   - Tracks the 95th percentile luminance across successive frames over a rolling buffer (`history_window = 15`).
   - Computes sample variance across time: strobe and LED flashing lights oscillating at 1–4 Hz induce high temporal variance (`variance > 250`).
   - Combines livery score (45%) and temporal variance (55%) into a composite heuristic score.

3. **Schema Mapping:**
   - Emits detection with label `'emergency_vehicle_heuristic'`.
   - Adapted to `VehicleEventCreate(event_type="emergency_preemption", vehicle_type="emergency_vehicle_heuristic")`.

---

## 8. Operational Traffic Metrics (`ai/cv/metrics.py`)

Operational metrics are calculated from raw `Detection` objects and tracked vehicle states:

### 1. Vehicle Counts per Class and Total
- **Definition:** Counts detected objects categorized by recognized vehicle classes (`car`, `motorcycle`, `bus`, `truck`, `emergency_vehicle_heuristic`).
- **Physical Deduplication:** Secondary heuristic detections sharing identical bounding boxes with primary vehicle classes are deduplicated to ensure that total physical vehicle counts reflect distinct physical vehicles.

### 2. Traffic Density (Vehicles / Frame Area)
- **Exact Formula:**
  $$\text{Density} = \frac{N_{\text{vehicles}}}{W \times H} \quad [\text{vehicles / pixel}^2]$$
  Normalized: $\text{Density}_{100k} = \text{Density} \times 100{,}000$ (vehicles per 100k square pixels).
- **Honest Limit & Calibration Story:**
  In civil traffic engineering, density is measured in vehicles per lane-kilometer ($\text{veh/km}$) or vehicles per square meter ($\text{veh/m}^2$).
  Projecting 2D camera pixel area to physical ground plane density is strictly non-linear due to perspective foreshortening. Objects close to the camera occupy drastically more pixel area than distant vehicles. Converting 2D screen density into physical roadway density requires per-camera calibration:
  - Intrinsic camera matrix (focal length, sensor optical center)
  - Extrinsic parameters (mounting elevation, tilt/pitch angle)
  - Homography perspective matrix mapping road surface to bird's-eye view.
  **Without per-camera calibration, pixel density is an image-space proxy only.**

### 3. Lane Occupancy (Polygon ROI Intersection)
- **Exact Formula:**
  $$\text{Occupancy} = \frac{\text{Area}\left(\left( \bigcup_{i} \text{BBox}_i \right) \cap \text{ROI} \right)}{\text{Area}(\text{ROI})} \in [0.0, 1.0]$$
- **Implementation:**
  Computed via OpenCV binary rasterization masks (`cv2.fillPoly` and `cv2.rectangle` with bitwise logical AND). This guarantees:
  - Pixel-exact occupancy calculation for arbitrary convex or concave polygon boundaries.
  - Automatic elimination of double-counting when multiple vehicle bounding boxes overlap within the same lane.
- **Honest Limit & Calibration Story:**
  Defining lane ROIs requires manual ground-truth surveying or per-camera polygon configuration. Distant sections of a lane appear smaller on camera; thus, an uncalibrated pixel occupancy does not equal the physical inductive loop occupancy used in SCATS/SCOOT without inverse perspective mapping (IPM).

### 4. Queue Length (Low-Movement Vehicles)
- **Exact Formula:**
  $$\text{Queue Length} = \sum_{j \in \text{Tracks}} \mathbb{I}\left( \text{Centroid}_j \in \text{ROI}_{\text{queue}} \land \text{Speed}_j \le v_{\text{thresh}} \right)$$
- **Default Threshold:** $v_{\text{thresh}} = 5.0 \text{ pixels/sec}$.
- **Motion History Requirement:**
  Single-frame detections without multi-frame temporal displacement history have unconfirmed speed (`speed_px_s is None`) and are strictly excluded from queue counts to prevent transient moving vehicles entering the zone from skewing queue statistics.
- **Occlusion Limit:**
  Camera occlusion (e.g. a tall commercial truck hiding small sedans behind it) causes undercounting in dense stop-bar queues.

---

## 9. Multi-Object Tracking & Speed Estimation (`ai/cv/tracking.py`)

### Tracker Architecture (`MultiObjectTracker`)
- **Stable IDs:** Assigns persistent integer track IDs across successive frames.
- **Dual Association Pipeline:**
  1. **Primary IoU Association:** Calculates pairwise Intersection-over-Union between existing track bounding boxes and new detections. Greedy matching pairs boxes with $\text{IoU} \ge 0.30$.
  2. **Centroid Proximity Fallback:** For remaining unmatched pairs, evaluates Euclidean distance between centroids $d = \sqrt{(x_2 - x_1)^2 + (y_2 - y_1)^2}$. Matches within $d \le 90\text{ px}$ are associated.
  3. **Track Lifecycle:** Unmatched detections initiate new tracks. Lost tracks persist across `max_lost_frames = 5` frames before being aged out and deregistered.

### Honest Speed Estimation & Calibration Policy
- **Speed in Pixels/Sec:**
  $$v_{\text{px/s}} = \frac{\Delta d_{\text{pixels}}}{\Delta t_{\text{seconds}}}$$
  Smoothed over a rolling 5-frame observation window to filter single-pixel spatial quantization noise.
- **Physical Speed (km/h) Strict Policy:**
  $$v_{\text{km/h}} = \left( \frac{\Delta d_{\text{pixels}}}{\text{pixels\_per\_meter}} \times \frac{1}{\Delta t} \right) \times 3.6$$
  **POLICY: AI TrafficOS NEVER fabricates or simulates km/h values.**
  If no valid, calibrated `pixels_per_meter` factor is provided, the tracker returns `speed_px_s` and sets `speed_kmh = None`.
- **Single-Frame Rejection:**
  Single static images contain zero temporal displacement ($\Delta t = 0$). Attempting to estimate speed on single images returns `None` or raises `SingleFrameSpeedError`.

---

## 10. Video Processing Pipeline (`ai/cv/video_processor.py`)

`VideoProcessor` ingests video files or camera streams, applies stride sampling, coordinates perception components, and yields per-frame results:

```python
processor = VideoProcessor(
    detector=YoloVehicleDetector(),
    tracker=MultiObjectTracker(pixels_per_meter=12.5),
    frame_stride=3,  # Sample every 3rd frame to conserve CPU
    rois={"lane_north": polygon_lane},
    queue_rois={"queue_north": polygon_queue},
)

for frame_result in processor.process_video("traffic_stream.mp4"):
    print(frame_result.frame_index, frame_result.metrics.total_vehicles)
```

### Stride Sampling for CPU Optimization
Processing 30 FPS video with deep learning on a standard CPU produces latency bottlenecks (~200ms per frame = ~5 FPS max).
Setting `frame_stride = 2` or `frame_stride = 5` reduces CPU load by 50% to 80% while tracking state machines adjust timestamps based on source video FPS ($t = \text{frame\_idx} / \text{FPS}$), preserving correct velocity calculations without temporal distortion.

---

## 11. Input Validation & Error Handling

All detector, tracking, and video processing components enforce typed validation with dedicated exceptions inheriting from `VisionDetectorError`:

- `InvalidInputFrameError`: Input image frame is `None`, empty array, zero dimensions, or missing file.
- `CorruptFrameError`: Image bytes undecodable or array contains `NaN` / `Inf` values.
- `UnsupportedInputFormatError`: Unsupported tensor dimensions or data types.
- `ModelLoadError`: Model weights cannot be located or loaded.
- `SingleFrameSpeedError`: Speed estimation attempted on single frame without temporal history.
- `VideoProcessingError`: Base class for video stream and file errors.
  - `VideoOpenError`: File cannot be opened or does not exist.
  - `UnsupportedVideoFormatError`: Container extension or codec is unsupported.
  - `EmptyVideoError`: Video file is 0 bytes or stream contains zero readable frames.
  - `CorruptVideoError`: Video stream contains corrupt or truncated frames.

---

## 12. Traffic Signal Perception & State Recognition

AI TrafficOS implements a two-stage traffic signal perception pipeline combining deep learning localization with deterministic classical computer vision state recognition:

```
Video Frame
    │
    ▼
[YOLOv8 Nano (Class 9: 'traffic light')]  ──► Bounding Boxes of Signal Heads
    │
    ▼
Crop Signal Head ([y1:y2, x1:x2])
    │
    ▼
[SignalStateHeuristic (Classical CV)]
  ├── 1. HSV Color Segmentation (Red, Yellow, Green masks)
  ├── 2. Vertical Spatial Lamp Partitioning (Top=Red, Mid=Yellow, Bot=Green)
  ├── 3. V-Channel Gaussian Peak Core Analysis
  └── 4. Dominance Margin Evaluation: M = (S_1 - S_2) / (S_1 + ε)
    │
    ├── If M < 0.20 or pixels < min_threshold ──► State: 'unknown' (Confidence <= 0.35)
    └── If M >= 0.20 ─────────────────────────► State: 'red' | 'yellow' | 'green'
```

### 1. Classical-CV Layer vs. Trained Deep Classifier

The illuminated lamp state is classified using **`SignalStateHeuristic`**, a classical-CV algorithm using OpenCV HSV color analysis and spatial position geometry. It is **explicitly NOT a trained machine learning or deep neural network classifier**.

**Architectural Rationale:**
1. **Annotation Scarcity:** Standard large-scale vision datasets (e.g. MS-COCO, OpenImages) supply bounding-box ground truth for the object class `"traffic light"`, but do **not** label which specific lamp is lit (red vs. yellow vs. green). Training a deep classifier would require massive, bespoke, per-jurisdiction datasets.
2. **Safety-Critical Explainability:** Traffic light state informs control decisions and emergency preemption. Deep convolutional networks act as black boxes subject to unpredictable domain shift (e.g., unusual backplates or surrounding neon signage). In contrast, deterministic HSV thresholds and spatial zone geometry are fully inspectable, repeatable, and auditable during safety reviews.
3. **Explicit Ambiguity Rejection vs. Softmax Overconfidence:** Deep classification heads apply softmax normalization which forces class probabilities to sum to 1.0, frequently outputting high confidence on ambiguous or out-of-distribution inputs. `SignalStateHeuristic` calculates an explicit color dominance margin:
   $$M = \frac{S_{\text{first}} - S_{\text{second}}}{S_{\text{first}} + 10^{-6}}$$
   When the margin is narrow ($M < 0.20$), the heuristic strictly refuses to guess and emits state `'unknown'` with low confidence.

### 2. Method & Technical Formulation

For each detected signal head bounding box $(x_1, y_1, x_2, y_2)$:
1. **Crop Normalization:** The sub-image is extracted with boundary clamping. Crops smaller than $4 \times 4$ pixels return `'unknown'`.
2. **HSV Color Masking:**
   - **Red:** Dual hue bands accounting for 8-bit wrap-around:
     $$H \in [0, 10] \cup [160, 180], \quad S \in [55, 255], \quad V \in [55, 255]$$
   - **Yellow / Amber:**
     $$H \in [11, 35], \quad S \in [55, 255], \quad V \in [55, 255]$$
   - **Green:** Pure green through traffic teal:
     $$H \in [36, 95], \quad S \in [45, 255], \quad V \in [45, 255]$$
3. **Vertical Spatial Partitioning:** Standard vertical signal heads follow MUTCD standards:
   - **Top 42% ($y < 0.42 H$):** Expected Red lamp zone.
   - **Middle band ($0.20 H \le y \le 0.80 H$):** Expected Yellow lamp zone.
   - **Bottom 42% ($y > 0.58 H$):** Expected Green lamp zone.
   Each color's raw pixel count $N_c$ is modulated by its spatial consistency factor $F_c \in [0.0, 1.0]$:
   $$S_c = N_c \times (0.65 + 0.35 \times F_c)$$
4. **Brightest Core Verification:** Gaussian smoothing on the $V$ (luminance) channel locates the primary emitter core coordinates $(x_{\text{peak}}, y_{\text{peak}})$, confirming that the illuminated region corresponds to an active emitter rather than passive ambient reflection.
5. **Confidence Scoring:**
   $$\text{Confidence} = \min\left(0.99, \, \max\left(0.40, \, 0.50 \times M + 0.30 \times F_{\text{top}} + 0.20 \times \frac{V_{\text{max}}}{255}\right)\right)$$

### 3. Physical & Optical Limitations

Civil traffic perception operates in harsh, unconstrained environments. The vision pipeline explicitly documents the following operational boundaries:

| Challenge | Physical Mechanism | System Mitigation |
| :--- | :--- | :--- |
| **Nighttime Bloom / Halation** | High-intensity LED signal lamps in dark environments cause lens flare bleeding across unlit adjacent lenses. | Spatial consistency factor checks lamp centroid; narrow margins trigger `'unknown'`. |
| **Sun Phantom Glare** | Low-angle sunlight (early morning/late afternoon) entering the signal lens reflects off internal parabolic mirrors, illuminating unlit lenses. | Luminance peak analysis combined with saturation filtering suppresses washed-out white/amber sun glare. |
| **Camera Occlusion** | Tall vehicles (semi-trailers, double-decker buses), tree branches, and construction equipment physically block camera line-of-sight. | Missing detections yield empty results (`[]`) without generating pipeline errors. |
| **Non-Standard Signal Heads** | Horizontal signal heads, doghouse 5-section turn clusters, flashing yellow arrows, and pedestrian walk signals deviate from standard vertical 3-lamp geometry. | Vertical spatial consistency penalizes non-vertical layouts; doghouse configurations require dedicated ROI templates. |

### 4. Storage Architecture & Minimal Honest Design Decision

#### Context & Problem Definition
A critical architectural distinction exists between commanded plans, hardware health, and computer vision observations:
- **`SignalPhase.state` (`red`, `yellow`, `green`):** The **commanded schedule** programmed into the municipal signal controller.
- **`Signal.status` (`active`, `inactive`, `maintenance`, `fault`):** The **hardware operational status** of the controller cabinet.
- **Camera Observation:** A **physical sensor measurement** captured at timestamp $t$ by an optical sensor ($(\text{state}, \text{confidence}, \text{timestamp})$).

#### Design Decision: In-Place `Signal` Extension via Alembic Migration
Rather than creating an unnecessary new table or shoehorning signal data into unrelated models, AI TrafficOS extends the existing `signals` table with dedicated observation columns:

```sql
ALTER TABLE signals ADD COLUMN observed_state VARCHAR(20);
ALTER TABLE signals ADD COLUMN observed_confidence FLOAT;
ALTER TABLE signals ADD COLUMN observed_at TIMESTAMP WITH TIME ZONE;
CREATE INDEX ix_signals_observed_state ON signals (observed_state);
```
*(Applied via Alembic migration `0004_signal_observations.py`)*

#### Architectural Justification
1. **Rejection of Unnecessary Tables:** Creating a separate `signal_observations` table would introduce write amplification, table proliferation, and expensive join requirements for real-time dashboard queries.
2. **Rejection of `TrafficRecord` Overloading:** `TrafficRecord` is strictly defined for aggregated vehicular flows (`vehicle_count`, `avg_speed_kmh`, `congestion_level`) across road lanes. Storing optical signal head states in `TrafficRecord` would violate single-responsibility domain boundaries.
3. **Automated Discrepancy & Fault Detection:** Maintaining `observed_state` directly on `Signal` allows downstream monitoring services to immediately compare real-world camera observations against the active commanded `SignalPhase.state`. If the controller commands `green` while the camera repeatedly observes `red` or unlit (`unknown`) with high confidence, the system can flag a physical lamp burnout or controller fault (`Signal.status = 'fault'`).

---

## 13. Operational Congestion Scoring & Far-Field Traffic-Ahead Architecture

AI TrafficOS evaluates corridor congestion directly from optical perception metrics via `ai/cv/congestion.py`. The resulting score is an honest integer percentage in $[0, 100]$ that maps directly onto `TrafficRecord.congestion_level` (`source='camera'`).

### 1. Documented Mathematical Formulation

The overall congestion score $C \in [0, 100]$ combines spatial occupancy, temporal speed deficit, and queue concentration:

$$C = \text{round}\left(100 \times \min\left(1.0, \max\left(0.0, C_{\text{raw}}\right)\right)\right)$$

#### Component 1: Lane Occupancy Factor ($S_{\text{occ}} \in [0.0, 1.0]$)
- When calibrated lane ROIs $L = \{l_1, \dots, l_k\}$ are defined:
  $$S_{\text{occ}} = \frac{1}{|L|} \sum_{l \in L} \text{Occupancy}(l)$$
- In uncalibrated screen space without lane polygons, normalized density per 100,000 pixels is compared against a reference jam density $D_{\text{jam}} = 5.0$ veh/100k px:
  $$S_{\text{occ}} = \min\left(1.0, \frac{D_{\text{100k}}}{D_{\text{jam}}}\right)$$

#### Component 2: Speed Deficit Factor ($S_{\text{speed}} \in [0.0, 1.0]$)
Measures the velocity reduction relative to expected free-flow velocity $V_{\text{free}}$:
$$\text{Deficit}(V_{\text{avg}}, V_{\text{free}}) = \max\left(0.0, \min\left(1.0, 1.0 - \frac{V_{\text{avg}}}{V_{\text{free}}}\right)\right)$$
- **Calibrated Physical Mode:** When tracked vehicles possess calibrated km/h speeds ($V_{\text{avg}} = \frac{1}{|T_{\text{cal}}|} \sum t.\text{speed\_kmh}$ and $V_{\text{free}} = 50.0\text{ km/h}$).
- **Pixel Speed Mode:** When uncalibrated pixel displacement speeds exist and $V_{\text{free,px\_s}}$ is configured.
- **Speed Absent Mode:** When tracking history is unavailable (e.g. single static frame or newly appeared objects), $S_{\text{speed}}$ is strictly `None`. The system **never fabricates km/h values**.

#### Component 3: Queue Factor ($S_{\text{queue}} \in [0.0, 1.0]$)
Measures the proportion of vehicles trapped at a standstill or low-movement ($\le 5.0\text{ px/s}$):
$$S_{\text{queue}} = \min\left(1.0, \frac{N_{\text{queue}}}{\max(1, N_{\text{total}})}\right)$$

#### Component 4: Honest Weight Rebalancing
When speed data is absent, weights dynamically rebalance across available spatial factors rather than assuming an arbitrary speed:

| Perception State | $w_{\text{occupancy}}$ | $w_{\text{speed}}$ | $w_{\text{queue}}$ | Governing Equation |
| :--- | :---: | :---: | :---: | :--- |
| **Full Multimodal** (calibrated/speed valid) | $0.45$ | $0.35$ | $0.20$ | $C_{\text{raw}} = 0.45 S_{\text{occ}} + 0.35 S_{\text{speed}} + 0.20 S_{\text{queue}}$ |
| **Spatial Only** (uncalibrated / speed None) | $0.70$ | $0.00$ | $0.30$ | $C_{\text{raw}} = 0.70 S_{\text{occ}} + 0.30 S_{\text{queue}}$ |
| **Empty Roadway** ($N_{\text{total}} = 0$) | — | — | — | $C = 0$ (empty road is free-flow, never congested) |

---

### 2. Traffic-Ahead Far-Field Detection

Traffic management systems require early warning of upstream highway backups before queues reach the intersection stop bar. `detect_traffic_ahead()` evaluates the differential between a configurable far-field ROI (approaching horizon) and near-field ROI (foreground stop bar):

$$\Delta_{\text{ahead}} = \text{Occupancy}_{\text{far}} - \text{Occupancy}_{\text{near}}$$

- Trigger Condition: $\Delta_{\text{ahead}} \ge 0.20$ OR ($\text{Occupancy}_{\text{far}} \ge 0.50$ and $\Delta_{\text{ahead}} > 0.05$).
- Output: `TrafficAheadResult(traffic_ahead_detected=True, differential=..., far_density=..., near_density=...)`.

#### Documented Optical & Physical Limitations
1. **Monocular 2D Projection (No Depth):** Monocular CCTV cameras lack true 3D spatial depth (no stereoscopic baseline, LiDAR, or radar). Distances are purely image-space pixel projections.
2. **Perspective Foreshortening:** Bounding boxes in the far field occupy exponentially fewer pixels per metric meter than in the near field. A 10m truck in the foreground covers 20,000 pixels, while three passenger cars 100m upstream may span fewer than 3,000 pixels combined.
3. **Line-of-Sight Occlusion:** Foreground high-profile vehicles (transit buses, commercial trucks) completely block camera line-of-sight to upstream traffic lanes.
4. **Resolution Attenuation:** Distant vehicles suffer optical blur, atmospheric haze, and low pixel contrast, producing higher detection noise in adverse weather or darkness.

---

## 14. Incident Foundations: Rule-Based CV Anomaly Heuristics

Foundational incident detection in `ai/cv/incidents.py` operates via deterministic computer vision heuristics.

> [!IMPORTANT]
> **CRITICAL HONESTY & ETHICAL AI NOTICE:**
> These components are **RULE-BASED COMPUTER VISION HEURISTICS, NEVER TRAINED MACHINE LEARNING ACCIDENT CLASSIFIERS**.
> 2D optical bounding boxes do not perceive driver intent, brake hydraulic failures, or micro-collisions. Every candidate emitted is explicitly labeled as a heuristic proposal for human officer verification.

```
Tracked Vehicles (MultiObjectTracker)
       │
       ├──► [StoppedVehicleHeuristic]
       │       ├── Check: Centroid inside Queue ROIs? ──► YES: Ignore (normal queue)
       │       └── NO: Speed <= 3.0 px/s for >= N frames?
       │              └── YES ──► Emit Candidate 'stopped_vehicle' (conf = 0.50..0.95)
       │
       └──► [WrongWayHeuristic]
               └── Check: Displacement vector vs LaneDirectionConfig heading?
                      └── Deviation > 90°?
                             └── YES ──► Emit Candidate 'wrong_way' (conf = 0.50..0.95)
```

### 1. Stopped-Vehicle Anomaly Heuristic (`StoppedVehicleHeuristic`)
- **Queue Suppression:** Vehicles stopped inside designated queue ROIs (such as red-light stop bars) are recognized as normal operational waiting queues and are strictly filtered out (`_stopped_counts[track_id] = 0`).
- **Anomaly Condition:** A vehicle whose centroid resides **outside** all queue ROIs maintaining speed $\le 3.0\text{ px/s}$ across $N \ge 10$ consecutive frames.
- **Empirical Confidence Semantics:**
  $$\text{Conf} = \min\left(0.95, \, 0.50 + 0.03 \times (\text{persistence\_frames} - 10)\right)$$
  Confidence starts at $0.50$ when the minimum duration threshold is reached, growing incrementally with confirmed persistence up to an empirical ceiling of $0.95$.
- **Motion Resumption:** If the vehicle resumes speed ($> 3.0\text{ px/s}$), the persistence counter immediately resets to zero.

### 2. Wrong-Way Heuristic (`WrongWayHeuristic`)
- **Per-Camera Configuration:** Requires `LaneDirectionConfig` specifying polygon ROI, expected heading $\theta_{\text{expected}} \in [0^\circ, 360^\circ)$, and tolerance angle ($90.0^\circ$).
- **Displacement Vector:** Computed across recent track history points:
  $$(\Delta x, \Delta y) = (x_{\text{latest}} - x_{\text{earliest}}, \, y_{\text{latest}} - y_{\text{earliest}}), \quad d = \sqrt{\Delta x^2 + \Delta y^2}$$
- **Jitter Filtering:** If total displacement $d < 15.0\text{ px}$, trajectory direction is considered unconfirmed (filtering out stationary tracking bounding-box jitter).
- **Angular Deviation:**
  $$\theta_{\text{actual}} = \text{atan2}(\Delta y, \Delta x) \pmod{360^\circ}$$
  $$\Delta \theta = \left|\left((\theta_{\text{actual}} - \theta_{\text{expected}} + 180^\circ) \pmod{360^\circ}\right) - 180^\circ\right|$$
  If $\Delta \theta > 90.0^\circ$, opposing motion is flagged.
- **Confidence Semantics:**
  $$\text{Conf} = \min\left(0.95, \, \max\left(0.50, \, 0.50 + 0.45 \times \frac{\Delta \theta - 90^\circ}{90^\circ}\right)\right)$$
  Head-on $180^\circ$ opposing trajectory yields maximum confidence ($0.95$).

---

## 15. Storage Architecture & Automated Perception Persistence Policy

The persistence pipeline in `backend/app/vision/storage.py` bridges perception dataclasses to async SQLAlchemy database models.

### 1. Data Contract Specifications

| Perception Output | Target Database Model | Field Mappings & Invariants |
| :--- | :--- | :--- |
| `CongestionResult` | `TrafficRecord` | • `congestion_level`: integer in $[0, 100]$<br>• `vehicle_count`: integer count<br>• `avg_speed_kmh`: populated **strictly** when `is_calibrated=True`, else `None`<br>• `source`: strictly `'camera'`<br>• `intersection_id`: foreign key |
| `IncidentCandidate` | `Incident` | • `severity`: deterministic mapping from confidence and event type<br>• `status`: strictly `'reported'`<br>• `description`: **MUST** contain `[Heuristic: <method>]` with diagnostic metrics<br>• `reported_by`: `None` (indicates automated camera perception) |

### 2. Deterministic Severity Mapping (`map_confidence_to_severity`)
- **`wrong_way`:**
  - $\text{conf} \ge 0.85 \implies$ `'critical'` (active lethal collision threat)
  - $0.65 \le \text{conf} < 0.85 \implies$ `'high'`
  - $\text{conf} < 0.65 \implies$ `'medium'`
- **`stopped_vehicle`:**
  - $\text{conf} \ge 0.85 \implies$ `'high'` (long-duration persistent stalled vehicle)
  - $0.60 \le \text{conf} < 0.85 \implies$ `'medium'`
  - $\text{conf} < 0.60 \implies$ `'low'` (early candidate)

### 3. Audit Trail Architectural Policy

> [!NOTE]
> **AUDIT TRAIL ARCHITECTURAL POLICY:**
> Automated computer vision writes (`record_congestion_observation`, `record_incident_candidate`) deliberately **bypass** the administrative `AuditLog` table (`log_audit()`).
> High-frequency video streams generate perception events every frame (10–30 FPS) or on minute-level rolling intervals across hundreds of edge cameras. Writing an immutable audit log record for every automated telemetry entry would induce catastrophic write amplification, database connection pool exhaustion, and storage ballooning.
> In accordance with Phase 2 specifications, `AuditLog` is strictly reserved for human user operations (incident acknowledgment, officer manual signal overrides, role permission changes, and plan modifications).

---

## 16. Downstream Consumption: Phase 5 & Phase 6 Integration

The perception artifacts generated in Phase 4 provide the core input data streams for downstream autonomous control and predictive pipelines:

```
┌────────────────────────────────────────────────────────┐
│               PHASE 4: COMPUTER VISION                │
│  • TrafficRecord (congestion_level, vehicle_count)     │
│  • Incident candidates (stopped_vehicle, wrong_way)    │
│  • Far-field traffic-ahead differentials               │
└───────────────────────────┬────────────────────────────┘
                            │
            ┌───────────────┴───────────────┐
            ▼                               ▼
┌──────────────────────────────┐ ┌──────────────────────────────┐
│  PHASE 5: FLOW FORECASTING   │ │  PHASE 6: SIGNAL CONTROL     │
│  • Spatio-temporal GNN/LSTM  │ │  • Dynamic Green Extensions  │
│  • Upstream Wave Predictor   │ │  • Wrong-Way Red-Hold Lock   │
│  • Network Bottleneck Alerts │ │  • Emergency Transit Routing │
└──────────────────────────────┘ └──────────────────────────────┘
```

1. **Phase 5 (Traffic Flow Forecasting & Analytics):**
   - **Continuous Flow Calibration:** Ingests rolling `TrafficRecord` time-series to train and update spatio-temporal Graph Neural Networks (GNNs) and LSTM corridor forecasters.
   - **Upstream Shockwave Anticipation:** The far-field traffic-ahead differential ($\Delta_{\text{ahead}}$) serves as a lead indicator for kinematic shockwaves, predicting intersection queue arrival 5 to 15 minutes before vehicles reach the physical stop bar.

2. **Phase 6 (Traffic Signal Control & Preemption):**
   - **Adaptive Green Split Optimization:** High congestion scores ($C > 70$) trigger dynamic green phase extensions on congested approaches while penalizing under-utilized conflicting phases.
   - **Critical Safety Interlocks:** A verified `'wrong_way'` candidate with `severity='critical'` triggers immediate controller interlocks: all-red holds on upstream conflicting phases and illuminated variable message warnings.
   - **Emergency Transit Preemption:** When combined with `EmergencyVehicleHeuristic` visual cues, active incidents reroute prioritized emergency apparatus onto uncongested bypass lanes.

---

## 17. REST API Endpoints & Backend Integration (`/api/v1/vision`)

The vision subsystem is fully exposed through the `/api/v1/vision` router (`backend/app/api/v1/vision.py`), mounted within the root v1 router.

### 1. Endpoint Catalog

| Method | Path | Auth / Roles | Request Format | Response Model | Description |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `POST` | `/api/v1/vision/analyze-image` | `admin`, `traffic_officer` | `multipart/form-data` | `ImageAnalysisResponse` | Analyzes a single uploaded image with YOLO detection, metrics, and traffic signal classification. |
| `POST` | `/api/v1/vision/analyze-video` | `admin`, `traffic_officer` | `multipart/form-data` | `VideoAnalysisResponse` | Processes recorded video with strided frame evaluation, tracking, and incident heuristics. |
| `GET` | `/api/v1/vision/signal-observations` | Authenticated (Any) | Query Parameters | `PaginatedSignalObservations` | Returns paginated physical signals possessing camera-observed optical states (`observed_state`). |

### 2. Single Image Analysis (`POST /vision/analyze-image`)

- **Payload Validation:**
  - Content-type validation: Supported image types are `image/jpeg`, `image/jpg`, `image/png`, `image/webp`. Unsupported types return an immediate `415 Unsupported Media Type` error.
  - Size validation: Maximum payload size is enforced at `10 MB` (`MAX_IMAGE_SIZE_BYTES`). Oversized uploads return a `413 Content Too Large` error.
  - Foreign key verification: Validates `intersection_id`, `lane_id`, and `signal_id` if supplied (returning `404 Not Found` if nonexistent).
- **Execution Lifecycle:**
  1. Writes uploaded buffer to a temporary file on disk.
  2. Decodes image with OpenCV.
  3. Executes `YoloVehicleDetector.detect()` and `compute_frame_metrics()`.
  4. Evaluates `compute_congestion_score()`.
  5. Executes `TrafficSignalDetector.detect()` to locate signal heads and classify lamp states (`red`, `yellow`, `green`, `unknown`).
  6. **Persistence:**
     - Creates a `TrafficRecord` row with `source='camera'`, `vehicle_count`, and `congestion_level` when `intersection_id` is provided.
     - Updates physical `Signal` record with `observed_state`, `observed_confidence`, and `observed_at`.
  7. **Guaranteed Cleanup:** Disk cleanup is performed within a `finally` block, ensuring no temporary files remain regardless of execution success or failure.

#### Architectural Justification: Opt-In Per-Vehicle Event Persistence (`persist_events`)
> [!IMPORTANT]
> **DATABASE WRITE AMPLIFICATION MITIGATION:**
> Persisting individual database records (`VehicleEvent`) for every single detected vehicle in every frame creates catastrophic table bloat and write amplification at scale (e.g. 10–30 FPS $\times$ dozens of intersection cameras generates millions of rows daily).
> In AI TrafficOS, macroscopic traffic control algorithms (Phase 3 routing, Phase 5 forecasting, Phase 6 signal timing) consume aggregated metrics captured in `TrafficRecord` (total count, lane occupancy, congestion index).
> Therefore, writing individual `VehicleEvent` rows defaults to **opt-in** (`persist_events=False`). When forensic tracking, audit logging, or targeted preemption is explicitly required, operators or services can enable `persist_events=True` to persist granular detection bounding boxes.

### 3. Video Stream & File Analysis (`POST /vision/analyze-video`)

- **Payload & Safety Limits:**
  - Supported containers: `video/mp4`, `video/avi`, `video/x-msvideo`, `video/quicktime`, `video/x-matroska`, `video/webm`.
  - Maximum upload size: `50 MB` (`MAX_VIDEO_SIZE_BYTES`).
  - Maximum duration: `60.0 seconds` (`MAX_VIDEO_DURATION_SECONDS`).
  - Frame Stride: Configurable stride (default: `5`, processing every 5th frame) balancing CPU/GPU utilization with tracking fidelity.
- **Honest Timeout Behavior:**
  - Video processing operates synchronously with strict wall-clock timeout monitoring (`timeout_seconds`, default 30.0s).
  - If frame evaluation exceeds the deadline, processing halts immediately and raises `HTTP 504 Gateway Timeout` rather than hanging worker threads.
- **Persistence:**
  - **Windowed Traffic Records:** Aggregates metrics over rolling 10-frame windows into `TrafficRecord` rows (`source='camera'`).
  - **Candidate Incidents:** Evaluates `IncidentDetector` across active tracks. Deduplicated candidate anomalies are persisted as `Incident` (`status='reported'`) with deterministic severity and heuristic diagnostic notes in `description`.

### 4. Optical Signal Observations (`GET /vision/signal-observations`)

- Accessible to all authenticated user roles (`admin`, `traffic_officer`, `analyst`).
- Queries all physical `Signal` controllers where `Signal.observed_state IS NOT NULL`.
- Joins the parent `Intersection` relation to present intersection names and municipal codes.
- Supports filtering by `observed_state` (`green`, `yellow`, `red`, `unknown`) and standard page/per_page pagination.

---

## 18. Phase 3 Road Graph Hydration Integration

Phase 3 implements an in-memory directed road network graph (`build_graph` in `backend/app/services/routing/builders.py`) used by Dijkstra and A* shortest path algorithms.

### Automatic Hydration Verification
Corridor impedance calculation in Phase 3 queries traffic sensor telemetry using a trailing 60-minute window across lane-level records:

```python
cutoff_time = datetime.now(timezone.utc) - timedelta(minutes=60)
congestion_stmt = (
    select(
        Lane.road_id,
        func.avg(TrafficRecord.congestion_level).label("avg_congestion"),
    )
    .join(TrafficRecord, TrafficRecord.lane_id == Lane.id)
    .where(
        Lane.road_id.in_(road_ids),
        TrafficRecord.recorded_at >= cutoff_time,
    )
    .group_by(Lane.road_id)
)
```

**Zero Coupling Architecture:**
- When Phase 4 Computer Vision endpoints persist `TrafficRecord` rows with `source='camera'`, `congestion_level`, and an associated `lane_id`, these records are automatically captured in the trailing-60-minute query.
- The hydrated road graph immediately incorporates camera-derived congestion into edge routing costs ($w_{\text{congestion}} \times c$).
- No new tables, foreign keys, or bespoke couplings were added, honoring the Phase 3 data contracts completely.

---

## 19. Live Stream Consumer Interface (`ai/cv/streaming.py`)

In accordance with architectural principles, AI TrafficOS does not expose a mock or synthetic "live-stream" HTTP endpoint. Instead, a production-grade abstract interface contract is established in `ai/cv/streaming.py`:

```
┌──────────────────────────────┐
│ Physical Camera / RTSP Feed  │
└──────────────┬───────────────┘
               │ H.264 / H.265 Stream
               ▼
┌──────────────────────────────┐
│     AbstractFrameSource      │  (Decodes to FramePacket)
└──────────────┬───────────────┘
               │ Bounded Queue (Buffer Size 5)
               ▼
┌──────────────────────────────┐
│    AbstractStreamConsumer    │  Backpressure Policy: DROP_OLDEST
│  • YoloVehicleDetector       │
│  • MultiObjectTracker        │
│  • FrameMetrics & Congestion │
│  • IncidentDetector          │
│  • TrafficSignalDetector     │
└──────────────┬───────────────┘
               │ Rolling Window (30s)
               ▼
┌──────────────────────────────┐
│  Database Persistence Layer  │
│  • TrafficRecord (source=cam)│
│  • Incident (status=reported)│
│  • Signal (observed_state)   │
└──────────────────────────────┘
```

### Core Interface Abstractions

1. **`StreamConfig`:**
   Declarative configuration defining camera identifier, stream URL (RTSP/RTMP/WebRTC), target FPS, frame stride, ring buffer capacity, and reconnect retry parameters.
2. **`FrameDropPolicy`:**
   Mitigates inference lag under variable load:
   - `DROP_OLDEST` (Default): Drops stale frames from the head of the buffer, guaranteeing the detector processes current real-time frames without drift.
   - `DROP_NEWEST`: Rejects incoming frames when the worker lags.
3. **`AbstractFrameSource`:**
   Asynchronous frame iterator yielding `FramePacket` instances containing normalized NumPy BGR arrays.
4. **`AbstractStreamConsumer`:**
   Autonomous stream worker lifecycle managing connection, pipeline processing, error recovery, and periodic window flushing (`flush_window_telemetry`).



