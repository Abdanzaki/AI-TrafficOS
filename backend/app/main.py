"""AI TrafficOS FastAPI application entry point.

Provides the application factory create_app(), lifespan context manager,
CORS middleware, and mounts API v1 routing including WebSocket endpoints.
"""

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import router as v1_router
from app.core.config import settings
from app.core.database import engine


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
        description="Foundation & Architecture backend for AI TrafficOS (Phase 1)",
        version="0.1.0",
        lifespan=lifespan,
    )

    # Configure Cross-Origin Resource Sharing (CORS) middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Mount API v1 router at prefix '/api/v1' (includes WebSocket router at /api/v1/ws)
    app.include_router(v1_router)

    return app


# Module-level application instance for 'uvicorn app.main:app'
app: FastAPI = create_app()
