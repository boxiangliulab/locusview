"""Application configuration, loaded from the environment (12-Factor).

Config lives in environment variables (or a local ``.env`` file), never in source.
Copy ``.env.example`` to ``.env`` to override defaults locally. All variables use the
``LOCUSVIEW_`` prefix, e.g. ``LOCUSVIEW_ENV=production``.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed application settings, read from ``LOCUSVIEW_*`` env vars / ``.env``."""

    model_config = SettingsConfigDict(
        env_prefix="LOCUSVIEW_",
        env_file=".env",
        extra="ignore",
    )

    env: str = "development"  # development | production
    log_level: str = "INFO"
    data_dir: str = "./data"


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings (cached)."""
    return Settings()
