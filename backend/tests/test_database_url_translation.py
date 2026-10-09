"""Tests for database URL translation, Neon SSL mode, and asyncpg compatibility."""

from unittest.mock import patch
import pytest
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.database import translate_database_url, translate_db_url


def test_neon_standard_url_translation():
    """Verify standard Neon PostgreSQL URL with ?sslmode=require is translated for asyncpg."""
    neon_url = "postgresql://neondb_owner:npg_abc123@ep-divine-sky-a5678.us-east-2.aws.neon.tech/neondb?sslmode=require"
    translated = translate_database_url(neon_url)

    assert translated.startswith("postgresql+asyncpg://")
    assert "ssl=require" in translated
    assert "sslmode" not in translated
    url_obj = make_url(translated)
    assert url_obj.query.get("ssl") == "require"
    assert "sslmode" not in url_obj.query


def test_neon_pooled_url_with_channel_binding():
    """Verify Neon pooled connection string strips channel_binding and translates sslmode."""
    pooled_url = (
        "postgresql://user:secret_pass@ep-divine-sky-a5678-pooler.us-east-2.aws.neon.tech/neondb"
        "?sslmode=require&channel_binding=require"
    )
    translated = translate_database_url(pooled_url)

    assert translated.startswith("postgresql+asyncpg://")
    assert "ssl=require" in translated
    assert "sslmode" not in translated
    assert "channel_binding" not in translated

    url_obj = make_url(translated)
    assert url_obj.query.get("ssl") == "require"
    assert "channel_binding" not in url_obj.query


def test_legacy_postgres_scheme():
    """Verify legacy postgres:// scheme is upgraded to postgresql+asyncpg://."""
    legacy_url = "postgres://trafficos:mypass@ep-test.neon.tech/trafficos?sslmode=require"
    translated = translate_database_url(legacy_url)

    assert translated.startswith("postgresql+asyncpg://")
    assert "ssl=require" in translated
    assert "sslmode" not in translated


def test_already_asyncpg_scheme():
    """Verify URL already specifying postgresql+asyncpg retains the scheme and translates params."""
    async_url = "postgresql+asyncpg://user:pass@ep-test.neon.tech/neondb?sslmode=require"
    translated = translate_database_url(async_url)

    assert translated.startswith("postgresql+asyncpg://")
    url_obj = make_url(translated)
    assert url_obj.query.get("ssl") == "require"
    assert "sslmode" not in url_obj.query


def test_local_dev_url_unchanged():
    """Verify standard local development connection string without SSL is preserved."""
    local_url = "postgresql+asyncpg://trafficos:trafficos@localhost:5432/trafficos"
    translated = translate_database_url(local_url)

    assert translated == local_url


def test_sslmode_disable_removes_ssl():
    """Verify sslmode=disable strips ssl parameters cleanly."""
    disabled_url = "postgresql://user:pass@localhost:5432/trafficos?sslmode=disable"
    translated = translate_database_url(disabled_url)

    assert translated.startswith("postgresql+asyncpg://")
    url_obj = make_url(translated)
    assert "ssl" not in url_obj.query
    assert "sslmode" not in url_obj.query


def test_preserves_additional_query_params():
    """Verify other connection query parameters like application_name are preserved."""
    complex_url = (
        "postgresql://user:pass@host.internal:5432/trafficos"
        "?sslmode=require&application_name=trafficos_backend"
    )
    translated = translate_database_url(complex_url)

    url_obj = make_url(translated)
    assert url_obj.query.get("ssl") == "require"
    assert url_obj.query.get("application_name") == "trafficos_backend"
    assert "sslmode" not in url_obj.query


def test_preserves_sqlite_urls():
    """Verify non-PostgreSQL URLs such as SQLite are left unmodified."""
    sqlite_url = "sqlite+aiosqlite:///./trafficos_test.db"
    assert translate_database_url(sqlite_url) == sqlite_url


def test_empty_or_none_url():
    """Verify empty or None values return safely."""
    assert translate_database_url("") == ""
    assert translate_database_url(None) is None


def test_translate_db_url_alias():
    """Verify translate_db_url alias works identically."""
    assert translate_db_url == translate_database_url


@pytest.mark.anyio
async def test_engine_connect_args_accepted_by_asyncpg():
    """Verify that create_async_engine with the translated URL passes ssl='require' to asyncpg without TypeError."""
    neon_url = "postgresql://user:secret@ep-demo-123.neon.tech/neondb?sslmode=require&channel_binding=require"
    translated = translate_database_url(neon_url)

    engine = create_async_engine(translated)
    captured_kwargs = {}

    with patch("asyncpg.connect") as mock_connect:
        async def fake_connect(*args, **kwargs):
            captured_kwargs.update(kwargs)
            raise ConnectionRefusedError("Simulated connection termination")

        mock_connect.side_effect = fake_connect

        with pytest.raises(Exception):
            async with engine.connect():
                pass

    # Ensure asyncpg was invoked with ssl='require', and NOT rejected with sslmode or channel_binding
    assert captured_kwargs.get("ssl") == "require"
    assert "sslmode" not in captured_kwargs
    assert "channel_binding" not in captured_kwargs
