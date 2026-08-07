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

TEMPLATES = Environment(
    loader=FileSystemLoader(str(_TEMPLATES_DIR)),
    autoescape=select_autoescape(),
)


def render(template: str, status_code: int = 200, **context: object) -> HTMLResponse:
    """Render a template with the app version in scope and wrap it in an ``HTMLResponse``."""
    html = TEMPLATES.get_template(template).render(version=__version__, **context)
    return HTMLResponse(html, status_code=status_code)
