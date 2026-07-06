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
    Gene,
    LocuscompareRepository,
    _ld_table,
    _row_to_eqtl,
    _row_to_gene,
    _shard_table,
    _to_float,
    _to_int,
    ensembl_number,
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


def test_locuscompare_eqtls_for_gene_empty_datasets() -> None:
    factory, log = _factory([])
    assert LocuscompareRepository(factory).eqtls_for_gene(1, []) == []
    assert log == []  # no query issued when there are no datasets


def test_pymysql_connection_factory_returns_callable() -> None:
    # Builds the factory (does not connect — that needs a live DB).
    assert callable(pymysql_connection_factory())


# ── gene resolution ─────────────────────────────────────────────────────────

_GENCODE = ("TP53", "ENSG00000141510.16", "17", 7661779, 7687550, "-")


def test_ensembl_number() -> None:
    assert ensembl_number("ENSG00000141510.16") == 141510
    assert ensembl_number("ENSG00000141510") == 141510
    assert ensembl_number("ensg00000000005") == 5


def test_ensembl_number_rejects_bad_input() -> None:
    with pytest.raises(ValueError):
        ensembl_number("TP53")


def test_row_to_gene() -> None:
    assert _row_to_gene(_GENCODE) == Gene(
        141510, "TP53", "ENSG00000141510.16", "17", 7661779, 7687550, "-"
    )


def test_fake_resolve_gene_by_symbol_and_ensembl() -> None:
    gene = Gene(141510, "TP53", "ENSG00000141510.16", "17", 7661779, 7687550, "-")
    repo = FakeQtlRepository(genes=[gene])
    assert repo.resolve_gene("tp53") == gene  # case-insensitive symbol
    assert repo.resolve_gene("ENSG00000141510") == gene  # unversioned Ensembl id
    assert repo.resolve_gene("NOPE") is None


def test_locuscompare_resolve_gene_by_symbol() -> None:
    factory, log = _factory([_GENCODE])
    gene = LocuscompareRepository(factory).resolve_gene("TP53")
    assert gene == Gene(141510, "TP53", "ENSG00000141510.16", "17", 7661779, 7687550, "-")
    assert "gene_name = %s" in log[0][0] and log[0][1] == ("TP53",)


def test_locuscompare_resolve_gene_by_ensembl_uses_like() -> None:
    factory, log = _factory([_GENCODE])
    LocuscompareRepository(factory).resolve_gene("ENSG00000141510.16")
    assert "gene_id LIKE %s" in log[0][0]
    assert log[0][1] == ("ENSG00000141510%",)


def test_locuscompare_resolve_gene_not_found() -> None:
    factory, _ = _factory([])
    assert LocuscompareRepository(factory).resolve_gene("NOPE") is None


# ── LD / cis / tissues-with-signal ──────────────────────────────────────────


def _routing_factory(
    responder: object,
) -> tuple[object, list[tuple[str, tuple[object, ...]]]]:
    """A fake connection whose returned rows depend on the SQL (for multi-query methods)."""
    log: list[tuple[str, tuple[object, ...]]] = []

    class _Cur:
        def execute(self, sql: str, params: Sequence[object] = ()) -> None:
            log.append((sql, tuple(params)))
            self._rows = responder(sql, tuple(params))  # type: ignore[operator]

        def fetchall(self) -> object:
            return self._rows

    class _Conn:
        def cursor(self) -> _Cur:
            return _Cur()

        def close(self) -> None:
            pass

    return (lambda: _Conn()), log


def test_ld_table_valid() -> None:
    assert _ld_table("1", "EUR") == "tkg_p3v5a_ld_chr1_EUR"
    assert _ld_table("X", "AFR") == "tkg_p3v5a_ld_chrX_AFR"


@pytest.mark.parametrize(("chrom", "pop"), [("23", "EUR"), ("1", "ALL"), ("Y", "EUR")])
def test_ld_table_rejects_bad_input(chrom: str, pop: str) -> None:
    with pytest.raises(ValueError):
        _ld_table(chrom, pop)


def test_fake_cis_associations() -> None:
    repo = FakeQtlRepository(
        associations=[
            EqtlAssociation(8, 141510, 1, 17, 100, 0.01, 0.2, 0.05),
            EqtlAssociation(8, 999, 2, 17, 200, 0.5, 0.1, 0.05),  # other gene
            EqtlAssociation(9, 141510, 3, 17, 300, 0.02, 0.3, 0.05),  # other tissue
        ]
    )
    assert [a.rs_id for a in repo.cis_associations(141510, 8)] == [1]


def test_fake_ld_r2() -> None:
    repo = FakeQtlRepository(ld={("17", 111, "EUR"): {222: 0.9}})
    assert repo.ld_r2("17", 111, "EUR") == {222: 0.9}
    assert repo.ld_r2("17", 999, "EUR") == {}


def test_fake_tissues_with_signal() -> None:
    repo = FakeQtlRepository(
        datasets=[Dataset(1, "Whole_Blood", "gtex-v8"), Dataset(2, "Liver", "gtex-v8")],
        associations=[
            EqtlAssociation(1, 7, 1, 1, 10, 1e-8, 0.2, 0.05),  # significant in ds 1
            EqtlAssociation(1, 7, 2, 1, 20, 1e-6, 0.1, 0.05),  # ds 1 (min stays 1e-8)
            EqtlAssociation(2, 7, 3, 1, 30, 0.5, 0.3, 0.05),  # ds 2: not significant
        ],
    )
    assert repo.tissues_with_signal(7) == [(1, "Whole_Blood", 1e-8)]


def test_locuscompare_cis_associations() -> None:
    factory, log = _factory([(141510, 12345, 17, 7670000, "0.001", "0.2", "0.05")])
    hits = LocuscompareRepository(factory).cis_associations(141510, 8)
    assert "eqtl_snp_8 " in log[0][0] and log[0][1] == (141510,)
    assert hits[0].rs_id == 12345 and hits[0].dataset_id == 8


def test_locuscompare_ld_r2_parses_and_dedupes() -> None:
    factory, log = _factory([("rs100", 0.8), ("rs200", 0.3), ("esv9", 0.9), ("rs111", 1.0)])
    r2 = LocuscompareRepository(factory).ld_r2("1", 111, "EUR")
    # 'esv9' skipped (non-rs); the lead rs111 removed so the caller sets it to 1.0.
    assert r2 == {100: 0.8, 200: 0.3}
    assert "tkg_p3v5a_ld_chr1_EUR" in log[0][0]
    assert log[0][1] == ("rs111", "rs111")


def test_locuscompare_tissues_with_signal() -> None:
    def responder(sql: str, params: tuple[object, ...]) -> list[tuple[object, ...]]:
        if "eqtl_raw" in sql:
            return [(1, "Whole_Blood", "gtex-v8"), (2, "Liver", "gtex-v8")]
        if "eqtl_snp_1 " in sql:
            return [(1e-8,)]
        return [(0.5,)]  # eqtl_snp_2: not significant

    factory, _ = _routing_factory(responder)
    assert LocuscompareRepository(factory).tissues_with_signal(7) == [(1, "Whole_Blood", 1e-8)]
