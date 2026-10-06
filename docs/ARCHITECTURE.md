# AI TrafficOS - System Architecture & Engineering Roadmap

## 1. System Overview

AI TrafficOS is a high-performance operating platform for intelligent intersection coordination, computer vision telemetry, predictive congestion forecasting, and autonomous signal timing.

In **Phase 1 (Foundation & Architecture)**, the core asynchronous application scaffolding, schema models, database migration tooling, and AI contracts are established. Concrete computer vision inference, predictive models, and autonomous control algorithms are introduced in planned downstream phases.

### System Architecture Diagram

```
+-----------------------------------------------------------------------------+
|                             Client Layer (Future)                           |
|   +------------------------------------+   +----------------------------+   |
|   |         Web Dashboard              |   |       Mobile / Tablet      |   |
|   |   (Next.js / React / TypeScript)   |   |     (Flutter / Operator)   |   |
|   +-----------------+------------------+   +--------------+-------------+   |
+---------------------|-------------------------------------|-----------------+
                      | HTTP / WebSocket                    | HTTP / WebSocket
                      +------------------+------------------+
                                         |
+----------------------------------------v------------------------------------+
|                         Application Backend (FastAPI)                       |
|                                                                             |
|   +---------------------------------------------------------------------+   |
|   |                           app/main.py                               |   |
|   |             FastAPI App Factory | CORS | Lifespan Manager            |   |
|   +----------------------------------+----------------------------------+   |
|                                      |                                      |
|            +-------------------------+-------------------------+            |
|            | prefix: /api/v1                                   |            |
|   +--------v-------------------------+       +-----------------v--------+   |
|   |        app/api/v1/router.py      |       |  app/api/v1/websocket.py |   |
|   |  - GET /health                   |       |  - /ws (Phase 1          |   |
|   |  - GET /version                  |       |     handshake & close)   |   |
|   |  - [Phase 2+: detection, signal, |       +--------------------------+   |
|   |     incident & prediction APIs]  |                                      |
|   +----------------------------------+                                      |
|                                                                             |
|   +----------------------------------+       +--------------------------+   |
|   |        app/core/database.py      |       |    app/core/config.py    |   |
|   |  SQLAlchemy 2.0 Async Session    |       |   Pydantic Settings      |   |
|   +----------------+-----------------+       +--------------------------+   |
|                    |                                                        |
+--------------------|--------------------------------------------------------+
                     |
         +-----------+-----------+
         |                       |
+--------v-----------+  +--------v-----------+
|    PostgreSQL 16   |  |      Redis 7       |
|   (AsyncPG Pool)   |  |  (Cache & Streams) |
|                    |  |                    |
| - intersections    |  | [Phase 2+: Real-   |
| - signal_phases    |  |  time pub/sub,     |
| - vehicle_events   |  |  telemetry cache,  |
| - incidents        |  |  task queue]       |
+--------------------+  +--------------------+

                      ................................
                      :    AI Sidecars (Future Phases):
                      :...............................:
                      :                               :
                      :  +-------------------------+  :
                      :  |     ai/cv/ (Phase 4)    |  :
                      :  |   YOLO Vehicle Detector |  :
                      :  |   Signal State Head     |  :
                      :  |   Emergency Vehicle CV  |  :
                      :  +-------------------------+  :
                      :                               :
                      :  +-------------------------+  :
                      :  | ai/prediction/ (Phase 5)|  :
                      :  |   ST-GNN Flow Forecaster|  :
                      :  |   Congestion Predictor  |  :
                      :  +-------------------------+  :
                      :...............................:
```

---

## 2. Technology Stack

| Layer | Technology | Version / Specification | Rationale & Notes |
| :--- | :--- | :--- | :--- |
| **Runtime** | Python | `>= 3.12` | Modern async performance, typed syntax, native sub-interpreter enhancements. |
| **Backend Framework** | FastAPI | `>= 0.110` | High-throughput asynchronous REST & WebSocket framework built on Starlette and Pydantic. |
| **ASGI Server** | Uvicorn | `>= 0.29 (standard)` | High-performance ASGI web server with uvloop and httptools. |
| **Configuration** | Pydantic Settings | `>= 2.2` | Strongly-typed environment configuration and validation from `.env`. |
| **ORM / Data Access** | SQLAlchemy Async | `>= 2.0` | Asynchronous 2.0 syntax, typing support, unified transactional sessions. |
| **Database Driver** | asyncpg | `>= 0.29` | High-speed asynchronous PostgreSQL binary protocol driver. |
| **Schema Migrations** | Alembic | `>= 1.13` | Async migration runner managing database revisions and declarative metadata. |
| **Primary Database** | PostgreSQL | `16` | Relational storage for intersections, signal topology, incidents, and audit trails. |
| **In-Memory Store** | Redis | `7` | Pub/Sub messaging, telemetry streaming, and fast cache (Phase 2+). |
| **Testing** | pytest + HTTPX | `>= 8.0` / `>= 0.27` | Asynchronous test harness for HTTP and WebSocket contracts. |
| **Perception Engine** | Python / PyTorch / OpenCV | Future (Phase 4) | Computer vision inference pipelines for edge and sidecar servers. |
| **Forecasting Engine** | Graph Neural Nets / GNN | Future (Phase 5) | Spatial-temporal graph forecasting for city grid congestion. |

---

## 3. Module Map

```
AI-TrafficOS/
├── backend/                        # Python 3.12 FastAPI backend service
│   ├── app/
│   │   ├── api/                    # API routers and endpoints
│   │   │   ├── __init__.py
│   │   │   └── v1/                 # API Version 1
│   │   │       ├── __init__.py
│   │   │       ├── router.py       # Root v1 router (/health, /version)
│   │   │       └── websocket.py    # WebSocket router (/ws)
│   │   ├── core/                   # Application infrastructure
│   │   │   ├── __init__.py
│   │   │   ├── config.py           # Pydantic Settings and env loader
│   │   │   └── database.py         # SQLAlchemy async engine & sessionmaker
│   │   ├── models/                 # SQLAlchemy 2.0 schema definitions
│   │   │   ├── __init__.py         # Base and model registry
│   │   │   ├── event.py            # VehicleEvent and Incident placeholders
│   │   │   ├── intersection.py     # Intersection core model
│   │   │   └── signal.py           # SignalPhase placeholder
│   │   ├── __init__.py
│   │   └── main.py                 # Application factory (create_app)
│   ├── .env.example                # Sample environment configuration
│   ├── requirements.txt            # Dependency manifest
│   └── README.md                   # Backend documentation
├── database/                       # Database schema migrations
│   ├── alembic/
│   │   ├── versions/
│   │   │   └── 0001_initial.py     # Initial DDL migration
│   │   └── env.py                  # Async Alembic runner
│   ├── alembic.ini                 # Alembic configuration
│   └── README.md                   # Database documentation
├── ai/                             # Perception and predictive contracts
│   ├── common/
│   │   ├── __init__.py
│   │   └── schemas.py              # Detection and TrafficSnapshot dataclasses
│   ├── cv/
│   │   ├── __init__.py
│   │   └── detectors.py            # BaseDetector abstract contract
│   ├── prediction/
│   │   ├── __init__.py
│   │   └── base.py                 # BasePredictor abstract contract
│   ├── __init__.py                 # AI package root & phase documentation
│   └── README.md                   # AI architecture and roadmap mapping
├── scripts/                        # Development and operational utilities
│   ├── dev.sh                      # Development bootstrapper
│   └── README.md                   # Script documentation
├── docs/
│   └── ARCHITECTURE.md             # System architecture and engineering roadmap
├── web/                            # Web operations console (Future)
├── mobile/                         # Mobile field operator client (Future)
├── docker-compose.yml              # Local container infrastructure (Postgres 16, Redis 7)
├── .gitignore                      # Git exclusion rules
└── README.md                       # Repository overview and entry point
```

---

## 4. Engineering Roadmap: Phase Comparison

| Phase | Title | Scope & Deliverables | Status |
| :--- | :--- | :--- | :--- |
| **Phase 1** | **Foundation & Architecture** | Architecture foundation: FastAPI app skeleton, configuration loading, async SQLAlchemy engine, base schema models (`intersections`, `signal_phases`, `vehicle_events`, `incidents`), Alembic async migration `0001`, health checks (`/health`, `/version`), WebSocket handshake, AI abstract contracts (`BaseDetector`, `BasePredictor`, schemas), and local container compose. | **Active / Current** |
| **Phase 2** | **Backend & DB Real Logic** | Implementation of production CRUD for intersections, signal state persistence, real event ingestion pipelines, Redis cache integration, structured error handling, and authorization. | Planned |
| **Phase 3** | **DSA & Traffic Algorithms** | Deterministic algorithms: Webster's equation for cycle length, green split allocation, coordination offsets, priority queue dispatch, and graph-based network routing. | Planned |
| **Phase 4** | **Computer Vision AI** | Concrete vision pipelines: YOLO vehicle detection, pedestrian and bicycle trackers, traffic signal aspect classification, emergency vehicle priority trigger, and camera RTSP ingestion. | Planned |
| **Phase 5** | **Predictive AI** | Spatial-temporal traffic flow forecasting (GNN/LSTM), bottleneck detection, queue length estimation, and incident risk modeling. | Planned |
| **Phase 6** | **Intelligent Traffic Control** | Reinforcement learning and adaptive control loops, actuated multi-intersection green waves, emergency preemption sequencing, and transit signal priority (TSP). | Planned |
