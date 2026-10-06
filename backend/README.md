# AI TrafficOS - Backend Service

Phase 1 foundation backend service implemented with Python 3.12 and FastAPI.

## Architecture & Scope

This service represents the architectural foundation for AI TrafficOS:
- Async FastAPI application factory (`create_app`) with CORS middleware and lifespan lifecycle management.
- SQLAlchemy 2.0 asynchronous database session handling with the `asyncpg` driver.
- Base schema models for intersections, signal control placeholders, and vehicle/incident event placeholders.
- API v1 endpoints providing system health, service metadata, and an initial WebSocket connection handshake.
- No detection or prediction features are implemented in Phase 1; hooks and architectural contracts are established for future phases.

## Getting Started

### 1. Prerequisites

- Python 3.12+
- PostgreSQL 16 (available via Docker Compose: `docker compose up -d postgres`)
- Redis 7 (available via Docker Compose: `docker compose up -d redis`)

### 2. Virtual Environment Setup

From the `backend/` directory:

```bash
# Create virtual environment with Python 3.12
python3.12 -m venv .venv

# Activate the virtual environment
source .venv/bin/activate

# Upgrade pip and install dependencies
pip install --upgrade pip
pip install -r requirements.txt
```

### 3. Environment Configuration

Copy the example environment configuration:

```bash
cp .env.example .env
```

Review and adjust variables in `.env` if necessary:
- `DATABASE_URL`: Asynchronous PostgreSQL connection string (`postgresql+asyncpg://trafficos:trafficos@localhost:5432/trafficos`).
- `REDIS_URL`: Redis connection URL (`redis://localhost:6379/0`).
- `ENV`: Runtime environment (`development`, `staging`, `production`).
- `CORS_ORIGINS`: JSON array of allowed origins (default: `["http://localhost:3000"]`).

### 4. Database Migrations

Apply the initial database schema using Alembic:

```bash
# From repository root or database/ directory:
cd ../database
alembic upgrade head
```

Or from `backend/`:
```bash
alembic -c ../database/alembic.ini upgrade head
```

### 5. Running the Application

Start the development server with live reload:

```bash
cd backend
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

## API Endpoints

Once the application is running:

| Endpoint | Method / Protocol | Description | Sample Response |
| :--- | :--- | :--- | :--- |
| `/api/v1/health` | `GET` | Health verification | `{"status": "ok", "service": "ai-trafficos", "version": "0.1.0"}` |
| `/api/v1/version` | `GET` | Service version metadata | `{"service": "ai-trafficos", "version": "0.1.0"}` |
| `/api/v1/ws` | `WebSocket` | WebSocket handshake | `{"type": "handshake", "status": "connected", "note": "Phase 1: no live traffic streams yet"}` |
| `/docs` | `GET` | Interactive OpenAPI documentation (Swagger UI) | HTML UI |
| `/redoc` | `GET` | ReDoc API documentation | HTML UI |

## Project Structure

```
backend/
├── app/
│   ├── api/
│   │   └── v1/
│   │       ├── router.py       # API v1 route definitions
│   │       └── websocket.py    # WebSocket connection handler
│   ├── core/
│   │   ├── config.py           # Pydantic Settings and env loader
│   │   └── database.py         # SQLAlchemy async engine & sessionmaker
│   ├── models/
│   │   ├── __init__.py         # Model registry and Base re-export
│   │   ├── event.py            # VehicleEvent and Incident placeholders
│   │   ├── intersection.py     # Intersection model
│   │   └── signal.py           # SignalPhase placeholder
│   └── main.py                 # Application factory and lifespan
├── .env.example                # Example environment variables
├── requirements.txt            # Python dependencies
└── README.md                   # Backend documentation
```
