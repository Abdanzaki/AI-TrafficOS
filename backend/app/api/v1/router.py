"""API v1 root router.

Feature routers (detection, signals, prediction, incidents) attach here in later phases.
"""

from typing import Any

from fastapi import APIRouter

from app.api.v1.websocket import router as websocket_router

APP_VERSION: str = "0.1.0"

router = APIRouter(prefix="/api/v1")

# Mount WebSocket router under the v1 prefix (reaches /api/v1/ws)
router.include_router(websocket_router)


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
