"""Tests for the QTL data-access layer.

The real ``LocuscompareRepository`` is exercised through a fake DB-API connection, so its SQL
and row-mapping are covered without touching a live database or the network.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import pytest

from locusview.repository import (
    Dataset,
    EqtlAssociation,
    FakeQtlRepository,
    LocuscompareRepository,
    _row_to_eqtl,
    _shard_table,
    _to_float,
    _to_int,
    pymysql_connection_factory,
)

# ── helpers ─────────────────────────────────────────────────────────────────


def test_shard_table_valid() -> None:
    assert _shard_table(42) == "eqtl_snp_42"


@pytest.mark.parametrize("bad", [-1, True, "3"])
def test_shard_table_rejects_bad_input(bad: Any) -> None:
    with pytest.raises(ValueError):
        _shard_table(bad)


def test_to_float() -> None:
    assert _to_float("0.5") == 0.5
    assert _to_float(None) is None
    assert _to_float("not-a-number") is None


def test_to_int() -> None:
    assert _to_int("7") == 7
    assert _to_int(None) is None
    assert _to_int("x") is None


def test_row_to_eqtl_maps_and_casts() -> None:
    assoc = _row_to_eqtl(5, (177951, 867721319, 11, 128951, "0.83", "-0.03", "0.15"))
    assert assoc == EqtlAssociation(
        dataset_id=5,
        gene_id=177951,
        rs_id=867721319,
        chrom=11,
        position=128951,
        pvalue=0.83,
        beta=-0.03,
        se=0.15,
    )


# ── FakeQtlRepository ────────────────────────────────────────────────────────


def test_fake_repository_filters_by_gene_and_dataset() -> None:
    repo = FakeQtlRepository(
        datasets=[Dataset(1, "Whole_Blood", "gtex-v8")],
        associations=[
            EqtlAssociation(1, 100, 1, 1, 10, 0.01, 0.2, 0.05),
            EqtlAssociation(1, 999, 2, 1, 20, 0.5, 0.1, 0.05),  # other gene
            EqtlAssociation(2, 100, 3, 1, 30, 0.02, 0.3, 0.05),  # other dataset
        ],
    )
    assert repo.datasets() == [Dataset(1, "Whole_Blood", "gtex-v8")]
    hits = repo.eqtls_for_gene(100, [1])
    assert [a.dataset_id for a in hits] == [1]
    assert hits[0].gene_id == 100


def test_fake_repository_respects_limit() -> None:
    repo = FakeQtlRepository(
        associations=[EqtlAssociation(1, 7, i, 1, i, 0.01, 0.1, 0.02) for i in range(5)]
    )
    assert len(repo.eqtls_for_gene(7, [1], limit=2)) == 2


# ── LocuscompareRepository (via a fake connection) ──────────────────────────


class _FakeCursor:
    def __init__(self, rows: Sequence[Row], log: list[tuple[str, tuple[Any, ...]]]) -> None:
        self._rows = rows
        self._log = log

    def execute(self, sql: str, params: Sequence[Any] = ()) -> None:
        self._log.append((sql, tuple(params)))

    def fetchall(self) -> Sequence[Row]:
        return self._rows


Row = Sequence[Any]


class _FakeConn:
    def __init__(self, rows: Sequence[Row], log: list[tuple[str, tuple[Any, ...]]]) -> None:
        self._rows = rows
        self._log = log
        self.closed = False

    def cursor(self) -> _FakeCursor:
        return _FakeCursor(self._rows, self._log)

    def close(self) -> None:
        self.closed = True


def _factory(rows: Sequence[Row]) -> tuple[Any, list[tuple[str, tuple[Any, ...]]]]:
    log: list[tuple[str, tuple[Any, ...]]] = []

    def make() -> _FakeConn:
        return _FakeConn(rows, log)

    return make, log


def test_locuscompare_datasets_maps_catalog_rows() -> None:
    factory, _ = _factory([(1, "Whole_Blood", "gtex-v8"), (2, "Stomach", "gtex-v8")])
    repo = LocuscompareRepository(factory)
    assert repo.datasets() == [
        Dataset(1, "Whole_Blood", "gtex-v8"),
        Dataset(2, "Stomach", "gtex-v8"),
    ]


def test_locuscompare_eqtls_for_gene_targets_correct_shards() -> None:
    factory, log = _factory([(177951, 867721319, 11, 128951, "0.83", "-0.03", "0.15")])
    repo = LocuscompareRepository(factory)
    hits = repo.eqtls_for_gene(177951, [1, 10], limit=50)

    # One query per shard, each with the right table name and parameters.
    tables = [sql for sql, _ in log]
    assert any("eqtl_snp_1 " in sql for sql in tables)
    assert any("eqtl_snp_10 " in sql for sql in tables)
    assert all(params == (177951, 50) for _, params in log)
    # Rows mapped for each shard queried.
    assert [a.dataset_id for a in hits] == [1, 10]
    assert hits[0].beta == -0.03


def test_pymysql_connection_factory_returns_callable() -> None:
    # Builds the factory (does not connect — that needs a live DB).
    assert callable(pymysql_connection_factory())
