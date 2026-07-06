"""Tests for the Phase-0 CLI placeholder — proves the console script is wired up."""

from __future__ import annotations

import pytest

from locusview.cli import main


def test_cli_runs_and_reports_phase(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main([])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "Phase 0" in captured.out


def test_cli_version_flag_exits_zero(capsys: pytest.CaptureFixture[str]) -> None:
    # argparse's `version` action prints and raises SystemExit(0).
    with pytest.raises(SystemExit) as excinfo:
        main(["--version"])
    assert excinfo.value.code == 0
    assert "locusview" in capsys.readouterr().out


def test_cli_serve_dispatches(monkeypatch: pytest.MonkeyPatch) -> None:
    # Verify `serve` routing + arg parsing without actually starting uvicorn.
    called: dict[str, object] = {}

    def fake_serve(host: str, port: int) -> int:
        called["host"], called["port"] = host, port
        return 0

    monkeypatch.setattr("locusview.cli._serve", fake_serve)
    assert main(["serve", "--host", "0.0.0.0", "--port", "9999"]) == 0
    assert called == {"host": "0.0.0.0", "port": 9999}
