"""Tests for environment-driven configuration."""

from __future__ import annotations

import pytest

from locusview.config import DatabaseSettings, Settings, get_db_settings


def test_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LOCUSVIEW_ENV", raising=False)
    # _env_file=None so a developer's local .env can't affect the test.
    settings = Settings(_env_file=None)
    assert settings.env == "development"
    assert settings.log_level == "INFO"
    assert settings.data_dir == "./data"


def test_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOCUSVIEW_ENV", "production")
    settings = Settings(_env_file=None)
    assert settings.env == "production"


def test_db_settings_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    for k in ("LOCUSCOMPARE2_DB_HOST", "LOCUSCOMPARE2_DB_USER", "LOCUSCOMPARE2_DB_NAME"):
        monkeypatch.delenv(k, raising=False)
    s = DatabaseSettings(_env_file=None)
    assert s.name == "colotool"
    assert s.port == 3306
    assert s.user == "locusview_ro"
    assert s.password == ""  # never defaulted to a real secret


def test_get_db_settings_is_cached() -> None:
    assert get_db_settings() is get_db_settings()
