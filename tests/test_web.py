"""Tests for the web application skeleton."""

from __future__ import annotations

from fastapi.testclient import TestClient

from locusview import __version__
from locusview.repository import Dataset, EqtlAssociation, FakeQtlRepository, Gene
from locusview.web import create_app

client = TestClient(create_app())


def _gene_client() -> TestClient:
    repo = FakeQtlRepository(
        datasets=[Dataset(1, "Whole_Blood", "gtex-v8"), Dataset(2, "Stomach", "gtex-v8")],
        genes=[Gene(141510, "TP53", "ENSG00000141510.16", "17", 7661779, 7687550, "-")],
        associations=[EqtlAssociation(1, 141510, 12345, 17, 7670000, 0.001, 0.2, 0.05)],
    )
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


def test_gene_page_renders_eqtls() -> None:
    response = _gene_client().get("/gene/TP53")
    assert response.status_code == 200
    assert "TP53" in response.text
    assert "Whole_Blood" in response.text  # tissue joined from the catalog
    assert "rs12345" in response.text  # variant rendered


def test_gene_page_unknown_gene_is_404() -> None:
    response = _gene_client().get("/gene/NOPE")
    assert response.status_code == 404
    assert "Nothing found" in response.text


def test_search_redirects_a_gene_symbol() -> None:
    response = _gene_client().get("/search", params={"q": "TP53"}, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/gene/TP53"


def test_search_redirects_an_ensembl_id() -> None:
    response = _gene_client().get(
        "/search", params={"q": "ENSG00000141510"}, follow_redirects=False
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/gene/ENSG00000141510"


def test_search_unsupported_query_is_404() -> None:
    response = _gene_client().get("/search", params={"q": "1:1000-2000"}, follow_redirects=False)
    assert response.status_code == 404
    assert "supports" in response.text.lower()


# ── variant page (reverse lookup) ───────────────────────────────────────────


def _variant_client() -> TestClient:
    repo = FakeQtlRepository(
        datasets=[Dataset(1, "Whole_Blood", "gtex-v8"), Dataset(2, "Liver", "gtex-v8")],
        genes=[Gene(141510, "TP53", "ENSG00000141510.16", "17", 7661779, 7687550, "-")],
        associations=[
            EqtlAssociation(
                1, 141510, 62062621, 17, 7757304, 3e-4, 0.03, 0.05
            ),  # TP53 / Whole_Blood
            EqtlAssociation(2, 141510, 62062621, 17, 7757304, 1e-3, 0.02, 0.05),  # TP53 / Liver
            EqtlAssociation(
                1, 99999, 62062621, 17, 7757304, 0.01, 0.10, 0.05
            ),  # gene not in catalog
        ],
    )
    return TestClient(create_app(repository=repo))


def test_variant_page_reverse_lookup() -> None:
    response = _variant_client().get("/variant/rs62062621")
    assert response.status_code == 200
    assert "rs62062621" in response.text
    assert "TP53" in response.text  # gene resolved from its integer id
    assert "Whole_Blood" in response.text and "Liver" in response.text  # both tissues
    assert "99999" in response.text  # unresolved gene falls back to its id


def test_variant_page_unknown_variant_is_404() -> None:
    response = _variant_client().get("/variant/rs999999")  # no association -> chrom unresolved
    assert response.status_code == 404


def test_variant_page_bad_rsid_is_404() -> None:
    assert _variant_client().get("/variant/notarsid").status_code == 404


def test_search_redirects_an_rsid() -> None:
    response = _variant_client().get("/search", params={"q": "rs62062621"}, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/variant/rs62062621"
