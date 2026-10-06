#!/usr/bin/env bash
set -euo pipefail

# AI TrafficOS - Local Development Bootstrap Script (Phase 1)
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="${REPO_ROOT}/backend"
VENV_DIR="${BACKEND_DIR}/.venv"

echo "=== AI TrafficOS: Starting Phase 1 Development Environment ==="

# 1. Start postgres via docker compose from repository root
echo "[1/4] Starting PostgreSQL container..."
cd "${REPO_ROOT}"
docker compose up -d postgres

# 2. Check and initialize virtual environment if missing
echo "[2/4] Verifying Python 3.12 virtual environment..."
if [ ! -d "${VENV_DIR}" ]; then
    echo "Creating virtual environment at ${VENV_DIR} using python3.12..."
    python3.12 -m venv "${VENV_DIR}"
fi

# Activate virtual environment
source "${VENV_DIR}/bin/activate"

# 3. Ensure dependencies are installed
echo "[3/4] Installing backend dependencies..."
pip install --upgrade pip
pip install -r "${BACKEND_DIR}/requirements.txt"

# Ensure local .env exists
if [ ! -f "${BACKEND_DIR}/.env" ]; then
    echo "Creating .env from .env.example..."
    cp "${BACKEND_DIR}/.env.example" "${BACKEND_DIR}/.env"
fi

# 4. Run uvicorn server from backend/ directory
echo "[4/4] Starting FastAPI server on port 8000..."
cd "${BACKEND_DIR}"
exec uvicorn app.main:app --port 8000 --reload
