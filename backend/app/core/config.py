"""Application configuration module.

Loads environment variables from backend/.env using pydantic-settings.
Provides production defaults for Phase 1 architecture foundation.
"""

import json
from pathlib import Path
from typing import Any, Optional, Union
import warnings

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Resolve path to backend/.env relative to this file (backend/app/core/config.py)
BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
ENV_FILE_PATH = BACKEND_DIR / ".env"

DEV_DEFAULT_SECRET_KEY = "dev-secret-key-change-in-production-trafficos-2026"
INSECURE_SECRET_KEYS = {
    DEV_DEFAULT_SECRET_KEY,
    "change-this-to-a-secure-random-secret-key-in-production",
    "secret",
    "changeme",
}


class Settings(BaseSettings):
    """Application settings and configuration parameters."""

    DATABASE_URL: str = "postgresql+asyncpg://trafficos:trafficos@localhost:5432/trafficos"
    REDIS_URL: str = "redis://localhost:6379/0"
    ENV: str = "development"
    CORS_ORIGINS: list[str] = ["http://localhost:3000"]
    SECRET_KEY: Optional[str] = None
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # Physical Signal Controller Guard (Phase 11: Hardware integration is disabled / simulation only)
    SIGNAL_HARDWARE_ENABLED: bool = False

    # Rate Limiting Configuration (Phase 11)
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_AUTH_PER_MINUTE: int = 60
    RATE_LIMIT_EXPENSIVE_PER_MINUTE: int = 60

    # AI Assistant Configuration (Phase 9 Stage 4 & Batch 1)
    ASSISTANT_LLM_PROVIDER: str = "deterministic"
    ASSISTANT_LLM_API_KEY: Optional[str] = None
    GEMINI_API_KEY: Optional[str] = None
    # Google Gemini model ID for generateContent v1beta REST API.
    # As of late 2026 (per Google AI for Developers documentation at https://ai.google.dev/gemini-api/docs/models):
    # - "gemini-3.8-flash" is the verified stable Flash model for new projects and newly created API keys.
    # - "gemini-3.5-flash-lite" is the verified ultra-fast, budget-friendly high-throughput Flash model.
    # - Note on legacy models: "gemini-2.0-flash" is shut down; "gemini-2.5-flash" is restricted to legacy accounts.
    # Note: If testing against mock environments or older deployments, override via GEMINI_MODEL="gemini-2.0-flash".
    GEMINI_MODEL: str = "gemini-3.8-flash"

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

    @model_validator(mode="after")
    def validate_security_settings(self) -> "Settings":
        """Validate production security invariants.
        
        Enforces fail-fast startup when ENV=production:
        - SECRET_KEY must come exclusively from environment (no default/placeholder, min 32 chars).
        - CORS_ORIGINS must be explicitly configured and cannot contain wildcards ('*') or localhost defaults.
        In development/test, warns loudly if SECRET_KEY is missing or insecure and uses dev fallback.
        """
        is_production = self.ENV.lower() in ("production", "prod")

        if is_production:
            # 1. SECRET_KEY fail-fast enforcement
            if not self.SECRET_KEY or self.SECRET_KEY in INSECURE_SECRET_KEYS:
                raise ValueError(
                    "FATAL SECURITY CONFIGURATION ERROR: In production (ENV=production), "
                    "SECRET_KEY must be explicitly set from the environment to a secure random key. "
                    "Using default or placeholder SECRET_KEY is prohibited."
                )
            if len(self.SECRET_KEY) < 32:
                raise ValueError(
                    "FATAL SECURITY CONFIGURATION ERROR: SECRET_KEY must be at least 32 characters in production."
                )

            # 2. CORS_ORIGINS fail-fast enforcement
            if "*" in self.CORS_ORIGINS:
                raise ValueError(
                    "FATAL SECURITY CONFIGURATION ERROR: Wildcard '*' CORS origin is strictly prohibited in production."
                )
            if set(self.CORS_ORIGINS) == {"http://localhost:3000"}:
                raise ValueError(
                    "FATAL SECURITY CONFIGURATION ERROR: In production (ENV=production), "
                    "CORS_ORIGINS must be explicitly configured with production frontend domains. "
                    "Default localhost origin cannot be used."
                )
        else:
            if not self.SECRET_KEY or self.SECRET_KEY in INSECURE_SECRET_KEYS:
                warnings.warn(
                    "SECURITY WARNING: SECRET_KEY is unset or using an insecure development default. "
                    "Ensure a strong, unique SECRET_KEY is configured in production.",
                    RuntimeWarning,
                    stacklevel=2,
                )
                if not self.SECRET_KEY:
                    self.SECRET_KEY = DEV_DEFAULT_SECRET_KEY

        return self

    model_config = SettingsConfigDict(
        env_file=ENV_FILE_PATH,
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=True,
    )


# Exported module-level singleton instance
settings = Settings()
