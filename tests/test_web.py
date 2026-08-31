"""Tests for the web application skeleton: health check, and search-query routing.

Feature-specific tests live alongside their router: see test_home.py, test_news.py, test_gene.py,
test_locus.py.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from locusview import __version__
from locusview.requestinfo import FakeQtlRepository, Gene
from locusview.templating import asset
from locusview.web import create_app

# Always pass an explicit repository — a bare create_app() falls back to _default_repository(),
# which reads real DB settings from .env if present, making tests non-hermetic (and, worse,
# network-dependent: they'd hang/fail if that host isn't reachable from wherever tests run).
client = TestClient(create_app(repository=FakeQtlRepository()))


def _gene_client() -> TestClient:
    repo = FakeQtlRepository(genes=[Gene(141510, "TP53", "ENSG00000141510.16", "17", 1, 2, "-")])
    return TestClient(create_app(repository=repo))


def test_health_returns_ok() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["version"] == __version__
    assert "env" in body


def test_index_renders_landing_page() -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "locusview" in response.text.lower()
    assert __version__ in response.text
    assert "Available QTL datasets" in response.text


def test_search_redirects_a_gene_symbol_to_browser() -> None:
    response = _gene_client().get("/search", params={"q": "TP53"}, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/browser?locus_mode=gene&gene=TP53"


def test_search_redirects_an_ensembl_id_to_browser() -> None:
    response = _gene_client().get(
        "/search", params={"q": "ENSG00000141510"}, follow_redirects=False
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/browser?locus_mode=gene&gene=ENSG00000141510"


def test_search_redirects_an_rsid_to_browser_variant_mode() -> None:
    response = client.get("/search", params={"q": "rs12345"}, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/browser?locus_mode=variant&variant=rs12345"


def test_search_redirects_a_bare_variant_to_browser_variant_mode() -> None:
    response = client.get("/search", params={"q": "chr17:7670000"}, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/browser?locus_mode=variant&variant=chr17%3A7670000"


def test_search_redirects_a_region_to_browser_region_mode() -> None:
    response = client.get(
        "/search", params={"q": "chr17:7660000-7690000"}, follow_redirects=False
    )
    assert response.status_code == 303
    assert response.headers["location"] == (
        "/browser?locus_mode=region&region=chr17%3A7660000-7690000"
    )


def test_search_unsupported_query_is_404() -> None:
    response = client.get("/search", params={"q": "???"}, follow_redirects=False)
    assert response.status_code == 404
    assert "gene, region, or variant" in response.text.lower()


# ── static-asset cache busting (templating.asset) ─────────────────────────────


def test_asset_urls_carry_a_modification_time_stamp() -> None:
    """Every static URL is ?v=<mtime>-stamped so an edited JS/CSS file can't be served from a
    browser's heuristic cache (StaticFiles sends no Cache-Control) — see templating.asset."""
    url = asset("js/plot-download.js")
    assert url.startswith("/static/js/plot-download.js?v=")
    assert int(url.rsplit("=", 1)[1]) > 0


def test_asset_url_for_a_missing_file_still_renders() -> None:
    """A typo'd asset name must 404 loudly in the browser, not blow up the whole page render."""
    assert asset("js/nope.js") == "/static/js/nope.js?v=0"


def test_pages_reference_stamped_asset_urls() -> None:
    html = client.get("/browser").text
    assert "/static/js/browser.js?v=" in html
    assert "/static/css/base.css?v=" in html
