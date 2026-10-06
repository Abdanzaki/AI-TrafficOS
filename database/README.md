# AI TrafficOS - Database & Migrations

Database management and asynchronous schema migrations for AI TrafficOS using Alembic and SQLAlchemy 2.0.

## Database Services (Docker Compose)

PostgreSQL 16 and Redis 7 are managed via the root `docker-compose.yml`:

```bash
# Start PostgreSQL service in background
docker compose up -d postgres

# Start Redis service in background
docker compose up -d redis

# Verify running services
docker compose ps
```

The PostgreSQL instance is preconfigured with:
- Database: `trafficos`
- User: `trafficos`
- Password: `trafficos`
- Port: `5432`

## Schema Migrations with Alembic

Alembic is configured for asynchronous database operations using `asyncpg` via `alembic/env.py`.

### Running Migrations

Ensure your virtual environment is active and dependencies are installed (`pip install -r backend/requirements.txt`).

From the `database/` directory:

```bash
# Apply all pending migrations to head
alembic upgrade head

# Rollback the most recent migration
alembic downgrade -1
```

From the `backend/` directory:

```bash
# Apply migrations specifying config location
alembic -c ../database/alembic.ini upgrade head
```

Or from the repository root:

```bash
alembic -c database/alembic.ini upgrade head
```

### Initial Schema (Revision `0001`)

The initial migration creates the foundational tables:
1. `intersections`: Core intersection entity with coordinates and indexed name.
2. `signal_phases`: Traffic signal phases (placeholder for Phase 6 control algorithms).
3. `vehicle_events`: Vehicle detection events (placeholder for Phase 4 CV telemetry).
4. `incidents`: Safety incident logging (placeholder for Phase 4/5 event management).

### Creating New Migrations

To generate a new auto-detected migration after modifying models in `backend/app/models/`:

```bash
cd database
alembic revision --autogenerate -m "describe_changes"
```
