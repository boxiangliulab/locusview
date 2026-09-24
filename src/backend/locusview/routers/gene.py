"""Gene page: search a gene by symbol/Ensembl id, browse its eQTLs across tissues, download as
CSV/TSV. The regional (LD-colored) plot itself is the ``locus`` feature — this page just embeds
it via ``partials/_regional_plot.html``.
"""

from __future__ import annotations

import csv
import io

from fastapi import APIRouter, Response
from fastapi.responses import HTMLResponse

from locusview.requestinfo import Dataset, QtlRepository
from locusview.templating import render as _render

# How many datasets (tissues) a gene page queries — bounded for responsiveness (issue #5 follow-up
# will page/rank across all of them).
MAX_TISSUES = 25


def router(repo: QtlRepository) -> APIRouter:
    """Build the Gene page's routes: the page itself and its CSV/TSV download."""
    router = APIRouter()

    @router.get("/gene/{name}", response_class=HTMLResponse)
    def gene_page(name: str) -> HTMLResponse:
        """Resolve a gene symbol/Ensembl id and render its eQTL table across up to
        :data:`MAX_TISSUES` tissues, or a 404 "not found" page if it doesn't resolve."""
        gene = repo.resolve_gene(name)
        if gene is None:
            return _render(
                "not_found.html",
                status_code=404,
                query=name,
                reason="No gene matched that symbol or Ensembl id.",
            )
        all_datasets = repo.datasets()
        datasets = all_datasets[:MAX_TISSUES]
        by_id: dict[int, Dataset] = {d.id: d for d in datasets}
        eqtls = repo.eqtls_for_gene(gene.gene_id, [d.id for d in datasets], limit=50)
        rows = [
            {
                "tissue": by_id[a.dataset_id].tissue,
                "variant": f"rs{a.rs_id}" if a.rs_id is not None else "",
                "chrom": a.chrom,
                "position": a.position,
                "pvalue": a.pvalue,
                "beta": a.beta,
                "se": a.se,
            }
            for a in eqtls
            if a.dataset_id in by_id
        ]
        return _render(
            "gene.html",
            gene=gene,
            rows=rows,
            datasets=datasets,
            n_tissues=len(datasets),
            total_tissues=len(all_datasets),
            plot_endpoint=f"/api/gene/{gene.symbol}/regional",
        )

    @router.get("/gene/{key}/download")
    def download(key: str, format: str = "csv") -> Response:
        """Download a gene's eQTL table (the current gene-page view) as CSV or TSV."""
        if format not in ("csv", "tsv"):
            return Response(
                "format must be 'csv' or 'tsv'", status_code=400, media_type="text/plain"
            )
        gene = repo.resolve_gene(key)
        if gene is None:
            return Response(f"gene not found: {key}", status_code=404, media_type="text/plain")

        datasets = repo.datasets()[:MAX_TISSUES]
        by_id: dict[int, Dataset] = {d.id: d for d in datasets}
        eqtls = repo.eqtls_for_gene(gene.gene_id, [d.id for d in datasets], limit=50)

        buffer = io.StringIO()
        writer = csv.writer(buffer, delimiter="," if format == "csv" else "\t")
        writer.writerow(
            ["gene", "ensembl_id", "tissue", "variant", "chrom", "position", "pvalue", "beta", "se"]
        )
        for a in eqtls:
            dataset = by_id[a.dataset_id]  # eqtls_for_gene only returns the datasets we asked for
            writer.writerow(
                [
                    gene.symbol,
                    gene.ensembl_id,
                    dataset.tissue,
                    f"rs{a.rs_id}" if a.rs_id is not None else "",
                    a.chrom,
                    a.position,
                    a.pvalue,
                    a.beta,
                    a.se,
                ]
            )
        media_type = "text/csv" if format == "csv" else "text/tab-separated-values"
        return Response(
            content=buffer.getvalue(),
            media_type=media_type,
            headers={"Content-Disposition": f'attachment; filename="{gene.symbol}_eqtls.{format}"'},
        )

    return router
