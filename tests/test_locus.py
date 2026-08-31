"""Tests for the Locus View regional-plot / LD API (routers/locus.py)."""

from __future__ import annotations

from collections.abc import Sequence

import pytest
from fastapi.testclient import TestClient

from locusview.requestinfo import (
    Dataset,
    EqtlAssociation,
    FakeQtlRepository,
    Gene,
    RepositoryTimeoutError,
)
from locusview.web import create_app


class _TimingOutRepository(FakeQtlRepository):
    """A repository whose region/rsid queries always raise RepositoryTimeoutError, simulating
    the real DB's missing chrom/position and rs_id indexes."""

    def associations_in_region(
        self, chrom: str, start: int, end: int, dataset_id: int
    ) -> list[EqtlAssociation]:
        raise RepositoryTimeoutError("simulated timeout")

    def associations_for_rsid(
        self, rs_id: int, dataset_ids: Sequence[int], gene_id: int | None = None
    ) -> list[EqtlAssociation]:
        raise RepositoryTimeoutError("simulated timeout")


def _plot_client(*, with_ld: bool = True) -> TestClient:
    repo = FakeQtlRepository(
        datasets=[Dataset(8, "Liver", "gtex-v8")],
        genes=[Gene(141510, "TP53", "ENSG00000141510.16", "17", 7661779, 7687550, "-")],
        associations=[
            EqtlAssociation(8, 141510, 111, 17, 7670000, 1e-30, 0.5, 0.05),  # lead (min p)
            EqtlAssociation(8, 141510, 222, 17, 7671000, 1e-3, 0.1, 0.05),  # r²=0.9
            EqtlAssociation(8, 141510, 333, 17, 7672000, 0.5, 0.01, 0.05),  # r²=0.3
            EqtlAssociation(8, 141510, 444, 17, 7673000, 0.4, 0.02, 0.05),  # absent from LD panel
            EqtlAssociation(8, 141510, None, 17, 7674000, 0.6, 0.02, 0.05),  # no rsID at all
        ],
        # A real panel never returns r² < 0.2 (the PLINK floor); nor does this fake.
        ld={("17", 111, "EUR"): {222: 0.9, 333: 0.3}} if with_ld else {},
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
    assert by_rs[222]["r2"] == 0.9 and by_rs[333]["r2"] == 0.3
    assert by_rs[111]["color"] == "#f97316"  # lead diamond color (orange, per Liu Fei)


def test_regional_missing_ld_is_low_bin_not_grey() -> None:
    """A variant absent from the LD panel is *below the 0.2 floor*, not "no data".

    Regression test for the review finding that ~99.7% of a real locus rendered grey.
    """
    body = _plot_client().get("/api/gene/TP53/regional", params={"tissue": 8}).json()
    by_rs = {v["rs_id"]: v for v in body["variants"]}
    assert by_rs[444]["r2"] is None
    assert by_rs[444]["color"] == "#463699"  # lowest bin (< 0.2) — NOT grey
    assert by_rs[None]["color"] == "#AAAAAA"  # no rsID -> LD genuinely unknown


def test_regional_without_usable_ld_pairs_returns_plain_plot_data() -> None:
    body = _plot_client(with_ld=False).get("/api/gene/TP53/regional", params={"tissue": 8}).json()

    assert body["reference_present_in_1000g"] is False
    assert body["ld_legend"] == []
    assert all(v["r2"] is None and v["color"] is None for v in body["variants"])
    assert next(v for v in body["variants"] if v["rs_id"] == 111)["is_lead"] is True


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


def test_ld_endpoint_does_not_fabricate_a_self_pair_when_ld_is_unavailable() -> None:
    response = _plot_client(with_ld=False).get(
        "/api/ld", params={"chrom": "17", "lead": 111, "population": "EUR"}
    )
    assert response.status_code == 200
    assert response.json()["reference_present_in_1000g"] is False
    assert response.json()["r2"] == {}


def test_ld_bad_chrom_is_400() -> None:
    assert _plot_client().get("/api/ld", params={"chrom": "99", "lead": 1}).status_code == 400


def test_ld_bad_population_is_400() -> None:
    r = _plot_client().get("/api/ld", params={"chrom": "17", "lead": 1, "population": "ZZ"})
    assert r.status_code == 400


# ── /api/locus/regional (Data Browser: gene / region / variant modes) ───────


def test_locus_regional_gene_mode_matches_gene_endpoint() -> None:
    gene_body = _plot_client().get("/api/gene/TP53/regional", params={"tissue": 8}).json()
    locus_body = (
        _plot_client()
        .get("/api/locus/regional", params={"locus_mode": "gene", "tissue": 8, "gene": "TP53"})
        .json()
    )
    assert locus_body["variants"] == gene_body["variants"]
    assert locus_body["lead"] == gene_body["lead"]


def test_locus_regional_gene_mode_missing_gene_is_400() -> None:
    r = _plot_client().get("/api/locus/regional", params={"locus_mode": "gene", "tissue": 8})
    assert r.status_code == 400


def test_locus_regional_gene_mode_unknown_gene_is_404() -> None:
    r = _plot_client().get(
        "/api/locus/regional", params={"locus_mode": "gene", "tissue": 8, "gene": "NOPE"}
    )
    assert r.status_code == 404


def test_locus_regional_bad_population_is_400() -> None:
    r = _plot_client().get(
        "/api/locus/regional",
        params={"locus_mode": "gene", "tissue": 8, "gene": "TP53", "population": "ZZ"},
    )
    assert r.status_code == 400


def test_locus_regional_region_mode_missing_params_is_400() -> None:
    r = _plot_client().get(
        "/api/locus/regional", params={"locus_mode": "region", "tissue": 8, "chrom": "17"}
    )
    assert r.status_code == 400


def test_locus_regional_variant_mode_bad_chrom_is_400() -> None:
    r = _plot_client().get(
        "/api/locus/regional",
        params={"locus_mode": "variant", "tissue": 8, "chrom": "99", "position": 1},
    )
    assert r.status_code == 400


def test_locus_regional_region_mode() -> None:
    body = (
        _plot_client()
        .get(
            "/api/locus/regional",
            params={
                "locus_mode": "region",
                "tissue": 8,
                "chrom": "17",
                "start": 7_669_000,
                "end": 7_671_500,
            },
        )
        .json()
    )
    by_rs = {v["rs_id"] for v in body["variants"]}
    assert by_rs == {111, 222}  # 333 (pos 7672000) and 444/None fall outside the window
    assert body["gene_id"] is None


def test_locus_regional_region_mode_bad_chrom_is_400() -> None:
    r = _plot_client().get(
        "/api/locus/regional",
        params={"locus_mode": "region", "tissue": 8, "chrom": "99", "start": 1, "end": 2},
    )
    assert r.status_code == 400


@pytest.mark.parametrize(
    ("start", "end"),
    [(-1, 2), (2, 1), (1, 10_000_002)],
)
def test_locus_regional_region_mode_rejects_unsafe_bounds(start: int, end: int) -> None:
    response = _plot_client().get(
        "/api/locus/regional",
        params={
            "locus_mode": "region",
            "tissue": 8,
            "chrom": "17",
            "start": start,
            "end": end,
        },
    )
    assert response.status_code == 400


def test_locus_regional_variant_mode_by_rsid() -> None:
    body = (
        _plot_client()
        .get(
            "/api/locus/regional",
            params={"locus_mode": "variant", "tissue": 8, "rsid": 222},
        )
        .json()
    )
    by_rs = {v["rs_id"] for v in body["variants"]}
    assert 222 in by_rs  # centered on the resolved variant's own position


def test_locus_regional_variant_mode_unknown_rsid_is_404() -> None:
    r = _plot_client().get(
        "/api/locus/regional", params={"locus_mode": "variant", "tissue": 8, "rsid": 999999}
    )
    assert r.status_code == 404


def test_locus_regional_variant_mode_by_position() -> None:
    body = (
        _plot_client()
        .get(
            "/api/locus/regional",
            params={
                "locus_mode": "variant",
                "tissue": 8,
                "chrom": "17",
                "position": 7_671_000,
            },
        )
        .json()
    )
    by_rs = {v["rs_id"] for v in body["variants"]}
    assert 222 in by_rs


def test_locus_regional_variant_mode_missing_locator_is_400() -> None:
    r = _plot_client().get("/api/locus/regional", params={"locus_mode": "variant", "tissue": 8})
    assert r.status_code == 400


def test_locus_regional_unknown_mode_is_400() -> None:
    r = _plot_client().get("/api/locus/regional", params={"locus_mode": "wat", "tissue": 8})
    assert r.status_code == 400


def test_locus_regional_unknown_dataset_is_404() -> None:
    r = _plot_client().get(
        "/api/locus/regional", params={"locus_mode": "gene", "tissue": 999, "gene": "TP53"}
    )
    assert r.status_code == 404


# ── unindexed-query timeout handling (region/variant modes) ────────────────


def _timing_out_client() -> TestClient:
    repo = _TimingOutRepository(datasets=[Dataset(8, "Liver", "gtex-v8")])
    return TestClient(create_app(repository=repo))


def test_locus_regional_region_mode_timeout_is_503() -> None:
    r = _timing_out_client().get(
        "/api/locus/regional",
        params={"locus_mode": "region", "tissue": 8, "chrom": "17", "start": 1, "end": 2},
    )
    assert r.status_code == 503


def test_locus_regional_variant_mode_timeout_is_503() -> None:
    r = _timing_out_client().get(
        "/api/locus/regional",
        params={"locus_mode": "variant", "tissue": 8, "chrom": "17", "position": 1},
    )
    assert r.status_code == 503
