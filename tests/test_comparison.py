"""Tests for the variant comparison table (routers/comparison.py)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from locusview.requestinfo import (
    Dataset,
    EqtlAssociation,
    FakeQtlRepository,
    GwasAssociation,
    GwasDataset,
    RepositoryTimeoutError,
)
from locusview.routers.comparison import _parse_dataset_keys
from locusview.web import create_app


def test_parse_dataset_keys_ignores_unknown_kinds_and_bad_ids() -> None:
    assert _parse_dataset_keys("qtl:1,gwas:2,foo:3,qtl:x,") == ([1], [2])


class _TimingOutRepository(FakeQtlRepository):
    """Simulates the real DB's missing-index perf gap (see RepositoryTimeoutError)."""

    def associations_in_region(
        self, chrom: str, start: int, end: int, dataset_id: int
    ) -> list[EqtlAssociation]:
        raise RepositoryTimeoutError("simulated timeout")

    def gwas_associations_in_region(
        self, chrom: str, start: int, end: int, dataset_id: int
    ) -> list[GwasAssociation]:
        raise RepositoryTimeoutError("simulated timeout")


def _client() -> TestClient:
    repo = FakeQtlRepository(
        datasets=[
            Dataset(1, "Whole_Blood", "GTEx_v10-eQTL-ALL"),
            Dataset(2, "Liver", "GTEx_v10-eQTL-ALL"),
        ],
        associations=[
            EqtlAssociation(1, 141510, None, 17, 7_670_000, 1e-9, 0.5, 0.05),  # significant
            EqtlAssociation(2, 141510, None, 17, 7_670_000, 0.02, 0.1, 0.05),  # not significant
            EqtlAssociation(2, 141510, None, 17, 7_680_000, 1e-10, 0.5, 0.05),  # other position
        ],
        gwas_datasets=[GwasDataset(1, "Basophil_count", "EUR", "GWAS Catalog", "GCST90002379")],
        gwas_associations=[
            GwasAssociation(1, 17, 7_670_000, 5e-12, 0.2, 0.03),  # strongest overall
        ],
    )
    return TestClient(create_app(repository=repo))


def test_variant_stats_by_position_compares_across_qtl_and_gwas() -> None:
    response = _client().get(
        "/browser/partials/variant-stats",
        params={"chrom": "17", "position": 7_670_000, "datasets": "qtl:1,qtl:2,gwas:1"},
    )
    assert response.status_code == 200
    html = response.text
    assert "chr17:7670000" in html
    assert "Whole_Blood" in html and "Liver" in html
    assert "Basophil count" in html
    assert "Basophil count (GCST90002379)" in html
    assert 'badge-blue">eQTL<' in html
    assert 'badge-orange">GWAS<' in html


def test_variant_stats_qtl_uses_context_project_and_actual_type() -> None:
    repo = FakeQtlRepository(
        datasets=[Dataset(1, "Blood", "eQTL-Catalogue-sQTL-EUR", "INTERVAL")],
        associations=[EqtlAssociation(1, 141510, None, 17, 7_670_000, 1e-8, 0.1, 0.05)],
    )
    html = TestClient(create_app(repository=repo)).get(
        "/browser/partials/variant-stats",
        params={"chrom": "17", "position": 7_670_000, "datasets": "qtl:1"},
    ).text
    assert "Blood (INTERVAL)" in html
    assert 'badge-blue">sQTL<' in html
    assert "eQTL-Catalogue-sQTL-EUR" not in html


def test_variant_stats_only_shows_requested_columns() -> None:
    html = _client().get(
        "/browser/partials/variant-stats",
        params={"chrom": "17", "position": 7_670_000, "datasets": "qtl:1,qtl:2"},
    ).text
    assert "<th>Dataset</th>" in html
    assert "<th>Type</th>" in html
    assert "p-value" in html
    assert "log" not in html
    assert "Sig." not in html


def test_variant_stats_only_selected_datasets_are_compared() -> None:
    response = _client().get(
        "/browser/partials/variant-stats",
        params={"chrom": "17", "position": 7_670_000, "datasets": "qtl:1"},
    )
    html = response.text
    assert "Whole_Blood" in html
    assert "Liver" not in html and "Basophil" not in html


def test_variant_stats_no_datasets_selected_is_400() -> None:
    response = _client().get(
        "/browser/partials/variant-stats", params={"chrom": "17", "position": 1}
    )
    assert response.status_code == 400


def test_variant_stats_missing_locator_is_422() -> None:
    """``chrom``/``position`` are required — the only caller (click-to-pin) always has them."""
    response = _client().get("/browser/partials/variant-stats", params={"datasets": "qtl:1"})
    assert response.status_code == 422


def test_variant_stats_no_hits_at_position() -> None:
    response = _client().get(
        "/browser/partials/variant-stats",
        params={"chrom": "17", "position": 1, "datasets": "qtl:1"},
    )
    assert response.status_code == 200
    assert "No stats found" in response.text


def test_variant_stats_unknown_dataset_id_is_skipped() -> None:
    response = _client().get(
        "/browser/partials/variant-stats",
        params={"chrom": "17", "position": 7_670_000, "datasets": "qtl:999,qtl:1"},
    )
    html = response.text
    assert "Whole_Blood" in html


# ── unindexed-query timeout handling ────────────────────────────────────────


def test_variant_stats_position_lookup_timeout_is_503() -> None:
    repo = _TimingOutRepository(datasets=[Dataset(1, "Whole_Blood", "GTEx_v10-eQTL-ALL")])
    response = TestClient(create_app(repository=repo)).get(
        "/browser/partials/variant-stats",
        params={"chrom": "17", "position": 1, "datasets": "qtl:1"},
    )
    assert response.status_code == 503
