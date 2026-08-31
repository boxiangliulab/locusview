"""Locus View: association-data feeds for the Data Browser's multi-track plot and the (now
gene-page-only) single-track regional plot.

``/api/locus/multi-track`` is what the Data Browser's three locus tabs (gene/region/variant)
actually call today — see :func:`multi_track`'s docstring for the exact per-tab DB-request and
frontend-display spec. ``/api/gene/{key}/regional`` (the gene-anchored single-track form) and
``/api/locus/regional`` (its region/variant-mode generalization) back ``partials/_regional_plot.
html`` / ``static/js/regional-plot.js`` — only embedded in the gene page (``gene.html``) now that
the Data Browser has moved to the multi-track plot; kept for the gene page's own LD-colored view.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TypeVar

from fastapi import APIRouter, Response
from fastapi.responses import JSONResponse

from locusview.requestinfo import (
    CHROMS,
    POPULATIONS,
    EqtlAssociation,
    Gene,
    GwasAssociation,
    QtlRepository,
    RepositoryTimeoutError,
)
from locusview.viz import ld_legend, neg_log10_p, r2_color

_UNINDEXED_QUERY_MESSAGE = (
    "This query needs a database index that hasn't been added yet (region/variant lookups "
    "aren't indexed the way gene lookups are) — see docs/process/status.md. Try gene mode, "
    "or a tissue with fewer variants."
)

# +/- around a variant position for variant-mode locus windows — shared by both the legacy
# single-track /api/locus/regional endpoint and the Data Browser's multi-track variant tab (see
# multi_track's docstring for its per-tab spec). Same size as _GENE_WINDOW, deliberately: a raw
# rsID/position query has no natural cis window of its own, so it borrows the gene-mode one.
_VARIANT_WINDOW = 1_000_000

# +/- around a gene's start for the multi-track plot's gene-mode window (Data Browser only — the
# single-track /api/locus/regional and /api/gene/{key}/regional endpoints keep using the gene's
# own span instead). Anchored to gene *start*, not the gene body, per the product spec.
_GENE_WINDOW = 1_000_000


def _lead_of(cis: list[EqtlAssociation]) -> EqtlAssociation | None:
    """The default lead: the min-p variant, falling back to the first row if none has a p-value.
    Requires ``pvalue > 0`` (not just non-``None``) — matching :func:`viz.neg_log10_p`'s own
    accepted-input rule, so the chosen lead is always one that actually renders (a p=0.0 row is a
    source-data underflow that gets dropped from display; picking it as "lead" would otherwise
    make no variant end up marked ``is_lead`` at all)."""
    lead: EqtlAssociation | None = None
    for a in cis:
        if a.pvalue is None or a.pvalue <= 0:
            continue
        if lead is None or lead.pvalue is None or a.pvalue < lead.pvalue:
            lead = a
    if lead is None and cis:
        lead = cis[0]
    return lead


def _variants_payload(
    cis: list[EqtlAssociation], lead: EqtlAssociation | None, r2map: dict[int, float]
) -> tuple[list[dict[str, object]], list[int]]:
    """Shape the single-track regional-plot response's per-point fields (position, r², LD color,
    is_lead) plus the list of plotted positions (used to derive the response's ``region``
    bounds)."""
    variants: list[dict[str, object]] = []
    positions: list[int] = []
    for a in cis:
        log_p = neg_log10_p(a.pvalue)
        if log_p is None:
            continue
        is_lead = lead is not None and a.rs_id == lead.rs_id and a.position == lead.position
        has_rsid = a.rs_id is not None
        # r2 None => the panel returned no pair => r² is below the 0.2 floor, not "no data".
        r2 = r2map.get(a.rs_id) if a.rs_id is not None else None
        variants.append(
            {
                "rs_id": a.rs_id,
                "gene_id": a.gene_id,  # lets a click-to-pin ask for a fast, gene_id-scoped
                # comparison lookup (see routers.comparison) instead of an unindexed rs_id scan.
                "chrom": str(a.chrom),
                "position": a.position,
                "pvalue": a.pvalue,
                "log_pvalue": log_p,
                "beta": a.beta,
                "se": a.se,
                "r2": r2,
                "is_lead": is_lead,
                "color": r2_color(r2, is_lead=is_lead, has_rsid=has_rsid),
            }
        )
        positions.append(a.position)
    return variants, positions


def _regional_response(
    cis: list[EqtlAssociation],
    *,
    label: str,
    gene_id: int | None,
    tissue: str,
    dataset_id: int,
    fallback_chrom: str,
    population: str,
    repo: QtlRepository,
) -> JSONResponse:
    """Build the single-track regional-plot JSON response shared by ``/api/gene/{key}/regional``
    and ``/api/locus/regional``: pick the default lead, fetch its LD if it has an rsID, then shape
    every variant's plot point via :func:`_variants_payload`."""
    lead = _lead_of(cis)
    r2map: dict[int, float] = {}
    reference_present = False
    if lead is not None and lead.rs_id is not None:
        r2map = repo.ld_r2(str(lead.chrom), lead.rs_id, population)
        reference_present = bool(r2map)
        r2map[lead.rs_id] = 1.0

    variants, positions = _variants_payload(cis, lead, r2map)
    return JSONResponse(
        {
            "gene": label,
            "gene_id": gene_id,
            "tissue": tissue,
            "dataset_id": dataset_id,
            "build": "GRCh38",
            "population": population,
            "reference_present_in_1000g": reference_present,
            "region": {
                "chrom": str(lead.chrom) if lead else fallback_chrom,
                "start": min(positions) if positions else 0,
                "end": max(positions) if positions else 0,
            },
            "lead": None
            if lead is None
            else {
                "rs_id": lead.rs_id,
                "position": lead.position,
                "log_pvalue": neg_log10_p(lead.pvalue),
            },
            "ld_legend": ld_legend(),
            "variants": variants,
        }
    )


_A = TypeVar("_A", EqtlAssociation, GwasAssociation)


def _min_p(assocs: Sequence[_A]) -> _A | None:
    """The min-p association in ``assocs`` (falling back to the first row if none has a
    p-value) — generic over :class:`EqtlAssociation` and :class:`GwasAssociation`, both of
    which just need a ``.pvalue``. Same logic (and same ``pvalue > 0`` requirement — see its
    docstring) as :func:`_lead_of`, generalized for multi-track."""
    best: _A | None = None
    for a in assocs:
        if a.pvalue is None or a.pvalue <= 0:
            continue
        if best is None or best.pvalue is None or a.pvalue < best.pvalue:
            best = a
    if best is None and assocs:
        best = assocs[0]
    return best


def _track_variants(assocs: Sequence[_A], lead: _A | None) -> list[dict[str, object]]:
    """Shape one multi-track panel's per-point fields (position, is_lead, rs_id/variant_id when
    available, phenotype_id for QTL) — the raw, un-LD-colored variant list the frontend fetches
    LD for itself on demand (see ``static/js/multi-track-plot.js``)."""
    out: list[dict[str, object]] = []
    for a in assocs:
        log_p = neg_log10_p(a.pvalue)
        if log_p is None:
            continue
        row: dict[str, object] = {
            "position": a.position,
            "pvalue": a.pvalue,
            "log_pvalue": log_p,
            "is_lead": lead is not None and a.position == lead.position,
        }
        # rs_id/ref/alt exist on both EqtlAssociation and GwasAssociation (both are enriched via
        # the same variant_rsid_mapping_raw join — see connectpostgres.py); phenotype_id is
        # QTL-only (GWAS has no phenotype concept). phenotype_id lets the frontend filter one
        # track's variants down to a single selected phenotype (see static/js/multi-track-plot.js's
        # renderQtlPanels) without a second fetch.
        if isinstance(a, (EqtlAssociation, GwasAssociation)):
            row["rs_id"] = a.rs_id
            row["variant_id"] = (
                f"chr{a.chrom}_{a.position}_{a.ref}_{a.alt}" if a.ref and a.alt else None
            )
        if isinstance(a, EqtlAssociation):
            row["phenotype_id"] = a.phenotype_id
        out.append(row)
    return out


# A full 1 Mb region can legitimately match 100+ distinct phenotypes (dense cis-window testing,
# confirmed live) — capped here to keep the results table and response payload sane.
_MAX_PHENOTYPE_ROWS = 50


def _group_by_phenotype(assocs: Sequence[EqtlAssociation]) -> list[dict[str, object]]:
    """Group a QTL track's associations by ``phenotype_id`` — a genomic window can legitimately
    contain variants tested against several different phenotypes at once (see
    ``connectpostgres.py``'s ``associations_in_region``/``cis_associations`` docstrings) — one row
    per phenotype with its lead (min-p) variant. Sorted by significance, capped at
    :data:`_MAX_PHENOTYPE_ROWS`. Backs the Data Browser's QTL results table."""
    groups: dict[str | None, list[EqtlAssociation]] = {}
    for a in assocs:
        groups.setdefault(a.phenotype_id, []).append(a)

    entries: list[tuple[float | None, dict[str, object]]] = []
    for phenotype_id, group in groups.items():
        lead = _min_p(group)
        pvalue = lead.pvalue if lead else None
        entries.append(
            (
                pvalue,
                {
                    "phenotype_id": phenotype_id,
                    "gene_id": lead.gene_id if lead else None,
                    "lead_position": lead.position if lead else None,
                    "lead_pvalue": pvalue,
                    "n": len(group),
                },
            )
        )
    entries.sort(key=lambda e: (e[0] is None, e[0] if e[0] is not None else 0.0))
    return [row for _, row in entries[:_MAX_PHENOTYPE_ROWS]]


def _qtl_track(
    repo: QtlRepository,
    dataset_id: int,
    gene: Gene | None,
    chrom: str,
    start: int,
    end: int,
) -> dict[str, object] | None:
    """One QTL panel for the multi-track plot — see ``multi_track``'s docstring for the full
    per-locus-tab request/display spec this implements. The initial request returns phenotype IDs
    only: gene mode uses ``phenotypes_for_gene`` (gene_id for eQTL/sQTL, or GENCODE gene start
    inside a caQTL peak); region/variant mode uses ``phenotype_summaries_in_region``. Association
    values are loaded later by ``/api/locus/qtl-phenotype`` after the user checks a row."""
    dataset = next((d for d in repo.datasets() if d.id == dataset_id), None)
    if dataset is None:
        return None
    # Values are fetched per selected phenotype, on demand — see this function's docstring.
    assocs: list[EqtlAssociation] = []
    summaries = None
    if gene is not None:
        summaries = repo.phenotypes_for_gene(gene, dataset_id)
    else:
        summaries = repo.phenotype_summaries_in_region(
            chrom, start, end, dataset_id, _MAX_PHENOTYPE_ROWS
        )
    lead = _min_p(assocs)
    if lead is None and summaries:
        best = summaries[0]
        lead_payload = (
            None
            if best.lead_position is None
            else {"position": best.lead_position, "log_pvalue": neg_log10_p(best.lead_pvalue)}
        )
    else:
        lead_payload = (
            None
            if lead is None
            else {"position": lead.position, "log_pvalue": neg_log10_p(lead.pvalue)}
        )
    dataset_name, qtl_type, population = dataset.catalog_parts
    # Every locus mode deliberately leaves variants empty. The browser requests one selected
    # phenotype's bounded, enriched values from /api/locus/qtl-phenotype on demand.
    variants = _track_variants(assocs, lead) if gene is not None else []
    return {
        "key": f"qtl:{dataset_id}",
        "kind": "qtl",
        "dataset_id": dataset_id,
        "label": f"{dataset.source} — {dataset.tissue}",
        "dataset": dataset_name,
        "qtl_type": qtl_type,
        "population": population,
        "context": dataset.tissue,
        "lead": lead_payload,
        "variants": variants,
        "phenotypes": _group_by_phenotype(assocs)
        if summaries is None
        else [
            {
                "phenotype_id": s.phenotype_id,
                "gene_id": s.gene_id,
                "lead_position": s.lead_position,
                "lead_pvalue": s.lead_pvalue,
                "n": s.n,
            }
            for s in summaries
        ],
    }


def _gwas_track(
    repo: QtlRepository, dataset_id: int, chrom: str, start: int, end: int
) -> dict[str, object] | None:
    """One GWAS panel for the multi-track plot — always window-anchored (no gene concept)."""
    gwas_dataset = next((g for g in repo.gwas_datasets() if g.id == dataset_id), None)
    if gwas_dataset is None:
        return None
    assocs = repo.gwas_associations_in_region(chrom, start, end, dataset_id)
    lead = _min_p(assocs)
    trait = gwas_dataset.trait.replace("_", " ")
    return {
        "key": f"gwas:{dataset_id}",
        "kind": "gwas",
        "label": f"{trait} ({gwas_dataset.population})",
        "lead": None
        if lead is None
        else {"position": lead.position, "log_pvalue": neg_log10_p(lead.pvalue)},
        "variants": _track_variants(assocs, lead),
    }


def router(repo: QtlRepository) -> APIRouter:
    """Build the Locus View routes: the two regional-plot feeds, the Data Browser's multi-track
    feed, the per-phenotype LD-enrichment endpoint, and the shared LD lookup."""
    router = APIRouter()

    @router.get("/api/gene/{key}/regional")
    def regional(key: str, tissue: int, population: str = "EUR") -> Response:
        """Association points for one gene x one tissue, with r² to the default (min-p) lead."""
        gene = repo.resolve_gene(key)
        if gene is None:
            return JSONResponse({"error": f"gene not found: {key}"}, status_code=404)
        if population not in POPULATIONS:
            return JSONResponse({"error": f"unknown population: {population}"}, status_code=400)
        dataset = next((d for d in repo.datasets() if d.id == tissue), None)
        if dataset is None:
            return JSONResponse({"error": f"unknown tissue/dataset: {tissue}"}, status_code=404)

        cis = repo.cis_associations(gene.gene_id, tissue)
        return _regional_response(
            cis,
            label=gene.symbol,
            gene_id=gene.gene_id,
            tissue=dataset.tissue,
            dataset_id=tissue,
            fallback_chrom=gene.chrom,
            population=population,
            repo=repo,
        )

    @router.get("/api/locus/regional")
    def locus_regional(
        locus_mode: str,
        tissue: int,
        population: str = "EUR",
        gene: str | None = None,
        chrom: str | None = None,
        start: int | None = None,
        end: int | None = None,
        rsid: int | None = None,
        position: int | None = None,
    ) -> Response:
        """Generalized regional-plot feed for the Data Browser: gene, region, or variant mode,
        all anchored to one selected dataset/tissue (see ``/api/gene/{key}/regional`` for the
        gene-page's dedicated gene-mode endpoint, which this mirrors). ``tissue`` names the same
        query param as that endpoint so both share ``static/js/regional-plot.js`` unchanged.
        """
        if population not in POPULATIONS:
            return JSONResponse({"error": f"unknown population: {population}"}, status_code=400)
        dataset_obj = next((d for d in repo.datasets() if d.id == tissue), None)
        if dataset_obj is None:
            return JSONResponse({"error": f"unknown tissue/dataset: {tissue}"}, status_code=404)

        if locus_mode == "gene":
            if not gene:
                return JSONResponse({"error": "gene is required for gene mode"}, status_code=400)
            g = repo.resolve_gene(gene)
            if g is None:
                return JSONResponse({"error": f"gene not found: {gene}"}, status_code=404)
            cis = repo.cis_associations(g.gene_id, tissue)
            return _regional_response(
                cis,
                label=g.symbol,
                gene_id=g.gene_id,
                tissue=dataset_obj.tissue,
                dataset_id=tissue,
                fallback_chrom=g.chrom,
                population=population,
                repo=repo,
            )

        if locus_mode == "region":
            if chrom is None or start is None or end is None:
                return JSONResponse(
                    {"error": "chrom, start, end are required for region mode"}, status_code=400
                )
            if chrom not in CHROMS:
                return JSONResponse({"error": f"unknown chromosome: {chrom}"}, status_code=400)
            try:
                cis = repo.associations_in_region(chrom, start, end, tissue)
            except RepositoryTimeoutError:
                return JSONResponse({"error": _UNINDEXED_QUERY_MESSAGE}, status_code=503)
            return _regional_response(
                cis,
                label=f"chr{chrom}:{start}-{end}",
                gene_id=None,
                tissue=dataset_obj.tissue,
                dataset_id=tissue,
                fallback_chrom=chrom,
                population=population,
                repo=repo,
            )

        if locus_mode == "variant":
            try:
                if rsid is not None:
                    hits = repo.associations_for_rsid(rsid, [tissue])
                    if not hits:
                        return JSONResponse(
                            {"error": f"variant rs{rsid} not found in this dataset"},
                            status_code=404,
                        )
                    center, variant_chrom = hits[0].position, str(hits[0].chrom)
                elif chrom is not None and position is not None:
                    center, variant_chrom = position, chrom
                else:
                    return JSONResponse(
                        {"error": "rsid, or chrom + position, is required for variant mode"},
                        status_code=400,
                    )
                if variant_chrom not in CHROMS:
                    return JSONResponse(
                        {"error": f"unknown chromosome: {variant_chrom}"}, status_code=400
                    )
                cis = repo.associations_in_region(
                    variant_chrom,
                    max(0, center - _VARIANT_WINDOW),
                    center + _VARIANT_WINDOW,
                    tissue,
                )
            except RepositoryTimeoutError:
                return JSONResponse({"error": _UNINDEXED_QUERY_MESSAGE}, status_code=503)
            return _regional_response(
                cis,
                label=f"chr{variant_chrom}:{center} (+/-{_VARIANT_WINDOW // 1_000_000}MB)",
                gene_id=None,
                tissue=dataset_obj.tissue,
                dataset_id=tissue,
                fallback_chrom=variant_chrom,
                population=population,
                repo=repo,
            )

        return JSONResponse({"error": f"unknown locus_mode: {locus_mode}"}, status_code=400)

    @router.get("/api/locus/multi-track")
    def multi_track(
        locus_mode: str,
        datasets: str,
        gene: str | None = None,
        chrom: str | None = None,
        start: int | None = None,
        end: int | None = None,
        rsid: int | None = None,
        position: int | None = None,
    ) -> Response:
        """Stacked multi-panel feed for the Data Browser's three locus tabs: one track per
        selected QTL/GWAS dataset (``datasets`` = comma-separated ``qtl:<id>``/``gwas:<id>``
        keys), all sharing one canonical genomic window resolved from ``locus_mode``. GWAS tracks
        (``_gwas_track``) are always window-anchored, identically across all three modes — GWAS is
        trait x variant, not gene x variant, so it has no phenotype concept to branch on. The spec
        below is for QTL tracks (``_qtl_track``) specifically, per ``locus_mode``:

        - **``gene``**: which phenotypes get matched depends on the dataset's *kind*, decided by
          :meth:`QtlRepository`'s ``phenotypes_for_gene``:
          eQTL/pQTL/sQTL-style datasets (phenotype table's ``gene_id`` column populated) match the
          phenotype list **tested against this gene's ``gene_id``** directly. caQTL-style datasets
          (``gene_id`` is ``NULL`` on every row — chromatin peaks aren't genes) instead match the
          phenotype list whose peak range **contains this gene's start position**. Either way, the
          frontend always shows a window of **gene start +/-1 MB** (``_GENE_WINDOW``) — the same
          fixed window regardless of which branch matched, gene coordinates themselves aren't used
          beyond finding *which* phenotypes qualify.
        - **``region``**: matches every phenotype that **overlaps the given region**
          (``phenotype_summaries_in_region``, chrom/position-bounded, no gene concept) — a region
          can legitimately overlap 100+ phenotypes at once. The frontend
          shows **exactly the region the user typed**, unexpanded (``window_start``/``window_end``
          are the caller's own ``start``/``end``, verbatim).
        - **``variant``**: resolves the variant to a position first (``resolve_variant`` for a bare
          rsID, or the given ``chrom``/``position`` directly), then matches the phenotype list at
          that exact position the same way region mode does (still phenotype-only initially,
          just position-bounded to one point before windowing). The frontend shows **variant
          position +/-1 MB** (``_VARIANT_WINDOW`` — shared with the older single-track
          ``/api/locus/regional`` endpoint's variant mode, same size).
        """
        keys = [k for k in datasets.split(",") if k]
        if not keys:
            return JSONResponse(
                {"error": "datasets is required (comma-separated qtl:<id>/gwas:<id>)"},
                status_code=400,
            )

        resolved_gene: Gene | None = None
        window_chrom: str
        window_start: int
        window_end: int
        label: str

        if locus_mode == "gene":
            if not gene:
                return JSONResponse({"error": "gene is required for gene mode"}, status_code=400)
            resolved_gene = repo.resolve_gene(gene)
            if resolved_gene is None:
                return JSONResponse({"error": f"gene not found: {gene}"}, status_code=404)
            window_chrom = resolved_gene.chrom
            window_start = max(0, resolved_gene.start - _GENE_WINDOW)
            window_end = resolved_gene.start + _GENE_WINDOW
            label = resolved_gene.symbol

        elif locus_mode == "region":
            if chrom is None or start is None or end is None:
                return JSONResponse(
                    {"error": "chrom, start, end are required for region mode"}, status_code=400
                )
            if chrom not in CHROMS:
                return JSONResponse({"error": f"unknown chromosome: {chrom}"}, status_code=400)
            window_chrom, window_start, window_end = chrom, start, end
            label = f"chr{chrom}:{start}-{end}"

        elif locus_mode == "variant":
            try:
                if rsid is not None:
                    # A standalone existence check (see resolve_variant's docstring) — no longer
                    # needs a QTL dataset selected first, unlike the old associations_for_rsid
                    # based lookup this replaced.
                    resolved = repo.resolve_variant(rsid)
                    if resolved is None:
                        return JSONResponse(
                            {"error": f"variant rs{rsid} not found"}, status_code=404
                        )
                    window_chrom, center = resolved
                elif chrom is not None and position is not None:
                    if chrom not in CHROMS:
                        return JSONResponse(
                            {"error": f"unknown chromosome: {chrom}"}, status_code=400
                        )
                    window_chrom, center = chrom, position
                else:
                    return JSONResponse(
                        {"error": "rsid, or chrom + position, is required for variant mode"},
                        status_code=400,
                    )
            except RepositoryTimeoutError:
                return JSONResponse({"error": _UNINDEXED_QUERY_MESSAGE}, status_code=503)
            window_start = max(0, center - _VARIANT_WINDOW)
            window_end = center + _VARIANT_WINDOW
            label = f"chr{window_chrom}:{center} (+/-{_VARIANT_WINDOW // 1_000_000}MB)"

        else:
            return JSONResponse({"error": f"unknown locus_mode: {locus_mode}"}, status_code=400)

        tracks: list[dict[str, object]] = []
        try:
            for key in keys:
                kind, _, id_str = key.partition(":")
                if not id_str.isdigit():
                    continue
                dataset_id = int(id_str)
                track: dict[str, object] | None
                if kind == "qtl":
                    track = _qtl_track(
                        repo, dataset_id, resolved_gene, window_chrom, window_start, window_end
                    )
                elif kind == "gwas":
                    track = _gwas_track(repo, dataset_id, window_chrom, window_start, window_end)
                else:
                    continue
                if track is not None:
                    tracks.append(track)
        except RepositoryTimeoutError:
            return JSONResponse({"error": _UNINDEXED_QUERY_MESSAGE}, status_code=503)

        return JSONResponse(
            {
                "label": label,
                "gene": (
                    {
                        "symbol": resolved_gene.symbol,
                        "ensembl_id": resolved_gene.ensembl_id,
                    }
                    if resolved_gene is not None
                    else None
                ),
                "region": {"chrom": window_chrom, "start": window_start, "end": window_end},
                "tracks": tracks,
            }
        )

    @router.get("/api/locus/qtl-phenotype")
    def qtl_phenotype(
        dataset_id: int, phenotype_id: str, chrom: str, start: int, end: int
    ) -> Response:
        """Enriched (rs_id-carrying) variants for ONE QTL phenotype, clipped to ``[start, end]``.

        All gene/region/variant initial requests return phenotype IDs only. Once the user checks
        one row, this endpoint fetches that phenotype's association values, already bounded to the
        displayed window in SQL, and enriches them for LD coloring."""
        if chrom not in CHROMS:
            return JSONResponse({"error": f"unknown chromosome: {chrom}"}, status_code=400)
        try:
            assocs = repo.associations_for_phenotype(
                dataset_id, phenotype_id, chrom, start, end
            )
        except RepositoryTimeoutError:
            return JSONResponse({"error": _UNINDEXED_QUERY_MESSAGE}, status_code=503)
        lead = _min_p(assocs)
        return JSONResponse({"variants": _track_variants(assocs, lead)})

    @router.get("/api/ld")
    def ld(chrom: str, lead: int, population: str = "EUR") -> Response:
        """r² of every variant to the given lead — for re-coloring on a user-clicked lead."""
        if chrom not in CHROMS:
            return JSONResponse({"error": f"unknown chromosome: {chrom}"}, status_code=400)
        if population not in POPULATIONS:
            return JSONResponse({"error": f"unknown population: {population}"}, status_code=400)
        r2map = repo.ld_r2(chrom, lead, population)
        reference_present = bool(r2map)
        r2map[lead] = 1.0
        return JSONResponse(
            {
                "lead_rs_id": lead,
                "chrom": chrom,
                "population": population,
                "reference_present_in_1000g": reference_present,
                "r2": {str(k): v for k, v in r2map.items()},
            }
        )

    return router
