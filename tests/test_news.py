"""Tests for the News page (routers/news.py)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from locusview.requestinfo import FakeQtlRepository
from locusview.web import create_app

# News never touches the repository, but pass one explicitly anyway — a bare create_app() falls
# back to _default_repository(), which reads real DB settings from .env if present (non-hermetic).
client = TestClient(create_app(repository=FakeQtlRepository()))


def test_news_renders_entries() -> None:
    response = client.get("/news")
    assert response.status_code == 200
    assert "News" in response.text
    assert "Search data links to LocusZoom plots" in response.text
    assert "Browse tissues and the expanded QTL catalogue" in response.text


def test_news_has_no_stale_upcoming_body_map() -> None:
    response = client.get("/news")
    assert 'class="news-entry upcoming"' not in response.text
    assert "Upcoming" not in response.text


def test_news_nav_marks_news_active() -> None:
    response = client.get("/news")
    assert 'href="/news" class="active"' in response.text
