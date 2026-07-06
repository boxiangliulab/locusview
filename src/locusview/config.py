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


class DatabaseSettings(BaseSettings):
    """Connection settings for the shared locuscompare2 database (ADR-0008).

    Read from ``LOCUSCOMPARE2_DB_*`` env vars / ``.env``. The password is injected by the
    deployment secret store and must never be committed. locusview connects with a
    least-privilege, read-only account.
    """

    model_config = SettingsConfigDict(
        env_prefix="LOCUSCOMPARE2_DB_",
        env_file=".env",
        extra="ignore",
    )

    host: str = ""
    port: int = 3306
    name: str = "colotool"
    user: str = "locusview_ro"
    password: str = ""
    ssl_mode: str = "REQUIRED"


@lru_cache
def get_db_settings() -> DatabaseSettings:
    """Return the process-wide database settings (cached)."""
    return DatabaseSettings()
