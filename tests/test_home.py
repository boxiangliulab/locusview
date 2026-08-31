"""Tests for the Home page (routers/home.py)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from locusview.requestinfo import Dataset, FakeQtlRepository, GwasDataset, QtlContextEntry
from locusview.web import create_app


def _client(
    datasets: list[Dataset] | None = None,
    gwas_datasets: list[GwasDataset] | None = None,
    qtl_contexts: list[QtlContextEntry] | None = None,
) -> TestClient:
    repo = FakeQtlRepository(
        datasets=datasets, gwas_datasets=gwas_datasets, qtl_contexts=qtl_contexts
    )
    return TestClient(create_app(repository=repo))


def test_home_groups_datasets_by_source() -> None:
    response = _client(
        [
            Dataset(1, "Whole_Blood", "gtex-v8"),
            Dataset(2, "Stomach", "gtex-v8"),
            Dataset(3, "Liver", "gtex-v8"),
        ]
    ).get("/")
    assert response.status_code == 200
    assert "Genotype-Tissue Expression" in response.text
    assert "Number of sub-datasets" in response.text
    assert "<td>3</td>" in response.text  # live count of rows grouped under this dataset


def test_home_shows_correct_qtl_type_badge() -> None:
    response = _client(
        [
            Dataset(1, "Whole_Blood", "GTEx_v10-eQTL-ALL"),
            Dataset(2, "Whole_Blood", "GTEx_v10-sQTL-ALL"),
        ]
    ).get("/")
    assert 'badge-blue">eQTL<' in response.text
    assert 'badge-blue">sQTL<' in response.text


def test_home_handles_hyphenated_eqtl_catalogue_dataset_name() -> None:
    response = _client(
        [
            Dataset(5, "INTERVAL", "eQTL-Catalogue-eQTL-EUR", "INTERVAL"),
            Dataset(6, "INTERVAL", "eQTL-Catalogue-sQTL-EUR", "INTERVAL"),
        ]
    ).get("/")
    assert response.text.count("eQTL Catalogue") == 2
    assert 'badge-blue">eQTL<' in response.text
    assert 'badge-blue">sQTL<' in response.text
    assert response.text.count("<td>1</td>") == 2


def test_home_unknown_source_falls_back_to_raw_string() -> None:
    response = _client([Dataset(1, "Cortex", "futurecohort")]).get("/")
    assert "futurecohort" in response.text


def test_home_dataset_table_shows_population() -> None:
    response = _client([Dataset(1, "Whole_Blood", "GTEx_v10-eQTL-EUR")]).get("/")
    assert "EUR" in response.text
    assert "Source id" not in response.text


def test_home_no_datasets_configured() -> None:
    response = _client([]).get("/")
    assert response.status_code == 200
    assert "No datasets configured" in response.text


def test_home_shows_citations() -> None:
    response = _client([]).get("/")
    assert "GTEx Consortium" in response.text
    assert "10.1126/science.aaz1776" in response.text


def test_home_nav_marks_home_active() -> None:
    response = _client([]).get("/")
    assert 'href="/" class="active"' in response.text


def test_home_has_no_hero_badge() -> None:
    response = _client([]).get("/")
    assert "QTL &amp; GWAS Browser" not in response.text
    assert "hero-badge" not in response.text
    assert "QTL + GWAS" not in response.text
    assert "Data types" not in response.text


# ── GWAS dataset table ───────────────────────────────────────────────────────


def test_home_shows_gwas_datasets() -> None:
    response = _client(
        gwas_datasets=[GwasDataset(1, "Basophil_count", "EUR", "GWAS Catalog", "GCST90002379")]
    ).get("/")
    assert "Basophil count" in response.text  # underscores replaced for display
    assert "GWAS Catalog" in response.text
    assert 'badge-orange">GWAS<' in response.text
    assert "GCST90002379" in response.text  # accession id column


def test_home_no_gwas_datasets_configured() -> None:
    response = _client().get("/")
    assert "No GWAS datasets configured" in response.text


def test_home_dataset_count_includes_both_qtl_and_gwas() -> None:
    response = _client(
        datasets=[Dataset(1, "Whole_Blood", "GTEx_v10-eQTL-ALL")],
        gwas_datasets=[GwasDataset(1, "Basophil_count", "EUR", "GWAS Catalog", "GCST90002379")],
    ).get("/")
    # 1 QTL source-group + 1 GWAS trait = 2 datasets in the hero stat
    assert '<div class="value">2</div>' in response.text


# ── Body map ─────────────────────────────────────────────────────────────────


def test_body_map_embeds_the_real_anatomogram_svg() -> None:
    """static/js/body-map.js does the data-region="..." tagging + leader-line-label building
    client-side (from the SVG's <title> elements) — the server's job is just to embed the real
    SVG plus the JSON payload JS reads from. One figure only (see content/body_map.py)."""
    response = _client([]).get("/")
    assert 'id="body-map-figure"' in response.text
    assert 'id="body-map-male"' not in response.text  # the second figure was removed, 2026-08
    # spot-check real organ ids from the actual fetched SVG asset. "blood" is female-SVG-only, so
    # it doubles as proof the *female* figure is the one embedded — the one that covers the
    # catalog's Whole_Blood / Artery_Tibial contexts (see content/body_map.py's docstring).
    assert '<title\n         id="liver">liver</title>' in response.text
    assert '<title\n         id="blood">blood</title>' in response.text
    assert "/static/js/body-map.js" in response.text


def test_body_map_leader_line_scaffold_present() -> None:
    """The label columns + connector-line overlay + results table that body-map.js populates."""
    response = _client([]).get("/")
    html = response.text
    assert 'id="body-map-container"' in html
    assert 'id="body-map-labels-left"' in html and 'id="body-map-labels-right"' in html
    assert 'id="body-map-leaders"' in html
    assert 'id="body-map-panel-table"' in html and 'id="body-map-panel-tbody"' in html
    assert 'id="body-map-panel-results"' in html


def test_body_map_has_no_ebi_licence_badge() -> None:
    """The badge is EBI's own attribution link baked into the source SVG — meaningless here,
    stripped at load time (content/body_map.py)."""
    response = _client([]).get("/")
    assert "licence.html" not in response.text


def test_body_map_marks_mapped_tissue_available() -> None:
    response = _client(
        qtl_contexts=[QtlContextEntry(1, "Whole_Blood", None, "GTEx_v10-eQTL-ALL")]
    ).get("/")
    assert '"blood":' in response.text and '"level_1": "Whole_Blood"' in response.text
    assert '"blood": "Blood"' in response.text.replace("'", '"')  # auto-derived label


def test_body_map_maps_both_blood_spellings_to_the_same_region() -> None:
    """The catalog uses BOTH "Whole_Blood" (GTEx) and plain "Blood" (CIMA/Tenk10k caQTL) for the
    same organ. A "whole_blood"-only keyword silently dropped the latter into "other" — regression
    guard for that (see REGION_KEYWORDS' comment)."""
    response = _client(
        qtl_contexts=[
            QtlContextEntry(1, "Whole_Blood", None, "GTEx_v10-eQTL-ALL"),
            QtlContextEntry(2, "Blood", "cMono_CD14", "CIMA-caQTL-EAS"),
        ]
    ).get("/")
    assert '"other":' not in response.text.replace(" ", "")
    assert '"level_1": "Blood"' in response.text  # landed under "blood", not "other"


def test_body_map_maps_tibial_artery_to_systemic_artery() -> None:
    response = _client(
        qtl_contexts=[QtlContextEntry(1, "Artery_Tibial", None, "GTEx_v10-eQTL-ALL")]
    ).get("/")
    compact = response.text.replace(" ", "")
    assert '"artery":' in compact
    assert '"level_1":"Artery_Tibial"' in compact


def test_body_map_unmapped_tissue_falls_back_to_other() -> None:
    response = _client(
        qtl_contexts=[QtlContextEntry(1, "SomeNewTissueType", None, "Foo-eQTL-ALL")]
    ).get("/")
    assert '"other":' in response.text.replace(" ", "")


def test_body_map_no_contexts_all_unavailable() -> None:
    response = _client().get("/")
    assert "unavailable" in response.text
    assert "/static/js/body-map.js" in response.text
