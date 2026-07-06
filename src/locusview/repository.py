"""Read access to QTL data.

Defines the :class:`QtlRepository` interface (a ``Protocol``) plus two implementations:

* :class:`FakeQtlRepository` — in-memory canned data for tests and offline development.
* :class:`LocuscompareRepository` — reads the shared locuscompare2 MySQL database (ADR-0008).

**locuscompare2 model (verified against the live DB).** ``eqtl_raw`` is a *catalog* of datasets
(one row per tissue; ``id`` -> shard). The associations live in per-dataset shard tables
``eqtl_snp_{id}`` with integer-encoded keys (``rs_id``, ``gene_id``, ``chrom``). NOTE: the shards
store no ref/alt/effect_allele or MAF, so ``beta``'s sign is not interpretable from the DB alone
(tracked in issue #18) — hence :class:`EqtlAssociation` has no effect-allele field.

Programming to this interface lets the app and its tests run against :class:`FakeQtlRepository`
today and swap in :class:`LocuscompareRepository` unchanged.
"""

from __future__ import annotations

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

    def eqtls_for_gene(
        self, gene_id: int, dataset_ids: Sequence[int], limit: int = 100
    ) -> list[EqtlAssociation]:
        """Return eQTL associations for ``gene_id`` within the given datasets."""
        ...


# ── Fake (in-memory) ────────────────────────────────────────────────────────


class FakeQtlRepository:
    """In-memory :class:`QtlRepository` for tests and offline development."""

    def __init__(
        self,
        datasets: Sequence[Dataset] | None = None,
        associations: Sequence[EqtlAssociation] | None = None,
    ) -> None:
        self._datasets = list(datasets or ())
        self._associations = list(associations or ())

    def datasets(self) -> list[Dataset]:
        return list(self._datasets)

    def eqtls_for_gene(
        self, gene_id: int, dataset_ids: Sequence[int], limit: int = 100
    ) -> list[EqtlAssociation]:
        wanted = set(dataset_ids)
        hits = [a for a in self._associations if a.gene_id == gene_id and a.dataset_id in wanted]
        return hits[:limit]


# ── Real (locuscompare2 MySQL) ──────────────────────────────────────────────

Row = Sequence[Any]
ConnectionFactory = Callable[[], Any]


def _shard_table(dataset_id: int) -> str:
    """Return the shard table name for a dataset id.

    The id is validated as a non-negative int so it is safe to interpolate into SQL (the shard
    table name cannot be parameterised, only the values can).
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


class LocuscompareRepository:
    """:class:`QtlRepository` backed by the shared locuscompare2 MySQL database.

    Takes a *connection factory* (a callable returning a DB-API connection) so it can be
    unit-tested with a fake connection and used with pymysql in production.
    """

    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._connect = connection_factory

    def _query(self, sql: str, params: Sequence[Any]) -> list[Row]:
        conn = self._connect()
        try:
            cur = conn.cursor()
            cur.execute(sql, params)
            return list(cur.fetchall())
        finally:
            conn.close()

    def datasets(self) -> list[Dataset]:
        rows = self._query("SELECT id, tissue, type FROM eqtl_raw", ())
        return [Dataset(id=int(r[0]), tissue=str(r[1]), source=str(r[2])) for r in rows]

    def eqtls_for_gene(
        self, gene_id: int, dataset_ids: Sequence[int], limit: int = 100
    ) -> list[EqtlAssociation]:
        out: list[EqtlAssociation] = []
        for dataset_id in dataset_ids:
            table = _shard_table(dataset_id)
            rows = self._query(
                f"SELECT gene_id, rs_id, chrom, position, pvalue, beta, se "
                f"FROM {table} WHERE gene_id = %s LIMIT %s",
                (gene_id, limit),
            )
            out.extend(_row_to_eqtl(dataset_id, r) for r in rows)
        return out


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
