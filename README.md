# AI TrafficOS

AI-powered intelligent traffic management platform — **live in production**.

- **Live demo:** https://ai-traffic-os-indol.vercel.app
- **API:** https://ai-trafficos-api.onrender.com
- **Android app:** APK in [GitHub release v1.0.0](https://github.com/Abdanzaki/AI-TrafficOS/releases)

## What this is

A complete, production-deployed traffic management system built in 11 phases:
Next.js web app (Vercel), Flutter Android app, FastAPI + PostgreSQL 18 backend
(Render + Neon), with role-based JWT auth (admin / traffic officer / analyst / citizen)
and 8 applied database migrations.

## Highlights

- Dijkstra + A* routing with traffic-aware costs; heap-based emergency dispatch with
  green-corridor orchestration
- CV-based violation detection (red-light / wrong-way / no-helmet) and crash
  auto-detection with control-room alerts
- LSTM traffic-flow forecasting with uncertainty bands, signal health scoring,
  daily traffic briefs, event demand forecasting
- Grounded Gemini-powered traffic assistant, citizen chatbot (allowlisted tools,
  graceful refusal), and voice interface
- Live TomTom traffic-flow tiles on the Hyderabad map

## Honest notes

- The map runs on a clearly labeled demo dataset (10 Hyderabad intersections) unless
  the TomTom live feed is enabled — built for demos, not real enforcement data.
- The civic theme (including the Telangana Police–style shield) is a design choice,
  not an official partnership.

**Tests:** 387 backend · 138/138 web (Vitest) · 143/143 Flutter — all green.

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
