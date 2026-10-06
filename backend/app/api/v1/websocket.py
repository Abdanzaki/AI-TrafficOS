"""WebSocket endpoints for API v1.

Phase 1 provides connection verification and initial handshake only.
Streaming traffic feeds, real-time vehicle detections, and signal telemetry
will be implemented in Phase 4 and Phase 6.
"""

from fastapi import APIRouter, WebSocket

router = APIRouter()


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    """Accept connection, transmit Phase 1 handshake payload, and close politely."""
    await websocket.accept()
    await websocket.send_json(
        {
            "type": "handshake",
            "status": "connected",
            "note": "Phase 1: no live traffic streams yet",
        }
    )
    await websocket.close(code=1000)
