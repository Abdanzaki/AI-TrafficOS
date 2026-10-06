# AI TrafficOS

> Phase 1: foundation only — API skeleton, health checks, DB schema stubs; no detection/prediction features yet.

AI TrafficOS is an intelligent operating platform for urban intersection management, traffic flow optimization, and perception telemetry.

This repository currently hosts the Phase 1 architectural foundation: Python 3.12 FastAPI backend skeleton, SQLAlchemy 2.0 asynchronous database configuration, Alembic migration tooling, containerized PostgreSQL and Redis local environments, and abstract contracts for computer vision and predictive engines.

## Documentation Links

- [System Architecture & Roadmap](docs/ARCHITECTURE.md)
- [Backend Documentation](backend/README.md)
- [Database & Migrations Guide](database/README.md)
- [AI Architecture & Contracts](ai/README.md)
- [Developer Scripts](scripts/README.md)

## Quick Start

The quickest way to bootstrap the development environment, launch local dependencies via Docker Compose, and start the FastAPI backend is using the development script:

```bash
./scripts/dev.sh
```

### Manual Start

1. Start containerized PostgreSQL and Redis:
   ```bash
   docker compose up -d postgres redis
   ```
2. Set up virtual environment and install dependencies:
   ```bash
   cd backend
   python3.12 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   cp .env.example .env
   ```
3. Run database migrations:
   ```bash
   cd ../database
   alembic upgrade head
   ```
4. Start the backend:
   ```bash
   cd ../backend
   uvicorn app.main:app --port 8000 --reload
   ```

5. Verify the service:
   - Health Check: `curl http://localhost:8000/api/v1/health`
   - Version: `curl http://localhost:8000/api/v1/version`
   - Interactive Docs: `http://localhost:8000/docs`
