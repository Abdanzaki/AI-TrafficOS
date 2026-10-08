"""WebSocket endpoints for API v1 and Phase 9 Real-Time Streaming.

Architectural Design & Routing Decisions
-----------------------------------------
1. Deprecation Strategy for Legacy `/api/v1/ws` Alias:
   - In Phase 1, `/api/v1/ws` existed as an unauthenticated static handshake skeleton.
   - Design Decision: We KEEP `/api/v1/ws` as a backward-compatible deprecated alias rather
     than removing it. Frontend dashboard components (Phase 7 web), mobile apps (Phase 8),
     and automated test suites may retain references to `/api/v1/ws`.
   - Behavior:
     a) Unauthenticated Legacy Callers: If connected without a `?token=` parameter, the endpoint
        maintains Phase 1 compatibility by emitting the static handshake:
        `{"type": "handshake", "status": "connected", "note": "Phase 1: no live traffic streams yet"}`
        and closing politely with code 1000.
     b) Authenticated Phase 9 Callers: If connected with a valid `?token=<access_token>`, the endpoint
        authenticates, activates the full Phase 9 real-time fan-out stream, and appends a deprecation
        notice in the handshake payload (`"deprecated": True`, `"note": "Use /ws/v1/stream instead"`).

2. Primary Streaming Endpoint (`/ws/v1/stream`):
   - Defined at root level in `app.main` as `/ws/v1/stream`.
   - Requires valid JWT via query parameter `?token=<jwt>`.
   - Rejects unauthenticated connections with code 4401 before accepting.

3. Authentication Decision: Query Parameter vs. Subprotocol
   - Standard browser JavaScript WebSocket constructors (`new WebSocket(url)`) do NOT permit
     custom HTTP headers like `Authorization: Bearer <token>`.
   - The alternative `Sec-WebSocket-Protocol` subprotocol header was evaluated and rejected:
     subprotocols are designed for application protocol negotiation (e.g. 'soap', 'wamp'),
     encode token punctuation that breaks strict proxy parsing, leak credentials in the
     response handshake, and lack cross-platform client ergonomic consistency.
   - Query parameter `?token=<access_token>` is universally compatible across all web and mobile
     clients and is encrypted over TLS (WSS).
"""

from fastapi import APIRouter, WebSocket

from app.realtime.stream import handle_websocket_stream

router = APIRouter()


@router.websocket("/ws")
async def websocket_deprecated_endpoint(websocket: WebSocket) -> None:
    """Deprecated WebSocket alias for /ws/v1/stream.

    Maintains backwards compatibility for Phase 1 unauthenticated regression tests,
    while servicing authenticated clients with full Phase 9 streaming plus deprecation notice.
    """
    await handle_websocket_stream(websocket, is_deprecated=True)
