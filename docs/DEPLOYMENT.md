# AI TrafficOS - Production Deployment Guide

This document provides complete instructions for deploying **AI TrafficOS** into production across its managed cloud infrastructure.

---

## 1. System Architecture Diagram

```
+---------------------------------------------------------------------------------------+
|                                    CLIENT LAYER                                       |
|                                                                                       |
|   +------------------------------------+             +----------------------------+   |
|   |         Web Frontend (Vercel)      |             |     Mobile App (Flutter)   |   |
|   |   Next.js 16 (React 19 / TS)       |             |   Android (AAB/APK) / iOS  |   |
|   |   Static Export / Edge Serving     |             |   Field Operator / Wardens |   |
|   +-----------------+------------------+             +-------------+--------------+   |
+---------------------|----------------------------------------------|------------------+
                      | HTTPS (REST)                                 | HTTPS (REST)
                      | WSS (WebSockets)                             | WSS (WebSockets)
                      +----------------------+-----------------------+
                                             |
                                             v
+---------------------------------------------------------------------------------------+
|                                 APPLICATION BACKEND                                   |
|                                                                                       |
|   Fly.io (Region: bom - Mumbai | Shared CPU 1x | 512MB RAM)                           |
|   +-------------------------------------------------------------------------------+   |
|   |                      FastAPI Asynchronous Gateway (Uvicorn)                   |   |
|   |                                                                               |   |
|   |   - REST API v1 (/api/v1/...)                                                 |   |
|   |   - Real-time Event Hub & WebSockets (/ws/v1/stream)                          |   |
|   |   - Signal Coordination & Adaptive Timing Logic                               |   |
|   |   - AI Assistant & Analytics Engine                                           |   |
|   |   - Computer Vision Telemetry Ingestion (YOLO CPU / Edge feed)                |   |
|   +-----------------------+-------------------------------+-----------------------+   |
+---------------------------|-------------------------------|---------------------------+
                            |                               |
                            | SQL / asyncpg (TLS)           | Redis Protocol / TLS
                            v                               v
+-------------------------------------------+   +---------------------------------------+
|             PRIMARY DATABASE              |   |          REAL-TIME EVENT BUS          |
|                                           |   |                                       |
|   Neon PostgreSQL (Managed Serverless)    |   |   Managed Redis (Upstash / Cloud)     |
|   - Direct Endpoint (Migrations/DDL)      |   |   - Redis Pub/Sub Stream Engine       |
|   - Pooled Endpoint (App Runtime / Query) |   |   - Fast Telemetry State Cache        |
|   - Automatic Branching & Point-in-Time   |   |   - Decoupled Real-time Fanout        |
+-------------------------------------------+   +---------------------------------------+
```

---

## 2. Production Hosting Topology

| Component | Provider | Tier / Specification | Key Rationale |
| :--- | :--- | :--- | :--- |
| **Web Frontend** | **Vercel** | Hobby / Pro | Global CDN edge caching, optimized Next.js 16 SSG/SSR builds. |
| **API Backend** | **Fly.io** | Shared CPU 1x, 512MB RAM (`bom` - Mumbai) | Native long-lived WebSocket connections, low latency to Hyderabad/India, containerized release pipeline. *(Note: Render is strictly avoided)*. |
| **Database** | **Neon** | Serverless PostgreSQL 16 (`ap-south-1` or nearest) | Autoscaling storage, zero-maintenance pooling, instantaneous branching. |
| **Cache & Streams**| **Managed Redis** | Upstash Redis / Redis Cloud | Serverless, standard `REDIS_URL` compatibility, pub/sub fanout. |
| **Mobile App** | **Google Play** | Android App Bundle (AAB) | Env-driven release keystore signing. |

---

## 3. Step-by-Step Deployment Guide

### Step A: Provision Neon PostgreSQL & Run Migrations

1. **Create Neon Project**:
   - Log in to [Neon Console](https://console.neon.tech).
   - Create a project named `ai-trafficos`. Select PostgreSQL 16 and a region close to your users (e.g., AWS Mumbai `ap-south-1` or `aws-us-east-2`).

2. **Retrieve Connection Strings**:
   Neon provides two connection strings:
   - **Pooled URL** (port 5432 or 6543, host contains `-pooler`):
     ```
     postgresql://neondb_owner:YOUR_PASSWORD@ep-xyz-pooler.ap-south-1.aws.neon.tech/neondb?sslmode=require
     ```
   - **Direct URL** (port 5432, host does NOT contain `-pooler`):
     ```
     postgresql://neondb_owner:YOUR_PASSWORD@ep-xyz.ap-south-1.aws.neon.tech/neondb?sslmode=require
     ```

3. **Important Note on Migrations (Direct vs. Pooled)**:
   > [!IMPORTANT]
   > **Always use the DIRECT Neon URL for Alembic migrations.**
   > Neon's pooled URL routes connections through PgBouncer in transaction mode. Transaction pooling restricts DDL transactions, advisory locks, and statement caching. The direct URL bypasses PgBouncer, ensuring schema migrations run cleanly without locking errors or prepared-statement conflicts.

4. **Execute Initial Database Migration**:
   Run the migration against Neon using the direct connection string:
   ```bash
   DATABASE_URL="postgresql://neondb_owner:YOUR_PASSWORD@ep-xyz.ap-south-1.aws.neon.tech/neondb?sslmode=require" \
   alembic -c database/alembic.ini upgrade head
   ```

---

### Step B: Provision Managed Redis

AI TrafficOS requires a managed Redis 7+ instance reachable over TCP.

**Recommended Options**:
- **Upstash Redis**: Serverless Redis with native TLS. Create a database in Mumbai (`ap-south-1`). Copy the `rediss://...` or `redis://...` connection string.
- **Redis Cloud / Aiven**: Fixed-size managed Redis with 99.99% SLA.
- **Fly.io Redis**: `fly redis create --region bom`.

**Example Redis URL format**:
```
redis://default:YOUR_REDIS_PASSWORD@trafficos-cache.upstash.io:6379
```

---

### Step C: Configure Fly.io Secrets

1. **Install Fly CLI & Authenticate**:
   ```bash
   curl -L https://fly.io/install.sh | sh
   fly auth login
   ```

2. **Initialize Fly App (if first time)**:
   From the repository root (`~/workspace/AI-TrafficOS`):
   ```bash
   fly apps create ai-trafficos-api
   ```

3. **Set Production Secrets**:
   Set secrets using `fly secrets set`. **Never commit secrets to Git.**

   ```bash
   # Generate a 32+ character random secret key
   SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")

   fly secrets set \
     DATABASE_URL="postgresql://neondb_owner:YOUR_PASSWORD@ep-xyz-pooler.ap-south-1.aws.neon.tech/neondb?sslmode=require" \
     REDIS_URL="redis://default:YOUR_PASSWORD@trafficos-cache.upstash.io:6379" \
     SECRET_KEY="$SECRET_KEY" \
     CORS_ORIGINS="https://ai-trafficos.vercel.app,https://trafficos.yourdomain.com" \
     ASSISTANT_LLM_PROVIDER="gemini" \
     ASSISTANT_LLM_API_KEY="YOUR_GEMINI_API_KEY"
   ```

   > [!NOTE]
   > For the Fly.io application runtime, use the **Pooled** URL for high connection concurrency. The automated release command (`alembic upgrade head`) will run during deployment. If your migration encounters PgBouncer lock contention on the pooler, temporarily point `DATABASE_URL` to the **Direct** URL.

---

### Step D: Deploy Backend to Fly.io & Health Check

1. **Deploy from Repository Root**:
   Always execute `fly deploy` from the root directory so Docker can copy both `backend/` and `database/`:
   ```bash
   fly deploy --config fly.toml
   ```

2. **Verify Release Migration & Machine Status**:
   ```bash
   fly status
   fly logs
   ```

3. **Understanding Auto-Stop vs. Persistent Machines**:
   - In `fly.toml`, `auto_stop_machines = "stop"` is enabled by default to conserve free-tier machine resources when idle.
   - **WebSocket Latency Consideration**: When idle machines sleep, the initial WebSocket connection (`/ws/v1/stream`) wakes the machine, causing a 1–3 second handshake delay.
   - **For 24/7 Zero-Latency WebSockets**:
     In `fly.toml`, change `min_machines_running` to `1`:
     ```toml
     [http_service]
       min_machines_running = 1
     ```
     Then redeploy with `fly deploy`.

4. **Verify Health**:
   ```bash
   curl -i https://ai-trafficos-api.fly.dev/health
   ```
   Expected response:
   ```json
   {"status":"ok","service":"ai-trafficos","version":"0.1.0"}
   ```

---

### Step E: Deploy Web Frontend to Vercel

1. **Connect Repository to Vercel**:
   - Go to [Vercel Dashboard](https://vercel.com/new).
   - Import the `AI-TrafficOS` repository.
   - Select **Root Directory**: `web`.

2. **Verify Build Settings**:
   - **Framework Preset**: Next.js
   - **Build Command**: `npm run build`
   - **Output Directory**: `.next`

3. **Configure Environment Variables in Vercel**:
   In Project Settings -> Environment Variables:
   | Key | Value | Target |
   | :--- | :--- | :--- |
   | `NEXT_PUBLIC_API_URL` | `https://ai-trafficos-api.fly.dev` | Production, Preview |

4. **Deploy**:
   - Click **Deploy**.
   - Note the production domain (e.g. `https://ai-trafficos.vercel.app`).
   - Ensure this domain is included in `CORS_ORIGINS` on Fly.io.

---

### Step F: Mobile Production Release Build (Flutter)

The Android release build uses environment-driven keystore signing with zero hardcoded credentials.

1. **Generate Android Release Keystore (one-time)**:
   ```bash
   keytool -genkey -v -keystore ~/ai-trafficos-release.jks \
     -keyalg RSA -keysize 2048 -validity 10000 \
     -alias trafficos-upload
   ```

2. **Supply Credentials via Environment Variables**:
   In your CI/CD runner (GitHub Actions, Codemagic) or local terminal:
   ```bash
   export ANDROID_KEYSTORE_PATH="/absolute/path/to/ai-trafficos-release.jks"
   export ANDROID_KEYSTORE_PASSWORD="your_keystore_password"
   export ANDROID_KEY_ALIAS="trafficos-upload"
   export ANDROID_KEY_PASSWORD="your_key_password"
   ```

   *(Alternative: create `mobile/android/key.properties` from `mobile/android/key.properties.example`. This file is git-ignored).*

3. **Build Android Release Artifacts**:
   ```bash
   cd mobile
   flutter clean
   flutter pub get

   # Build Android App Bundle for Google Play Console:
   flutter build appbundle --release \
     --dart-define=API_BASE_URL=https://ai-trafficos-api.fly.dev

   # Or build standalone APK for side-loading:
   flutter build apk --release \
     --dart-define=API_BASE_URL=https://ai-trafficos-api.fly.dev
   ```

---

## 4. Environment Variable Reference

### Backend (`backend/app/core/config.py`)

| Variable | Required in Prod | Default | Example Value | Description |
| :--- | :--- | :--- | :--- | :--- |
| `ENV` | Yes | `development` | `production` | Enables fail-fast security validations. |
| `PORT` | No | `8000` | `8000` | HTTP listening port for Uvicorn. |
| `DATABASE_URL` | **Yes** | Localhost | `postgresql://user:pass@ep-xyz-pooler.neon.tech/neondb?sslmode=require` | PostgreSQL connection string. `sslmode=require` is auto-translated for asyncpg. |
| `REDIS_URL` | **Yes** | Localhost | `redis://default:pass@redis.upstash.io:6379` | Managed Redis connection string for telemetry and event streaming. |
| `SECRET_KEY` | **Yes** | None | `bXk0bTJjMG...` (min 32 chars) | HMAC signing key for JWT tokens. Rejects insecure defaults in production. |
| `CORS_ORIGINS` | **Yes** | Localhost | `https://ai-trafficos.vercel.app` | Comma-separated allowed frontend origins. Wildcard `*` prohibited in prod. |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | No | `30` | `30` | JWT bearer token expiration duration. |
| `REFRESH_TOKEN_EXPIRE_DAYS` | No | `7` | `7` | JWT refresh token expiration duration. |
| `RATE_LIMIT_ENABLED` | No | `true` | `true` | Enforces IP and user rate limiting on critical endpoints. |
| `RATE_LIMIT_AUTH_PER_MINUTE` | No | `60` | `60` | Max auth attempts per IP per minute. |
| `RATE_LIMIT_EXPENSIVE_PER_MINUTE` | No | `60` | `60` | Max calls to heavy analytics/CV per minute. |
| `SIGNAL_HARDWARE_ENABLED` | No | `false` | `false` | Physical controller relay interface (keep `false` for simulated/cloud). |
| `ASSISTANT_LLM_PROVIDER` | No | `deterministic` | `gemini` or `openai` | AI Assistant backend engine (`deterministic`, `gemini`, `openai`, `anthropic`). |
| `ASSISTANT_LLM_API_KEY` | Conditional | None | `AIzaSy...` | API key required if using commercial LLM providers. |

### Web Frontend (`web/`)

| Variable | Required | Example Value | Description |
| :--- | :--- | :--- | :--- |
| `NEXT_PUBLIC_API_URL` | **Yes** | `https://ai-trafficos-api.fly.dev` | Public URL of the Fly.io backend for REST & WebSockets. |

### Mobile Application (`mobile/`)

| Variable / Property | Required for Release | Description |
| :--- | :--- | :--- |
| `API_BASE_URL` | **Yes** | Backend URL provided via `--dart-define=API_BASE_URL=...`. |
| `ANDROID_KEYSTORE_PATH` | **Yes** | Absolute path to `.jks` release keystore file. |
| `ANDROID_KEYSTORE_PASSWORD` | **Yes** | Password to access the release keystore. |
| `ANDROID_KEY_ALIAS` | **Yes** | Signing key alias inside keystore. |
| `ANDROID_KEY_PASSWORD` | **Yes** | Password for the signing key alias. |

---

## 5. Data Integrity & Simulation Invariants

> [!CAUTION]
> **No Fake Live Data in Production.**
> Synthetic training datasets must remain strictly decoupled from live operations.

- **Synthetic Training Data**:
  - Located under `ai/` and generated via offline simulation scripts.
  - Used solely for training ML regression/classification models, calibrating historical baselines, and CI pipeline validation.
- **Production Telemetry**:
  - Roadside sensors, induction loops, and camera detections ingested via `/api/v1/vehicle-events`, `/api/v1/traffic-records`, and optical CV pipelines must represent **authentic, timestamped telemetry**.
  - If hardware signal actuators are offline (`SIGNAL_HARDWARE_ENABLED=false`), the system operates in **Autonomous Simulation Mode**—simulated signal phase plans are logged for supervisory review without driving physical field voltages.
  - Telemetry records include audit provenance (`source='sensor' | 'cv_optical' | 'simulation_baseline'`) to guarantee end-to-end data traceability.

---

## 6. Monitoring, Backup & Disaster Recovery

### Primary Database (Neon)
- **Continuous Backups**: Neon maintains automatic point-in-time recovery (PITR) for up to 7 days on free tiers and 30 days on paid tiers.
- **Zero-Downtime Branching**: Before performing schema alterations or major releases, create an instantaneous database branch in the Neon Console to test migrations safely against live state.
- **Manual Backups**:
  ```bash
  pg_dump "$DATABASE_URL" --format=c --file=trafficos_backup_$(date +%Y%m%d).dump
  ```

### Real-Time Event Bus (Redis)
- Redis is used as an ephemeral cache and pub/sub message bus. In the event of a managed Redis outage, AI TrafficOS falls back to degraded local in-memory operation (`app.realtime.get_bus()` handles connection retries gracefully).
- If using persistent queues, ensure AOF (Append-Only File) or hourly RDB snapshots are enabled on your Redis provider.

### Application Health (Fly.io)
- **Health Checks**: The Docker container includes an automated `HEALTHCHECK` querying `/health` every 30 seconds.
- **Metrics**: Monitor CPU, RAM, and HTTP response percentiles in the Fly.io dashboard:
  ```bash
  fly metrics
  ```
- **Live Logs**:
  ```bash
  fly logs --app ai-trafficos-api
  ```

### Disaster Recovery Runbook
1. **Compromised Secret**: Rotate `SECRET_KEY` immediately via `fly secrets set SECRET_KEY=...`. Existing JWT sessions will be invalidated immediately, forcing re-authentication.
2. **Database Failure**: Fail over to a restored Neon branch, update `DATABASE_URL` via `fly secrets set`, and Fly will automatically trigger a rolling restart.
3. **Application Rollback**: If a bad release is deployed, roll back immediately:
   ```bash
   fly releases list
   # Deploy previous image tag or commit
   ```

---

## 7. Known Limitations & Architectural Constraints

1. **Free-Tier Resource Ceilings**:
   - **Neon Compute Suspend**: Neon free-tier databases suspend compute after 5 minutes of inactivity. The first query after suspension incurs a cold wake-up penalty of 1.0–2.0 seconds.
   - **Fly.io Memory Footprint**: The backend container runs on a 512MB RAM VM. Uvicorn with 2 workers operates within ~280MB. Heavy background processing must be monitored.
   - **Upstash Redis Command Caps**: Free-tier Upstash has a 10,000 commands/day limit. Ensure telemetry publish rates in staging do not exceed daily quotas.

2. **WebSocket Reconnect Behavior**:
   - Long-lived WebSocket connections will terminate if Fly.io stops idle machines (`auto_stop_machines = "stop"`).
   - Frontend and mobile clients implement exponential backoff reconnection (`1s, 2s, 4s, 8s, max 30s`).
   - For mission-critical traffic operations centers (TOC), configure `min_machines_running = 1` in `fly.toml` to prevent connection disconnects.

3. **Computer Vision Inference Compute**:
   - Running YOLOv8 object detection on a shared CPU 512MB VM is CPU-intensive (~150–400ms per frame).
   - In production, video streams should **never be streamed raw to the cloud API**.
   - Edge devices (roadside NVIDIA Jetson or Intel IPCs) must run YOLO locally and stream lightweight JSON telemetry (vehicle counts, bounding boxes, optical signal states) to the FastAPI backend.

---

## 8. Verification Checklist & Smoke Tests

Verify your deployment using the following curl commands. Replace `https://ai-trafficos-api.fly.dev` with your production API domain.

### 1. Root & Health Check
```bash
# General Health
curl -sS -i https://ai-trafficos-api.fly.dev/health
# Expect: HTTP/1.1 200 OK -> {"status":"ok","service":"ai-trafficos","version":"0.1.0"}

# API v1 Health
curl -sS -i https://ai-trafficos-api.fly.dev/api/v1/health
# Expect: HTTP/1.1 200 OK -> {"status":"ok","service":"ai-trafficos","version":"0.1.0"}

# Version Check
curl -sS https://ai-trafficos-api.fly.dev/version
# Expect: {"service":"ai-trafficos","version":"0.1.0"}
```

### 2. User Authentication Flow
```bash
# Register a test admin/operator
curl -sS -X POST https://ai-trafficos-api.fly.dev/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{
    "email": "operator@trafficos.internal",
    "password": "SecurePassword123!",
    "full_name": "Traffic Operator"
  }'

# Login to acquire JWT access token
TOKEN=$(curl -sS -X POST https://ai-trafficos-api.fly.dev/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{
    "email": "operator@trafficos.internal",
    "password": "SecurePassword123!"
  }' | python3 -c "import sys, json; print(json.load(sys.stdin).get('access_token', ''))")

echo "Acquired JWT: $TOKEN"
```

### 3. Core Domain Entity Verification
```bash
# Query Intersections
curl -sS -H "Authorization: Bearer $TOKEN" \
  https://ai-trafficos-api.fly.dev/api/v1/intersections

# Query Signals
curl -sS -H "Authorization: Bearer $TOKEN" \
  https://ai-trafficos-api.fly.dev/api/v1/signals

# Query Incidents
curl -sS -H "Authorization: Bearer $TOKEN" \
  https://ai-trafficos-api.fly.dev/api/v1/incidents
```

### 4. Real-time WebSocket Stream Handshake
Using `wscat` or `websocat`:
```bash
# Test WebSocket endpoint
wscat -c "wss://ai-trafficos-api.fly.dev/ws/v1/stream"
```
Expect immediate connection established with initial system status broadcast:
```json
{"type": "system_status", "status": "online", "service": "ai-trafficos"}
```
