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


# ── regional plot / LD API ──────────────────────────────────────────────────


def _plot_client() -> TestClient:
    repo = FakeQtlRepository(
        datasets=[Dataset(8, "Liver", "gtex-v8")],
        genes=[Gene(141510, "TP53", "ENSG00000141510.16", "17", 7661779, 7687550, "-")],
        associations=[
            EqtlAssociation(8, 141510, 111, 17, 7670000, 1e-30, 0.5, 0.05),  # lead (min p)
            EqtlAssociation(8, 141510, 222, 17, 7671000, 1e-3, 0.1, 0.05),
            EqtlAssociation(8, 141510, 333, 17, 7672000, 0.5, 0.01, 0.05),
        ],
        ld={("17", 111, "EUR"): {222: 0.9, 333: 0.1}},
    )
    return TestClient(create_app(repository=repo))


def test_regional_endpoint_attaches_r2_and_lead() -> None:
    response = _plot_client().get("/api/gene/TP53/regional", params={"tissue": 8})
    assert response.status_code == 200
    body = response.json()
    assert body["gene"] == "TP53"
    assert body["tissue"] == "Liver"
    assert body["lead"]["rs_id"] == 111
    by_rs = {v["rs_id"]: v for v in body["variants"]}
    assert by_rs[111]["is_lead"] is True and by_rs[111]["r2"] == 1.0
    assert by_rs[222]["r2"] == 0.9 and by_rs[333]["r2"] == 0.1
    assert by_rs[111]["color"] == "#9632B8"  # lead diamond color


def test_regional_unknown_gene_is_404() -> None:
    assert _plot_client().get("/api/gene/NOPE/regional", params={"tissue": 8}).status_code == 404


def test_regional_bad_population_is_400() -> None:
    r = _plot_client().get("/api/gene/TP53/regional", params={"tissue": 8, "population": "ZZ"})
    assert r.status_code == 400


def test_regional_unknown_tissue_is_404() -> None:
    assert _plot_client().get("/api/gene/TP53/regional", params={"tissue": 999}).status_code == 404


def test_regional_no_cis_associations() -> None:
    repo = FakeQtlRepository(
        datasets=[Dataset(8, "Liver", "gtex-v8")],
        genes=[Gene(141510, "TP53", "ENSG00000141510.16", "17", 1, 2, "-")],
    )
    body = (
        TestClient(create_app(repository=repo))
        .get("/api/gene/TP53/regional", params={"tissue": 8})
        .json()
    )
    assert body["variants"] == []
    assert body["lead"] is None
    assert body["region"]["chrom"] == "17"  # falls back to gene.chrom


def test_regional_all_pvalues_none() -> None:
    repo = FakeQtlRepository(
        datasets=[Dataset(8, "Liver", "gtex-v8")],
        genes=[Gene(141510, "TP53", "ENSG00000141510.16", "17", 1, 2, "-")],
        associations=[EqtlAssociation(8, 141510, 111, 17, 7670000, None, None, None)],
    )
    body = (
        TestClient(create_app(repository=repo))
        .get("/api/gene/TP53/regional", params={"tissue": 8})
        .json()
    )
    assert body["variants"] == []  # dropped (no log_pvalue)
    assert body["lead"]["rs_id"] == 111  # fell back to cis[0]


def test_ld_endpoint() -> None:
    body = (
        _plot_client()
        .get("/api/ld", params={"chrom": "17", "lead": 111, "population": "EUR"})
        .json()
    )
    assert body["r2"]["111"] == 1.0
    assert body["r2"]["222"] == 0.9
    assert body["reference_present_in_1000g"] is True


def test_ld_bad_chrom_is_400() -> None:
    assert _plot_client().get("/api/ld", params={"chrom": "99", "lead": 1}).status_code == 400


def test_ld_bad_population_is_400() -> None:
    r = _plot_client().get("/api/ld", params={"chrom": "17", "lead": 1, "population": "ZZ"})
    assert r.status_code == 400
