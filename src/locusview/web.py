"""The locusview web application (FastAPI + Jinja2/HTMX).

Routes:
  GET /health          liveness probe
  GET /                landing page with a search box
  GET /search?q=...    parse the query and route it (gene search only, so far)
  GET /gene/{name}     a gene page: its eQTLs across tissues

The app is built by a factory (:func:`create_app`) that accepts a
:class:`~locusview.repository.QtlRepository` — real in production, fake in tests.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from jinja2 import Environment, FileSystemLoader, select_autoescape

from locusview import __version__
from locusview.config import get_db_settings, get_settings
from locusview.repository import (
    CHROMS,
    POPULATIONS,
    Dataset,
    FakeQtlRepository,
    Gene,
    LocuscompareRepository,
    QtlRepository,
    pymysql_connection_factory,
)
from locusview.search import QueryKind, parse_query
from locusview.viz import ld_legend, neg_log10_p, r2_color

_TEMPLATES = Environment(
    loader=FileSystemLoader(str(Path(__file__).parent / "templates")),
    autoescape=select_autoescape(),
)

# How many datasets (tissues) a gene page queries — bounded for responsiveness (issue #5 follow-up
# will page/rank across all of them).
_MAX_TISSUES = 25


def _rs_to_int(rsid: str) -> int | None:
    """``"rs12345"`` -> ``12345``; anything else -> ``None``."""
    s = rsid.strip().lower()
    return int(s[2:]) if s.startswith("rs") and s[2:].isdigit() else None


def _default_repository() -> QtlRepository:
    """Pick a repository from config: the real DB if configured, else an empty fake."""
    if get_db_settings().host:  # pragma: no cover - requires DB config + network
        return LocuscompareRepository(pymysql_connection_factory())
    return FakeQtlRepository()


def _render(template: str, status_code: int = 200, **context: object) -> HTMLResponse:
    html = _TEMPLATES.get_template(template).render(version=__version__, **context)
    return HTMLResponse(html, status_code=status_code)


def create_app(repository: QtlRepository | None = None) -> FastAPI:
    """Build and return the locusview FastAPI application."""
    repo = repository if repository is not None else _default_repository()
    app = FastAPI(title="locusview", version=__version__)

    @app.get("/health")
    def health() -> dict[str, str]:
        """Liveness/readiness probe. Returns app status, version, and environment."""
        return {"status": "ok", "version": __version__, "env": get_settings().env}

    @app.get("/", response_class=HTMLResponse)
    def index() -> HTMLResponse:
        return _render("index.html")

    @app.get("/search")
    def search(q: str) -> Response:
        """Parse a query and route it. Only gene search is wired up so far."""
        parsed = parse_query(q)
        if parsed.kind is QueryKind.GENE_SYMBOL and parsed.gene_symbol:
            return RedirectResponse(f"/gene/{parsed.gene_symbol}", status_code=303)
        if parsed.kind is QueryKind.ENSEMBL_GENE and parsed.ensembl_id:
            return RedirectResponse(f"/gene/{parsed.ensembl_id}", status_code=303)
        if parsed.kind is QueryKind.RSID and parsed.rsid:
            return RedirectResponse(f"/variant/{parsed.rsid}", status_code=303)
        return _render(
            "not_found.html",
            status_code=404,
            query=q,
            reason="Search supports genes (symbol or Ensembl id) and variants (rsID) so far.",
        )

    @app.get("/gene/{name}", response_class=HTMLResponse)
    def gene_page(name: str) -> HTMLResponse:
        gene = repo.resolve_gene(name)
        if gene is None:
            return _render(
                "not_found.html",
                status_code=404,
                query=name,
                reason="No gene matched that symbol or Ensembl id.",
            )
        all_datasets = repo.datasets()
        datasets = all_datasets[:_MAX_TISSUES]
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
        )

    @app.get("/variant/{rsid}", response_class=HTMLResponse)
    def variant_page(rsid: str) -> HTMLResponse:
        rs_int = _rs_to_int(rsid)
        if rs_int is None:
            return _render(
                "not_found.html",
                status_code=404,
                query=rsid,
                reason="Not a valid rsID (expected e.g. rs12345).",
            )
        chrom = repo.variant_chrom(rs_int)
        if chrom is None:
            return _render(
                "not_found.html",
                status_code=404,
                query=f"rs{rs_int}",
                reason="Could not locate this variant on an autosome in the reference panel.",
            )
        all_datasets = repo.datasets()
        datasets = all_datasets[:_MAX_TISSUES]
        by_id: dict[int, Dataset] = {d.id: d for d in datasets}
        hits = repo.eqtls_for_variant(chrom, rs_int, [d.id for d in datasets])
        hits = sorted(hits, key=lambda a: (a.pvalue is None, a.pvalue or 0.0))  # significant first
        genes: dict[int, Gene | None] = {}
        rows: list[dict[str, object]] = []
        for a in hits:
            if a.gene_id not in genes:
                genes[a.gene_id] = repo.gene_by_id(a.gene_id)
            gene = genes[a.gene_id]
            rows.append(
                {
                    "tissue": by_id[a.dataset_id].tissue,
                    "gene": gene.symbol if gene else str(a.gene_id),
                    "ensembl_id": gene.ensembl_id if gene else "",
                    "position": a.position,
                    "pvalue": a.pvalue,
                    "beta": a.beta,
                    "se": a.se,
                }
            )
        return _render(
            "variant.html",
            rsid=f"rs{rs_int}",
            chrom=chrom,
            rows=rows,
            n_tissues=len(datasets),
            total_tissues=len(all_datasets),
        )

    @app.get("/api/gene/{key}/regional")
    def regional(key: str, tissue: int, population: str = "EUR") -> Response:
        """Association points for one gene × one tissue, with r² to the default (min-p) lead."""
        gene = repo.resolve_gene(key)
        if gene is None:
            return JSONResponse({"error": f"gene not found: {key}"}, status_code=404)
        if population not in POPULATIONS:
            return JSONResponse({"error": f"unknown population: {population}"}, status_code=400)
        dataset = next((d for d in repo.datasets() if d.id == tissue), None)
        if dataset is None:
            return JSONResponse({"error": f"unknown tissue/dataset: {tissue}"}, status_code=404)

        cis = repo.cis_associations(gene.gene_id, tissue)
        lead = None
        for a in cis:
            if a.pvalue is not None and (
                lead is None or lead.pvalue is None or a.pvalue < lead.pvalue
            ):
                lead = a
        if lead is None and cis:
            lead = cis[0]

        r2map: dict[int, float] = {}
        reference_present = False
        if lead is not None and lead.rs_id is not None:
            r2map = repo.ld_r2(str(lead.chrom), lead.rs_id, population)
            reference_present = bool(r2map)
            r2map[lead.rs_id] = 1.0

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

        return JSONResponse(
            {
                "gene": gene.symbol,
                "gene_id": gene.gene_id,
                "tissue": dataset.tissue,
                "dataset_id": tissue,
                "build": "GRCh38",
                "population": population,
                "reference_present_in_1000g": reference_present,
                "region": {
                    "chrom": str(lead.chrom) if lead else gene.chrom,
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

    @app.get("/api/ld")
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

    return app
