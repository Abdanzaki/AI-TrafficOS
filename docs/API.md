# AI-TrafficOS API Reference Manual (v1)

This catalog details all active `/api/v1` endpoints across the AI-TrafficOS platform. It acts as the definitive contract for web frontend (Phase 7), mobile Flutter applications (Phase 8), and autonomous AI agent subsystems.

## Authentication & Authorization Architecture

- **Token Scheme**: HTTP Bearer (`Authorization: Bearer <jwt_access_token>`).
- **Roles**:
  - `admin`: Full unrestricted control across all endpoints, configuration, and audit trails.
  - `traffic_officer`: Operational control: signal timing overrides, incident management, emergency preemption, and AI decision application.
  - `analyst`: Read-only access to perception telemetry, traffic statistics, analytics, and AI recommendations.
- **Audit Trail**: State mutations (create, update, delete, override, status transitions) automatically generate immutable audit entries in `audit_logs`.

---

## 1. System & Diagnostics

| Method | Path | Auth / Roles | Description |
|---|---|---|---|
| `GET` | `/api/v1/health` | Public | Returns service health status and current API version. |
| `GET` | `/api/v1/version` | Public | Returns application service name and semantic version. |
| `WS` | `/api/v1/ws` | Public | WebSocket handshake endpoint for real-time telemetry streaming (Phase 1 verified). |

---

## 2. Authentication & Identity (`/auth`)

| Method | Path | Auth / Roles | Description |
|---|---|---|---|
| `POST` | `/api/v1/auth/register` | Public | Registers a new user account (defaults to `analyst` role). |
| `POST` | `/api/v1/auth/login` | Public | Authenticates via credentials; returns access & refresh tokens. |
| `POST` | `/api/v1/auth/refresh` | Public | Issues a new access token using a valid refresh token. |
| `GET` | `/api/v1/auth/me` | Authenticated (Any) | Returns current authenticated user's profile and active role. |

---

## 3. User Administration (`/users`)

| Method | Path | Auth / Roles | Description |
|---|---|---|---|
| `GET` | `/api/v1/users` | `admin` | Paginated listing of system users with role and status filtering. |
| `POST` | `/api/v1/users` | `admin` | Creates a new user with an explicitly assigned role. |
| `GET` | `/api/v1/users/{id}` | `admin` or Self | Retrieves user details by ID. |
| `PATCH` | `/api/v1/users/{id}` | `admin` or Self | Updates user details, email, password, or active status. |
| `DELETE` | `/api/v1/users/{id}` | `admin` | Permanently deletes a user account. |

---

## 4. Physical Network Infrastructure (`/junctions`, `/roads`, `/lanes`)

| Method | Path | Auth / Roles | Description |
|---|---|---|---|
| `GET` | `/api/v1/junctions` | Authenticated (Any) | Paginated list of intersections with status, city, and zone filters. |
| `POST` | `/api/v1/junctions` | `admin`, `traffic_officer` | Creates a new intersection entity. |
| `GET` | `/api/v1/junctions/{id}` | Authenticated (Any) | Retrieves detailed intersection record with relations. |
| `PATCH` | `/api/v1/junctions/{id}` | `admin`, `traffic_officer` | Updates intersection configuration, status, or coordinates. |
| `DELETE` | `/api/v1/junctions/{id}` | `admin` | Deletes an intersection. |
| `GET` | `/api/v1/roads` | Authenticated (Any) | Paginated list of road segments. |
| `POST` | `/api/v1/roads` | `admin`, `traffic_officer` | Creates a new road segment with geometry and speed limits. |
| `GET` | `/api/v1/roads/{id}` | Authenticated (Any) | Retrieves road details. |
| `PATCH` | `/api/v1/roads/{id}` | `admin`, `traffic_officer` | Updates road attributes and speed limits. |
| `DELETE` | `/api/v1/roads/{id}` | `admin` | Deletes a road segment. |
| `GET` | `/api/v1/lanes` | Authenticated (Any) | Paginated listing of physical lanes with directional filtering. |
| `POST` | `/api/v1/lanes` | `admin`, `traffic_officer` | Registers a lane belonging to a road and intersection. |
| `GET` | `/api/v1/lanes/{id}` | Authenticated (Any) | Retrieves single lane details. |
| `PATCH` | `/api/v1/lanes/{id}` | `admin`, `traffic_officer` | Updates lane configuration or type. |
| `DELETE` | `/api/v1/lanes/{id}` | `admin` | Deletes a lane. |

---

## 5. Traffic Signals & Phasing (`/signals`, `/phases`)

| Method | Path | Auth / Roles | Description |
|---|---|---|---|
| `GET` | `/api/v1/signals` | Authenticated (Any) | Paginated list of traffic signals. |
| `POST` | `/api/v1/signals` | `admin`, `traffic_officer` | Registers a traffic signal controller at an intersection. |
| `GET` | `/api/v1/signals/{id}` | Authenticated (Any) | Retrieves signal controller details and its configured phases. |
| `PATCH` | `/api/v1/signals/{id}` | `admin`, `traffic_officer` | Updates signal controller status or metadata. |
| `DELETE` | `/api/v1/signals/{id}` | `admin` | Deletes a traffic signal controller. |
| `POST` | `/api/v1/signals/{id}/override` | `admin`, `traffic_officer` | Overrides signal timing or forces a specific active phase. |
| `GET` | `/api/v1/signals/{id}/phases` | Authenticated (Any) | Lists signal phases configured for a specific controller. |
| `POST` | `/api/v1/signals/{id}/phases` | `admin`, `traffic_officer` | Adds a timing phase (green/yellow/red) to a signal controller. |
| `GET` | `/api/v1/phases/{id}` | Authenticated (Any) | Retrieves detailed signal phase timing record. |
| `PATCH` | `/api/v1/phases/{id}` | `admin`, `traffic_officer` | Modifies phase duration, state, or order. |
| `DELETE` | `/api/v1/phases/{id}` | `admin` | Removes a signal phase. |

---

## 6. Events, Perception & Telemetry (`/vehicle-events`, `/incidents`, `/emergency-events`, `/traffic-records`)

| Method | Path | Auth / Roles | Description |
|---|---|---|---|
| `GET` | `/api/v1/vehicle-events` | Authenticated (Any) | Paginated listing of CV vehicle detections (types, speeds). |
| `POST` | `/api/v1/vehicle-events` | `admin`, `traffic_officer` | Ingests a single computer vision vehicle detection. |
| `POST` | `/api/v1/vehicle-events/batch` | `admin`, `traffic_officer` | Batch ingests up to 1,000 detection events in a single transaction. |
| `GET` | `/api/v1/vehicle-events/{id}` | Authenticated (Any) | Retrieves a vehicle detection event. |
| `GET` | `/api/v1/incidents` | Authenticated (Any) | Paginated listing of incidents filtered by severity, status, or date. |
| `POST` | `/api/v1/incidents` | `admin`, `traffic_officer` | Reports a traffic incident or road hazard. |
| `GET` | `/api/v1/incidents/{id}` | Authenticated (Any) | Retrieves detailed incident status and history. |
| `PATCH` | `/api/v1/incidents/{id}` | `admin`, `traffic_officer` | Updates incident status (`reported` -> `acknowledged` -> `resolved`). |
| `DELETE` | `/api/v1/incidents/{id}` | `admin` | Deletes an incident record. |
| `GET` | `/api/v1/emergency-events` | Authenticated (Any) | Paginated list of priority emergency vehicle routing events. |
| `POST` | `/api/v1/emergency-events` | `admin`, `traffic_officer` | Dispatches an emergency corridor preemption event. |
| `GET` | `/api/v1/emergency-events/{id}` | Authenticated (Any) | Retrieves emergency event details. |
| `PATCH` | `/api/v1/emergency-events/{id}` | `admin`, `traffic_officer` | Updates emergency vehicle route or clears preemption. |
| `GET` | `/api/v1/traffic-records` | Authenticated (Any) | Paginated telemetry observations (counts, average speeds, congestion). |
| `POST` | `/api/v1/traffic-records` | `admin`, `traffic_officer` | Ingests aggregated traffic observation record. |
| `POST` | `/api/v1/traffic-records/batch` | `admin`, `traffic_officer` | Batch ingests up to 500 aggregated traffic sensor records. |
| `GET` | `/api/v1/traffic-records/{id}` | Authenticated (Any) | Retrieves single traffic record observation. |

---

## 7. Notifications (`/notifications`)

| Method | Path | Auth / Roles | Description |
|---|---|---|---|
| `GET` | `/api/v1/notifications` | Authenticated (Any) | Lists user-specific notifications (or all if admin). |
| `POST` | `/api/v1/notifications` | `admin`, `traffic_officer` | Sends a notification targeted to a specific user. |
| `POST` | `/api/v1/notifications/broadcast` | `admin` | Broadcasts an alert notification to all active system users. |
| `PATCH` | `/api/v1/notifications/{id}/read` | Authenticated (Any) | Marks a notification as read. |

---

## 8. AI Predictions & Decisions (`/ai-predictions`, `/ai-decisions`)

| Method | Path | Auth / Roles | Description |
|---|---|---|---|
| `POST` | `/api/v1/ai-predictions` | `admin`, `traffic_officer` | Records inference outputs from predictive models (ST-GNN). |
| `GET` | `/api/v1/ai-predictions` | Authenticated (Any) | Paginated predictions filtered by type, intersection, and target time. |
| `GET` | `/api/v1/ai-predictions/{id}` | Authenticated (Any) | Retrieves prediction details including input payload and confidence. |
| `POST` | `/api/v1/ai-decisions` | `admin`, `traffic_officer` | Generates autonomous or supervisory control decisions (`status='proposed'`). |
| `GET` | `/api/v1/ai-decisions` | Authenticated (Any) | Paginated decisions filtered by decision type, status, and intersection. |
| `GET` | `/api/v1/ai-decisions/{id}` | Authenticated (Any) | Retrieves decision details, applier info, and rationale. |
| `PATCH` | `/api/v1/ai-decisions/{id}` | `admin`, `traffic_officer` | Transitions decision state (`proposed->applied`, `proposed->reverted`, `applied->reverted`). Records `applied_by` & `applied_at`. |

---

## 9. Analytics & Aggregations (`/analytics`)

| Method | Path | Auth / Roles | Description |
|---|---|---|---|
| `GET` | `/api/v1/analytics/traffic-summary` | Authenticated (Any) | SQL `date_trunc` aggregations: bucketed (`hour` or `day`) average vehicle count, speed, congestion, and record count. |
| `GET` | `/api/v1/analytics/incidents-summary` | Authenticated (Any) | Aggregated incident totals grouped by severity level and status lifecycle. |
| `GET` | `/api/v1/analytics/congestion-hotspots` | Authenticated (Any) | Top congested intersections ranked by average congestion level descending with name and code. |

---

## 10. System Audit Logs (`/audit-logs`)

| Method | Path | Auth / Roles | Description |
|---|---|---|---|
| `GET` | `/api/v1/audit-logs` | `admin` Only | Paginated query of immutable audit log trail filtered by action, entity type, actor ID, and timestamps. |

---

## 11. Computer Vision & Optical Perception (`/vision`)

| Method | Path | Auth / Roles | Description |
|---|---|---|---|
| `POST` | `/api/v1/vision/analyze-image` | `admin`, `traffic_officer` | Multipart image upload; runs YOLO vehicle detection, frame metrics, congestion scoring, and optical signal detection. Persists aggregate `TrafficRecord` (source=`camera`) and optional `VehicleEvent` records. Guaranteed temp file cleanup. |
| `POST` | `/api/v1/vision/analyze-video` | `admin`, `traffic_officer` | Multipart video upload; performs strided frame sampling, multi-object tracking, and incident heuristics. Persists windowed `TrafficRecord` rows and candidate `Incident` records (status=`reported`). Enforces max duration (60s) and timeout limits. |
| `GET` | `/api/v1/vision/signal-observations` | Authenticated (Any) | Paginated list of physical traffic signals possessing camera-observed optical states (`observed_state`), joining intersection records. Supports filtering by observed lamp state. |

