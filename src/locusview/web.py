"""The locusview web application (FastAPI + Jinja2/HTMX).

Phase-0/1 skeleton: a health endpoint and a landing page. Data-backed routes
(search, gene page, variant page) arrive once the data layer exists — see the
roadmap and the open issues.

The app is built by a factory (:func:`create_app`) so tests can instantiate a
fresh instance, and so configuration is read at construction time.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from jinja2 import Environment, FileSystemLoader, select_autoescape

from locusview import __version__
from locusview.config import get_settings

_TEMPLATES = Environment(
    loader=FileSystemLoader(str(Path(__file__).parent / "templates")),
    autoescape=select_autoescape(),
)


def create_app() -> FastAPI:
    """Build and return the locusview FastAPI application."""
    app = FastAPI(title="locusview", version=__version__)

    @app.get("/health")
    def health() -> dict[str, str]:
        """Liveness/readiness probe. Returns app status, version, and environment."""
        return {"status": "ok", "version": __version__, "env": get_settings().env}

    @app.get("/", response_class=HTMLResponse)
    def index() -> HTMLResponse:
        """Landing page (placeholder until search/browse routes land)."""
        html = _TEMPLATES.get_template("index.html").render(version=__version__)
        return HTMLResponse(html)

    return app
