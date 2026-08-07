"""Tests for the gene page and its CSV/TSV download (routers/gene.py)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from locusview.requestinfo import Dataset, EqtlAssociation, FakeQtlRepository, Gene
from locusview.web import create_app


def _gene_client() -> TestClient:
    repo = FakeQtlRepository(
        datasets=[Dataset(1, "Whole_Blood", "gtex-v8"), Dataset(2, "Stomach", "gtex-v8")],
        genes=[Gene(141510, "TP53", "ENSG00000141510.16", "17", 7661779, 7687550, "-")],
        associations=[EqtlAssociation(1, 141510, 12345, 17, 7670000, 0.001, 0.2, 0.05)],
    )
    return TestClient(create_app(repository=repo))


def test_gene_page_renders_eqtls() -> None:
    response = _gene_client().get("/gene/TP53")
    assert response.status_code == 200
    assert "TP53" in response.text
    assert "Whole_Blood" in response.text  # tissue joined from the catalog
    assert "rs12345" in response.text  # variant rendered


def test_gene_page_has_regional_plot_ui() -> None:
    html = _gene_client().get("/gene/TP53").text
    assert 'id="lv-plot"' in html  # Plotly container
    assert 'id="lv-tissue"' in html and "Stomach" in html  # tissue selector + options
    assert 'id="lv-population"' in html  # LD population selector
    assert "cdn.plot.ly" in html  # Plotly loaded
    assert "/api/gene/" in html  # JS wires the regional endpoint


def test_gene_page_unknown_gene_is_404() -> None:
    response = _gene_client().get("/gene/NOPE")
    assert response.status_code == 404
    assert "Nothing found" in response.text


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
