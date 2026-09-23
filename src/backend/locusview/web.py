"""The locusview web application (FastAPI + Jinja2/HTMX).

Only ``GET /health`` lives here; every page/feature (including search-query routing) is a
router in ``routers/`` (one module per feature — see each module's docstring), mounted by
:func:`create_app`. The app is built by a factory that accepts a
:class:`~locusview.requestinfo.QtlRepository` — real in production, fake in tests.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles

from locusview import __version__
from locusview.config import get_pg_settings, get_settings
from locusview.connectpostgres import PostgresQtlRepository, postgres_connection_factory
from locusview.requestinfo import FakeQtlRepository, QtlRepository
from locusview.routers import browser as browser_router
from locusview.routers import comparison as comparison_router
from locusview.routers import gene as gene_router
from locusview.routers import home as home_router
from locusview.routers import locus as locus_router
from locusview.routers import news as news_router
from locusview.routers import search as search_router
from locusview.routers import search_data as search_data_router
from locusview.routers import tutorial as tutorial_router

# static/ lives in the sibling frontend/ folder (src/backend/locusview/web.py -> src/backend/
# -> src/ -> src/frontend/static), not inside this package — see docs/process/status.md's
# frontend/backend split note. Both local dev (uv run) and the Docker image (which COPYs the
# whole repo, not just a built wheel) run from the full source tree, so this relative walk-up
# always resolves; there's no standalone-wheel-only deployment of this app today.
_STATIC_DIR = Path(__file__).resolve().parents[2] / "frontend" / "static"


def _default_repository() -> QtlRepository:
    """Pick a repository from config: the real (Postgres) DB if configured, else an empty fake.

    The legacy MySQL ``LocuscompareRepository`` path is commented out in requestinfo.py — see its
    module docstring — so there's currently no fallback to it here even if you wanted one.
    """
    if get_pg_settings().host:  # pragma: no cover - requires DB config + network
        return PostgresQtlRepository(postgres_connection_factory())
    return FakeQtlRepository()


def create_app(repository: QtlRepository | None = None) -> FastAPI:
    """Build and return the locusview FastAPI application."""
    repo = repository if repository is not None else _default_repository()
    app = FastAPI(title="locusview", version=__version__)
    # Search data's fully expanded tables are large and very repetitive HTML (a well-studied
    # variant is ~35k rows / ~12 MB raw); gzip shrinks that by an order of magnitude.
    app.add_middleware(GZipMiddleware, minimum_size=1024)
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")
    app.include_router(home_router.router(repo))
    app.include_router(news_router.router(repo))
    app.include_router(tutorial_router.router(repo))
    app.include_router(gene_router.router(repo))
    app.include_router(locus_router.router(repo))
    app.include_router(browser_router.router(repo))
    app.include_router(comparison_router.router(repo))
    app.include_router(search_router.router(repo))
    app.include_router(search_data_router.router(repo))

    @app.get("/health")
    def health() -> dict[str, str]:
        """Liveness/readiness probe. Returns app status, version, and environment."""
        return {"status": "ok", "version": __version__, "env": get_settings().env}

    return app
