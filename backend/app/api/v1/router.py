"""API v1 root router.

Feature routers (detection, signals, prediction, incidents) attach here in later phases.
"""

from typing import Any

from fastapi import APIRouter

from app.api.v1.ai_decisions import router as ai_decisions_router
from app.api.v1.ai_predictions import router as ai_predictions_router
from app.api.v1.analytics import router as analytics_router
from app.api.v1.audit import router as audit_router
from app.api.v1.auth import router as auth_router
from app.api.v1.emergency_events import router as emergency_events_router
from app.api.v1.incidents import router as incidents_router
from app.api.v1.intersections import router as intersections_router
from app.api.v1.lanes import router as lanes_router
from app.api.v1.notifications import router as notifications_router
from app.api.v1.roads import router as roads_router
from app.api.v1.routing import router as routing_router
from app.api.v1.signals import phases_router, router as signals_router
from app.api.v1.traffic_records import router as traffic_records_router
from app.api.v1.users import router as users_router
from app.api.v1.vehicle_events import router as vehicle_events_router
from app.api.v1.vision import router as vision_router
from app.api.v1.websocket import router as websocket_router

APP_VERSION: str = "0.1.0"

router = APIRouter(prefix="/api/v1")

# Mount WebSocket router under the v1 prefix (reaches /api/v1/ws)
router.include_router(websocket_router)

# Mount Auth and Users routers under v1 prefix
router.include_router(auth_router)
router.include_router(users_router)

# Mount domain REST routers under v1 prefix
router.include_router(intersections_router)
router.include_router(roads_router)
router.include_router(lanes_router)
router.include_router(signals_router)
router.include_router(phases_router)

# Mount event and telemetry routers under v1 prefix
router.include_router(vehicle_events_router)
router.include_router(incidents_router)
router.include_router(emergency_events_router)
router.include_router(traffic_records_router)
router.include_router(notifications_router)

# Mount AI records, analytics, and audit routers under v1 prefix
router.include_router(ai_predictions_router)
router.include_router(ai_decisions_router)
router.include_router(analytics_router)
router.include_router(audit_router)

# Mount routing services router under v1 prefix
router.include_router(routing_router)

# Mount vision router under v1 prefix
router.include_router(vision_router)


@router.get("/health")
async def health() -> dict[str, Any]:
    """Health check endpoint returning exact service status and version."""
    return {
        "status": "ok",
        "service": "ai-trafficos",
        "version": APP_VERSION,
    }


@router.get("/version")
async def version() -> dict[str, str]:
    """Service version endpoint."""
    return {
        "service": "ai-trafficos",
        "version": APP_VERSION,
    }
