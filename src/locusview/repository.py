"""Read access to QTL data.

Defines the :class:`QtlRepository` interface (a ``Protocol``) plus two implementations:

* :class:`FakeQtlRepository` — in-memory canned data for tests and offline development.
* :class:`LocuscompareRepository` — reads the shared locuscompare2 MySQL database (ADR-0008).

**locuscompare2 model (verified against the live DB).** ``eqtl_raw`` is a *catalog* of datasets
(one row per tissue; ``id`` -> shard). The associations live in per-dataset shard tables
``eqtl_snp_{id}`` with integer-encoded keys (``rs_id``, ``gene_id``, ``chrom``). Gene metadata
(symbol <-> Ensembl id <-> coordinates) lives in ``gencode_v26_hg38``. NOTE: the shards store no
ref/alt/effect_allele or MAF, so ``beta``'s sign is not interpretable from the DB alone (issue #18).

Programming to this interface lets the app and its tests run against :class:`FakeQtlRepository`
today and swap in :class:`LocuscompareRepository` unchanged.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class Dataset:
    """A QTL dataset in the catalog (one per tissue), keyed by its integer id."""

    id: int
    tissue: str
    source: str  # the catalog `type` column, e.g. "gtex-v8"


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

    def variant_chrom(self, rs_id: int) -> int | None:
        """Resolve a variant's chromosome (needed to use the ``(chrom, rs_id)`` index), or None."""
        ...

    def eqtls_for_variant(
        self, chrom: int, rs_id: int, dataset_ids: Sequence[int]
    ) -> list[EqtlAssociation]:
        """Reverse lookup: every association for one variant across the given datasets."""
        ...

    def gene_by_id(self, gene_id: int) -> Gene | None:
        """Resolve a :class:`Gene` from its integer id (reverse of :meth:`resolve_gene`)."""

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


# ── Shared pure helpers ──────────────────────────────────────────────────────

Row = Sequence[Any]
ConnectionFactory = Callable[[], Any]

_ENSG = re.compile(r"^ENSG0*(\d+)$", re.IGNORECASE)
_GENCODE_TABLE = "gencode_v26_hg38"  # GTEx v8 uses GENCODE v26 (hg38)
# 1000G phase-3 variant reference: rsid -> chr/pos/ref/alt + per-population AF. Indexed on `rsid`.
_VARIANT_REF_TABLE = "tkg_p3v5a_hg38"

_RS_PARTNER = re.compile(r"^rs(\d+)$")
CHROMS = frozenset([*(str(i) for i in range(1, 23)), "X"])
POPULATIONS = frozenset({"AFR", "AMR", "EAS", "EUR", "SAS"})


def _ld_table(chrom: str, population: str) -> str:
    """Return the 1000G LD table name for a chromosome + super-population (enum-validated,
    so the interpolated table name is safe)."""
    if chrom not in CHROMS:
        raise ValueError(f"unknown chromosome: {chrom!r}")
    if population not in POPULATIONS:
        raise ValueError(f"unknown population: {population!r}")
    return f"tkg_p3v5a_ld_chr{chrom}_{population}"


def ensembl_number(ensembl_id: str) -> int:
    """Convert an Ensembl gene id to the integer key used by the shards.

    ``"ENSG00000141510.16"`` or ``"ENSG00000141510"`` -> ``141510``.
    """
    core = ensembl_id.split(".", 1)[0]
    m = _ENSG.match(core)
    if not m:
        raise ValueError(f"not an Ensembl gene id: {ensembl_id!r}")
    return int(m.group(1))


def _shard_table(dataset_id: int) -> str:
    """Return the shard table name for a dataset id.

    The id is validated as a non-negative int so it is safe to interpolate into SQL (a table
    name cannot be parameterised, only values can).
    """
    if not isinstance(dataset_id, int) or isinstance(dataset_id, bool) or dataset_id < 0:
        raise ValueError(f"dataset_id must be a non-negative int, got {dataset_id!r}")
    return f"eqtl_snp_{dataset_id}"


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _row_to_eqtl(dataset_id: int, row: Row) -> EqtlAssociation:
    return EqtlAssociation(
        dataset_id=dataset_id,
        gene_id=int(row[0]),
        rs_id=_to_int(row[1]),
        chrom=int(row[2]),
        position=int(row[3]),
        pvalue=_to_float(row[4]),
        beta=_to_float(row[5]),
        se=_to_float(row[6]),
    )


def _row_to_gene(row: Row) -> Gene:
    ensembl_id = str(row[1])
    return Gene(
        gene_id=ensembl_number(ensembl_id),
        symbol=str(row[0]),
        ensembl_id=ensembl_id,
        chrom=str(row[2]),
        start=int(row[3]),
        end=int(row[4]),
        strand=str(row[5]),
    )


# ── Fake (in-memory) ────────────────────────────────────────────────────────


class FakeQtlRepository:
    """In-memory :class:`QtlRepository` for tests and offline development."""

    def __init__(
        self,
        datasets: Sequence[Dataset] | None = None,
        associations: Sequence[EqtlAssociation] | None = None,
        genes: Sequence[Gene] | None = None,
        ld: dict[tuple[str, int, str], dict[int, float]] | None = None,
    ) -> None:
        self._datasets = list(datasets or ())
        self._associations = list(associations or ())
        self._genes = list(genes or ())
        self._ld = dict(ld or {})

    def datasets(self) -> list[Dataset]:
        return list(self._datasets)

    def resolve_gene(self, symbol_or_ensembl: str) -> Gene | None:
        key = symbol_or_ensembl.strip()
        core = key.split(".", 1)[0].upper()
        for g in self._genes:
            if g.symbol.upper() == key.upper() or g.ensembl_id.split(".", 1)[0].upper() == core:
                return g
        return None

    def eqtls_for_gene(
        self, gene_id: int, dataset_ids: Sequence[int], limit: int = 100
    ) -> list[EqtlAssociation]:
        wanted = set(dataset_ids)
        hits = [a for a in self._associations if a.gene_id == gene_id and a.dataset_id in wanted]
        return hits[:limit]

    def variant_chrom(self, rs_id: int) -> int | None:
        for a in self._associations:
            if a.rs_id == rs_id:
                return a.chrom
        return None

    def eqtls_for_variant(
        self, chrom: int, rs_id: int, dataset_ids: Sequence[int]
    ) -> list[EqtlAssociation]:
        wanted = set(dataset_ids)
        return [
            a
            for a in self._associations
            if a.chrom == chrom and a.rs_id == rs_id and a.dataset_id in wanted
        ]

    def gene_by_id(self, gene_id: int) -> Gene | None:
        return next((g for g in self._genes if g.gene_id == gene_id), None)

    def cis_associations(self, gene_id: int, dataset_id: int) -> list[EqtlAssociation]:
        return [
            a for a in self._associations if a.gene_id == gene_id and a.dataset_id == dataset_id
        ]

    def ld_r2(self, chrom: str, lead_rs_id: int, population: str) -> dict[int, float]:
        return dict(self._ld.get((chrom, lead_rs_id, population), {}))

    def tissues_with_signal(
        self, gene_id: int, p_threshold: float = 1e-5
    ) -> list[tuple[int, str, float]]:
        name = {d.id: d.tissue for d in self._datasets}
        best: dict[int, float] = {}
        for a in self._associations:
            if a.gene_id == gene_id and a.pvalue is not None and a.pvalue < p_threshold:
                best[a.dataset_id] = min(best.get(a.dataset_id, 1.0), a.pvalue)
        return sorted(
            ((ds, name.get(ds, str(ds)), p) for ds, p in best.items()), key=lambda t: t[2]
        )


# ── Real (locuscompare2 MySQL) ──────────────────────────────────────────────


class LocuscompareRepository:
    """:class:`QtlRepository` backed by the shared locuscompare2 MySQL database.

    Takes a *connection factory* (a callable returning a DB-API connection) so it can be
    unit-tested with a fake connection and used with pymysql in production.
    """

    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._connect = connection_factory

    @staticmethod
    def _run(conn: Any, sql: str, params: Sequence[Any]) -> list[Row]:
        cur = conn.cursor()
        cur.execute(sql, params)
        return list(cur.fetchall())

    def _query(self, sql: str, params: Sequence[Any]) -> list[Row]:
        conn = self._connect()
        try:
            return self._run(conn, sql, params)
        finally:
            conn.close()

    def datasets(self) -> list[Dataset]:
        rows = self._query("SELECT id, tissue, type FROM eqtl_raw", ())
        return [Dataset(id=int(r[0]), tissue=str(r[1]), source=str(r[2])) for r in rows]

    def resolve_gene(self, symbol_or_ensembl: str) -> Gene | None:
        key = symbol_or_ensembl.strip()
        select = f"SELECT gene_name, gene_id, chr, start, end, strand FROM {_GENCODE_TABLE} "
        if key.upper().startswith("ENSG"):
            core = key.split(".", 1)[0]
            rows = self._query(select + "WHERE gene_id LIKE %s LIMIT 1", (f"{core}%",))
        else:
            rows = self._query(select + "WHERE gene_name = %s LIMIT 1", (key,))
        return _row_to_gene(rows[0]) if rows else None

    def eqtls_for_gene(
        self, gene_id: int, dataset_ids: Sequence[int], limit: int = 100
    ) -> list[EqtlAssociation]:
        if not dataset_ids:
            return []
        conn = self._connect()  # one connection for the whole fan-out
        try:
            out: list[EqtlAssociation] = []
            for dataset_id in dataset_ids:
                table = _shard_table(dataset_id)
                rows = self._run(
                    conn,
                    f"SELECT gene_id, rs_id, chrom, position, pvalue, beta, se "
                    f"FROM {table} WHERE gene_id = %s LIMIT %s",
                    (gene_id, limit),
                )
                out.extend(_row_to_eqtl(dataset_id, r) for r in rows)
            return out
        finally:
            conn.close()

    def variant_chrom(self, rs_id: int) -> int | None:
        """Resolve a variant's chromosome from the 1000G variant reference.

        ``tkg_p3v5a_hg38`` (75M rows) is indexed on ``rsid``, so this is a single ~15 ms seek, and
        it covers *every* 1000G variant — not only those appearing in an LD **pair**. Returns
        ``None`` for unknown rsIDs and for non-autosomes (the eQTL shards are autosomal).
        """
        rows = self._query(
            f"SELECT chr FROM {_VARIANT_REF_TABLE} WHERE rsid = %s LIMIT 1", (f"rs{rs_id}",)
        )
        if not rows:
            return None
        chrom = str(rows[0][0])
        return int(chrom) if chrom.isdigit() and 1 <= int(chrom) <= 22 else None

    def eqtls_for_variant(
        self, chrom: int, rs_id: int, dataset_ids: Sequence[int]
    ) -> list[EqtlAssociation]:
        if not dataset_ids:
            return []
        conn = self._connect()  # one connection for the whole fan-out
        try:
            out: list[EqtlAssociation] = []
            for dataset_id in dataset_ids:
                table = _shard_table(dataset_id)
                # (chrom, rs_id) hits idx_eqtl_snp_join — a precise seek, ~100 rows not a full scan.
                rows = self._run(
                    conn,
                    f"SELECT gene_id, rs_id, chrom, position, pvalue, beta, se "
                    f"FROM {table} WHERE chrom = %s AND rs_id = %s",
                    (chrom, rs_id),
                )
                out.extend(_row_to_eqtl(dataset_id, r) for r in rows)
            return out
        finally:
            conn.close()

    def gene_by_id(self, gene_id: int) -> Gene | None:
        ensg = f"ENSG{gene_id:011d}"  # 141510 -> "ENSG00000141510"
        rows = self._query(
            f"SELECT gene_name, gene_id, chr, start, end, strand FROM {_GENCODE_TABLE} "
            f"WHERE gene_id LIKE %s LIMIT 1",
            (f"{ensg}%",),
        )
        return _row_to_gene(rows[0]) if rows else None

    def cis_associations(self, gene_id: int, dataset_id: int) -> list[EqtlAssociation]:
        table = _shard_table(dataset_id)
        rows = self._query(
            f"SELECT gene_id, rs_id, chrom, position, pvalue, beta, se "
            f"FROM {table} WHERE gene_id = %s",
            (gene_id,),
        )
        return [_row_to_eqtl(dataset_id, r) for r in rows]

    def ld_r2(self, chrom: str, lead_rs_id: int, population: str) -> dict[int, float]:
        table = _ld_table(chrom, population)
        lead = f"rs{lead_rs_id}"
        # LD pairs are stored one-directional, so union both directions and dedupe with MAX.
        rows = self._query(
            f"SELECT partner, MAX(R2) AS r2 FROM ("
            f" SELECT SNP_B AS partner, R2 FROM {table} WHERE SNP_A = %s"
            f" UNION ALL"
            f" SELECT SNP_A AS partner, R2 FROM {table} WHERE SNP_B = %s"
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
        # Fan-out across dataset shards. NOTE: O(#tissues) queries — a candidate for a
        # per-gene summary table (schema-change-coordination) if it gets hot.
        out: list[tuple[int, str, float]] = []
        for dataset in self.datasets():
            table = _shard_table(dataset.id)
            # pvalue is stored as text; `+ 0.0` forces numeric MIN (handles decimal + scientific).
            rows = self._query(
                f"SELECT MIN(pvalue + 0.0) FROM {table} WHERE gene_id = %s", (gene_id,)
            )
            min_p = rows[0][0] if rows else None
            if min_p is not None and float(min_p) < p_threshold:
                out.append((dataset.id, dataset.tissue, float(min_p)))
        return sorted(out, key=lambda t: t[2])


def pymysql_connection_factory() -> ConnectionFactory:
    """Build a factory that opens a read-only pymysql connection from ``LOCUSCOMPARE2_DB_*``
    settings. The password must come from the secret store / ``.env`` — never source."""

    def _connect() -> Any:  # pragma: no cover - needs a live DB + network
        import pymysql

        from locusview.config import get_db_settings

        settings = get_db_settings()
        return pymysql.connect(
            host=settings.host,
            port=settings.port,
            user=settings.user,
            password=settings.password,
            database=settings.name,
            connect_timeout=8,
            read_timeout=30,
        )

    return _connect
