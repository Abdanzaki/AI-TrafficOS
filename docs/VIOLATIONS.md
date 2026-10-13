# Traffic Violation Detection Pipeline & Operational Specifications

This document outlines the architecture, heuristic algorithms, confidence semantics, model interfaces, and operational boundaries of the Traffic Violation Detection subsystem in **AI TrafficOS**.

---

## 1. Pipeline Overview

The Traffic Violation Detection subsystem automates the identification and review of high-risk roadway infractions through a deterministic computer vision and edge analytics pipeline:

```mermaid
flowchart LR
    A[Video Stream / Frames] --> B[YOLOv8 Detection]
    B --> C[Multi-Object Tracker]
    C --> D[CV Heuristic Engines]
    D --> E[ViolationCandidate Record]
    E --> F[Persistence & Evidence Store]
    F --> G[REST API /api/v1/violations]
    G --> H[Web Control Room UI]
```

### End-to-End Workflow

1. **Object Detection (`ai/cv/yolo_detector.py`):**
   Incoming video frames are processed by YOLOv8 (`yolov8n.pt`) to detect roadway entities including vehicles (`car`, `truck`, `bus`, `motorcycle`) and pedestrians (`person`).
2. **Trajectory & State Tracking (`ai/cv/tracking.py`):**
   The multi-object tracking engine assigns persistent track IDs (`TrackedVehicle`), recording temporal centroid trajectories, pixel displacements, and estimated velocities.
3. **Violation Heuristics (`ai/cv/violations.py`):**
   Active tracks, entity detections, and intersection signal states are fed into specialized deterministic heuristics:
   - `RedLightViolationHeuristic`
   - `WrongWayViolationHeuristic`
   - `NoHelmetViolationHeuristic`
4. **Structured Candidate Generation:**
   Detected violations are converted into immutable `ViolationCandidate` dataclasses containing UTC timestamps, camera IDs, track IDs, bounding boxes, confidence scores, and diagnostic metadata.
5. **Database Persistence & Evidence Snapshots (`backend/app/vision/violations.py`):**
   Violations are persisted to the PostgreSQL `violations` table via SQLAlchemy async sessions. Frame crops and evidence snapshots are written to `storage/evidence/violations/` and indexed in `evidence_ref`.
6. **Backend REST API (`backend/app/api/v1/violations.py`):**
   Protected API endpoints (`/api/v1/violations`) provide filtering by violation type, status, junction, camera, and date ranges, alongside status mutation endpoints (`recorded` -> `reviewed` / `escalated` / `dismissed`).
7. **Control Room Dashboard (`web/src/components/violations/ViolationsList.tsx`):**
   Operators review incidents, filter records, view associated evidence snapshots, inspect bounding box diagnostics, and execute workflow status transitions.

---

## 2. Detectors & Confidence Semantics

Every violation candidate emitted by the perception pipeline derives strictly from verifiable geometric and sensory measurements. The system does not emit random or unverified alerts.

### 2.1 Red Light Runner (`RedLightViolationHeuristic`)
- **Mechanism:** Evaluates 2D line segment intersection between a vehicle's centroid trajectory segment $(p_{t-1} \to p_t)$ and a configured stop-line segment $(p_1 \to p_2)$.
- **Signal Gating:** Intersections are only evaluated when the intersection lamp phase is strictly `'red'`. Trajectory crossing during `'green'`, `'yellow'`, or `'unknown'` phases produces zero violations.
- **Heading Alignment:** When `approach_heading_deg` is configured, vehicles moving away from the intersection or reversing are filtered out.
- **Debouncing:** Tracks are emitted at most once per vehicle track per red-phase cycle. Phase transitions automatically reset the emitted track registry.
- **Confidence Formula:**
  $$\text{conf} = \min\left(0.99, \max\left(0.50, 0.70 + 0.20 \cdot \text{track\_confidence} + (0.05 \text{ if displacement} \ge 10\text{px})\right)\right)$$
  Yields a deterministic score between $0.50$ and $0.99$ based on tracker stability and clear spatial crossing.

### 2.2 Wrong-Way Driving (`WrongWayViolationHeuristic`)
- **Mechanism:** Wraps `WrongWayHeuristic` from `ai.cv.incidents`. Compares vehicle trajectory velocity vectors against designated lane direction angles (`LaneDirectionConfig`) using angular difference and vector dot products.
- **Debouncing:** Emits a violation candidate once per offending vehicle trajectory to prevent duplicate database spam.
- **Confidence Semantics:** Directly reflects trajectory alignment divergence ($\ge 135^\circ$ opposing lane direction) combined with tracking duration stability.

### 2.3 Motorcycle Helmet Non-Compliance (`NoHelmetViolationHeuristic`)
- **Mechanism:**
  1. **Rider Association:** Identifies `person` detections overlapping `motorcycle` detections (horizontal overlap ratio $\ge 35\%$, vertical positioning verifying the rider is seated on the motorcycle).
  2. **Head Region Extraction:** Calculates the top vertical fraction (default $28\%$) of the rider's bounding box.
  3. **Classification:** Passes the head crop image to a `HelmetClassifier` protocol implementation.
- **Confidence Formula:**
  $$\text{conf} = \min\left(0.99, \max\left(0.50, 0.40 \cdot \text{assoc\_score} + 0.60 \cdot \text{classifier\_confidence}\right)\right)$$
  Blends the geometric rider-motorcycle spatial fit with the head classifier confidence.

---

## 3. Helmet Classifier: Real Implementation vs. Documented Interface

### Standard COCO Limitations
The standard Microsoft COCO dataset (used by off-the-shelf YOLO models) includes class 0 (`person`) and class 3 (`motorcycle`). **COCO does not label safety helmets or headgear.** Consequently, generic YOLO weights cannot verify helmet compliance.

### Architectural Separation
To handle this without hallucinating detections, the architecture defines a clean protocol interface:

```python
@runtime_checkable
class HelmetClassifier(Protocol):
    def is_available(self) -> bool: ...
    def classify_head(self, head_crop: np.ndarray) -> tuple[bool, float]: ...
```

The concrete implementation `PyTorchHelmetClassifier` expects trained weights:
- **Default Location:** `backend/app/ml/models/helmet_classifier.pt` or specified via `HELMET_MODEL_PATH`.
- **Target Model Architecture:** A fine-tuned classifier (e.g. YOLOv8-helmet crop model or ResNet-18) trained on the Safety Helmet Wearing Dataset (SHWD).

### Strict Anti-Hallucination Contract
When valid helmet weights are missing or unconfigured:
1. `classifier.is_available()` returns `False`.
2. `NoHelmetViolationHeuristic.evaluate()` returns an empty list `[]`.
3. If `classify_head()` is invoked without weights, it raises `HelmetModelMissingError`.
4. **Under no circumstances does the system fabricate violation records, simulate helmet presence, or output random guesses.**

---

## 4. Municipal Camera Authorization Limitations

AI TrafficOS is designed for integration into municipal Intelligent Transportation Systems (ITS). However, operational deployment is bounded by statutory and legal requirements:

1. **Passive Ingestion Architecture:**
   AI TrafficOS is a perception and decision-support engine. It processes frames and video feeds that are actively routed into its ingress endpoints (e.g., local video files, simulated feeds, or provisioned RTSP streams).
2. **Statutory Authority Requirement:**
   Accessing live municipal traffic cameras, Department of Transportation (DOT) CCTV feeds, or roadside sensor networks strictly requires formal statutory authorization, edge network access, and valid cryptographic credentials from the governing municipal or law-enforcement authority.
3. **Privacy & Evidentiary Compliance:**
   Production enforcement workflows require automated license plate recognition (ALPR) compliance, data privacy guardrails (GDPR/CCPA face and non-offending vehicle blurring), and an immutable cryptographic chain-of-custody for evidentiary submission.

---

## 5. Honest Limitations & Edge Cases

| Scenario | System Behavior / Impact | Mitigation / Handling |
| :--- | :--- | :--- |
| **Nighttime / Low Lux** | Trajectory centroids become noisy due to headlight glare and sensor blooming. | Bounded confidence thresholding; displacement requirements $\ge 10\text{px}$. |
| **Heavy Rain / Fog** | Occlusion reduces object detection recall; stop lines may be obscured. | Signal phase gating prevents false triggers; operator manual review in control room. |
| **Severe Camera Perspective Distortion** | 2D pixel displacement does not map linearly to metric speed or stop-line distance. | Extrinsics calibration and configurable stop-line coordinate mapping per camera view. |
| **Non-Standard Headgear** | Hoods, beanies, turbans, or hard hats may cause false classifications in head crops. | Blended confidence formula; human operator review before escalation. |
| **Rider Carrying Helmet on Elbow** | Head crop does not show helmet, but helmet is present on vehicle. | The system correctly flags non-wearing while seated; operator review verifies snapshot. |
| **Dense Traffic Tracker Occlusion** | Vehicle track IDs may swap if vehicles merge or cross during intersection transit. | Stop-line crossing debouncing per signal cycle avoids multi-firing on swapped IDs. |
