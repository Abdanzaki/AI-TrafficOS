"""AI TrafficOS FastAPI application entry point.

Provides the application factory create_app(), lifespan context manager,
CORS middleware, and mounts API v1 routing including WebSocket endpoints.
"""

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, HTTPException, Request, WebSocket, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import JSONResponse, RedirectResponse

from app.api.v1.router import router as v1_router
from app.core.config import settings
from app.core.database import engine
from app.core.logging import get_logger, setup_logging

setup_logging()
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Asynchronous lifespan context manager for startup and shutdown events."""
    # Startup: Database engines and connection pools initialized lazily
    yield
    # Shutdown: Cleanly dispose of the async database engine pool
    await engine.dispose()


def create_app() -> FastAPI:
    """Application factory returning a configured FastAPI instance."""
    app = FastAPI(
        title="AI TrafficOS",
        description="Foundation & Architecture backend for AI TrafficOS",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/api/v1/docs",
        openapi_url="/api/v1/openapi.json",
    )


    # Configure Cross-Origin Resource Sharing (CORS) middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Centralized exception handler for validation errors (422)
    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        errors = []
        for err in exc.errors():
            loc = [str(x) for x in err.get("loc", []) if str(x) != "body"]
            field_name = ".".join(loc) if loc else "body"
            errors.append({
                "field": field_name,
                "message": err.get("msg", "Validation error"),
                "type": err.get("type", "value_error"),
            })
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={
                "detail": errors,
                "message": "Request validation failed",
            },
        )

    # Centralized exception handler for unhandled server errors (500)
    @app.exception_handler(Exception)
    async def generic_exception_handler(
        request: Request,
        exc: Exception,
    ) -> JSONResponse:
        if isinstance(exc, (HTTPException, StarletteHTTPException)):
            return JSONResponse(
                status_code=exc.status_code,
                content={"detail": exc.detail},
                headers=getattr(exc, "headers", None),
            )
        logger.error("Unhandled server exception on %s %s: %s", request.method, request.url.path, exc, exc_info=True)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": "Internal server error"},
        )

    # Mount API v1 router at prefix '/api/v1' (includes WebSocket router at /api/v1/ws)
    app.include_router(v1_router)

    # Root Phase 1 aliases for /health, /version, and /ws handshake
    @app.get("/health")
    async def root_health():
        return {
            "status": "ok",
            "service": "ai-trafficos",
            "version": "0.1.0",
        }

    @app.get("/version")
    async def root_version():
        return {
            "service": "ai-trafficos",
            "version": "0.1.0",
        }

    @app.websocket("/ws")
    async def root_ws(websocket: WebSocket):
        await websocket.accept()
        await websocket.send_json(
            {
                "type": "handshake",
                "status": "connected",
                "note": "Phase 1: no live traffic streams yet",
            }
        )
        await websocket.close(code=1000)

    @app.get("/docs", include_in_schema=False)
    async def redirect_docs():
        return RedirectResponse(url="/api/v1/docs")

    return app



# Module-level application instance for 'uvicorn app.main:app'
app: FastAPI = create_app()

