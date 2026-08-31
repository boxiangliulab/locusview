"""Data Browser page: the sidebar's cascading QTL/GWAS picker (Dataset -> QTL type -> Context /
Dataset -> Accession+Trait) driving the stacked multi-track LocusZoom plot
(:mod:`locusview.routers.locus`'s multi-track endpoint). This module renders the page shell plus
five small JSON "catalog" endpoints the picker calls live as the user narrows each box down
(``static/js/browser-picker.js``) — deliberately not one big flat list (doesn't scale visually as
more datasets get ingested) and deliberately live per-request (not cached), so a newly-ingested
dataset shows up without a deploy.

No new repository/SQL methods needed: every level is a grouping of ``repo.datasets()`` /
``repo.gwas_datasets()`` (parsed via ``Dataset.catalog_parts``), called
fresh on every request.
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, JSONResponse

from locusview.requestinfo import Dataset, GwasDataset, QtlRepository
from locusview.templating import render as _render


def _qtl_dataset_names(datasets: list[Dataset]) -> list[str]:
    """Distinct QTL dataset names (the picker's first dropdown), e.g. ``["GTEx_v10", "CIMA"]``."""
    return sorted({d.catalog_parts[0] for d in datasets})


def _qtl_types(datasets: list[Dataset], dataset: str) -> list[str]:
    """QTL types available for one dataset name (the picker's second dropdown), e.g.
    ``["eQTL", "sQTL"]`` for ``GTEx_v10``."""
    types: set[str] = set()
    for d in datasets:
        dataset_name, qtl_type, _ = d.catalog_parts
        if dataset_name == dataset:
            types.add(qtl_type)
    return sorted(types)


def _qtl_contexts(datasets: list[Dataset], dataset: str, qtl_type: str) -> list[dict[str, object]]:
    """Context dropdown options for one dataset + QTL type. ``Dataset.tissue`` is already the
    display label — level 2 when present, else level 1 (see ``connectpostgres.py``'s
    ``datasets()``) — so nothing to reformat here."""
    options = []
    for d in datasets:
        dataset_name, dataset_qtl_type, _ = d.catalog_parts
        if dataset_name == dataset and dataset_qtl_type == qtl_type:
            options.append({"id": d.id, "label": d.tissue})
    return sorted(options, key=lambda o: str(o["label"]))


def _gwas_dataset_names(gwas_datasets: list[GwasDataset]) -> list[str]:
    """Distinct GWAS dataset/source names (the GWAS picker's first dropdown)."""
    return sorted({g.source for g in gwas_datasets})


def _gwas_options_for(gwas_datasets: list[GwasDataset], dataset: str) -> list[dict[str, object]]:
    """Accession+trait options for one GWAS dataset name (the picker's second, multi-select box)."""
    options = [
        {"id": g.id, "label": f"{g.accession} — {g.trait.replace('_', ' ')}"}
        for g in gwas_datasets
        if g.source == dataset
    ]
    return sorted(options, key=lambda o: str(o["label"]))


def _preselected_qtl_rows(
    datasets: list[Dataset], selected_ids: list[int]
) -> list[dict[str, object]]:
    """Group already-selected ``qtl:<id>`` ids (e.g. from a deep-linked ``?datasets=``) by
    (dataset, qtl_type) into rows the picker can hydrate — same shape it builds interactively."""
    by_id = {d.id: d for d in datasets}
    groups: dict[tuple[str, str], list[int]] = {}
    order: list[tuple[str, str]] = []
    for id_ in selected_ids:
        d = by_id.get(id_)
        if d is None:
            continue
        dataset_name, qtl_type, _ = d.catalog_parts
        key = (dataset_name, qtl_type)
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(id_)
    return [{"dataset": ds, "qtl_type": qt, "context_ids": groups[(ds, qt)]} for ds, qt in order]


def _preselected_gwas_rows(
    gwas_datasets: list[GwasDataset], selected_ids: list[int]
) -> list[dict[str, object]]:
    """GWAS counterpart of :func:`_preselected_qtl_rows` — groups already-selected ``gwas:<id>``
    ids by dataset name so the picker can hydrate itself."""
    by_id = {g.id: g for g in gwas_datasets}
    groups: dict[str, list[int]] = {}
    order: list[str] = []
    for id_ in selected_ids:
        g = by_id.get(id_)
        if g is None:
            continue
        if g.source not in groups:
            groups[g.source] = []
            order.append(g.source)
        groups[g.source].append(id_)
    return [{"dataset": ds, "option_ids": groups[ds]} for ds in order]


def _parse_ids(selected: list[str], kind: str) -> list[int]:
    """Pull the numeric ids out of ``"{kind}:<id>"`` keys (e.g. ``kind="qtl"`` from ``["qtl:1",
    "gwas:2"]`` -> ``[1]``), ignoring keys of the other kind or malformed ones."""
    out = []
    for key in selected:
        k, _, id_str = key.partition(":")
        if k == kind and id_str.isdigit():
            out.append(int(id_str))
    return out


def router(repo: QtlRepository) -> APIRouter:
    """Build the Data Browser's routes: the page shell plus the five picker catalog endpoints."""
    router = APIRouter()

    @router.get("/browser", response_class=HTMLResponse)
    def browser(
        locus_mode: str = "gene",
        datasets: str = "",
        gene: str = "",
        region: str = "",
        variant: str = "",
    ) -> HTMLResponse:
        """``datasets`` is a comma-separated list of ``qtl:<id>`` / ``gwas:<id>`` keys — grouped
        below into "preselected rows" so the cascading picker can hydrate itself on load."""
        qtl_datasets = repo.datasets()
        gwas_datasets = repo.gwas_datasets()

        selected = [key for key in datasets.split(",") if key]
        if not selected and qtl_datasets:
            selected = [f"qtl:{qtl_datasets[0].id}"]  # a sensible default so Run Query has data

        return _render(
            "browser.html",
            active="browser",
            preselected_qtl_rows=_preselected_qtl_rows(
                qtl_datasets, _parse_ids(selected, "qtl")
            ),
            preselected_gwas_rows=_preselected_gwas_rows(
                gwas_datasets, _parse_ids(selected, "gwas")
            ),
            has_qtl_datasets=bool(qtl_datasets),
            has_gwas_datasets=bool(gwas_datasets),
            locus_mode=locus_mode,
            gene=gene,
            region=region,
            variant=variant,
        )

    @router.get("/api/browser/qtl/datasets")
    def qtl_dataset_names() -> JSONResponse:
        """The picker's QTL "Dataset" dropdown, computed fresh from ``repo.datasets()``."""
        return JSONResponse(_qtl_dataset_names(repo.datasets()))

    @router.get("/api/browser/qtl/types")
    def qtl_types(dataset: str) -> JSONResponse:
        """The picker's QTL "Type" dropdown, once a dataset is chosen."""
        return JSONResponse(_qtl_types(repo.datasets(), dataset))

    @router.get("/api/browser/qtl/contexts")
    def qtl_contexts(dataset: str, qtl_type: str) -> JSONResponse:
        """The picker's QTL "Context" multi-select, once dataset + type are chosen."""
        return JSONResponse(_qtl_contexts(repo.datasets(), dataset, qtl_type))

    @router.get("/api/browser/gwas/datasets")
    def gwas_dataset_names() -> JSONResponse:
        """The picker's GWAS "Dataset" dropdown, computed fresh from ``repo.gwas_datasets()``."""
        return JSONResponse(_gwas_dataset_names(repo.gwas_datasets()))

    @router.get("/api/browser/gwas/options")
    def gwas_options(dataset: str) -> JSONResponse:
        """The picker's GWAS accession+trait multi-select, once a dataset is chosen."""
        return JSONResponse(_gwas_options_for(repo.gwas_datasets(), dataset))

    return router
