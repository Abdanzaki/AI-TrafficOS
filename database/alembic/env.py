"""Alembic async environment configuration for AI TrafficOS."""

import asyncio
import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

# Ensure backend/ is in sys.path to import application configuration and models
BASE_DIR = Path(__file__).resolve().parent.parent.parent
BACKEND_DIR = BASE_DIR / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# Import settings and metadata from backend app
try:
    from app.core.config import settings
    DATABASE_URL = settings.DATABASE_URL
except Exception:
    DATABASE_URL = os.getenv(
        "DATABASE_URL",
        "postgresql+asyncpg://trafficos:trafficos@localhost:5432/trafficos",
    )

try:
    from app.core.database import translate_database_url
    DATABASE_URL = translate_database_url(DATABASE_URL)
except Exception:
    try:
        from sqlalchemy.engine import make_url

        db_url = make_url(DATABASE_URL)
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
        DATABASE_URL = db_url.set(drivername=drivername, query=query).render_as_string(hide_password=False)
    except Exception:
        pass

from app.models import Base  # noqa: E402

# Alembic Config object
config = context.config

# Interpret the config file for Python logging
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Set database URL dynamically
config.set_main_option("sqlalchemy.url", DATABASE_URL)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    Configures the context with just a URL and not an Engine, though an Engine is acceptable
    here as well. By skipping the Engine creation we don't even need a DBAPI to be available.
    """
    url = config.get_main_option("sqlalchemy.url", DATABASE_URL)
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """Synchronous callback executing migration context."""
    context.configure(connection=connection, target_metadata=target_metadata)

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Run migrations in 'online' mode using an async engine."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
