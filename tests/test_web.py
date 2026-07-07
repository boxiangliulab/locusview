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
    response = _gene_client().get("/search", params={"q": "rs12345"}, follow_redirects=False)
    assert response.status_code == 404
    assert "gene search" in response.text.lower()


# ── download (CSV / TSV) ────────────────────────────────────────────────────


def test_download_csv() -> None:
    response = _gene_client().get("/gene/TP53/download")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert 'attachment; filename="TP53_eqtls.csv"' in response.headers["content-disposition"]
    lines = response.text.strip().splitlines()
    assert lines[0] == "gene,ensembl_id,tissue,variant,chrom,position,pvalue,beta,se"
    assert "TP53" in lines[1] and "Whole_Blood" in lines[1] and "rs12345" in lines[1]


def test_download_tsv() -> None:
    response = _gene_client().get("/gene/TP53/download", params={"format": "tsv"})
    assert response.status_code == 200
    assert "\t" in response.text
    assert 'filename="TP53_eqtls.tsv"' in response.headers["content-disposition"]


def test_download_unknown_gene_is_404() -> None:
    assert _gene_client().get("/gene/NOPE/download").status_code == 404


def test_download_bad_format_is_400() -> None:
    assert _gene_client().get("/gene/TP53/download", params={"format": "xml"}).status_code == 400
