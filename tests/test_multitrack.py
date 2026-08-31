"""Tests for the multi-track stacked-plot endpoint (routers/locus.py's /api/locus/multi-track)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from locusview.requestinfo import (
    Dataset,
    EqtlAssociation,
    FakeQtlRepository,
    Gene,
    GwasAssociation,
    GwasDataset,
)
from locusview.web import create_app


def _client() -> TestClient:
    repo = FakeQtlRepository(
        datasets=[
            Dataset(1, "Whole_Blood", "GTEx_v10-eQTL-ALL"),
            Dataset(2, "Liver", "GTEx_v10-eQTL-ALL"),
        ],
        genes=[Gene(141510, "TP53", "ENSG00000141510.16", "17", 7_661_779, 7_687_550, "?")],
        associations=[
            EqtlAssociation(1, 141510, None, 17, 7_670_000, 1e-30, 0.5, 0.05,
                            phenotype_id="ENSG00000141510.18"),
            EqtlAssociation(1, 141510, None, 17, 7_671_000, 1e-3, 0.1, 0.05,
                            phenotype_id="ENSG00000141510.18"),
            EqtlAssociation(2, 141510, None, 17, 7_670_000, 0.5, 0.1, 0.05,
                            phenotype_id="ENSG00000141510.18"),
        ],
        gwas_datasets=[GwasDataset(1, "Basophil_count", "EUR", "GWAS Catalog", "GCST90002379")],
        gwas_associations=[
            GwasAssociation(1, 17, 7_670_500, 1e-10, 0.2, 0.03),  # in window, lead
            GwasAssociation(1, 17, 9_000_000, 0.5, 0.1, 0.05),  # outside gene window
        ],
    )
    return TestClient(create_app(repository=repo))


def test_multi_track_gene_mode_qtl_and_gwas() -> None:
    response = _client().get(
        "/api/locus/multi-track",
        params={"locus_mode": "gene", "gene": "TP53", "datasets": "qtl:1,gwas:1"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["label"] == "TP53"
    assert body["gene"] == {"symbol": "TP53", "ensembl_id": "ENSG00000141510.16"}
    assert body["region"]["chrom"] == "17"
    keys = [t["key"] for t in body["tracks"]]
    assert keys == ["qtl:1", "gwas:1"]

    qtl_track = body["tracks"][0]
    assert qtl_track["kind"] == "qtl"
    assert "Whole_Blood" in qtl_track["label"]
    assert qtl_track["lead"] is None
    assert qtl_track["variants"] == []
    assert [p["phenotype_id"] for p in qtl_track["phenotypes"]] == ["ENSG00000141510.18"]

    gwas_track = body["tracks"][1]
    assert gwas_track["kind"] == "gwas"
    assert "Basophil count" in gwas_track["label"] and "EUR" in gwas_track["label"]
    assert gwas_track["lead"]["position"] == 7_670_500
    assert len(gwas_track["variants"]) == 1  # the out-of-window point is dropped


def test_multi_track_non_gene_mode_has_no_external_gene_target() -> None:
    response = _client().get(
        "/api/locus/multi-track",
        params={
            "locus_mode": "region",
            "chrom": "17",
            "start": 7_660_000,
            "end": 7_690_000,
            "datasets": "qtl:1",
        },
    )
    assert response.status_code == 200
    assert response.json()["gene"] is None


def test_multi_track_gene_mode_window_is_start_plus_minus_1mb() -> None:
    """The Data Browser's gene-mode window is the gene's *start* +/-1 MB, not its own span."""
    response = _client().get(
        "/api/locus/multi-track",
        params={"locus_mode": "gene", "gene": "TP53", "datasets": "qtl:1"},
    )
    region = response.json()["region"]
    assert region["start"] == 7_661_779 - 1_000_000
    assert region["end"] == 7_661_779 + 1_000_000


def test_multi_track_gene_mode_defers_all_variants_until_phenotype_selection() -> None:
    repo = FakeQtlRepository(
        datasets=[Dataset(1, "Whole_Blood", "GTEx_v10-eQTL-ALL")],
        genes=[Gene(141510, "TP53", "ENSG00000141510.16", "17", 7_661_779, 7_687_550, "?")],
        associations=[
            EqtlAssociation(1, 141510, None, 17, 7_670_000, 1e-9, 0.5, 0.05),  # in window
            EqtlAssociation(1, 141510, None, 17, 9_000_000, 1e-30, 0.5, 0.05),  # far outside
        ],
    )
    response = TestClient(create_app(repository=repo)).get(
        "/api/locus/multi-track",
        params={"locus_mode": "gene", "gene": "TP53", "datasets": "qtl:1"},
    )
    variants = response.json()["tracks"][0]["variants"]
    assert variants == []


def test_multi_track_gene_mode_does_not_eagerly_send_enriched_variants() -> None:
    repo = FakeQtlRepository(
        datasets=[Dataset(1, "Whole_Blood", "GTEx_v10-eQTL-ALL")],
        genes=[Gene(141510, "TP53", "ENSG00000141510.16", "17", 7_661_779, 7_687_550, "?")],
        associations=[
            EqtlAssociation(1, 141510, 12345, 17, 7_670_000, 1e-9, 0.5, 0.05, "C", "T"),
        ],
    )
    response = TestClient(create_app(repository=repo)).get(
        "/api/locus/multi-track",
        params={"locus_mode": "gene", "gene": "TP53", "datasets": "qtl:1"},
    )
    assert response.json()["tracks"][0]["variants"] == []


def test_multi_track_gene_mode_returns_phenotype_id_before_variant_data() -> None:
    repo = FakeQtlRepository(
        datasets=[Dataset(1, "Whole_Blood", "GTEx_v10-eQTL-ALL")],
        genes=[Gene(141510, "TP53", "ENSG00000141510.16", "17", 7_661_779, 7_687_550, "?")],
        associations=[
            EqtlAssociation(
                1, 141510, None, 17, 7_670_000, 1e-9, 0.5, 0.05,
                phenotype_id="ENSG00000141510.18",
            ),
        ],
    )
    response = TestClient(create_app(repository=repo)).get(
        "/api/locus/multi-track",
        params={"locus_mode": "gene", "gene": "TP53", "datasets": "qtl:1"},
    )
    track = response.json()["tracks"][0]
    assert track["variants"] == []
    assert track["phenotypes"][0]["phenotype_id"] == "ENSG00000141510.18"


def test_multi_track_qtl_track_carries_dataset_metadata() -> None:
    response = _client().get(
        "/api/locus/multi-track",
        params={"locus_mode": "gene", "gene": "TP53", "datasets": "qtl:1"},
    )
    qtl_track = response.json()["tracks"][0]
    assert qtl_track["dataset_id"] == 1
    assert qtl_track["dataset"] == "GTEx_v10"
    assert qtl_track["qtl_type"] == "eQTL"
    assert qtl_track["population"] == "ALL"
    assert qtl_track["context"] == "Whole_Blood"


def test_multi_track_qtl_track_groups_variants_by_phenotype() -> None:
    """Two associations tested against different phenotypes in the same window each get their
    own row in "phenotypes", with the lead (min-p) variant per group."""
    repo = FakeQtlRepository(
        datasets=[Dataset(1, "Whole_Blood", "GTEx_v10-eQTL-ALL")],
        genes=[Gene(141510, "TP53", "ENSG00000141510.16", "17", 7_661_779, 7_687_550, "?")],
        associations=[
            # sQTL-style: the same gene can have multiple splice-junction phenotypes.
            EqtlAssociation(
                1, 141510, None, 17, 7_670_000, 1e-9, 0.5, 0.05,
                phenotype_id="chr17:7670000:7671000:clu_1:ENSG00000141510.18",
            ),
            EqtlAssociation(
                1, 141510, None, 17, 7_671_000, 1e-3, 0.1, 0.05,
                phenotype_id="chr17:7671000:7672000:clu_2:ENSG00000141510.18",
            ),
        ],
    )
    response = TestClient(create_app(repository=repo)).get(
        "/api/locus/multi-track",
        params={"locus_mode": "gene", "gene": "TP53", "datasets": "qtl:1"},
    )
    phenotypes = response.json()["tracks"][0]["phenotypes"]
    assert {p["phenotype_id"] for p in phenotypes} == {
        "chr17:7670000:7671000:clu_1:ENSG00000141510.18",
        "chr17:7671000:7672000:clu_2:ENSG00000141510.18",
    }
    lead = next(
        p
        for p in phenotypes
        if p["phenotype_id"] == "chr17:7670000:7671000:clu_1:ENSG00000141510.18"
    )
    assert lead["lead_position"] is None and lead["lead_pvalue"] is None


def test_multi_track_gwas_track_has_no_phenotypes_key() -> None:
    response = _client().get(
        "/api/locus/multi-track",
        params={"locus_mode": "gene", "gene": "TP53", "datasets": "gwas:1"},
    )
    assert "phenotypes" not in response.json()["tracks"][0]


def test_multi_track_gwas_variants_carry_rs_id_key_even_when_unresolved() -> None:
    """The fixture's GwasAssociation rows don't set rs_id/ref/alt (no rsID mapping in the test
    data) — the key is still present (mirroring QTL's rs_id=None case), just null."""
    response = _client().get(
        "/api/locus/multi-track",
        params={"locus_mode": "gene", "gene": "TP53", "datasets": "gwas:1"},
    )
    variant = response.json()["tracks"][0]["variants"][0]
    assert variant["rs_id"] is None and variant["variant_id"] is None


def test_multi_track_gwas_variants_carry_rs_id_and_variant_id_when_present() -> None:
    repo = FakeQtlRepository(
        datasets=[],
        genes=[Gene(141510, "TP53", "ENSG00000141510.16", "17", 7_661_779, 7_687_550, "?")],
        gwas_datasets=[GwasDataset(1, "Basophil_count", "EUR", "GWAS Catalog", "GCST90002379")],
        gwas_associations=[
            GwasAssociation(1, 17, 7_670_000, 1e-10, 0.2, 0.03, ref="C", alt="T", rs_id=12345),
        ],
    )
    response = TestClient(create_app(repository=repo)).get(
        "/api/locus/multi-track",
        params={"locus_mode": "gene", "gene": "TP53", "datasets": "gwas:1"},
    )
    variant = response.json()["tracks"][0]["variants"][0]
    assert variant["rs_id"] == 12345
    assert variant["variant_id"] == "chr17_7670000_C_T"


def test_multi_track_qtl_track_is_gene_scoped_not_window_scoped() -> None:
    """Dataset 2 has an association at the same position but it's not significant relative to
    dataset 1's — each track should still only include ITS OWN dataset's rows."""
    response = _client().get(
        "/api/locus/multi-track", params={"locus_mode": "gene", "gene": "TP53", "datasets": "qtl:2"}
    )
    body = response.json()
    assert len(body["tracks"]) == 1
    assert body["tracks"][0]["lead"] is None
    assert body["tracks"][0]["phenotypes"][0]["phenotype_id"] == "ENSG00000141510.18"


def test_multi_track_empty_datasets_is_400() -> None:
    r = _client().get(
        "/api/locus/multi-track", params={"locus_mode": "gene", "gene": "TP53", "datasets": ""}
    )
    assert r.status_code == 400


def test_multi_track_unknown_gene_is_404() -> None:
    r = _client().get(
        "/api/locus/multi-track", params={"locus_mode": "gene", "gene": "NOPE", "datasets": "qtl:1"}
    )
    assert r.status_code == 404


def test_multi_track_missing_gene_is_400() -> None:
    r = _client().get("/api/locus/multi-track", params={"locus_mode": "gene", "datasets": "qtl:1"})
    assert r.status_code == 400


def test_multi_track_unknown_dataset_is_silently_skipped() -> None:
    response = _client().get(
        "/api/locus/multi-track",
        params={"locus_mode": "gene", "gene": "TP53", "datasets": "qtl:999,qtl:1"},
    )
    body = response.json()
    assert [t["key"] for t in body["tracks"]] == ["qtl:1"]


def test_multi_track_region_mode() -> None:
    response = _client().get(
        "/api/locus/multi-track",
        params={
            "locus_mode": "region",
            "chrom": "17",
            "start": 7_669_000,
            "end": 7_672_000,
            "datasets": "qtl:1",
        },
    )
    body = response.json()
    assert body["label"] == "chr17:7669000-7672000"
    # Region mode's variants aren't sent (see _qtl_track's docstring: associations_in_region is
    # never rs_id-enriched and a window's raw variant set can be huge — the frontend re-fetches a
    # checked phenotype's own enriched variants from /api/locus/qtl-phenotype instead). The
    # (small, already-grouped) phenotypes summary is what the results table actually uses.
    assert body["tracks"][0]["variants"] == []
    assert len(body["tracks"][0]["phenotypes"]) == 1


def test_multi_track_region_mode_bad_chrom_is_400() -> None:
    r = _client().get(
        "/api/locus/multi-track",
        params={"locus_mode": "region", "chrom": "99", "start": 1, "end": 2, "datasets": "qtl:1"},
    )
    assert r.status_code == 400


def test_multi_track_region_mode_missing_params_is_400() -> None:
    r = _client().get(
        "/api/locus/multi-track",
        params={"locus_mode": "region", "chrom": "17", "datasets": "qtl:1"},
    )
    assert r.status_code == 400


def test_multi_track_unknown_dataset_kind_is_skipped() -> None:
    response = _client().get(
        "/api/locus/multi-track",
        params={"locus_mode": "gene", "gene": "TP53", "datasets": "foo:1,qtl:1"},
    )
    assert [t["key"] for t in response.json()["tracks"]] == ["qtl:1"]


def test_multi_track_variant_mode_by_position() -> None:
    response = _client().get(
        "/api/locus/multi-track",
        params={
            "locus_mode": "variant",
            "chrom": "17",
            "position": 7_670_000,
            "datasets": "qtl:1,gwas:1",
        },
    )
    body = response.json()
    assert body["region"]["chrom"] == "17"
    assert body["region"]["start"] == 7_670_000 - 1_000_000  # +/-1 MB, _VARIANT_WINDOW
    assert body["region"]["end"] == 7_670_000 + 1_000_000
    keys = [t["key"] for t in body["tracks"]]
    assert keys == ["qtl:1", "gwas:1"]


def test_multi_track_variant_mode_missing_locator_is_400() -> None:
    r = _client().get(
        "/api/locus/multi-track", params={"locus_mode": "variant", "datasets": "qtl:1"}
    )
    assert r.status_code == 400


def test_multi_track_unknown_mode_is_400() -> None:
    r = _client().get(
        "/api/locus/multi-track", params={"locus_mode": "wat", "datasets": "qtl:1"}
    )
    assert r.status_code == 400


def test_multi_track_variant_mode_by_rsid_resolves_via_qtl_dataset() -> None:
    repo = FakeQtlRepository(
        datasets=[Dataset(1, "Whole_Blood", "GTEx_v10-eQTL-ALL")],
        associations=[EqtlAssociation(1, 141510, 12345, 17, 7_670_000, 1e-9, 0.5, 0.05)],
    )
    response = TestClient(create_app(repository=repo)).get(
        "/api/locus/multi-track",
        params={"locus_mode": "variant", "rsid": 12345, "datasets": "qtl:1"},
    )
    assert response.status_code == 200
    assert response.json()["region"]["chrom"] == "17"


def test_multi_track_variant_mode_by_rsid_works_without_a_qtl_dataset_selected() -> None:
    """resolve_variant is a standalone existence check (see requestinfo.py's docstring) — no
    longer needs a QTL dataset selected, unlike the old associations_for_rsid-based lookup this
    replaced."""
    repo = FakeQtlRepository(
        datasets=[Dataset(1, "Whole_Blood", "GTEx_v10-eQTL-ALL")],
        associations=[EqtlAssociation(1, 141510, 12345, 17, 7_670_000, 1e-9, 0.5, 0.05)],
        gwas_datasets=[GwasDataset(1, "Basophil_count", "EUR", "GWAS Catalog", "GCST90002379")],
        gwas_associations=[GwasAssociation(1, 17, 7_670_000, 1e-10, 0.2, 0.03)],
    )
    response = TestClient(create_app(repository=repo)).get(
        "/api/locus/multi-track",
        params={"locus_mode": "variant", "rsid": 12345, "datasets": "gwas:1"},
    )
    assert response.status_code == 200
    keys = [t["key"] for t in response.json()["tracks"]]
    assert keys == ["gwas:1"]  # only the requested track — qtl:1 has the rsid but wasn't asked for


def test_multi_track_variant_mode_unknown_rsid_is_404() -> None:
    r = _client().get(
        "/api/locus/multi-track",
        params={"locus_mode": "variant", "rsid": 999999, "datasets": "qtl:1"},
    )
    assert r.status_code == 404


def test_multi_track_variant_mode_by_position_bad_chrom_is_400() -> None:
    r = _client().get(
        "/api/locus/multi-track",
        params={"locus_mode": "variant", "chrom": "99", "position": 1, "datasets": "qtl:1"},
    )
    assert r.status_code == 400


# ── /api/locus/qtl-phenotype (per-phenotype LD enrichment for region/variant-mode panels) ──────


def test_qtl_phenotype_enriches_and_clips_to_window() -> None:
    repo = FakeQtlRepository(
        associations=[
            EqtlAssociation(
                1, 141510, 123, 17, 7_670_000, 1e-9, 0.5, 0.05, "C", "T",
                phenotype_id="ENSG00000141510.18",
            ),
            EqtlAssociation(
                1, 141510, None, 17, 9_000_000, 1e-3, 0.1, 0.05,
                phenotype_id="ENSG00000141510.18",  # same phenotype, outside the window
            ),
        ],
    )
    response = TestClient(create_app(repository=repo)).get(
        "/api/locus/qtl-phenotype",
        params={
            "dataset_id": 1,
            "phenotype_id": "ENSG00000141510.18",
            "chrom": "17",
            "start": 7_000_000,
            "end": 8_000_000,
        },
    )
    assert response.status_code == 200
    variants = response.json()["variants"]
    assert [v["position"] for v in variants] == [7_670_000]  # the out-of-window row is clipped
    assert variants[0]["rs_id"] == 123
    assert variants[0]["is_lead"] is True


def test_qtl_phenotype_bad_chrom_is_400() -> None:
    r = TestClient(create_app(repository=FakeQtlRepository())).get(
        "/api/locus/qtl-phenotype",
        params={"dataset_id": 1, "phenotype_id": "x", "chrom": "99", "start": 0, "end": 1},
    )
    assert r.status_code == 400
