"""Tests for the live dataset catalog on the Tutorial page."""

from __future__ import annotations

from fastapi.testclient import TestClient

from locusview.requestinfo import Dataset, FakeQtlRepository, GwasDataset
from locusview.web import create_app


def _client() -> TestClient:
    repo = FakeQtlRepository(
        datasets=[
            Dataset(1, "Whole_Blood", "GTEx_v10-eQTL-ALL", "GTEx_v10"),
            # tissue is already the level-2-preferred display context produced by datasets().
            Dataset(2, "cMono_CD14", "CIMA-caQTL-EAS", "CIMA"),
            Dataset(3, "INTERVAL", "eQTL-Catalogue-sQTL-EUR", "INTERVAL"),
        ],
        gwas_datasets=[GwasDataset(1, "Basophil_count", "EUR", "GWAS Catalog", "GCST90002379")],
    )
    return TestClient(create_app(repository=repo))


def test_tutorial_renders_live_gwas_catalog_columns() -> None:
    response = _client().get("/tutorial")
    assert response.status_code == 200
    html = response.text
    assert 'id="tutorial-gwas-table"' in html
    for heading in ("Datasource", "Accession ID", "Trait ID", "Population"):
        assert f"<th>{heading}</th>" in html
    assert "GWAS Catalog" in html and "GCST90002379" in html and "Basophil_count" in html


def test_tutorial_renders_every_qtl_list_and_required_columns() -> None:
    html = _client().get("/tutorial").text
    assert 'id="tutorial-qtl-table"' in html
    for heading in ("Dataset", "Source project ID", "QTL type", "Population", "Context"):
        assert f"<th>{heading}</th>" in html
    assert "GTEx_v10" in html and "CIMA" in html and "eQTL-Catalogue" in html
    assert "cMono_CD14" in html  # level 2 is shown directly when present
    assert "Whole_Blood" in html  # level 1 fallback when level 2 is absent
    assert "3 QTL lists currently available" in html


def test_tutorial_nav_is_active() -> None:
    html = _client().get("/tutorial").text
    assert 'href="/tutorial" class="active"' in html


def test_tutorial_empty_catalogs_have_clear_messages() -> None:
    html = TestClient(create_app(repository=FakeQtlRepository())).get("/tutorial").text
    assert "No GWAS datasets configured" in html
    assert "No QTL datasets configured" in html


def test_tutorial_explains_requesting_data_from_the_api() -> None:
    html = _client().get("/tutorial").text
    assert 'id="request-from-api"' in html and "Request data from the API" in html
    assert 'href="#request-from-api"' in html  # linked from the intro
    for param in ('<td class="mono">q</td>', '<td class="mono">p</td>', "datasets</td>"):
        assert param in html
    assert "Default <code>1e-4</code>" in html
    assert "import requests" in html and "/api/search-data" in html
    assert 'id="tutorial-origin"' in html
    assert "404" in html and "400" in html


def test_tutorial_dataset_tables_have_no_api_key_column() -> None:
    html = _client().get("/tutorial").text
    assert "API key" not in html
    for key in ("qtl:1", "qtl:2", "qtl:3", "gwas:1"):
        assert f'<td class="mono">{key}</td>' not in html
