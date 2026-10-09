"""News page: release notes. Purely static content, no database access."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from locusview.content.news import NEWS
from locusview.requestinfo import QtlRepository
from locusview.templating import render as _render


def router(_repo: QtlRepository) -> APIRouter:
    """``_repo`` is unused (News is static content) but kept for a uniform factory signature."""
    router = APIRouter()

    @router.get("/news", response_class=HTMLResponse)
    def news() -> HTMLResponse:
        """Render the News page from the static :data:`NEWS` list."""
        return _render("news.html", active="news", entries=NEWS)

    return router
