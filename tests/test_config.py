"""Tests for environment-driven configuration."""

from __future__ import annotations

import pytest

from locusview.config import Settings


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
