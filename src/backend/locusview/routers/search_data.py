"""The "Search data" tab and its JSON API: type a gene, rsID, or ``chr:pos`` and see, per context,
how strongly it associates — one row per QTL context (plus GWAS traits for variant searches), best
p-value first.

- **Variant** (``rs1042522`` or ``chr17:7676154``): every association at that exact position in
  each dataset (``variant_hits`` / ``gwas_variant_hits`` — one ``(chrom, position)`` index seek
  per shard, fetching only p-value and beta). A context
  usually tests the variant against several phenotypes; every one is listed, grouped under its
  context.
- **Gene** (``TP53`` or ``ENSG00000141510``): the gene's phenotypes in each QTL dataset, each
  with its most significant SNP (``gene_phenotype_leads``); the context's own most significant
  SNP is the best of those. GWAS has no gene concept, so gene searches cover QTL only.

Only associations with ``p <`` the threshold (``p``, default ``DEFAULT_P``) are returned; for
variant searches it's applied in SQL. With no ``datasets`` filter every dataset in the catalog is
searched: QTL shards in batches of ``_BATCH`` per query, run on a small thread pool. The Data
Browser's click-to-pin opens the page with ``chrom``/``position`` and its own ``datasets``.

``/search-data`` renders the page; ``/api/search-data`` returns the same search as JSON for
scripted access, e.g. Python ``requests`` — its ``rows`` are the page's table, row for row and
column for column (:func:`_table_rows`), so ``pd.DataFrame(data["rows"])`` matches the page.
"""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, TypeVar

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, JSONResponse
from markupsafe import Markup, escape

from locusview.requestinfo import (
    Dataset,
    EqtlAssociation,
    Gene,
    GwasAssociation,
    GwasDataset,
    PhenotypeLead,
    QtlRepository,
)
from locusview.routers.comparison import _parse_dataset_keys
from locusview.search import QueryKind, parse_query
from locusview.templating import render as _render

EXAMPLES = ["TP53", "ENSG00000141510", "rs1042522", "chr17:7676154"]
# Default p-value threshold: only associations with p < this are returned (user-editable).
DEFAULT_P = "1e-4"

# QTL shards are searched in batches of _BATCH per query (see connectpostgres.py's variant_hits /
# gene_phenotype_leads for why one query per shard is slow), with up to _WORKERS batches in flight
# — a ~150-shard search is ~15 small queries. A batch that fails only drops its own datasets.
_BATCH = 10
_WORKERS = 8

T = TypeVar("T")
D = TypeVar("D", Dataset, GwasDataset)


def _parse_threshold(raw: str) -> float | None:
    """The p-value threshold as typed (``"1e-4"``, ``"0.05"``, ...), or ``None`` unless it's a
    number in ``(0, 1]``."""
    try:
        value = float(raw.strip())
    except ValueError:
        return None
    return value if 0 < value <= 1 else None


@dataclass
class Hit:
    """One association inside a context: a variant search's (phenotype, stats) at the searched
    position, or a gene search's phenotype with its most significant SNP (``chrom``..``rs_id``)."""

    phenotype: str | None
    pvalue: float | None
    beta: float | None = None
    chrom: str | None = None
    position: int | None = None
    ref: str | None = None
    alt: str | None = None
    rs_id: int | None = None

    @property
    def phenotype_html(self) -> Markup:
        """The phenotype ID, escaped, with a ``<wbr>`` after each ``:`` so long sQTL IDs
        (``chr17:7670715:7673207:clu_27443_-:ENSG…``) wrap between fields, not mid-number."""
        return Markup(":<wbr>").join(escape(part) for part in (self.phenotype or "").split(":"))

    @property
    def snp(self) -> str | None:
        """``"rs12345"``, or ``"chr17:7676154"`` when no rsID resolves."""
        if self.rs_id is not None:
            return f"rs{self.rs_id}"
        return f"chr{self.chrom}:{self.position}" if self.position is not None else None

    @property
    def variant(self) -> str | None:
        """``"chr17:7676154 C>G"`` (alleles only when known) — the same text on the page and in
        the API, so no thousands separators."""
        if self.position is None:
            return None
        alleles = f" {self.ref}>{self.alt}" if self.ref and self.alt else ""
        return f"chr{self.chrom}:{self.position}{alleles}"


@dataclass
class ContextRow:
    """One QTL context (or GWAS trait) and every hit in it, most significant first."""

    context: str
    dataset: str
    type: str
    is_gwas: bool
    hits: list[Hit] = field(default_factory=list)

    @property
    def best(self) -> Hit | None:
        return self.hits[0] if self.hits else None

    @property
    def context_html(self) -> Markup:
        """The context name, escaped, with a ``<wbr>`` after each ``_`` so long names
        (``Skin_Sun_Exposed_Lower_leg``) can wrap inside the page's width-capped column."""
        return Markup("_<wbr>").join(escape(part) for part in self.context.split("_"))

    @property
    def pvalue(self) -> float | None:
        """The context's best p-value — what contexts are ordered by."""
        return self.best.pvalue if self.best else None


@dataclass
class SearchOutcome:
    """Everything one search produced — rendered by the page, serialized by the API.

    ``status`` is the API's HTTP status for it: 200 for a completed search (even with no rows),
    400 for input it can't search (bad threshold, unrecognized query, region), 404 for an unknown
    gene/rsID. ``mode`` is ``"variant"``/``"gene"`` for a completed search, ``"region"`` for a
    region query (answered with a pointer to the Data Browser), else ``None``."""

    query: str
    max_p: float | None
    mode: str | None = None
    status: int = 200
    message: str | None = None
    title: str | None = None
    gene: Gene | None = None
    variant: tuple[str, int, str | None] | None = None  # (chrom, position, rsid or None)
    rows: list[ContextRow] = field(default_factory=list)
    n_searched: int = 0
    failed: int = 0


def _sort_key(p: float | None) -> tuple[bool, float]:
    return (p is None, p or 0.0)


def _qtl_labels(d: Dataset) -> tuple[str, str]:
    """``(dataset label, qtl type)`` for a QTL context — e.g. ``("eQTL-Catalogue / INTERVAL",
    "sQTL")``; the project is only appended when it differs from the dataset name."""
    name, qtl_type, _ = d.catalog_parts
    project = d.source_project_id
    return (f"{name} / {project}" if project and project != name else name), qtl_type


def _gwas_labels(g: GwasDataset) -> tuple[str, str]:
    """``(trait, accession)`` for a GWAS trait."""
    return g.trait.replace("_", " "), g.accession


def _run_all(jobs: list[tuple[int, Callable[[], list[T]]]]) -> tuple[list[T], int]:
    """Run ``(weight, job)`` pairs on the thread pool. Returns every job's results concatenated,
    plus the summed ``weight`` of the jobs that raised — i.e. how many datasets went unsearched."""
    results: list[T] = []
    failed = 0
    with ThreadPoolExecutor(max_workers=_WORKERS) as pool:
        futures = [(weight, pool.submit(job)) for weight, job in jobs]
        for weight, future in futures:
            try:
                results.extend(future.result())
            except Exception:  # one slow/unreachable batch shouldn't sink the whole search
                failed += weight
    return results, failed


def _batches(datasets: list[D]) -> list[list[D]]:
    return [datasets[i : i + _BATCH] for i in range(0, len(datasets), _BATCH)]


def _variant_rows(
    repo: QtlRepository,
    chrom: str,
    position: int,
    qtl: list[Dataset],
    gwas: list[GwasDataset],
    max_p: float,
) -> tuple[list[ContextRow], int]:
    """One row per dataset with at least one association at ``chrom:position`` with
    ``p < max_p``."""
    by_id = {d.id: d for d in qtl}

    def qtl_job(batch: list[Dataset]) -> Callable[[], list[ContextRow]]:
        def run() -> list[ContextRow]:
            hits_by_dataset: dict[int, list[EqtlAssociation]] = {}
            for hit in repo.variant_hits(chrom, position, [d.id for d in batch], max_p):
                hits_by_dataset.setdefault(hit.dataset_id, []).append(hit)
            rows = []
            for dataset_id, hits in hits_by_dataset.items():
                ranked = sorted(hits, key=lambda h: _sort_key(h.pvalue))
                dataset_label, qtl_type = _qtl_labels(by_id[dataset_id])
                rows.append(
                    ContextRow(
                        context=by_id[dataset_id].tissue,
                        dataset=dataset_label,
                        type=qtl_type,
                        is_gwas=False,
                        hits=[Hit(h.phenotype_id, h.pvalue, h.beta) for h in ranked],
                    )
                )
            return rows

        return run

    gwas_by_id = {g.id: g for g in gwas}

    def gwas_job(batch: list[GwasDataset]) -> Callable[[], list[ContextRow]]:
        def run() -> list[ContextRow]:
            hits_by_trait: dict[int, list[GwasAssociation]] = {}
            for hit in repo.gwas_variant_hits(chrom, position, [g.id for g in batch], max_p):
                hits_by_trait.setdefault(hit.dataset_id, []).append(hit)
            rows = []
            for dataset_id, hits in hits_by_trait.items():
                ranked = sorted(hits, key=lambda h: _sort_key(h.pvalue))
                trait, accession = _gwas_labels(gwas_by_id[dataset_id])
                rows.append(
                    ContextRow(
                        context=trait,
                        dataset=accession,
                        type="GWAS",
                        is_gwas=True,
                        hits=[Hit(None, h.pvalue, h.beta) for h in ranked],
                    )
                )
            return rows

        return run

    jobs = [(len(b), qtl_job(b)) for b in _batches(qtl)] + [
        (len(b), gwas_job(b)) for b in _batches(gwas)
    ]
    return _run_all(jobs)


def _lead_hit(lead: PhenotypeLead) -> Hit:
    """A gene search's phenotype row: the phenotype and its most significant SNP."""
    return Hit(
        phenotype=lead.phenotype_id,
        pvalue=lead.pvalue,
        beta=lead.beta,
        chrom=lead.chrom,
        position=lead.position,
        ref=lead.ref,
        alt=lead.alt,
        rs_id=lead.rs_id,
    )


def _gene_rows(
    repo: QtlRepository, gene: Gene, qtl: list[Dataset], max_p: float
) -> tuple[list[ContextRow], int]:
    """One row per QTL context with at least one of the gene's phenotypes whose lead has
    ``p < max_p``."""
    by_id = {d.id: d for d in qtl}

    def qtl_job(batch: list[Dataset]) -> Callable[[], list[ContextRow]]:
        def run() -> list[ContextRow]:
            leads_by_dataset: dict[int, list[PhenotypeLead]] = {}
            for dataset_id, lead in repo.gene_phenotype_leads(gene, [d.id for d in batch]):
                if lead.pvalue is not None and lead.pvalue < max_p:
                    leads_by_dataset.setdefault(dataset_id, []).append(lead)
            rows = []
            for dataset_id, leads in leads_by_dataset.items():
                ranked = sorted(leads, key=lambda s: _sort_key(s.pvalue))
                dataset_label, qtl_type = _qtl_labels(by_id[dataset_id])
                rows.append(
                    ContextRow(
                        context=by_id[dataset_id].tissue,
                        dataset=dataset_label,
                        type=qtl_type,
                        is_gwas=False,
                        hits=[_lead_hit(lead) for lead in ranked],
                    )
                )
            return rows

        return run

    return _run_all([(len(b), qtl_job(b)) for b in _batches(qtl)])


def _search(repo: QtlRepository, query: str, datasets: str, p: str) -> SearchOutcome:
    """Run one search — shared by the page and the JSON API."""
    max_p = _parse_threshold(p)
    out = SearchOutcome(query=query, max_p=max_p)
    if not query:
        out.status, out.message = 400, "Enter a gene, rsID, or chr:position to search."
        return out
    if max_p is None:
        out.status = 400
        out.message = (
            f"“{p}” isn't a valid p-value threshold: enter a number between 0 and 1, "
            f"e.g. {DEFAULT_P} or 0.05."
        )
        return out

    qtl = repo.datasets()
    gwas = repo.gwas_datasets()
    if datasets:  # restrict to the Data Browser's own selection
        qtl_ids, gwas_ids = _parse_dataset_keys(datasets)
        qtl = [d for d in qtl if d.id in set(qtl_ids)]
        gwas = [g for g in gwas if g.id in set(gwas_ids)]

    parsed = parse_query(query)
    if parsed.kind in (QueryKind.RSID, QueryKind.VARIANT):
        rsid: str | None = None
        if parsed.kind is QueryKind.RSID and parsed.rsid:
            resolved = repo.resolve_variant(int(parsed.rsid[2:]))
            if resolved is None:
                out.status, out.message = 404, f"{parsed.rsid} was not found."
                return out
            (v_chrom, v_pos), rsid = resolved, parsed.rsid
            out.title = f"{rsid} · chr{v_chrom}:{v_pos:,}"
        else:
            assert parsed.chrom is not None and parsed.position is not None
            v_chrom, v_pos = parsed.chrom, parsed.position  # parse_query checked CHROMS
            out.title = f"chr{v_chrom}:{v_pos:,}"
        out.mode, out.variant = "variant", (v_chrom, v_pos, rsid)
        out.n_searched = len(qtl) + len(gwas)
        out.rows, out.failed = _variant_rows(repo, v_chrom, v_pos, qtl, gwas, max_p)
    elif parsed.kind in (QueryKind.GENE_SYMBOL, QueryKind.ENSEMBL_GENE):
        gene_query = parsed.gene_symbol or parsed.ensembl_id or query
        gene = repo.resolve_gene(gene_query)
        if gene is None:
            out.status, out.message = 404, f"Gene {gene_query} was not found."
            return out
        out.mode, out.gene = "gene", gene
        out.title = f"{gene.symbol} ({gene.ensembl_id})"
        out.n_searched = len(qtl)
        out.rows, out.failed = _gene_rows(repo, gene, qtl, max_p)
    elif parsed.kind is QueryKind.REGION:
        out.mode, out.status = "region", 400
        out.message = (
            "Search data looks up a single gene or variant; use the Data Browser for a region."
        )
    else:
        out.status = 400
        out.message = f"Couldn't recognize “{query}” as a gene, rsID, or chr:position."
    out.rows.sort(key=lambda r: _sort_key(r.pvalue))
    return out


def _table_rows(out: SearchOutcome) -> list[dict[str, Any]]:
    """The Search data table, flattened: one dict per table row (context x phenotype), with the
    table's columns in the table's order — so ``pd.DataFrame(rows)`` reproduces the page.

    Gene searches: ``context, dataset, type, phenotype, lead_snp, variant, pvalue, beta``;
    variant searches: ``context, dataset, type, phenotype, pvalue, beta`` (``phenotype`` is
    ``None`` for GWAS rows, shown as a dash on the page)."""
    is_gene = out.mode == "gene"
    table: list[dict[str, Any]] = []
    for r in out.rows:
        for h in r.hits:
            row: dict[str, Any] = {
                "context": r.context,
                "dataset": r.dataset,
                "type": r.type,
                "phenotype": h.phenotype,
            }
            if is_gene:
                row["lead_snp"] = h.snp
                row["variant"] = h.variant
            row["pvalue"] = h.pvalue
            row["beta"] = h.beta
            table.append(row)
    return table


def _to_json(out: SearchOutcome) -> dict[str, Any]:
    """The API's response body. A completed search::

        {"query", "type": "gene" | "variant", "p_threshold",
         "gene": {"symbol", "ensembl_id", "chrom", "start", "end"} | null,
         "variant": {"rsid", "chrom", "position"} | null,
         "datasets_searched", "datasets_failed", "n_contexts", "n_rows",
         "rows": [...]}   # exactly the page's table — see _table_rows

    Anything else is ``{"query", "error"}`` with the matching HTTP status."""
    if out.mode not in ("gene", "variant"):
        return {"query": out.query, "error": out.message}
    gene = out.gene
    variant = out.variant
    rows = _table_rows(out)
    return {
        "query": out.query,
        "type": out.mode,
        "p_threshold": out.max_p,
        "gene": (
            {
                "symbol": gene.symbol,
                "ensembl_id": gene.ensembl_id,
                "chrom": gene.chrom,
                "start": gene.start,
                "end": gene.end,
            }
            if gene is not None
            else None
        ),
        "variant": (
            {"rsid": variant[2], "chrom": variant[0], "position": variant[1]}
            if variant is not None
            else None
        ),
        "datasets_searched": out.n_searched,
        "datasets_failed": out.failed,
        "n_contexts": len(out.rows),
        "n_rows": len(rows),
        "rows": rows,
    }


def router(repo: QtlRepository) -> APIRouter:
    """Build the Search data page and its JSON API route."""
    router = APIRouter()

    @router.get("/search-data", response_class=HTMLResponse)
    def search_data(
        q: str = "",
        chrom: str | None = None,
        position: int | None = None,
        datasets: str = "",
        p: str = DEFAULT_P,
    ) -> HTMLResponse:
        """Render the search box, and — for a recognized query — the per-context results with
        ``p <`` the page's threshold box (default ``DEFAULT_P``)."""
        query = q.strip()
        if not query and chrom is not None and position is not None:
            query = f"chr{chrom}:{position}"  # Data Browser click-to-pin
        threshold = p.strip() or DEFAULT_P
        page: dict[str, object] = {
            "active": "search_data",
            "q": query,
            "examples": EXAMPLES,
            "datasets": datasets,
            "p": threshold,
            "default_p": DEFAULT_P,
        }
        if not query:  # the bare page: just the search box
            return _render("search_data.html", 200, **page, mode=None, message=None, rows=[])
        out = _search(repo, query, datasets, threshold)
        return _render(
            "search_data.html",
            200,
            **page,
            mode=out.mode,
            title=out.title,
            message=out.message,
            rows=out.rows,
            failed=out.failed,
            n_searched=out.n_searched,
        )

    @router.get("/api/search-data")
    def search_data_api(q: str = "", p: str = DEFAULT_P, datasets: str = "") -> JSONResponse:
        """The Search data page's search as JSON — ``q`` a gene symbol / Ensembl id / rsID /
        ``chr:position``, ``p`` the p-value threshold (default ``1e-4``), optional ``datasets``
        (``qtl:<id>,gwas:<id>``) to limit which datasets are searched. See :func:`_to_json`."""
        out = _search(repo, q.strip(), datasets, p.strip() or DEFAULT_P)
        return JSONResponse(_to_json(out), status_code=out.status)

    return router
