"""Read access to QTL data.

Defines the :class:`QtlRepository` interface (a ``Protocol``). Implementations:

* :class:`FakeQtlRepository` — in-memory canned data for tests and offline development.
* :class:`~locusview.connectpostgres.PostgresQtlRepository` (``connectpostgres.py``) — reads the
  **new** Postgres locuscompare2 DB (superseded the MySQL one below, 2026-08).
* ``LocuscompareRepository`` — reads the **old** shared locuscompare2 **MySQL** database
  (ADR-0008). **Commented out below, not deleted**, 2026-08: kept as a fallback pattern in case
  something the new Postgres DB still lacks needs to come back to it. Both gaps this note
  originally listed (gene-annotation, LD-reference) have since landed in the new DB — see
  ``connectpostgres.py``'s module docstring — so nothing currently depends on this path.

**Old locuscompare2 MySQL model (verified against the live DB).** ``eqtl_raw`` is a *catalog* of
datasets (one row per tissue; ``id`` -> shard). The associations live in per-dataset shard tables
``eqtl_snp_{id}`` with integer-encoded keys (``rs_id``, ``gene_id``, ``chrom``). Gene metadata
(symbol <-> Ensembl id <-> coordinates) lives in ``gencode_v26_hg38``. NOTE: the shards store no
ref/alt/effect_allele or MAF, so ``beta``'s sign is not interpretable from the DB alone (issue #18).

**New locuscompare2 Postgres model** — see ``connectpostgres.py``'s module docstring.

Programming to the :class:`QtlRepository` interface lets the app and its tests run against
:class:`FakeQtlRepository` today and swap in a real implementation unchanged.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Protocol


class RepositoryTimeoutError(RuntimeError):
    """A real-DB query failed or timed out — not a bug in the query logic.

    Known cause today: the ``eqtl_snp_*`` shards are effectively indexed only by ``gene_id``
    (the pattern every original query used). :meth:`LocuscompareRepository.associations_in_region`
    (filters by chrom/position) and :meth:`LocuscompareRepository.associations_for_rsid` (filters
    by rs_id) can full-scan and time out until a covering index lands — a real DDL change on the
    *shared* DB, routed through schema-change-coordination (owner Junbin), same pattern as the
    already-known LD-table index gap. See docs/process/status.md.
    """


@dataclass(frozen=True)
class Dataset:
    """A QTL dataset in the catalog (one per tissue), keyed by its integer id."""

    id: int
    # Display label for the context: the level-2 context when the dataset has one (e.g. caQTL's
    # "cMono_CD14"), else level 1 (e.g. eQTL's "Whole_Blood") — never both joined. Built in
    # connectpostgres.py's datasets(); see there for why.
    tissue: str
    source: str  # the catalog `type` column, e.g. "gtex-v8"
    source_project_id: str | None = None  # qtl_lists.source_project_id, e.g. "INTERVAL"

    @property
    def catalog_parts(self) -> tuple[str, str, str]:
        """``(dataset, qtl_type, population)`` parsed from ``source``.

        Dataset names may themselves contain hyphens (notably ``eQTL-Catalogue``), so the two
        metadata suffixes must be split from the right. Legacy source strings without both
        suffixes retain their whole value as the dataset name.
        """
        parts = self.source.rsplit("-", 2)
        if len(parts) == 2:  # legacy source form such as "gtex-v8"
            return parts[0], "QTL", ""
        if len(parts) != 3:
            return self.source, "QTL", ""
        return parts[0], parts[1], parts[2]


@dataclass(frozen=True)
class Gene:
    """A gene resolved from the GENCODE annotation table."""

    gene_id: int  # integer key used by the eqtl_snp shards (the ENSG number)
    symbol: str
    ensembl_id: str  # versioned, e.g. "ENSG00000141510.16"
    chrom: str
    start: int
    end: int
    strand: str


@dataclass(frozen=True)
class EqtlAssociation:
    """One eQTL association from a dataset shard.

    ``effect_allele`` and MAF are intentionally absent — the source shards do not store them
    (issue #18), so ``beta``'s direction is not interpretable from this record alone.
    """

    dataset_id: int
    gene_id: int
    rs_id: int | None
    chrom: int
    position: int
    pvalue: float | None
    beta: float | None
    se: float | None
    # Populated only by :meth:`PostgresQtlRepository.cis_associations` (gene-anchored, bounded —
    # see its docstring); every other association source leaves these ``None``. Together with
    # ``chrom``/``position`` they let a caller derive a ``variant_id`` (``chr{chrom}_{position}_
    # {ref}_{alt}``) without widening this dataclass further.
    ref: str | None = None
    alt: str | None = None
    # Populated by both :meth:`~PostgresQtlRepository.cis_associations` and
    # :meth:`~PostgresQtlRepository.associations_in_region` — which phenotype (gene, splice
    # junction, or caQTL peak) this row was tested under. Lets callers group a locus's variants by
    # phenotype (see ``routers/locus.py``'s ``_group_by_phenotype``), since one genomic window can
    # legitimately contain variants tested against several different phenotypes at once.
    phenotype_id: str | None = None


@dataclass(frozen=True)
class PhenotypeSummary:
    """Small, database-aggregated summary used to list phenotypes in a region."""

    phenotype_id: str | None
    gene_id: int | None
    lead_position: int | None
    lead_pvalue: float | None
    n: int


@dataclass(frozen=True)
class GwasDataset:
    """A GWAS trait/list in the catalog (one per trait x population), keyed by its integer id
    (the ``gwas_snp_{id}`` shard number — same "id = shard number" convention as :class:`Dataset`
    uses for QTL)."""

    id: int
    trait: str
    population: str
    source: str  # the gwas_datasets.dataset column, e.g. "GWAS Catalog"
    accession: str  # e.g. "GCST90002379" (GWAS Catalog study accession)


@dataclass(frozen=True)
class GwasAssociation:
    """One GWAS association from a trait shard. No gene concept (GWAS is trait x variant, not
    gene x variant) — comparison/click-to-pin still isn't available for GWAS points (see
    routers/comparison.py), but ``rs_id``/``ref``/``alt`` (populated by
    :meth:`PostgresQtlRepository.gwas_associations_in_region`'s ``variant_rsid_mapping_raw`` join)
    let GWAS locuszoom panels be LD-colored client-side the same way QTL panels are."""

    dataset_id: int
    chrom: int
    position: int
    pvalue: float | None
    beta: float | None
    se: float | None
    ref: str | None = None
    alt: str | None = None
    rs_id: int | None = None


@dataclass(frozen=True)
class QtlContextEntry:
    """One row of the body map's underlying data: a QTL dataset's tissue/cell-type label, from
    ``qtl_contexts`` joined back to its dataset. ``level_2`` is optional (e.g. a cell type within
    a tissue); ``qtl_list_id`` is the dataset id to select in the Data Browser."""

    qtl_list_id: int
    level_1: str
    level_2: str | None
    dataset_label: str  # e.g. "GTEx_v10-eQTL" — "{dataset}-{qtltype}", no population


class QtlRepository(Protocol):
    """Read interface for QTL data. Implementations may be real or fake."""

    def datasets(self) -> list[Dataset]:
        """Return the dataset catalog."""
        ...

    def resolve_gene(self, symbol_or_ensembl: str) -> Gene | None:
        """Resolve a gene symbol or Ensembl id to a :class:`Gene`, or ``None`` if unknown."""
        ...

    def eqtls_for_gene(
        self, gene_id: int, dataset_ids: Sequence[int], limit: int = 100
    ) -> list[EqtlAssociation]:
        """Return eQTL associations for ``gene_id`` within the given datasets."""
        ...

    def cis_associations(self, gene_id: int, dataset_id: int) -> list[EqtlAssociation]:
        """ALL cis variants for one gene in ONE tissue (the regional-plot set, ~thousands)."""
        ...

    def ld_r2(self, chrom: str, lead_rs_id: int, population: str) -> dict[int, float]:
        """r² of every partner variant to the lead, from the 1000G LD panel (excludes the lead)."""
        ...

    def tissues_with_signal(
        self, gene_id: int, p_threshold: float = 1e-5
    ) -> list[tuple[int, str, float]]:
        """(dataset_id, tissue, min_pvalue) for tissues where the gene has a significant eQTL."""
        ...

    def associations_in_region(
        self, chrom: str, start: int, end: int, dataset_id: int
    ) -> list[EqtlAssociation]:
        """All variants in ONE dataset within ``[start, end]`` on ``chrom`` — the region-mode
        locus set (not anchored to a gene)."""
        ...

    def phenotype_summaries_in_region(
        self, chrom: str, start: int, end: int, dataset_id: int, limit: int = 50
    ) -> list[PhenotypeSummary]:
        """Return the phenotypes whose OWN feature overlaps ``[start, end]``.

        "Overlaps" is about the phenotype's own coordinates — a caQTL peak, or a gene — NOT about
        where its tested variants fall: a cis window reaches ~1 Mb past the feature, so matching on
        variant positions returns peaks/genes that sit well outside the region the user typed.

        Implementations should aggregate before transferring rows; this is the initial
        region/variant-mode request and must not materialize the full association window.
        """
        ...

    def phenotypes_for_gene(self, gene: Gene, dataset_id: int) -> list[PhenotypeSummary]:
        """Return every phenotype matched to a gene, without loading association values."""
        ...

    def associations_for_phenotype(
        self, dataset_id: int, phenotype_id: str, chrom: str, start: int, end: int
    ) -> list[EqtlAssociation]:
        """ALL variants tested for ONE phenotype in one dataset, enriched with rs_id/ref/alt where
        available — the region/variant-mode equivalent of :meth:`cis_associations`'s per-gene
        enrichment (see ``connectpostgres.py``'s docstring for why ``associations_in_region`` itself
        can't afford this for a whole window at once)."""
        ...

    def associations_for_rsid(
        self, rs_id: int, dataset_ids: Sequence[int], gene_id: int | None = None
    ) -> list[EqtlAssociation]:
        """One variant's stats across multiple datasets — resolves a bare rsID's position and
        powers the cross-tissue variant comparison table.

        Pass ``gene_id`` whenever it's known (the shards are effectively indexed by gene_id
        only) — it turns an unindexed, potentially slow ``rs_id``-only scan into a fast
        ``gene_id AND rs_id`` lookup. See :class:`RepositoryTimeoutError`.
        """
        ...

    def resolve_variant(self, rs_id: int) -> tuple[str, int] | None:
        """``(chrom, position)`` for a bare rsID, or ``None`` if it doesn't resolve to a known
        variant at all — a standalone existence check, independent of any particular QTL/GWAS
        dataset (unlike :meth:`associations_for_rsid`, which needs ``dataset_ids`` up front).
        Powers the Data Browser's variant-mode "does this rsID even exist" step."""
        ...

    def gwas_datasets(self) -> list[GwasDataset]:
        """Return the GWAS trait catalog (parallel to :meth:`datasets` for QTL)."""
        ...

    def gwas_associations_in_region(
        self, chrom: str, start: int, end: int, dataset_id: int
    ) -> list[GwasAssociation]:
        """All GWAS variants in one trait shard within ``[start, end]`` on ``chrom`` — GWAS has
        no gene concept, so this is the only lookup shape (region-anchored, like QTL's
        :meth:`associations_in_region`)."""
        ...

    def qtl_contexts(self) -> list[QtlContextEntry]:
        """Every QTL dataset's tissue/cell-type label — drives the Home page body map."""
        ...


# ── Shared pure helpers ──────────────────────────────────────────────────────

Row = Sequence[Any]
ConnectionFactory = Callable[[], Any]

_ENSG = re.compile(r"^ENSG0*(\d+)$", re.IGNORECASE)

def _parse_peak_id(phenotype_id: str | None) -> tuple[str, int, int] | None:
    """Parse a caQTL peak id (``"chr1_628997_629498"``) into ``(chrom, start, end)``.

    Returns ``None`` for anything else — a gene id, an sQTL splice-cluster id, or a malformed
    peak — so callers can fall back to placing the phenotype by its gene. ``chrom`` comes back
    bare (``"1"``), matching :class:`Gene`'s form.
    """
    if not phenotype_id:
        return None
    match = re.fullmatch(r"(chr)?([0-9]{1,2}|MT|[XYM])_([0-9]+)_([0-9]+)", phenotype_id)
    if match is None:
        return None
    return match.group(2), int(match.group(3)), int(match.group(4))


CHROMS = frozenset([*(str(i) for i in range(1, 23)), "X"])
POPULATIONS = frozenset({"AFR", "AMR", "EAS", "EUR", "SAS"})  # LD populations — see note above

# ── Legacy MySQL-only helpers (commented out with LocuscompareRepository below) ────────────
#
# _GENCODE_TABLE = "gencode_v26_hg38"  # GTEx v8 uses GENCODE v26 (hg38)
# _RS_PARTNER = re.compile(r"^rs(\d+)$")
#
# # A server-side cap (MySQL optimizer hint, not a client socket timeout) for the two queries that
# # can hit an unindexed full-table-scan: associations_in_region (chrom/position) and
# # associations_for_rsid without a gene_id (rs_id alone). The client-side read_timeout doesn't
# # reliably bound this on the shared, NodePort-proxied DB, so the query itself must self-limit.
# _MAX_EXECUTION_TIME_HINT = "/*+ MAX_EXECUTION_TIME(8000) */"
#
#
# def _ld_table(chrom: str, population: str) -> str:
#     """Return the 1000G LD table name for a chromosome + super-population (enum-validated,
#     so the interpolated table name is safe)."""
#     if chrom not in CHROMS:
#         raise ValueError(f"unknown chromosome: {chrom!r}")
#     if population not in POPULATIONS:
#         raise ValueError(f"unknown population: {population!r}")
#     return f"tkg_p3v5a_ld_chr{chrom}_{population}"


def ensembl_number(ensembl_id: str) -> int:
    """Convert an Ensembl gene id to the integer key used by the shards.

    ``"ENSG00000141510.16"`` or ``"ENSG00000141510"`` -> ``141510``.
    """
    core = ensembl_id.split(".", 1)[0]
    m = _ENSG.match(core)
    if not m:
        raise ValueError(f"not an Ensembl gene id: {ensembl_id!r}")
    return int(m.group(1))


# Legacy MySQL-only (commented out with LocuscompareRepository below) — the new schema's shard
# naming (qtl_snp_{id}) and table-safety validation live in connectpostgres.py instead.
#
# def _shard_table(dataset_id: int) -> str:
#     """Return the shard table name for a dataset id.
#
#     The id is validated as a non-negative int so it is safe to interpolate into SQL (a table
#     name cannot be parameterised, only values can).
#     """
#     if not isinstance(dataset_id, int) or isinstance(dataset_id, bool) or dataset_id < 0:
#         raise ValueError(f"dataset_id must be a non-negative int, got {dataset_id!r}")
#     return f"eqtl_snp_{dataset_id}"


def _to_float(value: Any) -> float | None:
    """Coerce a raw DB value to ``float``, or ``None`` if it's ``NULL``/not numeric."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_int(value: Any) -> int | None:
    """Coerce a raw DB value to ``int``, or ``None`` if it's ``NULL``/not numeric."""
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


# Legacy MySQL-only row mappers (commented out with LocuscompareRepository below) — shaped for
# that schema's column order. connectpostgres.py has its own, shaped for the new schema.
#
# def _row_to_eqtl(dataset_id: int, row: Row) -> EqtlAssociation:
#     return EqtlAssociation(
#         dataset_id=dataset_id,
#         gene_id=int(row[0]),
#         rs_id=_to_int(row[1]),
#         chrom=int(row[2]),
#         position=int(row[3]),
#         pvalue=_to_float(row[4]),
#         beta=_to_float(row[5]),
#         se=_to_float(row[6]),
#     )
#
#
# def _row_to_gene(row: Row) -> Gene:
#     ensembl_id = str(row[1])
#     return Gene(
#         gene_id=ensembl_number(ensembl_id),
#         symbol=str(row[0]),
#         ensembl_id=ensembl_id,
#         chrom=str(row[2]),
#         start=int(row[3]),
#         end=int(row[4]),
#         strand=str(row[5]),
#     )


# ── Fake (in-memory) ────────────────────────────────────────────────────────


class FakeQtlRepository:
    """In-memory :class:`QtlRepository` for tests and offline development."""

    def __init__(
        self,
        datasets: Sequence[Dataset] | None = None,
        associations: Sequence[EqtlAssociation] | None = None,
        genes: Sequence[Gene] | None = None,
        ld: dict[tuple[str, int, str], dict[int, float]] | None = None,
        gwas_datasets: Sequence[GwasDataset] | None = None,
        gwas_associations: Sequence[GwasAssociation] | None = None,
        qtl_contexts: Sequence[QtlContextEntry] | None = None,
    ) -> None:
        """Store the canned rows each method below filters/scans in memory — no DB, no network."""
        self._datasets = list(datasets or ())
        self._associations = list(associations or ())
        self._genes = list(genes or ())
        self._ld = dict(ld or {})
        self._gwas_datasets = list(gwas_datasets or ())
        self._gwas_associations = list(gwas_associations or ())
        self._qtl_contexts = list(qtl_contexts or ())

    def datasets(self) -> list[Dataset]:
        """See :meth:`QtlRepository.datasets`."""
        return list(self._datasets)

    def resolve_gene(self, symbol_or_ensembl: str) -> Gene | None:
        """See :meth:`QtlRepository.resolve_gene` — matches by symbol or bare/versioned Ensembl
        id."""
        key = symbol_or_ensembl.strip()
        core = key.split(".", 1)[0].upper()
        for g in self._genes:
            if g.symbol.upper() == key.upper() or g.ensembl_id.split(".", 1)[0].upper() == core:
                return g
        return None

    def eqtls_for_gene(
        self, gene_id: int, dataset_ids: Sequence[int], limit: int = 100
    ) -> list[EqtlAssociation]:
        """See :meth:`QtlRepository.eqtls_for_gene`."""
        wanted = set(dataset_ids)
        hits = [a for a in self._associations if a.gene_id == gene_id and a.dataset_id in wanted]
        return hits[:limit]

    def cis_associations(self, gene_id: int, dataset_id: int) -> list[EqtlAssociation]:
        """See :meth:`QtlRepository.cis_associations`."""
        return [
            a for a in self._associations if a.gene_id == gene_id and a.dataset_id == dataset_id
        ]

    def ld_r2(self, chrom: str, lead_rs_id: int, population: str) -> dict[int, float]:
        """See :meth:`QtlRepository.ld_r2`."""
        return dict(self._ld.get((chrom, lead_rs_id, population), {}))

    def tissues_with_signal(
        self, gene_id: int, p_threshold: float = 1e-5
    ) -> list[tuple[int, str, float]]:
        """See :meth:`QtlRepository.tissues_with_signal`."""
        name = {d.id: d.tissue for d in self._datasets}
        best: dict[int, float] = {}
        for a in self._associations:
            if a.gene_id == gene_id and a.pvalue is not None and a.pvalue < p_threshold:
                best[a.dataset_id] = min(best.get(a.dataset_id, 1.0), a.pvalue)
        return sorted(
            ((ds, name.get(ds, str(ds)), p) for ds, p in best.items()), key=lambda t: t[2]
        )

    def associations_in_region(
        self, chrom: str, start: int, end: int, dataset_id: int
    ) -> list[EqtlAssociation]:
        """See :meth:`QtlRepository.associations_in_region`."""
        return [
            a
            for a in self._associations
            if a.dataset_id == dataset_id and str(a.chrom) == chrom and start <= a.position <= end
        ]

    def _phenotype_overlaps(
        self, hit: EqtlAssociation, chrom: str, start: int, end: int
    ) -> bool:
        """Whether this association's PHENOTYPE (not its variant) overlaps ``[start, end]``.

        A ``chr_start_end`` phenotype id carries the caQTL peak's own coordinates; otherwise the
        phenotype is a gene, whose coordinates come from this fake's ``genes``. With neither
        available there's nothing to place the phenotype by, so it can't match.
        """
        peak = _parse_peak_id(hit.phenotype_id)
        if peak is not None:
            peak_chrom, peak_start, peak_end = peak
            return peak_chrom == chrom and peak_start <= end and peak_end >= start
        gene = next((g for g in self._genes if g.gene_id == hit.gene_id), None)
        if gene is None:
            return False
        return gene.chrom == chrom and gene.start <= end and gene.end >= start

    def phenotype_summaries_in_region(
        self, chrom: str, start: int, end: int, dataset_id: int, limit: int = 50
    ) -> list[PhenotypeSummary]:
        """See :meth:`QtlRepository.phenotype_summaries_in_region`."""
        groups: dict[str | None, list[EqtlAssociation]] = {}
        for hit in self._associations:
            if hit.dataset_id != dataset_id:
                continue
            if not self._phenotype_overlaps(hit, chrom, start, end):
                continue
            groups.setdefault(hit.phenotype_id, []).append(hit)
        summaries = []
        for phenotype_id, group in groups.items():
            ranked = sorted(group, key=lambda a: (a.pvalue is None, a.pvalue or 0.0))
            lead = ranked[0]
            summaries.append(
                PhenotypeSummary(
                    phenotype_id, lead.gene_id, lead.position, lead.pvalue, len(group)
                )
            )
        summaries.sort(key=lambda s: (s.lead_pvalue is None, s.lead_pvalue or 0.0))
        return summaries[:limit]

    def phenotypes_for_gene(self, gene: Gene, dataset_id: int) -> list[PhenotypeSummary]:
        """See :meth:`QtlRepository.phenotypes_for_gene`."""
        groups: dict[str | None, int | None] = {}
        for hit in self._associations:
            matched = hit.dataset_id == dataset_id and hit.gene_id == gene.gene_id
            if not matched and hit.dataset_id == dataset_id:
                peak = _parse_peak_id(hit.phenotype_id)
                # Gene mode's peak rule: the peak CONTAINS the gene's start (see
                # PostgresQtlRepository.cis_associations), not merely overlaps its span.
                matched = peak is not None and (
                    peak[0] == gene.chrom and peak[1] <= gene.start <= peak[2]
                )
            if matched:
                groups[hit.phenotype_id] = hit.gene_id
        return [PhenotypeSummary(pid, gid, None, None, 0) for pid, gid in groups.items()]

    def associations_for_phenotype(
        self, dataset_id: int, phenotype_id: str, chrom: str, start: int, end: int
    ) -> list[EqtlAssociation]:
        """See :meth:`QtlRepository.associations_for_phenotype`."""
        return [
            a
            for a in self._associations
            if a.dataset_id == dataset_id
            and a.phenotype_id == phenotype_id
            and str(a.chrom) == chrom
            and start <= a.position <= end
        ]

    def associations_for_rsid(
        self, rs_id: int, dataset_ids: Sequence[int], gene_id: int | None = None
    ) -> list[EqtlAssociation]:
        """See :meth:`QtlRepository.associations_for_rsid`."""
        wanted = set(dataset_ids)
        return [
            a
            for a in self._associations
            if a.rs_id == rs_id
            and a.dataset_id in wanted
            and (gene_id is None or a.gene_id == gene_id)
        ]

    def resolve_variant(self, rs_id: int) -> tuple[str, int] | None:
        """See :meth:`QtlRepository.resolve_variant`."""
        for a in self._associations:
            if a.rs_id == rs_id:
                return str(a.chrom), a.position
        return None

    def gwas_datasets(self) -> list[GwasDataset]:
        """See :meth:`QtlRepository.gwas_datasets`."""
        return list(self._gwas_datasets)

    def gwas_associations_in_region(
        self, chrom: str, start: int, end: int, dataset_id: int
    ) -> list[GwasAssociation]:
        """See :meth:`QtlRepository.gwas_associations_in_region`."""
        return [
            a
            for a in self._gwas_associations
            if a.dataset_id == dataset_id and str(a.chrom) == chrom and start <= a.position <= end
        ]

    def qtl_contexts(self) -> list[QtlContextEntry]:
        """See :meth:`QtlRepository.qtl_contexts`."""
        return list(self._qtl_contexts)


# ── Legacy: real (old locuscompare2 MySQL) ──────────────────────────────────
#
# Superseded 2026-08 by PostgresQtlRepository (connectpostgres.py), which reads the new, better-
# indexed Postgres locuscompare2 DB (which has since gained both a gene-annotation table and an
# LD-reference table too — see connectpostgres.py's module docstring). Commented out rather than
# deleted in case something it still doesn't cover needs a fallback, or a hybrid with the new
# repository. See docs/process/status.md's "Scope note".
#
# class LocuscompareRepository:
#     """:class:`QtlRepository` backed by the shared locuscompare2 MySQL database.
#
#     Takes a *connection factory* (a callable returning a DB-API connection) so it can be
#     unit-tested with a fake connection and used with pymysql in production.
#     """
#
#     def __init__(self, connection_factory: ConnectionFactory) -> None:
#         self._connect = connection_factory
#
#     @staticmethod
#     def _run(conn: Any, sql: str, params: Sequence[Any]) -> list[Row]:
#         cur = conn.cursor()
#         cur.execute(sql, params)
#         return list(cur.fetchall())
#
#     def _query(self, sql: str, params: Sequence[Any]) -> list[Row]:
#         conn = self._connect()
#         try:
#             return self._run(conn, sql, params)
#         finally:
#             conn.close()
#
#     def datasets(self) -> list[Dataset]:
#         rows = self._query("SELECT id, tissue, type FROM eqtl_raw", ())
#         return [Dataset(id=int(r[0]), tissue=str(r[1]), source=str(r[2])) for r in rows]
#
#     def resolve_gene(self, symbol_or_ensembl: str) -> Gene | None:
#         key = symbol_or_ensembl.strip()
#         select = f"SELECT gene_name, gene_id, chr, start, end, strand FROM {_GENCODE_TABLE} "
#         if key.upper().startswith("ENSG"):
#             core = key.split(".", 1)[0]
#             rows = self._query(select + "WHERE gene_id LIKE %s LIMIT 1", (f"{core}%",))
#         else:
#             rows = self._query(select + "WHERE gene_name = %s LIMIT 1", (key,))
#         return _row_to_gene(rows[0]) if rows else None
#
#     def eqtls_for_gene(
#         self, gene_id: int, dataset_ids: Sequence[int], limit: int = 100
#     ) -> list[EqtlAssociation]:
#         if not dataset_ids:
#             return []
#         conn = self._connect()  # one connection for the whole fan-out
#         try:
#             out: list[EqtlAssociation] = []
#             for dataset_id in dataset_ids:
#                 table = _shard_table(dataset_id)
#                 rows = self._run(
#                     conn,
#                     f"SELECT gene_id, rs_id, chrom, position, pvalue, beta, se "
#                     f"FROM {table} WHERE gene_id = %s LIMIT %s",
#                     (gene_id, limit),
#                 )
#                 out.extend(_row_to_eqtl(dataset_id, r) for r in rows)
#             return out
#         finally:
#             conn.close()
#
#     def cis_associations(self, gene_id: int, dataset_id: int) -> list[EqtlAssociation]:
#         table = _shard_table(dataset_id)
#         rows = self._query(
#             f"SELECT gene_id, rs_id, chrom, position, pvalue, beta, se "
#             f"FROM {table} WHERE gene_id = %s",
#             (gene_id,),
#         )
#         return [_row_to_eqtl(dataset_id, r) for r in rows]
#
#     def ld_r2(self, chrom: str, lead_rs_id: int, population: str) -> dict[int, float]:
#         table = _ld_table(chrom, population)
#         lead = f"rs{lead_rs_id}"
#         # LD pairs are stored one-directional, so union both directions and dedupe with MAX.
#         rows = self._query(
#             f"SELECT partner, MAX(R2) AS r2 FROM ("
#             f" SELECT SNP_B AS partner, R2 FROM {table} WHERE SNP_A = %s"
#             f" UNION ALL"
#             f" SELECT SNP_A AS partner, R2 FROM {table} WHERE SNP_B = %s"
#             f") u GROUP BY partner",
#             (lead, lead),
#         )
#         out: dict[int, float] = {}
#         for partner, r2 in rows:
#             m = _RS_PARTNER.match(str(partner))
#             if m is None or r2 is None:  # skip non-rs ids (esv/ss/…) and NULLs
#                 continue
#             out[int(m.group(1))] = max(0.0, min(1.0, float(r2)))
#         out.pop(lead_rs_id, None)  # exclude self; the caller sets the lead's own r² = 1.0
#         return out
#
#     def tissues_with_signal(
#         self, gene_id: int, p_threshold: float = 1e-5
#     ) -> list[tuple[int, str, float]]:
#         # Fan-out across dataset shards. NOTE: O(#tissues) queries — a candidate for a
#         # per-gene summary table (schema-change-coordination) if it gets hot.
#         out: list[tuple[int, str, float]] = []
#         for dataset in self.datasets():
#             table = _shard_table(dataset.id)
#             # pvalue is stored as text; `+ 0.0` forces numeric MIN (handles decimal + scientific).
#             rows = self._query(
#                 f"SELECT MIN(pvalue + 0.0) FROM {table} WHERE gene_id = %s", (gene_id,)
#             )
#             min_p = rows[0][0] if rows else None
#             if min_p is not None and float(min_p) < p_threshold:
#                 out.append((dataset.id, dataset.tissue, float(min_p)))
#         return sorted(out, key=lambda t: t[2])
#
#     def associations_in_region(
#         self, chrom: str, start: int, end: int, dataset_id: int
#     ) -> list[EqtlAssociation]:
#         table = _shard_table(dataset_id)
#         try:
#             rows = self._query(
#                 f"SELECT {_MAX_EXECUTION_TIME_HINT} gene_id, rs_id, chrom, position, pvalue, "
#                 f"beta, se FROM {table} WHERE chrom = %s AND position BETWEEN %s AND %s",
#                 (chrom, start, end),
#             )
#         except Exception as exc:  # pragma: no cover - needs a live, slow/unindexed DB
#             raise RepositoryTimeoutError(
#                 f"region query on {table} failed or timed out (see RepositoryTimeoutError)"
#             ) from exc
#         return [_row_to_eqtl(dataset_id, r) for r in rows]
#
#     def associations_for_rsid(
#         self, rs_id: int, dataset_ids: Sequence[int], gene_id: int | None = None
#     ) -> list[EqtlAssociation]:
#         if not dataset_ids:
#             return []
#         # gene_id turns this into a fast, gene_id-indexed lookup; without it, rs_id alone can
#         # full-scan an unindexed shard — hence the MAX_EXECUTION_TIME hint either way (see
#         # RepositoryTimeoutError): the client-side socket read_timeout doesn't reliably bound a
#         # slow query on this shared, NodePort-proxied DB, so the cap has to be server-side.
#         where: str
#         params: tuple[int, ...]
#         if gene_id is None:
#             where, params = "rs_id = %s", (rs_id,)
#         else:
#             where, params = "gene_id = %s AND rs_id = %s", (gene_id, rs_id)
#         conn = self._connect()  # one connection for the whole fan-out
#         try:
#             out: list[EqtlAssociation] = []
#             for dataset_id in dataset_ids:
#                 table = _shard_table(dataset_id)
#                 try:
#                     rows = self._run(
#                         conn,
#                         f"SELECT {_MAX_EXECUTION_TIME_HINT} gene_id, rs_id, chrom, position, "
#                         f"pvalue, beta, se FROM {table} WHERE {where}",
#                         params,
#                     )
#                 except Exception as exc:  # pragma: no cover - needs a live, slow/unindexed DB
#                     raise RepositoryTimeoutError(
#                         f"rsid query on {table} failed or timed out (see RepositoryTimeoutError)"
#                     ) from exc
#                 out.extend(_row_to_eqtl(dataset_id, r) for r in rows)
#             return out
#         finally:
#             conn.close()
#
#
# def pymysql_connection_factory() -> ConnectionFactory:
#     """Build a factory that opens a read-only pymysql connection from ``LOCUSCOMPARE2_DB_*``
#     settings. The password must come from the secret store / ``.env`` — never source."""
#
#     def _connect() -> Any:  # pragma: no cover - needs a live DB + network
#         import pymysql
#
#         from locusview.config import get_db_settings
#
#         settings = get_db_settings()
#         return pymysql.connect(
#             host=settings.host,
#             port=settings.port,
#             user=settings.user,
#             password=settings.password,
#             database=settings.name,
#             connect_timeout=8,
#             read_timeout=30,
#         )
#
#     return _connect
