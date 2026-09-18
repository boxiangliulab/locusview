"""Shared Jinja2 environment for all routers.

One :class:`~jinja2.Environment` for the whole app (HTML templates live in the sibling
``frontend/displays/`` folder, not inside this package — see ``web.py``'s ``_STATIC_DIR`` comment
for why that's safe), so every router renders through the same autoescaping config and the same
``_render`` helper instead of each module standing up its own.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.responses import HTMLResponse
from jinja2 import Environment, FileSystemLoader, select_autoescape

from locusview import __version__

_TEMPLATES_DIR = Path(__file__).resolve().parents[2] / "frontend" / "displays"
_STATIC_DIR = Path(__file__).resolve().parents[2] / "frontend" / "static"

TEMPLATES = Environment(
    loader=FileSystemLoader(str(_TEMPLATES_DIR)),
    autoescape=select_autoescape(),
)


def asset(path: str) -> str:
    """Return the URL for a ``static/`` file, stamped with its modification time.

    Templates call this instead of hard-coding ``/static/...``. Starlette's ``StaticFiles`` sends
    an ETag but no ``Cache-Control``, so browsers fall back to *heuristic* caching: a JS/CSS file
    that was already a few days old when the page loaded stays "fresh" for hours and the browser
    won't even revalidate it — editing the file server-side then has no visible effect until a
    hard refresh. The ``?v=<mtime>`` stamp changes the URL whenever the file changes, so a new
    build is always a cache miss and an unchanged one still gets served from cache.
    """
    try:
        stamp = int((_STATIC_DIR / path).stat().st_mtime)
    except OSError:  # missing asset — still emit the URL so the 404 is visible, don't fail the page
        stamp = 0
    return f"/static/{path}?v={stamp}"


TEMPLATES.globals["asset"] = asset


def render(template: str, status_code: int = 200, **context: object) -> HTMLResponse:
    """Render a template with the app version in scope and wrap it in an ``HTMLResponse``."""
    html = TEMPLATES.get_template(template).render(version=__version__, **context)
    return HTMLResponse(html, status_code=status_code)
