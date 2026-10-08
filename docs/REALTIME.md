# AI TrafficOS — Phase 9 Backend: Real-Time & AI Assistant

This document describes the Phase 9 backend track: the Redis-backed real-time
event bus, the WebSocket streaming API, publish hooks, the AI assistant backend,
and the notification wiring. All code lives under `backend/app/realtime/`,
`backend/app/assistant/`, plus hook call-sites in the domain routers.

> Status note (2026-10-08): Stages 1–6 are complete and verified (270 pytest
> tests passing). Stage 5 notification policy evaluation is integrated into the
> stream fan-out listener, Stage 6 integration tests are green, and NLU coverage
> gaps are resolved.

## 1. Architecture overview

```
Domain routers (signals, incidents, emergency, control, forecasting, …)
   │  emit_*() after successful DB commit (fire-and-forget, non-raising)
   ▼
EventBus (backend/app/realtime/bus.py)
   │  XADD → Redis Stream  `trafficos:events`   (durable, replayable, MAXLEN ~10000)
   │  PUBLISH → `trafficos:events:pubsub`        (live fan-out)
   ▼
WS fan-out (backend/app/realtime/stream.py)
   one shared Redis subscriber task per process → per-connection asyncio.Queue
   → role/type filter → websocket.send_json
   ▼
Clients: ws://host/ws/v1/stream?token=<JWT>
```

PostgreSQL remains the source of persistent truth. Redis is used for
pub/sub, the replayable event stream, dedupe keys, and transient
threshold/gating state only.

### Degraded mode

If Redis is unreachable at startup, the bus logs a warning and runs degraded:
`publish`/`safe_publish` become logged no-ops, `subscribe` yields nothing, the
API still boots and serves. Endpoints never block on event publishing.

## 2. Event catalog

Envelope schema (`backend/app/realtime/events.py`, `EventEnvelope`):

| Field       | Type     | Notes                                            |
|-------------|----------|--------------------------------------------------|
| `event_id`  | UUID     | server-generated, dedupe key                     |
| `type`      | Literal  | one of the types below                           |
| `timestamp` | datetime | server time, UTC                                 |
| `payload`   | dict     | small delta: IDs + changed fields, never secrets |
| `source`    | str      | e.g. `"signals-api"`, `"control-engine"`        |

Event types (11): `traffic.update`, `congestion.change`, `signal.change`,
`incident.created`, `incident.updated`, `emergency.created`,
`emergency.updated`, `prediction.published`, `control.decision`,
`notification.created`, `system.status`.

### Publish hooks (`backend/app/realtime/hooks.py`)

Hooked into domain routers; each publishes **only after a successful commit**
and **only when state actually changed** (no-op updates emit nothing):

| Endpoint / service                              | Event                |
|-------------------------------------------------|----------------------|
| signals create/update/delete/override/phase     | `signal.change`      |
| incidents create / status change                | `incident.created` / `incident.updated` |
| emergency events create / resolve               | `emergency.created` / `emergency.updated` |
| control recommendations/decisions/apply         | `control.decision` (IDs + one-line summary; explanations stay in `ai_decisions`) |
| forecasting batch publish                       | `prediction.published` |
| vehicle_events batch ingest                     | **one** `traffic.update` per batch (never per vehicle) |
| congestion threshold crossing                   | `congestion.change` (last-emitted level in Redis, no DB writes) |
| notification creation (shared helper)           | `notification.created` |
| backend startup (lifespan)                      | `system.status` (`{"status":"online"}`) |

## 3. WebSocket streaming API

- **Endpoint:** `/ws/v1/stream` (websocket route, registered in `main.py`).
  The old Phase-1 `/api/v1/ws` and `/ws` handshakes are kept as deprecated
  aliases returning the new handshake shape with a deprecation note.
- **Auth:** JWT via query parameter `?token=<access_token>`.
  Rationale (documented in `stream.py`): browsers cannot set `Authorization`
  headers on a WebSocket handshake, so the query param is the pragmatic
  choice. The token is validated with `app.core.security.decode_token`
  **before** `accept()`; invalid/expired → close code `4401` (surfaces as
  HTTP 403 at the TCP upgrade layer under uvicorn — accounted for in tests).
  If the token has < 60 s of life left at connect, the connection is rejected
  with 4401 and told to refresh first. A watchdog sends
  `{"type":"auth.expired"}` and closes 4401 when `exp` passes mid-connection;
  the client refreshes and reconnects (optionally with `?last_event_id=`).
- **Handshake:** `{"type":"connection.established","event_types":[…],
  "heartbeat_interval_ms":25000,"server_time":…,"role":…}`.
- **Subscriptions:** client JSON control messages
  `{"type":"subscribe","event_types":[…]}` /
  `{"type":"unsubscribe","event_types":[…]}`; default = all types the role
  may receive. Unknown types → `{"type":"error",…}`.
- **Role filtering** (`ROLE_EVENT_ALLOWLIST` in `stream.py`):

| Role              | Receives |
|-------------------|----------|
| `admin`           | all 11 event types |
| `traffic_officer` | all 11 event types |
| `analyst`         | `traffic.update`, `congestion.change`, `signal.change`, `incident.created`, `incident.updated`, `prediction.published`, `control.decision`, `system.status` — **not** `emergency.*` or `notification.created` |

  Additionally, payload keys in `SENSITIVE_PAYLOAD_KEYS` (operator emails,
  phones, internal notes, …) are stripped before delivery to analysts.
- **Fan-out & backpressure:** one shared Redis subscriber task per process;
  per-connection `asyncio.Queue(maxsize=100)`; on full, drop oldest and count;
  if dropped > 50 → send `{"type":"stale",…}` and reset the queue.
- **Heartbeat:** server WS ping every 25 s; no pong within 60 s → close 1001.
  Client `{"type":"ping"}` → `{"type":"pong","server_time":…}`.
- **Reconnect resync:** `?last_event_id=<uuid>` at connect or
  `{"type":"resync","last_event_id":…}` message → server replays missed
  events in order via `bus.read_since()` (still role/type-filtered and
  dedupe-checked), then `{"type":"resync.complete","replayed":N}`.
  Unknown/trimmed ID → `{"type":"stale","message":"event history
  unavailable; refetch state via REST"}`.
- **Duplicate suppression:** per-connection bounded set of the last 1000
  `event_id`s; re-delivery skipped. Redis-side dedupe via
  `SETNX trafficos:event:{event_id}` (TTL 1 h).

## 4. Redis key inventory

| Key | Purpose |
|-----|---------|
| `trafficos:events` | Redis Stream, event log (MAXLEN ~10000) |
| `trafficos:events:pubsub` | pub/sub channel for live fan-out |
| `trafficos:event:{event_id}` | dedupe guard, TTL 1 h |
| `trafficos:congestion:last:{junction_id}` | last emitted congestion band (threshold-crossing detection) |
| `trafficos:notify:congestion:{junction_id}` | 15-min severe-congestion notification gate (TTL 900 s) |

Config: `REDIS_URL` (default `redis://localhost:6379/0`), already in
`backend/app/core/config.py` and `backend/.env.example`.

## 5. AI assistant backend (`backend/app/assistant/`)

### Tool / data layer (`tools.py`)

One async tool per domain; each takes the caller's role, raises
`PermissionDeniedError` for disallowed domains, and returns structured dicts
where every datum carries `provenance`: `"observed"` | `"predicted"` |
`"recommended"` (plus `confidence` where applicable). Tools call the
**existing** services — they never invent data; empty results return explicit
"no data" markers.

| Tool | Domain / provenance |
|------|---------------------|
| `get_traffic_state` | current observed traffic (observed) |
| `get_congestion_ranking` | most congested junctions (observed) |
| `get_predictions_30min` | Phase 5 forecasts, horizon + model version labeled (predicted) |
| `get_routing_advice` | Phase 3 routing, observed graph + predicted costs (observed→predicted) |
| `get_incidents` | incidents, optional junction filter (observed) |
| `get_junction_history` | traffic + incidents + signal history per junction (observed) |
| `get_signal_status` | signal states (observed) |
| `get_control_decisions` | decisions with stored explanations (recommended) |
| `get_analytics_summary` | aggregated network stats (observed) |
| `get_emergency_events` | emergency events (observed) |
| `simulate_signal_timing` | Phase 6 what-if simulator, measured deltas only (predicted) |

Per-tool RBAC matrix is documented in `tools.py`. Operator-oriented tools
(`simulate_signal_timing`, `get_routing_advice`) require `admin` or
`traffic_officer`; analysts get a clean permission message otherwise.

### Deterministic grounded NLU (`nlu.py`)

Regex/keyword intent patterns (ordered by specificity) + junction entity
resolution by numeric ID **or** name against the real `intersections` table
(unknown/ambiguous → clarification with close matches, never a guess).
Handled intents: `current_traffic_situation`, `congested_junctions`,
`predicted_congestion_30min`, `why_signal_recommendation`,
`worst_traffic_areas`, `route_advice`, `active_incidents`,
`junction_history`, `why_green_extended`, `whatif_signal_timing`.

Answers always separate **observed → predicted → recommended**, state
confidence/uncertainty, and say plainly when data is insufficient
(e.g. "I don't have enough recent data for junction X — last observation
was …"). Unknown questions → "I can't answer that from system data" +
concrete example questions. Conversation history supports junction
carryover ("what about junction 5?"); limits documented in `nlu.py`.

### LLM provider interface (`providers.py`)

- `LLMProvider` abstract base (`async def complete(prompt, context) -> str`).
- `DeterministicProvider` (default): runs the NLU engine, zero network.
- `HttpLLMProvider`: extension point for a real vendor — no vendor SDK
  imported at module load.
- Env-driven: `ASSISTANT_LLM_PROVIDER` (default `"deterministic"`),
  `ASSISTANT_LLM_API_KEY` (env **only** — never hardcoded, never logged).
  Honest contract: the deterministic engine ships working; setting a real
  provider key upgrades to conversational LLM mode with tool grounding.

### REST endpoint

`POST /api/v1/assistant/chat` (router `backend/app/api/v1/assistant.py`,
prefix `/assistant`). Body: `{message (1–2000 chars), conversation_history?
(max 20), junction_id?}`. All authenticated roles may call; tools enforce
per-domain RBAC. Returns `{answer, tool_calls: [{tool, args, provenance}],
provenance_summary: {observed, predicted, recommended},
confidence: high|medium|low, model}`. Every chat is audit-logged via
`app/core/audit.py log_audit` (user, IP, message, intent, tools — full
history not logged).

## 6. Notifications wiring (complete & verified)

Design (implemented in `backend/app/realtime/notify.py`, 552 lines):

| Event | Notification policy |
|-------|---------------------|
| `incident.created` | warning (error if incident severity high/critical) |
| `incident.updated` | info, deduped per incident |
| `emergency.created` | critical |
| `emergency.updated` | info, only on resolve/close |
| `congestion.change` | warning only for severe band (> 75%), max 1 per junction per 15 min (Redis gate) |
| `control.decision` | info, only operationally significant types (`OPERATIONALLY_SIGNIFICANT_DECISION_TYPES`) |
| `signal.change` | none by default; warning on emergency manual overrides |
| `prediction.published` | none (dashboards pull) |
| `notification.created` | **never** triggers another notification (explicit recursion guard) |

Delivery: system-wide broadcasts (`user_id=NULL`) per the existing model
pattern. Dedupe: single indexed query on
`(entity_type, entity_id, is_read, created_at)` within a 15-min window —
migration `0006_notifications_dedupe_index` adds the composite index
(applied to `trafficos_dev` and `trafficos_test`).

Integration point: `maybe_notify_for_event()` is wired directly into the shared
fan-out listener task in `backend/app/realtime/stream.py` (`run_fanout(bus)`).
Evaluations are scheduled as non-blocking background tasks (`asyncio.create_task`)
so the real-time fan-out delivery hot path is never blocked. Live verified
against PostgreSQL and Redis across all 6 operational scenarios.

## 7. Tests

| File | Coverage | Count |
|------|----------|-------|
| `test_realtime.py` | bus: publish/subscribe, dedupe, replay, stale, degraded mode | 7 |
| `test_realtime_websocket.py` | WS auth (incl. 4401), watchdog, RBAC filtering, dedupe, resync, heartbeat | 18 |
| `test_assistant.py` | tools + provenance, intents, unknown/clarification/insufficient-data, RBAC, chat endpoint, audit, 10 required questions | 13 |
| `test_eventbus_integration.py` | real Redis publish/stream/sub, dedupe, read_since, degraded mode, payload hygiene | 5 |
| `test_publish_hooks.py` | incident create/patch, signal state change/identical, emergency create/resolve, recommendations, vehicle batch ingest single update | 5 |
| `test_notifications_realtime.py` | incident notification flow, unread dedupe window, severity gating, 15-min congestion gate, recursion guard | 5 |
| `test_ws_notifications.py` | WS notification on broadcast/targeted REST create, per-connection dedupe cache, analyst role filtering | 4 |

Full suite: **270 passed** (213 pre-Phase-9 baseline + 57 Phase 9 tests), 0 failures.

## 8. Known gaps / honest limitations

1. **Stage 5 integration (CLOSED 2026-10-08):** `maybe_notify_for_event()` in
   `backend/app/realtime/notify.py` is wired into the shared background fan-out
   subscriber task (`run_fanout(bus)` in `backend/app/realtime/stream.py`),
   scheduled fail-safely as non-blocking background tasks. Verified live on
   `:8000` across all 6 operational scenarios.
2. **Stage 6 tests (CLOSED 2026-10-08):** Dedicated integration test files
   authored and verified (`test_eventbus_integration.py`, `test_publish_hooks.py`,
   `test_notifications_realtime.py`, `test_ws_notifications.py`), bringing the
   test suite to 270 passing tests.
3. The deterministic NLU handles the listed intents; free-form conversation
   beyond them needs a real LLM provider key (not configured).
4. WS auth uses a JWT query param (documented trade-off); token refresh is
   client-driven via 4401 + `last_event_id` resync.
5. `system.status` is emitted only on backend startup; no periodic heartbeat
   event is published.
6. **Frontend/backend WS contract mismatch (found 2026-10-08, fix staged):**
   `web/src/lib/realtime-protocol.ts` and
   `mobile/lib/services/realtime_protocol.dart` were written against a
   `topics` wire contract (`?topics=t1,t2`, `{"type":"subscribe","topics":[...]}`),
   but the backend implements `event_types`
   (`{"type":"subscribe","event_types":[...]}`, handshake carries `event_types`;
   see `backend/app/realtime/stream.py`). Live-verified: subscriptions using
   `topics` receive an error frame. Fix staged in
   `~/workspace/phase9-frontend-webui-retry.md` and
   `~/workspace/phase9-frontend-mobile-retry.md` (Task 0 in each).
7. **NLU phrasing gaps (found 2026-10-08, fix staged):** 3 of the 10 required
   example questions fall through to the unknown-question fallback:
   "Which junctions are congested?", "What route should traffic take?",
   "What would happen if this signal timing changed?" (the intent patterns
   don't match these wordings). Fix staged as Task C in
   `~/workspace/phase9-backend-retry.md`.
8. **UI layers not yet rebuilt (agy quota):** web UI layer (ConnectionStatus
   pill, AppShell integration, AssistantChat, assistant page) and mobile
   per-screen realtime wirings (7 screens) are staged in the retry prompts
   above; only the lib/service layers are currently in the tree and tested.
