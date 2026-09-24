"""Home page: hero stats, the available QTL + GWAS dataset tables, the tissue body map, and
citations.

Everything here is derived live from the repository (:meth:`QtlRepository.datasets`,
:meth:`~QtlRepository.gwas_datasets`, :meth:`~QtlRepository.qtl_contexts` — real counts, no
placeholder numbers) plus the static citation list in :mod:`locusview.content.citations` and the
static tissue -> body-region mapping in :mod:`locusview.content.body_map`.
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from locusview.content.body_map import ANATOMOGRAM_SVG, REGIONS, region_for_tissue
from locusview.content.citations import CITATIONS
from locusview.requestinfo import Dataset, GwasDataset, QtlContextEntry, QtlRepository
from locusview.templating import render as _render

# Friendly display name for a known catalog `source` prefix. Anything else falls back to the raw
# source string rather than inventing a description for a dataset we don't actually know about.
_SOURCE_LABELS: dict[str, str] = {
    "gtex": "Genotype-Tissue Expression",
    "eqtl-catalogue": "eQTL Catalogue",
}


def _dataset_table(datasets: list[Dataset]) -> list[dict[str, object]]:
    """Group the flat per-tissue catalog by ``source`` into one row per integrated dataset."""
    subdatasets_by_source: dict[str, list[Dataset]] = {}
    for d in datasets:
        subdatasets_by_source.setdefault(d.source, []).append(d)

    rows = []
    for source, subdatasets in sorted(subdatasets_by_source.items()):
        dataset, qtl_type, population = subdatasets[0].catalog_parts
        rows.append(
            {
                "source": source,
                "label": _SOURCE_LABELS.get(dataset.lower(), dataset),
                "qtl_type": qtl_type,
                "population": population,
                # repo.datasets() contains one row per ready qtl_lists row, so this is the live
                # database count of materialized sub-datasets, not a static tissue count.
                "n_subdatasets": len(subdatasets),
            }
        )
    return rows


def _gwas_dataset_table(gwas_datasets: list[GwasDataset]) -> list[dict[str, object]]:
    """One row per GWAS trait — already the natural granularity (unlike QTL, there's no
    per-tissue grouping to do)."""
    return [
        {
            "id": g.id,
            "trait": g.trait,
            "population": g.population,
            "source": g.source,
            "accession": g.accession,
        }
        for g in sorted(gwas_datasets, key=lambda g: g.trait)
    ]


def _body_map_regions(contexts: list[QtlContextEntry]) -> dict[str, list[dict[str, object]]]:
    """Group qtl_contexts by body-map region id (see content/body_map.py) for the hover/click
    panel. Contexts whose tissue name doesn't map to a drawn region land under ``"other"``."""
    grouped: dict[str, list[dict[str, object]]] = {}
    for c in contexts:
        region = region_for_tissue(c.level_1) or "other"
        grouped.setdefault(region, []).append(
            {
                "qtl_list_id": c.qtl_list_id,
                "level_1": c.level_1,
                "level_2": c.level_2,
                "dataset_label": c.dataset_label,
            }
        )
    return grouped


def router(repo: QtlRepository) -> APIRouter:
    """Build the Home page's single route."""
    router = APIRouter()

    @router.get("/", response_class=HTMLResponse)
    def home() -> HTMLResponse:
        """Render the Home page: dataset tables, body map, and citations, all live from ``repo``."""
        datasets = repo.datasets()
        dataset_rows = _dataset_table(datasets)
        gwas_datasets = repo.gwas_datasets()
        gwas_rows = _gwas_dataset_table(gwas_datasets)
        body_map_regions = _body_map_regions(repo.qtl_contexts())
        return _render(
            "home.html",
            active="home",
            n_datasets=len(dataset_rows) + len(gwas_rows),
            n_tissues=len(datasets),
            dataset_rows=dataset_rows,
            gwas_rows=gwas_rows,
            body_map_regions=body_map_regions,
            body_map_region_labels=REGIONS,
            anatomogram_svg=ANATOMOGRAM_SVG,
            citations=CITATIONS,
        )

    return router
