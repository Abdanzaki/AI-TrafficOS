# AI TrafficOS - Developer Scripts

Automated scripts for local development, environment provisioning, and testing.

## `scripts/dev.sh`

`dev.sh` is the primary local bootstrap script. It executes the following steps:
1. Starts the PostgreSQL container via `docker compose up -d postgres` from the repository root.
2. Creates a Python 3.12 virtual environment at `backend/.venv` if one does not already exist.
3. Activates the environment, upgrades `pip`, and installs dependencies from `backend/requirements.txt`.
4. Copies `backend/.env.example` to `backend/.env` if missing.
5. Launches the Uvicorn development server from `backend/` on port 8000 with auto-reload enabled.

### Usage

From anywhere in the repository:

```bash
./scripts/dev.sh
```

## Manual Alternatives

If you prefer to run steps manually or need isolated control:

### 1. Launch Containers
```bash
docker compose up -d postgres redis
```

### 2. Prepare Virtual Environment
```bash
cd backend
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

### 3. Run Database Migrations
```bash
cd ../database
alembic upgrade head
```

### 4. Run Server
```bash
cd ../backend
uvicorn app.main:app --port 8000 --reload
```
