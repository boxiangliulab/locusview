"""Tests for the Data Browser page shell + cascading picker catalog endpoints
(routers/browser.py)."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from locusview.requestinfo import Dataset, FakeQtlRepository, GwasDataset
from locusview.web import create_app


def _client() -> TestClient:
    repo = FakeQtlRepository(
        datasets=[
            Dataset(1, "Whole_Blood", "GTEx_v10-eQTL-ALL"),
            Dataset(2, "Stomach", "GTEx_v10-eQTL-ALL"),
            Dataset(3, "Whole_Blood", "GTEx_v10-sQTL-ALL"),
        ],
        gwas_datasets=[
            GwasDataset(1, "Basophil_count", "EUR", "GWAS Catalog", "GCST90002379"),
            GwasDataset(2, "Mean_corpuscular_hemoglobin", "EUR", "GWAS Catalog", "GCST90002390"),
        ],
    )
    return TestClient(create_app(repository=repo))


def _preselected(html: str, marker: str) -> object:
    needle = f"window.{marker} = "
    start = html.index(needle) + len(needle)
    end = html.index(";", start)
    return json.loads(html[start:end])


# ── page shell ────────────────────────────────────────────────────────────────


def test_browser_renders_picker_shell() -> None:
    response = _client().get("/browser")
    assert response.status_code == 200
    html = response.text
    assert 'id="qtl-rows"' in html and 'id="qtl-add-row"' in html
    assert 'id="qtl-row-template"' in html
    assert 'id="gwas-rows"' in html and 'id="gwas-add-row"' in html
    assert 'id="gwas-row-template"' in html
    assert 'id="db-run"' in html
    assert 'id="db-gene-links"' in html
    assert "/static/js/browser-picker.js" in html
    assert "/static/js/browser.js" in html
    # Per-plot "download as SVG" button for each locuszoom panel (static/js/plot-download.js).
    assert "/static/js/plot-download.js" in html


def test_browser_defaults_to_first_qtl_dataset_preselected() -> None:
    html = _client().get("/browser").text
    assert _preselected(html, "PRESELECTED_QTL_ROWS") == [
        {"dataset": "GTEx_v10", "qtl_type": "eQTL", "context_ids": [1]}
    ]
    assert _preselected(html, "PRESELECTED_GWAS_ROWS") == []


def test_browser_prefills_datasets_param_grouped_by_dataset_and_type() -> None:
    html = _client().get("/browser", params={"datasets": "qtl:1,qtl:3,gwas:2"}).text
    assert _preselected(html, "PRESELECTED_QTL_ROWS") == [
        {"dataset": "GTEx_v10", "qtl_type": "eQTL", "context_ids": [1]},
        {"dataset": "GTEx_v10", "qtl_type": "sQTL", "context_ids": [3]},
    ]
    assert _preselected(html, "PRESELECTED_GWAS_ROWS") == [
        {"dataset": "GWAS Catalog", "option_ids": [2]}
    ]


def test_browser_prefills_datasets_param_groups_same_row_together() -> None:
    """Two QTL ids sharing a (dataset, qtl_type) land in ONE row's context_ids, not two rows."""
    html = _client().get("/browser", params={"datasets": "qtl:1,qtl:2"}).text
    assert _preselected(html, "PRESELECTED_QTL_ROWS") == [
        {"dataset": "GTEx_v10", "qtl_type": "eQTL", "context_ids": [1, 2]}
    ]


def test_browser_nav_marks_browser_active() -> None:
    response = _client().get("/browser")
    assert 'href="/browser" class="active"' in response.text


def test_browser_prefills_locus_mode_and_region() -> None:
    response = _client().get("/browser", params={"locus_mode": "region", "region": "chr1:1-2"})
    html = response.text
    assert 'db-toggle-btn active" data-locus-mode="region"' in html
    assert 'value="chr1:1-2"' in html


def test_browser_no_datasets_configured() -> None:
    response = TestClient(create_app(repository=FakeQtlRepository())).get("/browser")
    assert response.status_code == 200
    assert "No QTL datasets available" in response.text
    assert "No GWAS datasets available" in response.text


# ── catalog endpoints (cascading picker, static/js/browser-picker.js) ──────────


def test_qtl_dataset_names() -> None:
    response = _client().get("/api/browser/qtl/datasets")
    assert response.status_code == 200
    assert response.json() == ["GTEx_v10"]


def test_qtl_catalog_endpoints_handle_hyphenated_dataset_name() -> None:
    repo = FakeQtlRepository(
        datasets=[
            Dataset(5, "INTERVAL", "eQTL-Catalogue-eQTL-EUR", "INTERVAL"),
            Dataset(6, "INTERVAL", "eQTL-Catalogue-sQTL-EUR", "INTERVAL"),
        ]
    )
    client = TestClient(create_app(repository=repo))
    assert client.get("/api/browser/qtl/datasets").json() == ["eQTL-Catalogue"]
    assert client.get(
        "/api/browser/qtl/types", params={"dataset": "eQTL-Catalogue"}
    ).json() == ["eQTL", "sQTL"]
    assert client.get(
        "/api/browser/qtl/contexts",
        params={"dataset": "eQTL-Catalogue", "qtl_type": "sQTL"},
    ).json() == [{"id": 6, "label": "INTERVAL"}]


def test_qtl_types_for_dataset() -> None:
    response = _client().get("/api/browser/qtl/types", params={"dataset": "GTEx_v10"})
    assert response.json() == ["eQTL", "sQTL"]


def test_qtl_types_for_unknown_dataset_is_empty() -> None:
    response = _client().get("/api/browser/qtl/types", params={"dataset": "NOPE"})
    assert response.json() == []


def test_qtl_contexts_for_dataset_and_type() -> None:
    response = _client().get(
        "/api/browser/qtl/contexts", params={"dataset": "GTEx_v10", "qtl_type": "eQTL"}
    )
    assert response.json() == [{"id": 2, "label": "Stomach"}, {"id": 1, "label": "Whole_Blood"}]


def test_qtl_contexts_does_not_cross_qtl_types() -> None:
    response = _client().get(
        "/api/browser/qtl/contexts", params={"dataset": "GTEx_v10", "qtl_type": "sQTL"}
    )
    assert response.json() == [{"id": 3, "label": "Whole_Blood"}]


def test_qtl_contexts_passes_dataset_tissue_through_as_the_label() -> None:
    """Dataset.tissue is already the display label (level 2 when present, else level 1 — built in
    connectpostgres.py's datasets()), so the picker endpoint just sorts and passes it through."""
    repo = FakeQtlRepository(
        datasets=[
            Dataset(1, "cMono_CD14", "CIMA-caQTL-EAS"),
            Dataset(2, "CD4_Treg_FCRL3", "CIMA-caQTL-EAS"),
            Dataset(3, "Whole_Blood", "CIMA-caQTL-EAS"),  # a row with no level 2
        ]
    )
    response = TestClient(create_app(repository=repo)).get(
        "/api/browser/qtl/contexts", params={"dataset": "CIMA", "qtl_type": "caQTL"}
    )
    # plain (case-sensitive) sort: "CD4_..." < "Whole_Blood" < "cMono_..."
    assert response.json() == [
        {"id": 2, "label": "CD4_Treg_FCRL3"},
        {"id": 3, "label": "Whole_Blood"},
        {"id": 1, "label": "cMono_CD14"},
    ]


def test_gwas_dataset_names() -> None:
    response = _client().get("/api/browser/gwas/datasets")
    assert response.json() == ["GWAS Catalog"]


def test_gwas_options_for_dataset() -> None:
    response = _client().get("/api/browser/gwas/options", params={"dataset": "GWAS Catalog"})
    assert response.json() == [
        {"id": 1, "label": "GCST90002379 — Basophil count"},
        {"id": 2, "label": "GCST90002390 — Mean corpuscular hemoglobin"},
    ]


def test_gwas_options_for_unknown_dataset_is_empty() -> None:
    response = _client().get("/api/browser/gwas/options", params={"dataset": "NOPE"})
    assert response.json() == []
