"""Database session and engine management.

Provides SQLAlchemy 2.0 async engine, sessionmaker, declarative Base,
and the get_db dependency yielding AsyncSession.
"""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from sqlalchemy.engine import make_url

from app.core.config import settings


def translate_database_url(url: str) -> str:
    """Translate standard PostgreSQL URL to an asyncpg-compatible URL.

    - Rewrites driver from 'postgres' or 'postgresql' to 'postgresql+asyncpg'.
    - Translates libpq-style 'sslmode' query parameters to asyncpg's 'ssl' parameter
      (e.g., 'sslmode=require' -> 'ssl=require'). If 'sslmode=disable', removes SSL.
    - Strips 'channel_binding' query parameter which is unsupported by asyncpg.
    - Preserves non-Postgres URLs (e.g. SQLite).
    """
    if not url:
        return url

    db_url = make_url(url)
    drivername = db_url.drivername
    if drivername in ("postgres", "postgresql"):
        drivername = "postgresql+asyncpg"

    query = dict(db_url.query)
    if "sslmode" in query:
        sslmode_val = query.pop("sslmode")
        if sslmode_val.lower() in ("disable", "false", "0"):
            query.pop("ssl", None)
        else:
            query["ssl"] = sslmode_val

    query.pop("channel_binding", None)

    translated = db_url.set(drivername=drivername, query=query)
    return translated.render_as_string(hide_password=False)


# Alias for backward-compatibility or alternate naming conventions
translate_db_url = translate_database_url


# Create asynchronous engine using asyncpg driver with translated URL
engine = create_async_engine(
    translate_database_url(settings.DATABASE_URL),
    echo=(settings.ENV == "development"),
    future=True,
)

# Async session factory
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


class Base(DeclarativeBase):
    """Declarative Base class for all SQLAlchemy models."""
    pass


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency yielding an async database session."""
    async with AsyncSessionLocal() as session:
        yield session

