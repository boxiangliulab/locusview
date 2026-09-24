"""Search: parse a free-text query (:mod:`locusview.search`) and redirect it into the Data
Browser (or the legacy gene page, for the two kinds it still owns).

All five query kinds :func:`~locusview.search.parse_query` recognizes now land somewhere:
gene symbol / Ensembl id -> ``/browser`` gene mode; rsID / chr:pos -> variant mode;
chr:start-end -> region mode.
"""

from __future__ import annotations

from urllib.parse import urlencode

from fastapi import APIRouter, Response
from fastapi.responses import RedirectResponse

from locusview.requestinfo import QtlRepository
from locusview.search import QueryKind, parse_query
from locusview.templating import render as _render


def router(_repo: QtlRepository) -> APIRouter:
    """``_repo`` is unused (parsing is pure logic) but kept for a uniform factory signature."""
    router = APIRouter()

    @router.get("/search")
    def search(q: str) -> Response:
        """Classify the query and 303-redirect into the Data Browser with the right locus mode
        pre-filled, or render a 404 "not found" page if it doesn't parse as anything recognized."""
        parsed = parse_query(q)

        if parsed.kind is QueryKind.GENE_SYMBOL and parsed.gene_symbol:
            params = {"locus_mode": "gene", "gene": parsed.gene_symbol}
        elif parsed.kind is QueryKind.ENSEMBL_GENE and parsed.ensembl_id:
            params = {"locus_mode": "gene", "gene": parsed.ensembl_id}
        elif parsed.kind is QueryKind.RSID and parsed.rsid:
            params = {"locus_mode": "variant", "variant": parsed.rsid}
        elif parsed.kind is QueryKind.VARIANT and parsed.chrom and parsed.position is not None:
            params = {"locus_mode": "variant", "variant": f"chr{parsed.chrom}:{parsed.position}"}
        elif (
            parsed.kind is QueryKind.REGION
            and parsed.chrom
            and parsed.start is not None
            and parsed.end is not None
        ):
            params = {
                "locus_mode": "region",
                "region": f"chr{parsed.chrom}:{parsed.start}-{parsed.end}",
            }
        else:
            return _render(
                "not_found.html",
                status_code=404,
                query=q,
                reason="Couldn't recognize that as a gene, region, or variant.",
            )

        return RedirectResponse(f"/browser?{urlencode(params)}", status_code=303)

    return router
