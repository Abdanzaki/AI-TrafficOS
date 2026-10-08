"""Application configuration module.

Loads environment variables from backend/.env using pydantic-settings.
Provides production defaults for Phase 1 architecture foundation.
"""

import json
from pathlib import Path
from typing import Any, Optional, Union

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Resolve path to backend/.env relative to this file (backend/app/core/config.py)
BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
ENV_FILE_PATH = BACKEND_DIR / ".env"


class Settings(BaseSettings):
    """Application settings and configuration parameters."""

    DATABASE_URL: str = "postgresql+asyncpg://trafficos:trafficos@localhost:5432/trafficos"
    REDIS_URL: str = "redis://localhost:6379/0"
    ENV: str = "development"
    CORS_ORIGINS: list[str] = ["http://localhost:3000"]
    SECRET_KEY: str = "dev-secret-key-change-in-production-trafficos-2026"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # AI Assistant Configuration (Phase 9 Stage 4)
    ASSISTANT_LLM_PROVIDER: str = "deterministic"
    ASSISTANT_LLM_API_KEY: Optional[str] = None

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def assemble_cors_origins(cls, value: Union[str, list[Any]]) -> list[str]:
        """Parse CORS_ORIGINS from JSON string, comma-separated string, or list."""
        if isinstance(value, str):
            value = value.strip()
            if value.startswith("[") and value.endswith("]"):
                try:
                    parsed = json.loads(value)
                    if isinstance(parsed, list):
                        return [str(item).strip() for item in parsed]
                except json.JSONDecodeError:
                    pass
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        if isinstance(value, list):
            return [str(item).strip() for item in value]
        return ["http://localhost:3000"]

    model_config = SettingsConfigDict(
        env_file=ENV_FILE_PATH,
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=True,
    )


# Exported module-level singleton instance
settings = Settings()
