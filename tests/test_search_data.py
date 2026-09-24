"""Tests for the Search data tab (routers/search_data.py)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from fastapi.testclient import TestClient

from locusview.requestinfo import (
    Dataset,
    EqtlAssociation,
    FakeQtlRepository,
    Gene,
    GwasAssociation,
    GwasDataset,
    RepositoryTimeoutError,
)
from locusview.routers.search_data import ContextRow, Hit
from locusview.web import create_app

_TP53 = Gene(141510, "TP53", "ENSG00000141510.16", "17", 7_661_779, 7_687_550, "-")


def _repo() -> FakeQtlRepository:
    return FakeQtlRepository(
        datasets=[
            Dataset(1, "Whole_Blood", "GTEx_v10-eQTL-ALL", "GTEx_v10"),
            Dataset(2, "Liver", "GTEx_v10-eQTL-ALL", "GTEx_v10"),
            Dataset(3, "Blood", "eQTL-Catalogue-sQTL-EUR", "INTERVAL"),
        ],
        genes=[_TP53],
        associations=[
            # The searched variant (rs1042522 at 17:7676154), tested against two phenotypes in
            # Whole_Blood and one in Liver; nothing at that position in dataset 3.
            EqtlAssociation(1, 141510, 1042522, 17, 7_676_154, 1e-9, 0.5, 0.05, phenotype_id="P_A"),
            EqtlAssociation(1, 141510, 1042522, 17, 7_676_154, 0.3, 0.1, 0.05, phenotype_id="P_B"),
            EqtlAssociation(2, 141510, 1042522, 17, 7_676_154, 0.02, 0.1, 0.05, phenotype_id="P_C"),
            # TP53's own phenotype in dataset 3 (sQTL), lead elsewhere in the cis window.
            EqtlAssociation(3, 141510, None, 17, 7_700_000, 1e-4, 0.2, 0.05, phenotype_id="clu_1"),
            EqtlAssociation(
                3, 141510, 555, 17, 7_710_000, 1e-6, 0.2, 0.05, "C", "G", phenotype_id="clu_1"
            ),
            EqtlAssociation(3, 141510, None, 17, 7_720_000, 1e-3, 0.3, 0.05, phenotype_id="clu_2"),
        ],
        gwas_datasets=[GwasDataset(1, "Basophil_count", "EUR", "GWAS Catalog", "GCST90002379")],
        gwas_associations=[GwasAssociation(1, 17, 7_676_154, 5e-12, 0.2, 0.03)],
    )


def _get(params: dict[str, object] | None = None, repo: FakeQtlRepository | None = None) -> str:
    client = TestClient(create_app(repository=repo or _repo()))
    response = client.get("/search-data", params=params or {})
    assert response.status_code == 200
    # Context names carry <wbr> wrap hints (see ContextRow.context_html); compare on plain text.
    return response.text.replace("<wbr>", "")  # (phenotype IDs carry them too: Hit.phenotype_html)


def test_empty_page_shows_search_box_and_examples() -> None:
    html = _get()
    assert "<h1>Search data</h1>" in html
    assert 'name="q"' in html
    assert "e.g. TP53, rs1042522, chr17:7676154" in html
    for example in ("TP53", "ENSG00000141510", "rs1042522", "chr17:7676154"):
        assert f'href="/search-data?q={example.replace(":", "%3A")}&amp;p=1e-4"' in html
    assert "<table" not in html


def test_nav_tab_is_marked_active() -> None:
    html = _get()
    assert '<a href="/search-data" class="active">Search data</a>' in html
    assert html.index('href="/search-data"') < html.index('href="/browser"')


def test_phenotype_links_target_the_matching_context_and_plot() -> None:
    gene_html = _get({"q": "TP53", "p": "0.01"})
    assert (
        'href="/browser?locus_mode=gene&amp;gene=TP53&amp;datasets=qtl:3&amp;phenotype=clu_1"'
        in gene_html
    )
    variant_html = _get({"q": "rs1042522", "p": "1"})
    assert (
        'href="/browser?locus_mode=variant&amp;variant=rs1042522&amp;datasets=qtl:1&amp;phenotype=P_A"'
        in variant_html
    )
    assert 'datasets=qtl:2&amp;phenotype=P_C' in variant_html
    assert 'datasets=qtl:1&amp;phenotype=P_B' in variant_html


def test_rsid_search_lists_every_dataset_with_a_hit_best_first() -> None:
    html = _get({"q": "rs1042522", "p": "1"})
    assert "rs1042522 · chr17:7,676,154" in html
    assert "3 of 4 datasets" in html  # 3 QTL contexts + 1 GWAS searched; dataset 3 has no hit
    # Most significant first: GWAS 5e-12, Whole_Blood 1e-9, Liver 2e-2.
    assert html.index("Basophil count") < html.index("Whole_Blood") < html.index("Liver")
    assert "GCST90002379" in html
    # Every phenotype is listed in full (no folding), grouped under its context.
    assert "<details" not in html
    assert "phenotypes</div>" not in html  # no "N phenotypes" note
    assert "P_A" in html and "P_B" in html
    assert 'rowspan="2"' in html  # Whole_Blood's context cells span both of its phenotype rows
    assert "1.00e-09" in html
    assert "0.500" in html  # beta
    assert "SE</th>" not in html  # standard errors aren't shown


def test_position_search_matches_rsid_search() -> None:
    html = _get({"q": "chr17:7676154", "p": "1"})
    assert "chr17:7,676,154" in html
    assert "Whole_Blood" in html and "Liver" in html and "Basophil count" in html


def test_gene_search_shows_each_contexts_most_significant_snp_and_every_phenotype() -> None:
    html = _get({"q": "TP53", "p": "0.01"})
    assert "TP53 (ENSG00000141510.16)" in html
    assert "QTL contexts" in html and "GWAS has no gene concept" in html
    assert "Lead SNP" in html and "Most significant SNP" not in html
    # Context, Dataset, Type are followed directly by the per-phenotype columns.
    assert '<th>Type</th>\n              <th class="sd-divide">Phenotype</th>' in html
    # Dataset 3's best SNP is clu_1's lead (rs555, 1e-6); clu_2 (no rsID) is listed too.
    assert "rs555" in html and "chr17:7710000 C&gt;G" in html and "1.00e-06" in html
    assert "clu_2" in html and "chr17:7720000" in html and "1.00e-03" in html
    assert html.index("clu_1") < html.index("clu_2")
    assert "Basophil count" not in html


def test_ensembl_search_resolves_the_gene() -> None:
    assert "TP53 (ENSG00000141510.16)" in _get({"q": "ENSG00000141510"})


def test_unknown_rsid_and_gene_say_not_found() -> None:
    assert "rs999 was not found." in _get({"q": "rs999"})
    assert "Gene NOPE1 was not found." in _get({"q": "NOPE1"})


def test_region_query_points_to_the_data_browser() -> None:
    html = _get({"q": "chr17:7000000-8000000"})
    assert "For a region, use the" in html
    assert "/browser?locus_mode=region" in html


def test_unrecognized_query_and_unsupported_chromosome() -> None:
    assert "as a gene, rsID, or chr:position." in _get({"q": "!!"})
    assert "as a gene, rsID, or chr:position." in _get({"q": "chrY:100"})


def test_data_browser_click_limits_to_its_datasets() -> None:
    html = _get({"chrom": "17", "position": 7_676_154, "datasets": "qtl:2", "p": "1"})
    assert "Showing only the datasets selected in the Data Browser" in html
    assert 'href="/search-data?q=chr17%3A7676154&amp;p=1"' in html  # "Search all datasets"
    assert 'name="datasets" value="qtl:2"' in html  # changing the threshold keeps the scope
    assert "1 of 1 datasets" in html
    assert "Liver" in html and "Whole_Blood" not in html and "Basophil count" not in html


def test_no_hits_says_so() -> None:
    assert "No associations at p &lt; 1e-4." in _get({"q": "chr1:100"})


def test_default_threshold_is_1e_4() -> None:
    html = _get({"q": "rs1042522"})
    assert 'name="p" value="1e-4"' in html
    assert "at p &lt; 1e-4" in html
    # Only GWAS (5e-12) and Whole_Blood's P_A (1e-9) pass; P_B (0.3) and Liver (0.02) don't.
    assert "2 of 4 datasets" in html
    assert "P_A" in html and "P_B" not in html and "Liver" not in html
    assert "Basophil count" in html


def test_custom_threshold_is_applied_and_kept_in_links() -> None:
    html = _get({"q": "rs1042522", "p": "0.05"})
    assert "3 of 4 datasets" in html and "at p &lt; 0.05" in html
    assert "Liver" in html and "P_B" not in html
    assert 'href="/search-data?q=TP53&amp;p=0.05"' in html  # examples keep the threshold


def test_gene_search_threshold_drops_weak_phenotypes() -> None:
    html = _get({"q": "TP53"})  # default 1e-4: clu_1 (1e-6) passes, clu_2 (1e-3) doesn't
    assert "clu_1" in html and "clu_2" not in html


def test_invalid_threshold_is_explained_not_searched() -> None:
    for bad in ("abc", "0", "2", "-1e-5"):
        html = _get({"q": "TP53", "p": bad})
        assert "isn&#39;t a valid p-value threshold" in html or "isn't a valid p-value" in html
        assert "<table" not in html


class _FlakyRepository(FakeQtlRepository):
    """The QTL batch query times out; GWAS still answers."""

    def variant_hits(
        self, chrom: str, position: int, dataset_ids: Sequence[int]
    ) -> list[EqtlAssociation]:
        raise RepositoryTimeoutError("simulated timeout")


def test_a_failing_dataset_is_reported_not_fatal() -> None:
    base = _repo()
    flaky = _FlakyRepository(
        datasets=base.datasets(),
        genes=[_TP53],
        associations=base._associations,
        gwas_datasets=base.gwas_datasets(),
        gwas_associations=base._gwas_associations,
    )
    html = _get({"q": "chr17:7676154", "p": "1"}, repo=flaky)
    # The whole QTL batch (all 3 contexts) is dropped; the GWAS trait still answers.
    assert "3 datasets could not be searched right now and are missing" in html
    assert "Basophil count" in html and "Whole_Blood" not in html


def test_context_best_pvalue_handles_no_hits() -> None:
    assert ContextRow("c", "d", "eQTL", False).pvalue is None
    assert ContextRow("c", "d", "eQTL", False, [Hit("p", 0.01), Hit("q", 0.5)]).pvalue == 0.01


def test_fake_gene_phenotype_leads_picks_min_p_per_phenotype() -> None:
    leads = _repo().gene_phenotype_leads(_TP53, [3])
    assert [(d, s.phenotype_id, s.position, s.rs_id, s.pvalue) for d, s in leads] == [
        (3, "clu_1", 7_710_000, 555, 1e-6),
        (3, "clu_2", 7_720_000, None, 1e-3),
    ]


def test_large_pages_are_gzip_compressed() -> None:
    client = TestClient(create_app(repository=_repo()))
    response = client.get(
        "/search-data", params={"q": "rs1042522", "p": "1"}, headers={"Accept-Encoding": "gzip"}
    )
    assert response.headers.get("content-encoding") == "gzip"


# ── JSON API (/api/search-data) ─────────────────────────────────────────────


def _api(params: dict[str, object]) -> tuple[int, dict[str, Any]]:
    response = TestClient(create_app(repository=_repo())).get("/api/search-data", params=params)
    return response.status_code, response.json()


def test_api_variant_search_returns_the_table_rows() -> None:
    status, body = _api({"q": "rs1042522", "p": "1"})
    assert status == 200
    assert body["type"] == "variant" and body["gene"] is None
    assert body["variant"] == {"rsid": "rs1042522", "chrom": "17", "position": 7_676_154}
    assert body["p_threshold"] == 1.0
    assert body["datasets_searched"] == 4 and body["datasets_failed"] == 0
    assert body["n_contexts"] == 3 and body["n_rows"] == 4
    assert "results" not in body
    assert body["rows"] == [
        {
            "context": "Basophil count",
            "dataset": "GCST90002379",
            "type": "GWAS",
            "phenotype": None,
            "pvalue": 5e-12,
            "beta": 0.2,
        },
        {
            "context": "Whole_Blood",
            "dataset": "GTEx_v10",
            "type": "eQTL",
            "phenotype": "P_A",
            "pvalue": 1e-9,
            "beta": 0.5,
        },
        {
            "context": "Whole_Blood",
            "dataset": "GTEx_v10",
            "type": "eQTL",
            "phenotype": "P_B",
            "pvalue": 0.3,
            "beta": 0.1,
        },
        {
            "context": "Liver",
            "dataset": "GTEx_v10",
            "type": "eQTL",
            "phenotype": "P_C",
            "pvalue": 0.02,
            "beta": 0.1,
        },
    ]


def test_api_default_threshold_is_1e_4() -> None:
    status, body = _api({"q": "chr17:7676154"})
    assert status == 200 and body["p_threshold"] == 1e-4
    assert body["variant"]["rsid"] is None
    assert [(r["context"], r["phenotype"]) for r in body["rows"]] == [
        ("Basophil count", None),
        ("Whole_Blood", "P_A"),
    ]


def test_api_gene_search_rows_carry_lead_snp_and_variant() -> None:
    status, body = _api({"q": "TP53", "p": "0.01"})
    assert status == 200 and body["type"] == "gene" and body["variant"] is None
    assert body["gene"] == {
        "symbol": "TP53",
        "ensembl_id": "ENSG00000141510.16",
        "chrom": "17",
        "start": 7_661_779,
        "end": 7_687_550,
    }
    # Whole_Blood's P_A (1e-9) and Blood's clu_1 / clu_2 pass p < 0.01; Liver's P_C (0.02) doesn't.
    assert body["n_contexts"] == 2 and body["n_rows"] == 3
    assert list(body["rows"][0]) == [
        "context",
        "dataset",
        "type",
        "phenotype",
        "lead_snp",
        "variant",
        "pvalue",
        "beta",
    ]
    assert body["rows"][1:] == [
        {
            "context": "Blood",
            "dataset": "eQTL-Catalogue / INTERVAL",
            "type": "sQTL",
            "phenotype": "clu_1",
            "lead_snp": "rs555",
            "variant": "chr17:7710000 C>G",
            "pvalue": 1e-6,
            "beta": 0.2,
        },
        {
            "context": "Blood",
            "dataset": "eQTL-Catalogue / INTERVAL",
            "type": "sQTL",
            "phenotype": "clu_2",
            "lead_snp": "chr17:7720000",
            "variant": "chr17:7720000",
            "pvalue": 1e-3,
            "beta": 0.3,
        },
    ]


def test_api_datasets_param_limits_the_search() -> None:
    status, body = _api({"q": "rs1042522", "p": "1", "datasets": "qtl:2"})
    assert status == 200 and body["datasets_searched"] == 1
    assert [r["context"] for r in body["rows"]] == ["Liver"]


def _page_table(html: str) -> list[list[str]]:
    """The page's results table as plain-text rows, with each context's rowspan cells
    (Context / Dataset / Type) repeated onto every one of its phenotype rows."""
    import html as html_lib
    import re

    def text(cell: str) -> str:
        return html_lib.unescape(re.sub(r"<[^>]+>", "", cell)).strip()

    table = html[html.index('<table class="data-table sd-table"') : html.index("</table>")]
    rows: list[list[str]] = []
    for group in re.findall(r'<tbody class="sd-group">(.*?)</tbody>', table, re.S):
        shared: list[str] = []
        for i, tr in enumerate(re.findall(r"<tr>(.*?)</tr>", group, re.S)):
            cells = [text(c) for c in re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)]
            if i == 0:
                shared, cells = cells[:3], cells[3:]
            rows.append(shared + cells)
    return rows


def _api_as_page_text(rows: list[dict[str, Any]]) -> list[list[str]]:
    """The API rows formatted the way the page displays them (rounded p / beta, dash for GWAS)."""
    out = []
    for r in rows:
        cells = [str(v) if v is not None else "" for v in r.values()]
        keys = list(r)
        cells[keys.index("phenotype")] = r["phenotype"] if r["phenotype"] is not None else "—"
        cells[keys.index("pvalue")] = f"{r['pvalue']:.2e}"
        cells[keys.index("beta")] = f"{r['beta']:.3f}"
        out.append(cells)
    return out


def test_api_rows_match_the_page_table_cell_for_cell() -> None:
    for params in (
        {"q": "rs1042522", "p": "1"},
        {"q": "chr17:7676154"},
        {"q": "TP53", "p": "0.01"},
        {"q": "TP53", "p": "1"},
    ):
        _status, body = _api(params)
        assert _page_table(_get(params)) == _api_as_page_text(body["rows"]), params


def test_api_errors_carry_status_and_message() -> None:
    cases = [
        ({}, 400, "Enter a gene"),
        ({"q": "TP53", "p": "abc"}, 400, "isn't a valid p-value threshold"),
        ({"q": "!!"}, 400, "Couldn't recognize"),
        ({"q": "chr17:7000000-8000000"}, 400, "use the Data Browser for a region"),
        ({"q": "rs999"}, 404, "rs999 was not found."),
        ({"q": "NOPE1"}, 404, "Gene NOPE1 was not found."),
    ]
    for params, want_status, want_text in cases:
        status, body = _api(params)
        assert status == want_status, params
        assert want_text in body["error"], params
        assert "results" not in body


def test_page_links_to_the_api_tutorial() -> None:
    html = _get()
    assert 'href="/tutorial#request-from-api"' in html
    assert "import requests" not in html  # the walkthrough lives in the Tutorial


def test_hit_labels_without_a_position() -> None:
    assert Hit("p", 0.1).snp is None and Hit("p", 0.1).variant is None


def test_context_names_wrap_at_underscores_and_stay_escaped() -> None:
    row = ContextRow("Skin_Sun<b>", "d", "eQTL", False)
    assert str(row.context_html) == "Skin_<wbr>Sun&lt;b&gt;"


def test_page_context_cells_carry_wrap_hints() -> None:
    client = TestClient(create_app(repository=_repo()))
    html = client.get("/search-data", params={"q": "rs1042522", "p": "1"}).text
    assert '<div class="sd-context-name">Whole_<wbr>Blood</div>' in html


def test_table_columns_match_between_gene_and_variant_tables() -> None:
    import re

    def layout(html: str) -> tuple[float, list[float]]:
        card = float(re.search(r'class="card sd-card" style="width:([\d.]+)%"', html).group(1))
        colgroup = html[html.index("<colgroup>") : html.index("</colgroup>")]
        return card, [float(w) for w in re.findall(r"width:([\d.]+)%", colgroup)]

    gene_card, gene = layout(_get({"q": "TP53", "p": "0.01"}))
    var_card, var = layout(_get({"q": "rs1042522", "p": "1"}))
    assert len(gene) == 8 and len(var) == 6  # variant: no Lead SNP / Variant columns
    assert abs(sum(gene) - 100) < 0.1 and abs(sum(var) - 100) < 0.1
    assert gene_card == 100 and var_card == 76
    # Shared columns get the same absolute width in both tables (% of card x card width).
    shared_gene = [gene[i] for i in (0, 1, 2, 3, 6, 7)]
    for g, v in zip(shared_gene, var, strict=True):
        assert abs(g - v * var_card / 100) < 0.05, (shared_gene, var)
    assert gene[3] == 27  # Phenotype: 1.5x its original 18%


def test_phenotype_ids_wrap_at_colons_and_stay_escaped() -> None:
    assert (
        str(Hit("chr17:1:clu_1:<x>", 0.1).phenotype_html)
        == "chr17:<wbr>1:<wbr>clu_1:<wbr>&lt;x&gt;"
    )
    assert str(Hit(None, 0.1).phenotype_html) == ""


def test_fake_gene_phenotype_leads_skips_unlabelled_rows_and_keeps_the_min_p() -> None:
    repo = FakeQtlRepository(
        genes=[_TP53],
        associations=[
            EqtlAssociation(1, 141510, None, 17, 100, 1e-3, 0.1, 0.05, phenotype_id="P"),
            EqtlAssociation(1, 141510, None, 17, 200, 1e-2, 0.1, 0.05, phenotype_id="P"),  # worse
            EqtlAssociation(1, 141510, None, 17, 300, 1e-9, 0.1, 0.05),  # no phenotype_id
        ],
    )
    leads = repo.gene_phenotype_leads(_TP53, [1])
    assert [(d, s.phenotype_id, s.position, s.pvalue) for d, s in leads] == [(1, "P", 100, 1e-3)]
