"""``PostgresQtlRepository``: reads the new Postgres locuscompare2 DB (superseded the old MySQL
one, 2026-08 — see ``requestinfo.py``'s module docstring and ``docs/process/status.md``).

**Schema (verified against the live DB via Adminer, 2026-08).**

- ``qtl_datasets`` — catalog: ``(id, dataset, qtl_type, population, description)``, e.g.
  ``(1, "GTEx_v10", "eQTL", "ALL")``.
- ``qtl_lists`` — one row per (dataset, context): ``(id, qtl_dataset_id, context, ...)``.
  **``qtl_lists.id`` is the shard-table number** — ``qtl_lists.id = 1`` means the association
  data lives in ``qtl_snp_1`` / ``qtl_snp_1_phenotype``. Not every ``qtl_lists`` row has a shard
  yet (ingestion in progress); :meth:`PostgresQtlRepository.datasets` only lists ones that do.
- ``qtl_contexts`` — ``(id, qtl_list_id, level_1_context, level_2_context)``, e.g. tissue +
  optional cell type. Joined to ``qtl_lists`` for the display label.
- ``qtl_snp_{id}`` — the association shard: ``(id, chrom, position, ref, alt, beta, se, pval,
  phenotype_key, maf)``. Indexed on ``(chrom, position)`` and ``(phenotype_key, pval)`` — unlike
  the old MySQL shards, region-mode queries don't need a timeout hint here.
- ``qtl_snp_{id}_phenotype`` — ``(id, phenotype_id, gene_id)``. For **eQTL/sQTL-style** datasets
  ``gene_id`` is the truncated numeric Ensembl id (e.g. ``"287265"``), one row per (usually)
  several phenotypes per gene. For **caQTL-style** datasets (e.g. CIMA) ``gene_id`` is ``NULL`` on
  *every* row instead — phenotypes there are chromatin peaks, not genes, and ``phenotype_id`` is
  shaped ``"chr_start_end"`` (e.g. ``"chr1_628997_629498"``). :meth:`_is_peak_dataset` tells which
  mode a given dataset is in — from the catalog's ``qtl_type``, since only caQTL is peak-shaped;
  :meth:`cis_associations` branches on it (matching by ``gene_id``, or by the gene's start falling
  inside the peak's range — see its docstring). ``phenotype_key`` on the shard is this table's
  ``id``.
  The **caQTL** shards' companions were rebuilt (2026-08) with the peak coordinates as real
  columns — ``(id, phenotype_id, gene_id, chrom, start, end)``, ``chrom`` in ``"chr1"`` form —
  plus an ``ix_qtl_snp_{id}_phenotype_locus`` index on ``(chrom, start, "end")``. Peak lookups go
  through :meth:`_peak_phenotypes`, which filters **chromosome first, then the peak range**, so
  they ride that index instead of parsing ``phenotype_id`` with ``split_part`` (unindexable — it
  scanned every peak row). **eQTL/sQTL/pQTL and every other type keep the original three columns**
  and must never take that branch — they resolve phenotypes purely through ``gencode_v39`` ->
  ``gene_id``. That's why the branch is keyed on ``qtl_type`` (:meth:`_is_peak_dataset`) and not
  on ``gene_id`` being NULL: a non-caQTL dataset ingested with an empty ``gene_id`` column would
  otherwise be sent down the peak path, querying columns its table doesn't have.
- ``gencode_v39`` — the real gene-annotation table: ``(gene_id_key, gene_name, gene_id, chr,
  start, "end", strand)``, indexed on ``gene_id``/``gene_id_key``/``gene_name``/``(chr, start,
  end)``. ``gene_id_key`` is the bare numeric id matching the phenotype tables' ``gene_id`` (e.g.
  ``"141510"``); ``gene_id`` is versioned (``"ENSG00000141510.18"``) — there is no separate
  version-less-Ensembl-id column, so :meth:`resolve_gene` strips the version off ``gene_id``
  itself (``split_part(gene_id, '.', 1)``) to also accept a bare ``"ENSG00000141510"``, alongside
  a symbol or the exact versioned id, all in one query. :meth:`_gene_by_key` looks a gene up by
  ``gene_id_key`` (used by :meth:`cis_associations`'s caQTL branch).
- ``variant_rsid_mapping_raw`` — ``(variant_id, chrom, pos, ref, alt, rsid)``, indexed on
  ``rsid`` *and* ``variant_id`` (``variant_id`` = ``"chr{chrom}_{pos}_{ref}_{alt}"``). The primary
  rsID lookup path (see :meth:`associations_for_rsid`); also joined per-row by
  :meth:`cis_associations` — confirmed index-only-scan fast at that (gene-bounded) scale, see its
  docstring for the query-shape pitfall to avoid.
- ``gwas_datasets`` -> ``gwas_lists`` -> ``gwas_snp_{id}`` — the GWAS side, same shard-per-id
  convention as the QTL tables above, but trait/population-keyed instead of gene-keyed: no
  ``_phenotype`` companion table, no gene concept at all. ``gwas_snp_{id}`` columns: ``(id, chrom,
  position, ref, alt, beta, se, pval, maf, manh_plot_used)``, indexed on ``(chrom, position)`` and
  ``pval`` — see :meth:`gwas_datasets` / :meth:`gwas_associations_in_region`. Unlike
  ``associations_in_region`` (QTL), ``gwas_associations_in_region`` *does* enrich every row with
  ``rs_id`` via a ``variant_rsid_mapping_raw`` join — confirmed live at gene/variant-mode window
  scale (~2 Mb, ~28k rows: ~2s) and still linear (not catastrophic) at 10 Mb (~147k rows: ~7s), so
  it's affordable for the fixed-size windows the multi-track plot actually uses; a user-typed
  region-mode window has no upper bound today (same pre-existing condition as the unenriched QTL
  path), so very large custom regions will be proportionally slower.
- ``tkg_p3v5a_ld_chr{chrom}_{population}`` (e.g. ``tkg_p3v5a_ld_chr17_EUR``) — the 1000G phase 3
  LD reference, re-hosted here from the old MySQL DB (2026-08, landed after the initial schema
  pass — see :meth:`ld_r2`). ``(id, SNP_A, SNP_B, R2)``, PLINK ``--r2`` output shape: one row per
  variant pair with r² >= 0.2 (PLINK's default window floor — see ``viz.py``'s ``LD_R2_FLOOR``),
  indexed on both ``SNP_A`` and ``SNP_B`` (pairs are stored once, so a lookup unions both
  directions). Table/column names are mixed-case and must be double-quoted in SQL.

**Per-variant ``rs_id``/``ref``/``alt``** on the QTL side are only populated by
:meth:`cis_associations` (gene-anchored, bounded — see its docstring for why that's affordable
there but not on :meth:`associations_in_region` / :meth:`eqtls_for_gene`, which stay
``rs_id=None``, so their points can't be LD-colored client-side either — no rsID to look up
against ``ld_r2``). A user-provided rsID (variant-mode search) still resolves anywhere, via
:meth:`associations_for_rsid`, which only needs one indexed lookup. The GWAS side has no such
restriction — :meth:`gwas_associations_in_region` always enriches (see its docstring for the
live-tested performance envelope).
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any

from locusview.requestinfo import (
    CHROMS,
    POPULATIONS,
    ConnectionFactory,
    Dataset,
    EqtlAssociation,
    Gene,
    GwasAssociation,
    GwasDataset,
    PhenotypeSummary,
    QtlContextEntry,
    RepositoryTimeoutError,
    Row,
    _to_float,
    _to_int,
)

_RS_PARTNER = re.compile(r"^rs(\d+)$")


def _shard_table(qtl_list_id: int) -> str:
    """Return the association-shard table name for a ``qtl_lists.id`` (safe to interpolate: a
    non-negative int, table names can't be parameterised)."""
    if not isinstance(qtl_list_id, int) or isinstance(qtl_list_id, bool) or qtl_list_id < 0:
        raise ValueError(f"qtl_list_id must be a non-negative int, got {qtl_list_id!r}")
    return f"qtl_snp_{qtl_list_id}"


# ``qtl_datasets.qtl_type`` values whose phenotypes are chromatin peaks (``chr_start_end``) rather
# than genes — the only ones whose ``_phenotype`` companion carries chrom/start/end columns. Every
# other type resolves its phenotypes through gencode_v39's gene id. See :meth:`_is_peak_dataset`.
_PEAK_QTL_TYPES = frozenset({"caqtl"})


def _phenotype_table(qtl_list_id: int) -> str:
    """Return the phenotype-companion table name for a ``qtl_lists.id``."""
    return f"{_shard_table(qtl_list_id)}_phenotype"


def _gwas_shard_table(gwas_list_id: int) -> str:
    """Return the GWAS association-shard table name for a ``gwas_lists.id`` — same "id = shard
    number" convention as :func:`_shard_table`, on the ``gwas_snp_{id}`` tables instead."""
    if not isinstance(gwas_list_id, int) or isinstance(gwas_list_id, bool) or gwas_list_id < 0:
        raise ValueError(f"gwas_list_id must be a non-negative int, got {gwas_list_id!r}")
    return f"gwas_snp_{gwas_list_id}"


def _ld_table(chrom: str, population: str) -> str:
    """Return the 1000G phase 3 LD table name for a chromosome + super-population — enum-
    validated against :data:`CHROMS`/:data:`POPULATIONS`, so interpolating it into SQL is safe (a
    table name can't be parameterised, only values can). Double-quoted: the table's own name has
    a mixed-case population suffix (``_EUR``, not ``_eur``) and Postgres folds unquoted
    identifiers to lowercase."""
    if chrom not in CHROMS:
        raise ValueError(f"unknown chromosome: {chrom!r}")
    if population not in POPULATIONS:
        raise ValueError(f"unknown population: {population!r}")
    return f'"tkg_p3v5a_ld_chr{chrom}_{population}"'


def _row_to_eqtl(dataset_id: int, row: Row) -> EqtlAssociation:
    """``row`` = ``(chrom, position, pval, beta, se, gene_id[, phenotype_id])``. ``rs_id`` isn't
    looked up per row here (see module docstring) — callers that need it use
    :meth:`associations_for_rsid`. The optional 7th column is only selected by
    :meth:`associations_in_region`'s query — :meth:`eqtls_for_gene`'s doesn't include it."""
    return EqtlAssociation(
        dataset_id=dataset_id,
        gene_id=_to_int(row[5]) or 0,
        rs_id=None,
        chrom=int(row[0]),
        position=int(row[1]),
        pvalue=_to_float(row[2]),
        beta=_to_float(row[3]),
        se=_to_float(row[4]),
        phenotype_id=str(row[6]) if len(row) > 6 and row[6] is not None else None,
    )


def _row_to_eqtl_enriched(
    dataset_id: int, gene_id: int, phenotype_map: dict[int, str], row: Row
) -> EqtlAssociation:
    """``row`` = ``(chrom, position, pval, beta, se, ref, alt, rsid, phenotype_key)`` — the
    :meth:`PostgresQtlRepository.cis_associations` shape, which (unlike :func:`_row_to_eqtl`) is
    gene-bounded enough to afford the ``variant_rsid_mapping_raw`` join. ``phenotype_map`` maps
    each matched ``phenotype_key`` back to its ``phenotype_id`` (built in ``cis_associations``'s
    first step, avoiding a second join here)."""
    rsid = row[7]
    rs_id = int(str(rsid)[2:]) if rsid else None  # "rs12345" -> 12345
    return EqtlAssociation(
        dataset_id=dataset_id,
        gene_id=gene_id,
        rs_id=rs_id,
        chrom=int(row[0]),
        position=int(row[1]),
        pvalue=_to_float(row[2]),
        beta=_to_float(row[3]),
        se=_to_float(row[4]),
        ref=str(row[5]) if row[5] is not None else None,
        alt=str(row[6]) if row[6] is not None else None,
        phenotype_id=phenotype_map.get(row[8]),
    )


def _row_to_eqtl_phenotype(
    dataset_id: int, gene_id: int, phenotype_id: str, row: Row
) -> EqtlAssociation:
    """``row`` = ``(chrom, position, pval, beta, se, ref, alt, rsid)`` — same enrichment shape as
    :func:`_row_to_eqtl_enriched`, for :meth:`PostgresQtlRepository.associations_for_phenotype`.
    No ``phenotype_map`` needed here (unlike that function): every row belongs to the one
    already-resolved ``phenotype_id`` the caller asked for."""
    rsid = row[7]
    rs_id = int(str(rsid)[2:]) if rsid else None
    return EqtlAssociation(
        dataset_id=dataset_id,
        gene_id=gene_id,
        rs_id=rs_id,
        chrom=int(row[0]),
        position=int(row[1]),
        pvalue=_to_float(row[2]),
        beta=_to_float(row[3]),
        se=_to_float(row[4]),
        ref=str(row[5]) if row[5] is not None else None,
        alt=str(row[6]) if row[6] is not None else None,
        phenotype_id=phenotype_id,
    )


class PostgresQtlRepository:
    """:class:`~locusview.repository.QtlRepository` backed by the new Postgres locuscompare2 DB.

    Takes a *connection factory* (a callable returning a DB-API connection), same pattern as the
    old (commented-out) ``LocuscompareRepository`` — unit-testable with a fake connection, real
    with :func:`postgres_connection_factory` / pg8000 in production.
    """

    def __init__(self, connection_factory: ConnectionFactory) -> None:
        """Store the connection factory; no connection is opened until a query actually runs."""
        self._connect = connection_factory

    @staticmethod
    def _run(conn: Any, sql: str, params: Sequence[Any]) -> list[Row]:
        """Execute one query on an already-open connection and return all rows."""
        cur = conn.cursor()
        cur.execute(sql, params)
        return list(cur.fetchall())

    def _query(self, sql: str, params: Sequence[Any]) -> list[Row]:
        """Open a connection, run one query, close the connection — the one-shot path most
        methods use (multi-query methods open their own connection and call :meth:`_run`
        directly instead, to reuse it across queries)."""
        try:
            conn = self._connect()
        except (TimeoutError, OSError) as exc:
            raise RepositoryTimeoutError("database connection timed out") from exc
        try:
            try:
                return self._run(conn, sql, params)
            except (TimeoutError, OSError) as exc:
                # pg8000 exposes socket read failures as built-in TimeoutError/OSError.  Convert
                # them to the repository boundary the HTTP routes already handle; never reuse a
                # connection whose protocol stream may now be out of sync.
                raise RepositoryTimeoutError("database query timed out") from exc
        finally:
            conn.close()

    def datasets(self) -> list[Dataset]:
        """The QTL dataset catalog: one row per (dataset, context) whose shard is ready to query.
        Only list qtl_lists rows whose association shard has actually been created —
        ingestion registers the qtl_lists/qtl_datasets/qtl_contexts rows before the shard table
        exists, so this filters out "not ready yet" datasets (e.g. CIMA in dev, 2026-08)."""
        rows = self._query(
            "SELECT ql.id, qd.dataset, qd.qtl_type, qd.population, "
            "coalesce(qc.level_1_context, ql.context) AS level_1, qc.level_2_context, "
            "ql.source_project_id "
            "FROM qtl_lists ql "
            "JOIN qtl_datasets qd ON qd.id = ql.qtl_dataset_id "
            "LEFT JOIN qtl_contexts qc ON qc.qtl_list_id = ql.id "
            "WHERE to_regclass('qtl_snp_' || ql.id) IS NOT NULL "
            "ORDER BY ql.id",
            (),
        )
        out = []
        for r in rows:
            list_id, dataset, qtl_type, population, level_1, level_2, source_project_id = r
            # The context label is level 2 when there is one, else level 1 — NOT both joined
            # (2026-08, by request): eQTL-style rows have only a tissue ("Whole_Blood"), while
            # caQTL-style rows add a cell type ("cMono_CD14") that's already the distinguishing
            # part — level 1 is the same "Whole_Blood" across many of them, so prefixing it just
            # made every label longer without adding information.
            # NOTE: the Home page's body map deliberately still matches on level 1 (via
            # QtlContextEntry.level_1, a separate query — see qtl_contexts()), because a cell type
            # like "cMono_CD14" has no anatomogram organ to point at; only "Whole_Blood" does.
            tissue = str(level_2) if level_2 else str(level_1)
            out.append(
                Dataset(
                    id=int(list_id),
                    tissue=tissue,
                    source=f"{dataset}-{qtl_type}-{population}",
                    source_project_id=str(source_project_id)
                    if source_project_id is not None
                    else None,
                )
            )
        return out

    def resolve_gene(self, symbol_or_ensembl: str) -> Gene | None:
        """Resolve a gene symbol or Ensembl id (versioned or bare) against ``gencode_v39`` — the
        DB's real gene-annotation table (see module docstring). One query tries all three forms;
        whichever matches wins. Real chrom/start/end/strand, not derived from variant positions."""
        key = symbol_or_ensembl.strip()
        if not key:
            return None
        rows = self._query(
            'SELECT gene_id_key, gene_name, gene_id, chr, start, "end", strand '
            "FROM gencode_v39 "
            "WHERE gene_id = %s OR split_part(gene_id, '.', 1) = %s "
            "OR upper(gene_name) = upper(%s) "
            "LIMIT 1",
            (key, key, key),
        )
        if not rows:
            return None
        gene_id_key, gene_name, ensembl_id, chrom, start, end, strand = rows[0]
        return Gene(
            gene_id=int(gene_id_key),
            symbol=str(gene_name),
            ensembl_id=str(ensembl_id),
            chrom=str(chrom).removeprefix("chr"),  # gencode's "chr17" -> the shards' bare "17"
            start=int(start),
            end=int(end),
            strand=str(strand),
        )

    def _gene_by_key(self, gene_id: int) -> Gene | None:
        """Look up a gene by its integer ``gene_id_key`` (e.g. ``141510``) — used by
        :meth:`cis_associations`'s caQTL-style branch to get the gene's genomic start."""
        rows = self._query(
            'SELECT gene_id_key, gene_name, gene_id, chr, start, "end", strand '
            "FROM gencode_v39 WHERE gene_id_key = %s LIMIT 1",
            (str(gene_id),),
        )
        if not rows:
            return None
        gene_id_key, gene_name, ensembl_id, chrom, start, end, strand = rows[0]
        return Gene(
            gene_id=int(gene_id_key),
            symbol=str(gene_name),
            ensembl_id=str(ensembl_id),
            chrom=str(chrom).removeprefix("chr"),  # gencode's "chr17" -> the shards' bare "17"
            start=int(start),
            end=int(end),
            strand=str(strand),
        )

    def _is_peak_dataset(self, dataset_id: int) -> bool:
        """Whether this shard's phenotypes are chromatin **peaks** (caQTL) rather than genes.

        Decided by the catalog's ``qtl_datasets.qtl_type``, *not* by whether ``gene_id`` happens
        to be NULL: only the **caQTL** companions were rebuilt with ``chrom``/``start``/``end``
        (2026-08), so every other QTL type — eQTL, sQTL, pQTL, whatever lands next — must take the
        gene path even if its own ``gene_id`` column is unpopulated. Inferring "peak-shaped" from
        NULL ``gene_id``s would send such a dataset down the peak branch and query columns its
        table doesn't have.
        """
        rows = self._query(
            "SELECT d.qtl_type FROM qtl_lists l JOIN qtl_datasets d ON d.id = l.qtl_dataset_id "
            "WHERE l.id = %s LIMIT 1",
            (dataset_id,),
        )
        return bool(rows) and str(rows[0][0]).strip().lower() in _PEAK_QTL_TYPES

    def _peak_phenotypes(
        self, dataset_id: int, chrom: str, start: int, end: int, limit: int | None = None
    ) -> list[Row]:
        """``(id, phenotype_id, gene_id)`` for every caQTL peak **overlapping** ``[start, end]``.

        Chromosome first, then the peak's range: that's exactly the ``(chrom, start, "end")``
        index the rebuilt ``qtl_snp_{id}_phenotype`` tables carry (2026-08), so Postgres seeks
        straight to the one chromosome's peaks instead of reading the table. The columns replace
        the old ``split_part(phenotype_id, '_', n)`` parse of the ``chr_start_end`` peak ID, which
        no index could serve — every caQTL lookup used to scan all ~115k-440k peak rows.

        Overlap is the standard half-open-free test ``peak.start <= end AND peak.end >= start``.
        Gene mode passes ``start == end == gene.start``, which collapses to "the peak contains this
        gene's start" — the semantics :meth:`cis_associations` has always used.

        Ordered by position, not by ``phenotype_id``: the IDs are strings, so ordering by them
        sorts ``chr17_9...`` before ``chr17_10...`` and, worse, makes a ``LIMIT`` return an
        arbitrary slice of the window rather than its left edge.
        """
        sql = (
            f"SELECT id, phenotype_id, gene_id FROM {_phenotype_table(dataset_id)} "
            f'WHERE chrom = %s AND start <= %s AND "end" >= %s '
            f'ORDER BY start, "end"'
        )
        params: tuple[Any, ...] = (f"chr{chrom}", end, start)  # peak chrom uses the "chr1" form
        if limit is not None:
            sql += " LIMIT %s"
            params += (limit,)
        return self._query(sql, params)

    def eqtls_for_gene(
        self, gene_id: int, dataset_ids: Sequence[int], limit: int = 100
    ) -> list[EqtlAssociation]:
        """eQTL associations for one gene across several datasets, capped at ``limit`` rows per
        dataset — the Gene page's own eQTL table (not the regional plot, which uses
        :meth:`cis_associations` instead)."""
        if not dataset_ids:
            return []
        conn = self._connect()
        try:
            out: list[EqtlAssociation] = []
            for dataset_id in dataset_ids:
                shard, pheno = _shard_table(dataset_id), _phenotype_table(dataset_id)
                rows = self._run(
                    conn,
                    f"SELECT s.chrom, s.position, s.pval, s.beta, s.se, p.gene_id "
                    f"FROM {shard} s JOIN {pheno} p ON p.id = s.phenotype_key "
                    f"WHERE p.gene_id::bigint = %s LIMIT %s",
                    (gene_id, limit),
                )
                out.extend(_row_to_eqtl(dataset_id, r) for r in rows)
            return out
        finally:
            conn.close()

    def cis_associations(self, gene_id: int, dataset_id: int) -> list[EqtlAssociation]:
        """ALL variants tied to this gene in one QTL dataset (the regional-plot / multi-track
        set) — gene-anchored and bounded, so (unlike :meth:`associations_in_region` etc.) this
        affords enriching every row with ``rs_id``/``ref``/``alt``.

        Two branches, decided by :meth:`_is_peak_dataset`:

        - **caQTL** (peaks, not genes): ``phenotype_id`` is a ``chr_start_end`` peak; match
          wherever this gene's start (from ``gencode_v39``, via :meth:`_gene_by_key`) falls inside
          that range, chromosome first — see :meth:`_peak_phenotypes`.
        - **every other QTL type** (eQTL/sQTL/pQTL/...): the gene resolved from ``gencode_v39`` is
          all that's needed — match ``phenotype.gene_id == gene_id`` directly. These tables have
          no peak coordinates to match on.

        Both resolve matching ``phenotype_key``s *first*, then fetch shard rows bounded by that
        (small) key set via ``phenotype_key = ANY(...)`` — resolving a inline gene_id/position
        filter straight into a query that also joins the ~9M-row ``variant_rsid_mapping_raw``
        table defeats the planner's row-count estimate and it picks a full seq scan/hash join
        instead of the indexed nested loop (confirmed: this literally times out). Keeping the two
        steps separate keeps every step index-backed — confirmed fast (~100-200ms) either way.
        """
        shard, pheno = _shard_table(dataset_id), _phenotype_table(dataset_id)
        if self._is_peak_dataset(dataset_id):
            gene = self._gene_by_key(gene_id)
            if gene is None:
                return []
            key_rows = self._peak_phenotypes(dataset_id, gene.chrom, gene.start, gene.start)
        else:
            key_rows = self._query(
                f"SELECT id, phenotype_id FROM {pheno} WHERE gene_id = %s", (str(gene_id),)
            )
        phenotype_map = {int(r[0]): str(r[1]) for r in key_rows}
        if not phenotype_map:
            return []

        rows = self._query(
            f"SELECT s.chrom, s.position, s.pval, s.beta, s.se, s.ref, s.alt, v.rsid, "
            f"s.phenotype_key "
            f"FROM {shard} s "
            f"LEFT JOIN variant_rsid_mapping_raw v "
            f"ON v.variant_id = 'chr' || s.chrom || '_' || s.position || '_' || s.ref || '_' "
            f"|| s.alt "
            f"WHERE s.phenotype_key = ANY(%s)",
            (list(phenotype_map.keys()),),
        )
        return [_row_to_eqtl_enriched(dataset_id, gene_id, phenotype_map, r) for r in rows]

    @staticmethod
    def _row_to_gwas(dataset_id: int, row: Row) -> GwasAssociation:
        """``row`` = ``(chrom, position, pval, beta, se, ref, alt, rsid)`` — same
        ``variant_rsid_mapping_raw`` join shape as :func:`_row_to_eqtl_enriched`, applied
        unconditionally by :meth:`gwas_associations_in_region` (see its docstring)."""
        rsid = row[7]
        rs_id = int(str(rsid)[2:]) if rsid else None  # "rs12345" -> 12345
        return GwasAssociation(
            dataset_id=dataset_id,
            chrom=int(row[0]),
            position=int(row[1]),
            pvalue=_to_float(row[2]),
            beta=_to_float(row[3]),
            se=_to_float(row[4]),
            ref=str(row[5]) if row[5] is not None else None,
            alt=str(row[6]) if row[6] is not None else None,
            rs_id=rs_id,
        )

    def ld_r2(self, chrom: str, lead_rs_id: int, population: str) -> dict[int, float]:
        """r² of every variant paired with the lead in the 1000G phase 3 reference panel
        (``tkg_p3v5a_ld_chr{chrom}_{population}`` — population-specific, re-hosted from the old
        MySQL DB; see module docstring). Pairs are stored one-directional (``SNP_A``/``SNP_B``),
        so this unions both directions and de-dupes with ``MAX`` — confirmed fast (~0.2s) via the
        indexes on both columns."""
        try:
            table = _ld_table(chrom, population)
        except ValueError:
            return {}
        lead = f"rs{lead_rs_id}"
        rows = self._query(
            f'SELECT partner, MAX("R2") AS r2 FROM ('
            f' SELECT "SNP_B" AS partner, "R2" FROM {table} WHERE "SNP_A" = %s'
            f" UNION ALL"
            f' SELECT "SNP_A" AS partner, "R2" FROM {table} WHERE "SNP_B" = %s'
            f") u GROUP BY partner",
            (lead, lead),
        )
        out: dict[int, float] = {}
        for partner, r2 in rows:
            m = _RS_PARTNER.match(str(partner))
            if m is None or r2 is None:  # skip non-rs ids (esv/ss/…) and NULLs
                continue
            out[int(m.group(1))] = max(0.0, min(1.0, float(r2)))
        out.pop(lead_rs_id, None)  # exclude self; the caller sets the lead's own r² = 1.0
        return out

    def tissues_with_signal(
        self, gene_id: int, p_threshold: float = 1e-5
    ) -> list[tuple[int, str, float]]:
        """Which datasets have at least one significant (p < ``p_threshold``) eQTL for this gene,
        sorted by significance — one MIN(p) query per dataset (not currently used by any live
        page, kept for ad-hoc/future "which tissues show signal" views)."""
        out: list[tuple[int, str, float]] = []
        for dataset in self.datasets():
            shard, pheno = _shard_table(dataset.id), _phenotype_table(dataset.id)
            rows = self._query(
                f"SELECT MIN(s.pval) FROM {shard} s JOIN {pheno} p ON p.id = s.phenotype_key "
                f"WHERE p.gene_id::bigint = %s",
                (gene_id,),
            )
            min_p = rows[0][0] if rows else None
            if min_p is not None and float(min_p) < p_threshold:
                out.append((dataset.id, dataset.tissue, float(min_p)))
        return sorted(out, key=lambda t: t[2])

    def associations_in_region(
        self, chrom: str, start: int, end: int, dataset_id: int
    ) -> list[EqtlAssociation]:
        """All variants in one dataset within a genomic window, not anchored to a gene — backs
        region/variant-mode locus queries. Deliberately not rs_id-enriched (see
        :meth:`associations_for_phenotype`'s docstring for why a whole window can't afford that
        the way a single phenotype can)."""
        shard = _shard_table(dataset_id)
        rows = self._query(
            f"SELECT s.chrom, s.position, s.pval, s.beta, s.se, p.gene_id, p.phenotype_id "
            f"FROM {shard} s JOIN {_phenotype_table(dataset_id)} p ON p.id = s.phenotype_key "
            f"WHERE s.chrom = %s AND s.position BETWEEN %s AND %s",
            (chrom, start, end),
        )
        return [_row_to_eqtl(dataset_id, r) for r in rows]

    def phenotype_summaries_in_region(
        self, chrom: str, start: int, end: int, dataset_id: int, limit: int = 50
    ) -> list[PhenotypeSummary]:
        """Phenotypes whose OWN feature overlaps ``[start, end]``, without loading association
        values. p-values and variant details are deliberately deferred until the user selects one.

        "Overlaps" means the phenotype's own coordinates — the caQTL peak, or the gene — intersect
        the window, which is what a user typing ``chr17:6661179-8661779`` is asking for:

        - **caQTL**: peaks straight out of the rebuilt ``_phenotype`` table's ``(chrom, start,
          "end")`` index (:meth:`_peak_phenotypes`).
        - **every other type**: the window's overlapping genes from ``gencode_v39`` (its own
          ``(chr, start, end)`` index), then the phenotype rows carrying those ``gene_id``s —
          the same gencode-then-gene_id path :meth:`phenotypes_for_gene` uses, just for a window's
          worth of genes instead of one.

        This deliberately does NOT go through the shard's variant positions the way
        :meth:`associations_in_region` does. Matching "phenotypes with a tested variant inside the
        window" pulls in phenotypes sitting up to a full cis window (~1 Mb) OUTSIDE it: their
        variants reach in, but the peak/gene itself is nowhere near what the user typed. Confirmed
        live on ``chr17:6661179-8661779`` — peak ``chr17_5665386_5665629`` (a megabyte to the left)
        matched because its tested variants span 4,666,082-6,665,497, and since those out-of-window
        peaks also sort first by ``phenotype_id``, all 50 rows of the Tenk10k panel were peaks that
        didn't overlap the window at all, hiding every one of the 596 that did.
        """
        pheno = _phenotype_table(dataset_id)
        if self._is_peak_dataset(dataset_id):
            rows: list[Row] = [
                (r[1], r[2]) for r in self._peak_phenotypes(dataset_id, chrom, start, end, limit)
            ]
        else:
            gene_keys = [
                str(r[0])
                for r in self._query(
                    "SELECT gene_id_key FROM gencode_v39 "
                    'WHERE chr = %s AND start <= %s AND "end" >= %s ORDER BY start',
                    (f"chr{chrom}", end, start),
                )
            ]
            if not gene_keys:
                return []
            rows = self._query(
                f"SELECT phenotype_id, gene_id FROM {pheno} WHERE gene_id = ANY(%s) "
                f"ORDER BY phenotype_id LIMIT %s",
                (gene_keys, limit),
            )
        return [
            PhenotypeSummary(
                phenotype_id=str(r[0]) if r[0] is not None else None,
                gene_id=int(r[1]) if r[1] is not None else None,
                lead_position=None,
                lead_pvalue=None,
                n=0,
            )
            for r in rows
        ]

    def phenotypes_for_gene(self, gene: Gene, dataset_id: int) -> list[PhenotypeSummary]:
        """Resolve a gene to phenotype IDs only; association values are fetched after selection.

        Only **caQTL** tables hold peaks: their ``chr_start_end`` phenotype IDs are matched when
        the GENCODE gene start lies inside the peak (:meth:`_peak_phenotypes`). Every other QTL
        type (eQTL/sQTL/pQTL/...) just matches the GENCODE gene's numeric ``gene_id_key`` against
        the phenotype table's ``gene_id``. No shard rows are touched either way.
        """
        pheno = _phenotype_table(dataset_id)
        rows: list[Row]
        if self._is_peak_dataset(dataset_id):
            # _peak_phenotypes selects (id, phenotype_id, gene_id); drop the shard key here.
            peaks = self._peak_phenotypes(dataset_id, gene.chrom, gene.start, gene.start)
            rows = [(r[1], r[2]) for r in peaks]
        else:
            rows = self._query(
                f"SELECT phenotype_id, gene_id FROM {pheno} WHERE gene_id = %s "
                "ORDER BY phenotype_id",
                (str(gene.gene_id),),
            )
        return [
            PhenotypeSummary(
                phenotype_id=str(r[0]),
                gene_id=_to_int(r[1]),
                lead_position=None,
                lead_pvalue=None,
                n=0,
            )
            for r in rows
        ]

    def associations_for_phenotype(
        self, dataset_id: int, phenotype_id: str, chrom: str, start: int, end: int
    ) -> list[EqtlAssociation]:
        """ALL variants tested for ONE phenotype (a gene's cis window, an sQTL splice cluster, or
        a caQTL peak), bounded to the displayed genomic window and enriched with
        ``rs_id``/``ref``/``alt``.

        Backs the Data Browser's region/variant-mode locus tabs' per-phenotype locuszoom panel.
        :meth:`associations_in_region` itself deliberately stays unenriched — a region/variant
        window can span 100+ phenotypes at once (see ``routers/locus.py``'s
        ``_group_by_phenotype``), and enriching all of them up front hits the same catastrophic-
        join risk :meth:`cis_associations`'s docstring warns about (confirmed live: a 1 Mb region
        here is 300k+ rows before any join, times out). But once the user checks *one* phenotype
        row to plot, that phenotype alone is the same order of magnitude as a gene's cis window
        (confirmed live: ~9k rows, ~2.4s enriched) — safe to fetch fresh here, on demand, giving
        region/variant-mode panels the same rs_id-driven LD coloring gene-mode panels already get
        from :meth:`cis_associations`."""
        pheno = _phenotype_table(dataset_id)
        shard = _shard_table(dataset_id)
        key_rows = self._query(
            f"SELECT id, gene_id FROM {pheno} WHERE phenotype_id = %s", (phenotype_id,)
        )
        if not key_rows:
            return []
        phenotype_key, gene_id_raw = key_rows[0]
        gene_id = _to_int(gene_id_raw) or 0
        rows = self._query(
            f"SELECT s.chrom, s.position, s.pval, s.beta, s.se, s.ref, s.alt, v.rsid "
            f"FROM {shard} s "
            f"LEFT JOIN variant_rsid_mapping_raw v "
            f"ON v.variant_id = 'chr' || s.chrom || '_' || s.position || '_' || s.ref || '_' "
            f"|| s.alt "
            f"WHERE s.phenotype_key = %s AND s.chrom = %s "
            f"AND s.position BETWEEN %s AND %s",
            (phenotype_key, chrom, start, end),
        )
        return [_row_to_eqtl_phenotype(dataset_id, gene_id, phenotype_id, r) for r in rows]

    def associations_for_rsid(
        self, rs_id: int, dataset_ids: Sequence[int], gene_id: int | None = None
    ) -> list[EqtlAssociation]:
        """Resolve ``rs{rs_id}`` -> ``(chrom, pos, ref, alt)`` via the indexed
        ``variant_rsid_mapping_raw`` table, then look that exact variant up per dataset
        (chrom/position is indexed on every shard)."""
        if not dataset_ids:
            return []
        mapped = self._query(
            "SELECT chrom, pos, ref, alt FROM variant_rsid_mapping_raw WHERE rsid = %s LIMIT 1",
            (f"rs{rs_id}",),
        )
        if not mapped:
            return []
        chrom, pos, ref, alt = mapped[0]

        conn = self._connect()
        try:
            out: list[EqtlAssociation] = []
            for dataset_id in dataset_ids:
                shard = _shard_table(dataset_id)
                rows = self._run(
                    conn,
                    f"SELECT s.chrom, s.position, s.pval, s.beta, s.se, p.gene_id "
                    f"FROM {shard} s JOIN {_phenotype_table(dataset_id)} p "
                    f"ON p.id = s.phenotype_key "
                    f"WHERE s.chrom = %s AND s.position = %s AND s.ref = %s AND s.alt = %s",
                    (chrom, pos, ref, alt),
                )
                out.extend(
                    EqtlAssociation(
                        dataset_id=dataset_id,
                        gene_id=_to_int(r[5]) or 0,
                        rs_id=rs_id,
                        chrom=int(r[0]),
                        position=int(r[1]),
                        pvalue=_to_float(r[2]),
                        beta=_to_float(r[3]),
                        se=_to_float(r[4]),
                    )
                    for r in rows
                )
            return out
        finally:
            conn.close()

    def resolve_variant(self, rs_id: int) -> tuple[str, int] | None:
        """A standalone "does this rsID exist at all" check — lighter than
        :meth:`associations_for_rsid` (which also fetches ``ref``/``alt`` for its own per-dataset
        exact-variant shard lookups)."""
        rows = self._query(
            "SELECT chrom, pos FROM variant_rsid_mapping_raw WHERE rsid = %s LIMIT 1",
            (f"rs{rs_id}",),
        )
        if not rows:
            return None
        return str(rows[0][0]), int(rows[0][1])

    def gwas_datasets(self) -> list[GwasDataset]:
        """The GWAS trait catalog: one row per (dataset, trait) whose shard is ready to query —
        same "only list ready shards" filter as :meth:`datasets`, a gwas_lists row can exist
        before its gwas_snp_{id} shard has been ingested."""
        rows = self._query(
            "SELECT gl.id, gl.trait, gl.population, gd.dataset, gl.accession "
            "FROM gwas_lists gl "
            "JOIN gwas_datasets gd ON gd.id = gl.gwas_dataset_id "
            "WHERE to_regclass('gwas_snp_' || gl.id) IS NOT NULL "
            "ORDER BY gl.id",
            (),
        )
        return [
            GwasDataset(
                id=int(r[0]),
                trait=str(r[1]),
                population=str(r[2]),
                source=str(r[3]),
                accession=str(r[4]) if r[4] is not None else "",
            )
            for r in rows
        ]

    def gwas_associations_in_region(
        self, chrom: str, start: int, end: int, dataset_id: int
    ) -> list[GwasAssociation]:
        """All GWAS variants in one trait within a genomic window, rs_id-enriched unconditionally
        (see the module docstring's performance note on why GWAS can afford this where QTL's
        :meth:`associations_in_region` can't)."""
        shard = _gwas_shard_table(dataset_id)
        rows = self._query(
            f"SELECT s.chrom, s.position, s.pval, s.beta, s.se, s.ref, s.alt, v.rsid "
            f"FROM {shard} s "
            f"LEFT JOIN variant_rsid_mapping_raw v "
            f"ON v.variant_id = 'chr' || s.chrom || '_' || s.position || '_' || s.ref || '_' "
            f"|| s.alt "
            f"WHERE s.chrom = %s AND s.position BETWEEN %s AND %s",
            (chrom, start, end),
        )
        return [self._row_to_gwas(dataset_id, r) for r in rows]

    def qtl_contexts(self) -> list[QtlContextEntry]:
        """Every ready (tissue, dataset) context, for the Home page's body map — see
        ``routers/home.py``'s ``_body_map_regions``."""
        rows = self._query(
            "SELECT ql.id, qc.level_1_context, qc.level_2_context, qd.dataset, qd.qtl_type, "
            "qd.population "
            "FROM qtl_contexts qc "
            "JOIN qtl_lists ql ON ql.id = qc.qtl_list_id "
            "JOIN qtl_datasets qd ON qd.id = ql.qtl_dataset_id "
            "WHERE to_regclass('qtl_snp_' || ql.id) IS NOT NULL "
            "ORDER BY ql.id",
            (),
        )
        return [
            QtlContextEntry(
                qtl_list_id=int(r[0]),
                level_1=str(r[1]),
                level_2=str(r[2]) if r[2] is not None else None,
                dataset_label=f"{r[3]}-{r[4]}",
            )
            for r in rows
        ]


def postgres_connection_factory() -> ConnectionFactory:
    """Build a factory that opens a read-only pg8000 connection from ``LOCUSCOMPARE2_PG_*``
    settings. The password must come from the secret store / ``.env`` — never source."""

    def _connect() -> Any:  # pragma: no cover - needs a live DB + network
        """Open one new pg8000 connection using the current settings."""
        import pg8000

        from locusview.config import get_pg_settings

        settings = get_pg_settings()
        conn = pg8000.connect(
            host=settings.host,
            port=settings.port,
            user=settings.user,
            password=settings.password,
            database=settings.name,
            timeout=8,
        )
        conn.run(f"SET search_path TO {settings.db_schema}")
        return conn

    return _connect
