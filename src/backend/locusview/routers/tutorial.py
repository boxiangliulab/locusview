"""Tutorial page: a short guide plus live, row-level QTL and GWAS dataset catalogs."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from locusview.requestinfo import QtlRepository
from locusview.templating import render as _render


def router(repo: QtlRepository) -> APIRouter:
    """Build the Tutorial page from the repository's current ready dataset catalogs."""
    router = APIRouter()

    @router.get("/tutorial", response_class=HTMLResponse)
    def tutorial() -> HTMLResponse:
        """Show usage guidance and the concrete GWAS/QTL datasets available to query."""
        qtl_rows = []
        for entry in repo.datasets():
            dataset, qtl_type, population = entry.catalog_parts
            qtl_rows.append(
                {
                    "id": entry.id,
                    "dataset": dataset,
                    "source_project_id": entry.source_project_id or "",
                    "qtl_type": qtl_type,
                    "population": population,
                    # datasets() already applies level 2 when present, otherwise level 1.
                    "context": entry.tissue,
                }
            )
        qtl_rows.sort(key=lambda r: (str(r["dataset"]), str(r["qtl_type"]), str(r["context"])))

        gwas_rows = [
            {
                "datasource": entry.source,
                "accession_id": entry.accession,
                "trait_id": entry.trait,
                "population": entry.population,
            }
            for entry in repo.gwas_datasets()
        ]
        gwas_rows.sort(key=lambda r: (str(r["datasource"]), str(r["trait_id"])))

        return _render(
            "tutorial.html",
            active="tutorial",
            qtl_rows=qtl_rows,
            gwas_rows=gwas_rows,
        )

    return router
