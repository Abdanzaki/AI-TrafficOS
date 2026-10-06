# AI TrafficOS - Production Database Architecture & Schema Reference

## 1. Architectural Overview & Design Principles

The AI TrafficOS database layer provides the relational, transactional, and temporal backbone for real-time intelligent traffic management, edge computer vision telemetry, autonomous signal optimization, emergency preemption, and regulatory audit compliance.

The database runs on **PostgreSQL 16**, accessed via **SQLAlchemy 2.0 (asynchronous core & ORM)** using the high-performance binary **asyncpg** driver. Migrations are managed deterministically via **Alembic**.

### Core Schema Principles

1. **Strict Relational Integrity & Explicit Cascade Rules**:
   - Every foreign key constraint explicitly declares `ondelete` semantics (`CASCADE`, `SET NULL`, or `RESTRICT`).
   - Parent physical assets cascade down to internal components (e.g., deleting an intersection cascades to signals, deleting a road cascades to lanes).
   - Historical records, telemetry, decisions, and audit events safeguard data provenance by using `SET NULL` when referenced actors, lanes, or predictions are modified or purged.
   - Security-critical entities employ `RESTRICT` (e.g., users bound to a role cannot have their role deleted while active accounts exist).

2. **Universal Temporal Tracking & Indexing**:
   - All tables implement `id` (integer auto-increment primary key), `created_at` (timestamptz with `server_default=now()`), and `updated_at` (timestamptz with `server_default=now()` and `onupdate=now()`).
   - Indexes are established on all foreign key columns, on all `created_at` columns, and on operational triage filters (`status`, `severity`).

3. **High-Performance JSONB for AI & Audit Payloads**:
   - Dynamic inference tensors, decision parameter overrides, and audit log change deltas use PostgreSQL native `JSONB` columns, enabling schema flexibility without sacrificing relational foreign keys for core assets.

4. **Future-Proof GIS Preparation**:
   - Geographic coordinates use floating-point latitude/longitude and geometry text fields (GeoJSON / WKT), preparing for zero-friction migration to PostGIS spatial types in subsequent phases.

5. **Cloud-Native Neon Compatibility**:
   - The schema adheres to standard PostgreSQL wire-protocol primitives supported natively by serverless PostgreSQL engines such as Neon. Hosted deployment requires only appending `?sslmode=require` to `DATABASE_URL` with zero application code modifications.

---

## 2. Entity-Relationship Topology

```
             +------------------+
             |      roles       |
             +--------+---------+
                      | 1:N (RESTRICT)
                      v
             +------------------+
             |      users       |<-----------------------------------+
             +--------+---------+                                    |
                      |                                              |
        +-------------+-----------------------+                      |
        | 1:N (SET NULL)                      | 1:N (CASCADE)        | 1:N (SET NULL)
        v                                     v                      v
+------------------+                  +------------------+   +------------------+
|    incidents     |                  |  notifications   |   |    audit_logs    |
+--------+---------+                  +------------------+   +------------------+
   ^     | 1:N (SET NULL)
   |     v
   |  +--------------------+
   |  |  emergency_events  |
   |  +--------------------+
   |
   | 1:N (CASCADE)
+--+---------------+          +------------------+
|  intersections   |          |      roads       |
+--+-----+-----+---+          +--------+---------+
   |     |     |                       | 1:N (CASCADE)
   |     |     | 1:N (SET NULL)        v
   |     |     +---------------->+------------------+
   |     |                       |      lanes       |
   |     | 1:N (CASCADE)         +--------+---------+
   |     +--------------------+           |
   |                          |           | 1:N (SET NULL)
   | 1:N (CASCADE)            v           v
   |                   +----------------------+
   |                   |    vehicle_events    |
   |                   +----------------------+
   |
   | 1:N (CASCADE)     +----------------------+
   +------------------>|   traffic_records    |<-- 1:N (SET NULL) [lanes]
   |                   +----------------------+
   |
   | 1:N (CASCADE)
   v
+------------------+   1:N (CASCADE)   +------------------+
|     signals      +------------------>|  signal_phases   |
+------------------+                   +------------------+
   ^
   | 1:N (SET NULL)
+--+---------------+   1:N (SET NULL)  +------------------+
|  ai_predictions  +------------------>|   ai_decisions   |
+------------------+                   +--------+---------+
                                                | 1:N (SET NULL)
                                                +---> [users (applied_by)]
```

---

## 3. Schema Catalog & Field Justifications

### 3.1 Authentication & Access Control

#### `roles`
Defines role-based access control (RBAC) tiers for operators and automated systems.
- **`id`** (`Integer`, PK): Primary key identifier.
- **`name`** (`String(50)`, Unique, Indexed): Functional role slug (`admin`, `traffic_officer`, `analyst`).
- **`description`** (`String(255)`, Nullable): Human-readable operational scope.
- **`created_at`**, **`updated_at`** (`DateTime(timezone=True)`): Audit timestamps.
- **Seeded Records**:
  - `admin`: Full platform control, credential administration, policy changes.
  - `traffic_officer`: Control room operations, signal overrides, incident verification.
  - `analyst`: Read-only access to metrics, forecasting data, model evaluation reports.

#### `users`
Authenticated human actors and service operators.
- **`id`** (`Integer`, PK): Primary key identifier.
- **`email`** (`String(255)`, Unique, Indexed): Canonical login credential and contact point.
- **`hashed_password`** (`String(255)`): Argon2 / bcrypt password digest. Plaintext credentials are never stored.
- **`full_name`** (`String(150)`): Operator display name.
- **`role_id`** (`Integer`, FK -> `roles.id`, `ondelete="RESTRICT"`, Indexed): Enforces active role assignment; role deletion is blocked while users exist.
- **`is_active`** (`Boolean`, Default `true`): Immediate revocation flag without breaking audit relations.
- **`last_login_at`** (`DateTime(timezone=True)`, Nullable): Session activity monitor for security compliance.
- **`created_at`**, **`updated_at`** (`DateTime(timezone=True)`): Record lifecycle timestamps.

---

### 3.2 Roadway Topology & Physical Network

#### `roads`
Physical street corridors categorized by functional transport hierarchy.
- **`id`** (`Integer`, PK): Primary key identifier.
- **`name`** (`String(150)`, Indexed): Public road name or corridor designation (e.g., "Grand Avenue"). Indexed for operator search.
- **`road_type`** (`String(50)`): Road classification (`arterial`, `collector`, `local`). Dictates speed expectations and signal prioritization.
- **`speed_limit_kmh`** (`Integer`, Nullable): Legal speed limit used in anomaly detection and velocity scoring.
- **`geometry`** (`Text`, Nullable): GeoJSON or WKT polyline representation of the road corridor. Stored as text prior to PostGIS extension integration.
- **`created_at`**, **`updated_at`** (`DateTime(timezone=True)`): Operational timestamps.

#### `intersections` *(Extended from Phase 1)*
Physical nodes where roadways meet and traffic flow is coordinated.
- **`id`** (`Integer`, PK): Primary key identifier (retained from Phase 1).
- **`name`** (`String(120)`, Indexed): Human-readable crossroads name (e.g., "5th Ave & Pine St").
- **`code`** (`String(50)`, Unique, Indexed): Unique municipal dispatch code (e.g., `INT-NW-042`).
- **`status`** (`String(30)`, Default `active`, Indexed): Operational state (`active`, `inactive`, `maintenance`). Indexed for bulk health queries.
- **`city`** (`String(100)`, Nullable): Municipal administrative jurisdiction.
- **`zone`** (`String(100)`, Nullable): Traffic control sector or urban zoning tag (e.g., "Downtown Core").
- **`lat`**, **`lon`** (`Float`, Nullable): Decimal coordinates for map projection.
- **`created_at`**, **`updated_at`** (`DateTime(timezone=True)`): Record lifecycle timestamps.

#### `lanes`
Granular approach and departure lanes linked to roads and intersections.
- **`id`** (`Integer`, PK): Primary key identifier.
- **`road_id`** (`Integer`, FK -> `roads.id`, `ondelete="CASCADE"`, Indexed): Road corridor parent. Cascaded upon road deletion.
- **`intersection_id`** (`Integer`, FK -> `intersections.id`, `ondelete="SET NULL"`, Nullable, Indexed): Approaching or intersecting junction. Preserved if intersection is reconfigured.
- **`lane_number`** (`Integer`): Left-to-right approach index (e.g., 1 = innermost / left-turn lane).
- **`direction`** (`String(50)`): Directional orientation (`northbound`, `southbound`, `eastbound`, `westbound`).
- **`lane_type`** (`String(50)`): Channelization usage (`through`, `left_turn`, `right_turn`, `bus`, `bike`).
- **`created_at`**, **`updated_at`** (`DateTime(timezone=True)`): Lifecycle timestamps.

---

### 3.3 Traffic Signal Automation & Timing

#### `signals`
Physical traffic signal cabinet hardware controllers deployed at an intersection.
- **`id`** (`Integer`, PK): Primary key identifier.
- **`intersection_id`** (`Integer`, FK -> `intersections.id`, `ondelete="CASCADE"`, Indexed): Bound junction. Cascaded when junction asset is decommissioned.
- **`code`** (`String(50)`, Unique, Indexed): Hardware controller identifier (e.g., `SIG-INT-042-A`).
- **`status`** (`String(30)`, Default `active`, Indexed): Controller health (`active`, `inactive`, `maintenance`, `fault`).
- **`created_at`**, **`updated_at`** (`DateTime(timezone=True)`): Operational timestamps.

#### `signal_phases` *(Extended from Phase 1)*
Discrete signal timing intervals defining light states and durations within a cycle.
- **`id`** (`Integer`, PK): Primary key identifier (retained from Phase 1).
- **`signal_id`** (`Integer`, FK -> `signals.id`, `ondelete="CASCADE"`, Indexed): Parent signal controller.
- **`intersection_id`** (`Integer`, FK -> `intersections.id`, `ondelete="CASCADE"`, Nullable, Indexed): Retained for Phase 1 backwards compatibility and direct intersection lookups.
- **`name`** (`String(80)`): Phase movement label (e.g., "Phase 2 - Northbound Through").
- **`phase_order`** (`Integer`, Default `1`): Execution sequence position inside the signal cycle program.
- **`duration_seconds`** (`Integer`, Default `30`): Allocated green/clearance duration interval in seconds.
- **`state`** (`String(20)`, Default `red`): Current signal display state (`red`, `yellow`, `green`).
- **`is_active`** (`Boolean`, Default `true`): Dynamic toggle for skipping actuated phases during low-demand cycles.
- **`created_at`**, **`updated_at`** (`DateTime(timezone=True)`): Timestamps.

---

### 3.4 Perception Telemetry, Incidents & Emergency Preemption

#### `vehicle_events` *(Extended from Phase 1)*
High-frequency vehicle detections emitted by edge computer vision (YOLO) sidecars.
- **`id`** (`Integer`, PK): Primary key identifier.
- **`intersection_id`** (`Integer`, FK -> `intersections.id`, `ondelete="CASCADE"`, Nullable, Indexed): Observation intersection.
- **`lane_id`** (`Integer`, FK -> `lanes.id`, `ondelete="SET NULL"`, Nullable, Indexed): Specific lane association if spatial bounding boxes resolve to a calibrated lane geometry.
- **`event_type`** (`String(60)`): Detection classification (e.g., `vehicle_entry`, `vehicle_exit`, `stationary`).
- **`vehicle_type`** (`String(50)`, Default `car`): Classified class (`car`, `truck`, `bus`, `motorcycle`, `bicycle`).
- **`speed_kmh`** (`Float`, Nullable): Estimated instantaneous velocity from optical tracking.
- **`direction`** (`String(50)`, Nullable): Track vector compass bearing or approach label.
- **`confidence`** (`Float`, Nullable): Edge model detection confidence (0.0 to 1.0).
- **`detected_at`** (`DateTime(timezone=True)`, Indexed): Precise edge detection timestamp. Indexed for high-throughput temporal aggregations.
- **`created_at`**, **`updated_at`** (`DateTime(timezone=True)`): Ingestion record timestamps.

#### `incidents` *(Extended from Phase 1)*
Roadway events impacting capacity, safety, or requiring emergency/operator intervention.
- **`id`** (`Integer`, PK): Primary key identifier.
- **`intersection_id`** (`Integer`, FK -> `intersections.id`, `ondelete="CASCADE"`, Nullable, Indexed): Associated intersection.
- **`severity`** (`String(20)`, Default `unknown`, Indexed): Incident severity (`low`, `medium`, `high`, `critical`, `unknown`). Indexed for emergency filtering.
- **`status`** (`String(30)`, Default `reported`, Indexed): Lifecycle state (`reported`, `acknowledged`, `resolved`).
- **`description`** (`String(500)`, Nullable): Narrative details or edge detector event summary.
- **`reported_by`** (`Integer`, FK -> `users.id`, `ondelete="SET NULL"`, Nullable, Indexed): Operator who verified/logged the incident. `NULL` if reported by automated AI pipeline.
- **`resolved_at`** (`DateTime(timezone=True)`, Nullable): Timestamp when normal roadway flow was restored.
- **`lat`**, **`lon`** (`Float`, Nullable): Precise coordinates if the incident occurred between intersections.
- **`created_at`**, **`updated_at`** (`DateTime(timezone=True)`): Record lifecycle timestamps.

#### `emergency_events`
Active emergency vehicle transit requiring preemption routing and green wave signal clearing.
- **`id`** (`Integer`, PK): Primary key identifier.
- **`incident_id`** (`Integer`, FK -> `incidents.id`, `ondelete="SET NULL"`, Nullable, Indexed): Correlated incident prompting emergency response, if known.
- **`vehicle_type`** (`String(50)`): Vehicle classification (`ambulance`, `fire`, `police`).
- **`priority`** (`Integer`, Default `1`): Preemption hierarchy level (1 = standard, 5 = highest emergency override).
- **`status`** (`String(30)`, Default `active`, Indexed): Preemption status (`active`, `dispatched`, `on_scene`, `resolved`).
- **`detected_at`** (`DateTime(timezone=True)`, Indexed): Time when the emergency vehicle approach was registered.
- **`cleared_at`** (`DateTime(timezone=True)`, Nullable): Time when intersection preemption was relinquished.
- **`created_at`**, **`updated_at`** (`DateTime(timezone=True)`): Record timestamps.

#### `traffic_records`
Aggregated macroscopic traffic telemetry summarized over rolling time windows.
- **`id`** (`Integer`, PK): Primary key identifier.
- **`intersection_id`** (`Integer`, FK -> `intersections.id`, `ondelete="CASCADE"`, Indexed): Monitored intersection.
- **`lane_id`** (`Integer`, FK -> `lanes.id`, `ondelete="SET NULL"`, Nullable, Indexed): Lane breakdown, or `NULL` for intersection-wide aggregate.
- **`recorded_at`** (`DateTime(timezone=True)`, Indexed): Measurement epoch timestamp.
- **`vehicle_count`** (`Integer`, Default `0`): Total vehicle volume observed in the measurement window.
- **`avg_speed_kmh`** (`Float`, Nullable): Mean vehicle speed.
- **`congestion_level`** (`Integer`, Default `0`): Normalized congestion metric from 0 (free flow) to 100 (complete gridlock).
- **`source`** (`String(50)`, Default `sensor`): Data ingestion source (`sensor`, `camera`, `manual`, `ai`).
- **`created_at`**, **`updated_at`** (`DateTime(timezone=True)`): Ingestion timestamps.

---

### 3.5 Operational Notifications

#### `notifications`
Targeted alerts dispatched to operators or broadcast system-wide.
- **`id`** (`Integer`, PK): Primary key identifier.
- **`user_id`** (`Integer`, FK -> `users.id`, `ondelete="CASCADE"`, Nullable, Indexed): Targeted recipient. `NULL` denotes a broadcast alert to all active operators.
- **`title`** (`String(200)`): Alert headline.
- **`message`** (`Text`): Detailed explanation, instructions, or error stack summary.
- **`severity`** (`String(30)`, Default `info`, Indexed): Notification priority level (`info`, `warning`, `error`, `critical`).
- **`is_read`** (`Boolean`, Default `false`): Read receipt status.
- **`entity_type`** (`String(50)`, Nullable): Correlated entity model name (`incident`, `signal`, `emergency_event`).
- **`entity_id`** (`Integer`, Nullable): Primary key of the correlated entity for deep linking in UI dashboards.
- **`created_at`**, **`updated_at`** (`DateTime(timezone=True)`): Dispatch timestamps.

---

### 3.6 Predictive Forecasting & Autonomous Decisions

#### `ai_predictions`
Spatial-temporal model inference output forecasting congestion and traffic volume horizons.
- **`id`** (`Integer`, PK): Primary key identifier.
- **`intersection_id`** (`Integer`, FK -> `intersections.id`, `ondelete="SET NULL"`, Nullable, Indexed): Forecasted intersection node.
- **`prediction_type`** (`String(50)`): Forecasting category (`congestion`, `flow`, `incident_risk`).
- **`predicted_for`** (`DateTime(timezone=True)`, Indexed): The future timestamp horizon for which the prediction applies (e.g., T + 15 minutes).
- **`payload`** (`JSONB`): Structured tensor output, feature maps, flow matrices, or confidence intervals.
- **`confidence`** (`Float`, Nullable): Statistical confidence score (0.0 to 1.0).
- **`model_version`** (`String(50)`): Active model architecture slug and checkpoint identifier (e.g., `st-gnn-v2.1.0`).
- **`created_at`**, **`updated_at`** (`DateTime(timezone=True)`): Inference generation timestamps.

#### `ai_decisions`
Autonomous or supervisory control recommendations synthesized from predictive forecasts.
- **`id`** (`Integer`, PK): Primary key identifier.
- **`prediction_id`** (`Integer`, FK -> `ai_predictions.id`, `ondelete="SET NULL"`, Nullable, Indexed): Originating inference record.
- **`intersection_id`** (`Integer`, FK -> `intersections.id`, `ondelete="SET NULL"`, Nullable, Indexed): Target intersection where the control action takes effect.
- **`decision_type`** (`String(50)`): Action classification (`signal_timing`, `route_advisory`, `alert`).
- **`payload`** (`JSONB`): Precise execution configuration (e.g., `{"phase_id": 3, "added_seconds": 12}`).
- **`status`** (`String(30)`, Default `proposed`, Indexed): Lifecycle state (`proposed`, `applied`, `reverted`).
- **`applied_by`** (`Integer`, FK -> `users.id`, `ondelete="SET NULL"`, Nullable, Indexed): Operator user who approved or executed the action (`NULL` if executed autonomously by reinforcement learning policy).
- **`rationale`** (`Text`, Nullable): Human-readable or automated explanation justifying the action.
- **`created_at`**, **`updated_at`** (`DateTime(timezone=True)`): Decision lifecycle timestamps.

---

### 3.7 Governance & Audit Logging

#### `audit_logs`
Immutable compliance and forensic log recording operator actions and critical system events.
- **`id`** (`Integer`, PK): Primary key identifier.
- **`actor_user_id`** (`Integer`, FK -> `users.id`, `ondelete="SET NULL"`, Nullable, Indexed): User who initiated the action (`NULL` for automated background jobs).
- **`action`** (`String(100)`, Indexed): Hierarchical dot-separated action identifier (e.g., `auth.login`, `user.created`, `incident.updated`, `signal.timing_override`).
- **`entity_type`** (`String(50)`, Nullable): Affected model table name.
- **`entity_id`** (`Integer`, Nullable): Primary key of the affected record.
- **`details`** (`JSONB`, Nullable): Before/after state snapshot diff or query parameters.
- **`ip_address`** (`String(45)`, Nullable): Client network address (IPv4 or IPv6 format).
- **`created_at`** (`DateTime(timezone=True)`, Indexed): Immutable timestamp of the audited event.
- **`updated_at`** (`DateTime(timezone=True)`): Uniform timestamp column maintained across all schema entities.

---

## 4. Indexing & Query Optimization Matrix

| Table | Index Name | Indexed Columns | Justification / Query Pattern |
| :--- | :--- | :--- | :--- |
| `roles` | `ix_roles_name` | `name` (Unique) | O(1) lookup during role verification and JWT authorization. |
| `roles` | `ix_roles_created_at` | `created_at` | Ordered pagination in admin consoles. |
| `users` | `ix_users_email` | `email` (Unique) | Authentication credential verification on every login attempt. |
| `users` | `ix_users_role_id` | `role_id` | FK indexing; joins on user authorization and role checks. |
| `users` | `ix_users_created_at` | `created_at` | Operator account registration auditing. |
| `roads` | `ix_roads_name` | `name` | Autocomplete and geographic search by street name. |
| `roads` | `ix_roads_created_at` | `created_at` | Network topology change ordering. |
| `intersections` | `ix_intersections_code` | `code` (Unique) | Direct lookup by municipal dispatch identifier. |
| `intersections` | `ix_intersections_name` | `name` | Human operator crossroad search. |
| `intersections` | `ix_intersections_status` | `status` | Filter operational vs maintenance nodes across city maps. |
| `intersections` | `ix_intersections_created_at` | `created_at` | Node creation chronology. |
| `lanes` | `ix_lanes_road_id` | `road_id` | Fetch all lanes belonging to a roadway corridor. |
| `lanes` | `ix_lanes_intersection_id` | `intersection_id` | Fetch approaching lanes for junction signal mapping. |
| `lanes` | `ix_lanes_created_at` | `created_at` | Lane geometry revision tracking. |
| `signals` | `ix_signals_intersection_id` | `intersection_id` | Resolve hardware controller deployed at a target junction. |
| `signals` | `ix_signals_code` | `code` (Unique) | Direct hardware telemetry stream mapping. |
| `signals` | `ix_signals_status` | `status` | Monitoring controllers with hardware faults or offline state. |
| `signals` | `ix_signals_created_at` | `created_at` | Controller installation timeline. |
| `signal_phases` | `ix_signal_phases_signal_id` | `signal_id` | Fetch all sequential timing phases for a controller. |
| `signal_phases` | `ix_signal_phases_intersection_id` | `intersection_id` | Direct junction-to-phase queries (Phase 1 compatibility). |
| `signal_phases` | `ix_signal_phases_created_at` | `created_at` | Timing revision history. |
| `vehicle_events` | `ix_vehicle_events_intersection_id` | `intersection_id` | High-frequency telemetry stream filtering by junction. |
| `vehicle_events` | `ix_vehicle_events_lane_id` | `lane_id` | Lane-level vehicle occupancy rate calculations. |
| `vehicle_events` | `ix_vehicle_events_detected_at` | `detected_at` | Time-series sliding window telemetry queries. |
| `vehicle_events` | `ix_vehicle_events_created_at` | `created_at` | DB ingestion latency analysis. |
| `incidents` | `ix_incidents_intersection_id` | `intersection_id` | Retrieve active incidents for a specific junction. |
| `incidents` | `ix_incidents_reported_by` | `reported_by` | Filter incidents reported by specific operators. |
| `incidents` | `ix_incidents_status` | `status` | Control room queue filtering (`reported`, `acknowledged`). |
| `incidents` | `ix_incidents_severity` | `severity` | Prioritize critical collisions and road hazards. |
| `incidents` | `ix_incidents_created_at` | `created_at` | Incident timeline and response duration reporting. |
| `emergency_events` | `ix_emergency_events_incident_id` | `incident_id` | Link emergency transit to reported accidents. |
| `emergency_events` | `ix_emergency_events_status` | `status` | Active preemption event polling for green-wave triggers. |
| `emergency_events` | `ix_emergency_events_detected_at` | `detected_at` | Preemption arrival estimation and velocity scoring. |
| `emergency_events` | `ix_emergency_events_created_at` | `created_at` | Emergency response dispatch auditing. |
| `traffic_records` | `ix_traffic_records_intersection_id` | `intersection_id` | Macroscopic trend analysis per intersection. |
| `traffic_records` | `ix_traffic_records_lane_id` | `lane_id` | Granular throughput metrics per approach. |
| `traffic_records` | `ix_traffic_records_recorded_at` | `recorded_at` | Time-series aggregation (hourly/daily peak trends). |
| `traffic_records` | `ix_traffic_records_created_at` | `created_at` | Ingestion pipeline audit. |
| `notifications` | `ix_notifications_user_id` | `user_id` | Fetch operator inbox and unread alerts. |
| `notifications` | `ix_notifications_severity` | `severity` | Urgent broadcast alert popups. |
| `notifications` | `ix_notifications_created_at` | `created_at` | Chronological alert feed. |
| `ai_predictions` | `ix_ai_predictions_intersection_id` | `intersection_id` | Fetch active forecasts for a specific crossroads. |
| `ai_predictions` | `ix_ai_predictions_predicted_for` | `predicted_for` | Query predictions matching upcoming time windows. |
| `ai_predictions` | `ix_ai_predictions_created_at` | `created_at` | Model inference generation chronology. |
| `ai_decisions` | `ix_ai_decisions_prediction_id` | `prediction_id` | Link executed action back to originating ML forecast. |
| `ai_decisions` | `ix_ai_decisions_intersection_id` | `intersection_id` | Fetch timing adjustments proposed for an intersection. |
| `ai_decisions` | `ix_ai_decisions_applied_by` | `applied_by` | Audit operator overrides versus automated decisions. |
| `ai_decisions` | `ix_ai_decisions_status` | `status` | Filter pending decisions awaiting operator approval. |
| `ai_decisions` | `ix_ai_decisions_created_at` | `created_at` | Decision pipeline latency tracking. |
| `audit_logs` | `ix_audit_logs_actor_user_id` | `actor_user_id` | Filter forensic activities by specific user account. |
| `audit_logs` | `ix_audit_logs_action` | `action` | Filter specific security actions (e.g., `auth.login_failed`). |
| `audit_logs` | `ix_audit_logs_created_at` | `created_at` | Immutable temporal event sequence analysis. |

---

## 5. Migration Execution & Verification

### Executing Migrations
From the repository root:
```bash
cd database
../backend/.venv/bin/alembic upgrade head
```

### Rollback / Downgrade Verification
To revert Phase 2 migrations and restore Phase 1 baseline:
```bash
cd database
../backend/.venv/bin/alembic downgrade 0001
```

All 15 tables are verified with downgrade tests, ensuring reversible schema evolution throughout all engineering cycles.
