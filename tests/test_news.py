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
    assert "Regional plot with LD-based coloring" in response.text


def test_news_marks_upcoming_entries() -> None:
    response = client.get("/news")
    assert 'class="news-entry upcoming"' in response.text
    assert "Tissue body map" in response.text


def test_news_nav_marks_news_active() -> None:
    response = client.get("/news")
    assert 'href="/news" class="active"' in response.text
