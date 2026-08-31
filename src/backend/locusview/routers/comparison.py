"""Variant comparison table: one variant's association stats across the selected QTL + GWAS
datasets (the same dropdowns driving the Data Browser's multi-track plot — see
``routers/browser.py`` / ``static/js/browser.js``).

Backs ``partials/_variant_stats.html``. The only caller is Locus View's click-to-pin on a
multi-track panel point (caller already has ``chrom``/``position`` from the click — see
``static/js/multi-track-plot.js``), so this is position-based only, not rsID-based: the new
Postgres shards don't carry a usable per-row rsID (see ``connectpostgres.py``'s module docstring),
and ``(chrom, position)`` is indexed on every shard (QTL and GWAS alike) — see
``docs/process/status.md``.
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from locusview.requestinfo import QtlRepository, RepositoryTimeoutError
from locusview.templating import render as _render

_UNAVAILABLE_MESSAGE = (
    "<p class='muted'>This comparison needs a database index that hasn't been added yet "
    "(region/variant lookups aren't indexed the way gene lookups are) — see "
    "docs/process/status.md. Try comparing by gene instead.</p>"
)


def _parse_dataset_keys(datasets: str) -> tuple[list[int], list[int]]:
    """``"qtl:1,gwas:2"`` -> ``([1], [2])``. Unknown kinds / non-numeric ids are dropped, same
    tolerance as the multi-track endpoint."""
    qtl_ids: list[int] = []
    gwas_ids: list[int] = []
    for key in datasets.split(","):
        if not key:
            continue
        kind, _, id_str = key.partition(":")
        if not id_str.isdigit():
            continue
        if kind == "qtl":
            qtl_ids.append(int(id_str))
        elif kind == "gwas":
            gwas_ids.append(int(id_str))
    return qtl_ids, gwas_ids


def router(repo: QtlRepository) -> APIRouter:
    """Build the variant-comparison partial's single route."""
    router = APIRouter()

    @router.get("/browser/partials/variant-stats", response_class=HTMLResponse)
    def variant_stats(
        chrom: str,
        position: int,
        datasets: str = "",
    ) -> HTMLResponse:
        """The only caller (click-to-pin — see module docstring) always has an exact
        ``chrom``/``position`` in hand, so this doesn't need to resolve a locus itself."""
        qtl_ids, gwas_ids = _parse_dataset_keys(datasets)
        if not qtl_ids and not gwas_ids:
            return HTMLResponse("<p class='muted'>No datasets selected.</p>", status_code=400)

        qtl_by_id = {d.id: d for d in repo.datasets()}
        gwas_by_id = {g.id: g for g in repo.gwas_datasets()}

        title = f"chr{chrom}:{position}"
        # (pvalue, row) pairs keep sorting separate from the display-row dictionary.
        entries: list[tuple[float | None, dict[str, object]]] = []
        try:
            for did in qtl_ids:
                dataset = qtl_by_id.get(did)
                if dataset is None:
                    continue
                for qtl_hit in repo.associations_in_region(chrom, position, position, did):
                    entries.append(
                        (
                            qtl_hit.pvalue,
                            {
                                "tissue": f"{dataset.tissue} ({dataset.source})",
                                "kind": "QTL",
                                "pvalue": qtl_hit.pvalue,
                            },
                        )
                    )
            for did in gwas_ids:
                gwas_dataset = gwas_by_id.get(did)
                if gwas_dataset is None:
                    continue
                for gwas_hit in repo.gwas_associations_in_region(chrom, position, position, did):
                    trait = gwas_dataset.trait.replace("_", " ")
                    entries.append(
                        (
                            gwas_hit.pvalue,
                            {
                                "tissue": f"{trait} ({gwas_dataset.population})",
                                "kind": "GWAS",
                                "pvalue": gwas_hit.pvalue,
                            },
                        )
                    )
        except RepositoryTimeoutError:
            return HTMLResponse(_UNAVAILABLE_MESSAGE, status_code=503)

        # Most significant (lowest p) first; associations with no p-value sort last.
        entries.sort(key=lambda e: (e[0] is None, e[0] or 0))
        rows = [row for _, row in entries]

        return _render(
            "partials/_variant_stats.html",
            title=title,
            coord=title,
            rows=rows,
        )

    return router
