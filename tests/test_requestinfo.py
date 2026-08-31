"""Tests for the QTL data-access layer's shared pieces: the Protocol's :class:`FakeQtlRepository`
and pure helpers. The real Postgres implementation (``PostgresQtlRepository``) is tested in
``test_connectpostgres.py`` instead.
"""

from __future__ import annotations

import pytest

from locusview.requestinfo import (
    Dataset,
    EqtlAssociation,
    FakeQtlRepository,
    Gene,
    GwasAssociation,
    GwasDataset,
    QtlContextEntry,
    _to_float,
    _to_int,
    ensembl_number,
)

# ── helpers ─────────────────────────────────────────────────────────────────


def test_to_float() -> None:
    assert _to_float("0.5") == 0.5
    assert _to_float(None) is None
    assert _to_float("not-a-number") is None


def test_to_int() -> None:
    assert _to_int("7") == 7
    assert _to_int(None) is None
    assert _to_int("x") is None


def test_ensembl_number() -> None:
    assert ensembl_number("ENSG00000141510.16") == 141510
    assert ensembl_number("ENSG00000141510") == 141510
    assert ensembl_number("ensg00000000005") == 5


def test_ensembl_number_rejects_bad_input() -> None:
    with pytest.raises(ValueError):
        ensembl_number("TP53")


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


def test_fake_resolve_gene_by_symbol_and_ensembl() -> None:
    gene = Gene(141510, "TP53", "ENSG00000141510.16", "17", 7661779, 7687550, "-")
    repo = FakeQtlRepository(genes=[gene])
    assert repo.resolve_gene("tp53") == gene  # case-insensitive symbol
    assert repo.resolve_gene("ENSG00000141510") == gene  # unversioned Ensembl id
    assert repo.resolve_gene("NOPE") is None


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


def test_fake_associations_in_region() -> None:
    repo = FakeQtlRepository(
        associations=[
            EqtlAssociation(8, 100, 1, 17, 7_670_000, 0.01, 0.2, 0.05),  # in window
            EqtlAssociation(8, 200, 2, 17, 7_680_000, 0.02, 0.1, 0.05),  # in window, other gene
            EqtlAssociation(8, 100, 3, 17, 9_000_000, 0.5, 0.1, 0.05),  # outside window
            EqtlAssociation(9, 100, 4, 17, 7_670_500, 0.5, 0.1, 0.05),  # other dataset
            EqtlAssociation(8, 100, 5, 18, 7_670_500, 0.5, 0.1, 0.05),  # other chrom
        ]
    )
    hits = repo.associations_in_region("17", 7_660_000, 7_690_000, 8)
    assert [a.rs_id for a in hits] == [1, 2]


def test_fake_phenotype_summaries_in_region_places_phenotypes_by_their_own_feature() -> None:
    """The exact bug seen live on chr17:6661179-8661779: a caQTL peak a megabyte to the LEFT of
    the window whose tested variants reach into it must not be listed, while a peak that really
    overlaps must be — see PostgresQtlRepository.phenotype_summaries_in_region."""
    repo = FakeQtlRepository(
        datasets=[Dataset(1, "cMono_CD14", "CIMA-caQTL-EAS")],
        associations=[
            # peak sits at 5.66 Mb; this tested variant reaches into the window
            EqtlAssociation(
                1, 0, None, 17, 6_665_497, 0.01, 0.1, 0.05, phenotype_id="chr17_5665386_5665629"
            ),
            # peak genuinely overlaps the window
            EqtlAssociation(
                1, 0, None, 17, 6_670_000, 0.02, 0.1, 0.05, phenotype_id="chr17_6665950_6666451"
            ),
        ],
    )
    summaries = repo.phenotype_summaries_in_region("17", 6_661_179, 8_661_779, 1)
    assert [s.phenotype_id for s in summaries] == ["chr17_6665950_6666451"]


def test_fake_phenotype_summaries_in_region_places_gene_phenotypes_by_gene_coords() -> None:
    """Gene-keyed phenotypes are placed by the gene's own span, not by variant positions."""
    repo = FakeQtlRepository(
        datasets=[Dataset(1, "Whole_Blood", "GTEx_v10-eQTL-ALL")],
        genes=[
            Gene(141510, "TP53", "ENSG00000141510.18", "17", 7_661_779, 7_687_550, "-"),
            Gene(999, "FARAWAY", "ENSG00000000999.1", "17", 1_000_000, 1_010_000, "+"),
        ],
        associations=[
            EqtlAssociation(
                1, 141510, None, 17, 7_670_000, 0.01, 0.1, 0.05, phenotype_id="ENSG00000141510.18"
            ),
            # variant lands inside the window, but its gene is a long way outside it
            EqtlAssociation(
                1, 999, None, 17, 7_670_500, 0.02, 0.1, 0.05, phenotype_id="ENSG00000000999.1"
            ),
        ],
    )
    summaries = repo.phenotype_summaries_in_region("17", 7_660_000, 7_690_000, 1)
    assert [s.phenotype_id for s in summaries] == ["ENSG00000141510.18"]


def test_fake_associations_for_rsid() -> None:
    repo = FakeQtlRepository(
        associations=[
            EqtlAssociation(1, 100, 111, 17, 7_670_000, 0.01, 0.2, 0.05),
            EqtlAssociation(2, 100, 111, 17, 7_670_000, 0.02, 0.1, 0.05),
            EqtlAssociation(3, 100, 111, 17, 7_670_000, 0.5, 0.1, 0.05),  # not in dataset_ids
            EqtlAssociation(1, 100, 222, 17, 7_680_000, 0.5, 0.1, 0.05),  # other rsid
        ]
    )
    hits = repo.associations_for_rsid(111, [1, 2])
    assert sorted(a.dataset_id for a in hits) == [1, 2]


def test_fake_resolve_variant() -> None:
    repo = FakeQtlRepository(
        associations=[EqtlAssociation(1, 100, 111, 17, 7_670_000, 0.01, 0.2, 0.05)]
    )
    assert repo.resolve_variant(111) == ("17", 7_670_000)
    assert repo.resolve_variant(999) is None


def test_fake_gwas_datasets() -> None:
    repo = FakeQtlRepository(
        gwas_datasets=[GwasDataset(1, "Basophil_count", "EUR", "GWAS Catalog", "GCST90002379")]
    )
    assert repo.gwas_datasets() == [
        GwasDataset(1, "Basophil_count", "EUR", "GWAS Catalog", "GCST90002379")
    ]


def test_fake_gwas_associations_in_region() -> None:
    repo = FakeQtlRepository(
        gwas_associations=[
            GwasAssociation(1, 17, 100, 0.01, 0.2, 0.05),  # in window
            GwasAssociation(1, 17, 999_000, 0.5, 0.1, 0.05),  # outside window
            GwasAssociation(2, 17, 100, 0.5, 0.1, 0.05),  # other dataset
        ]
    )
    hits = repo.gwas_associations_in_region("17", 0, 200, 1)
    assert hits == [GwasAssociation(1, 17, 100, 0.01, 0.2, 0.05)]


def test_fake_qtl_contexts() -> None:
    repo = FakeQtlRepository(
        qtl_contexts=[QtlContextEntry(1, "Whole_Blood", None, "GTEx_v10-eQTL-ALL")]
    )
    assert repo.qtl_contexts() == [QtlContextEntry(1, "Whole_Blood", None, "GTEx_v10-eQTL-ALL")]


# ── Legacy: LocuscompareRepository (old MySQL) tests ────────────────────────
#
# Commented out with requestinfo.py's LocuscompareRepository (superseded 2026-08 by
# PostgresQtlRepository — see test_connectpostgres.py). See docs/process/status.md.
#
# from collections.abc import Sequence
#
# from locusview.requestinfo import (
#     LocuscompareRepository,
#     _ld_table,
#     _row_to_eqtl,
#     _row_to_gene,
#     _shard_table,
#     pymysql_connection_factory,
# )
#
# Row = Sequence[Any]
#
#
# def test_shard_table_valid() -> None:
#     assert _shard_table(42) == "eqtl_snp_42"
#
#
# @pytest.mark.parametrize("bad", [-1, True, "3"])
# def test_shard_table_rejects_bad_input(bad: Any) -> None:
#     with pytest.raises(ValueError):
#         _shard_table(bad)
#
#
# def test_row_to_eqtl_maps_and_casts() -> None:
#     assoc = _row_to_eqtl(5, (177951, 867721319, 11, 128951, "0.83", "-0.03", "0.15"))
#     assert assoc == EqtlAssociation(
#         dataset_id=5,
#         gene_id=177951,
#         rs_id=867721319,
#         chrom=11,
#         position=128951,
#         pvalue=0.83,
#         beta=-0.03,
#         se=0.15,
#     )
#
#
# class _FakeCursor:
#     def __init__(self, rows: Sequence[Row], log: list[tuple[str, tuple[Any, ...]]]) -> None:
#         self._rows = rows
#         self._log = log
#
#     def execute(self, sql: str, params: Sequence[Any] = ()) -> None:
#         self._log.append((sql, tuple(params)))
#
#     def fetchall(self) -> Sequence[Row]:
#         return self._rows
#
#
# class _FakeConn:
#     def __init__(self, rows: Sequence[Row], log: list[tuple[str, tuple[Any, ...]]]) -> None:
#         self._rows = rows
#         self._log = log
#         self.closed = False
#
#     def cursor(self) -> _FakeCursor:
#         return _FakeCursor(self._rows, self._log)
#
#     def close(self) -> None:
#         self.closed = True
#
#
# def _factory(rows: Sequence[Row]) -> tuple[Any, list[tuple[str, tuple[Any, ...]]]]:
#     log: list[tuple[str, tuple[Any, ...]]] = []
#
#     def make() -> _FakeConn:
#         return _FakeConn(rows, log)
#
#     return make, log
#
#
# def test_locuscompare_datasets_maps_catalog_rows() -> None:
#     factory, _ = _factory([(1, "Whole_Blood", "gtex-v8"), (2, "Stomach", "gtex-v8")])
#     repo = LocuscompareRepository(factory)
#     assert repo.datasets() == [
#         Dataset(1, "Whole_Blood", "gtex-v8"),
#         Dataset(2, "Stomach", "gtex-v8"),
#     ]
#
#
# def test_locuscompare_eqtls_for_gene_targets_correct_shards() -> None:
#     factory, log = _factory([(177951, 867721319, 11, 128951, "0.83", "-0.03", "0.15")])
#     repo = LocuscompareRepository(factory)
#     hits = repo.eqtls_for_gene(177951, [1, 10], limit=50)
#
#     # One query per shard, each with the right table name and parameters.
#     tables = [sql for sql, _ in log]
#     assert any("eqtl_snp_1 " in sql for sql in tables)
#     assert any("eqtl_snp_10 " in sql for sql in tables)
#     assert all(params == (177951, 50) for _, params in log)
#     # Rows mapped for each shard queried.
#     assert [a.dataset_id for a in hits] == [1, 10]
#     assert hits[0].beta == -0.03
#
#
# def test_locuscompare_eqtls_for_gene_empty_datasets() -> None:
#     factory, log = _factory([])
#     assert LocuscompareRepository(factory).eqtls_for_gene(1, []) == []
#     assert log == []  # no query issued when there are no datasets
#
#
# def test_pymysql_connection_factory_returns_callable() -> None:
#     # Builds the factory (does not connect — that needs a live DB).
#     assert callable(pymysql_connection_factory())
#
#
# _GENCODE = ("TP53", "ENSG00000141510.16", "17", 7661779, 7687550, "-")
#
#
# def test_row_to_gene() -> None:
#     assert _row_to_gene(_GENCODE) == Gene(
#         141510, "TP53", "ENSG00000141510.16", "17", 7661779, 7687550, "-"
#     )
#
#
# def test_locuscompare_resolve_gene_by_symbol() -> None:
#     factory, log = _factory([_GENCODE])
#     gene = LocuscompareRepository(factory).resolve_gene("TP53")
#     assert gene == Gene(141510, "TP53", "ENSG00000141510.16", "17", 7661779, 7687550, "-")
#     assert "gene_name = %s" in log[0][0] and log[0][1] == ("TP53",)
#
#
# def test_locuscompare_resolve_gene_by_ensembl_uses_like() -> None:
#     factory, log = _factory([_GENCODE])
#     LocuscompareRepository(factory).resolve_gene("ENSG00000141510.16")
#     assert "gene_id LIKE %s" in log[0][0]
#     assert log[0][1] == ("ENSG00000141510%",)
#
#
# def test_locuscompare_resolve_gene_not_found() -> None:
#     factory, _ = _factory([])
#     assert LocuscompareRepository(factory).resolve_gene("NOPE") is None
#
#
# def _routing_factory(
#     responder: object,
# ) -> tuple[object, list[tuple[str, tuple[object, ...]]]]:
#     """A fake connection whose returned rows depend on the SQL (for multi-query methods)."""
#     log: list[tuple[str, tuple[object, ...]]] = []
#
#     class _Cur:
#         def execute(self, sql: str, params: Sequence[object] = ()) -> None:
#             log.append((sql, tuple(params)))
#             self._rows = responder(sql, tuple(params))  # type: ignore[operator]
#
#         def fetchall(self) -> object:
#             return self._rows
#
#     class _Conn:
#         def cursor(self) -> _Cur:
#             return _Cur()
#
#         def close(self) -> None:
#             pass
#
#     return (lambda: _Conn()), log
#
#
# def test_ld_table_valid() -> None:
#     assert _ld_table("1", "EUR") == "tkg_p3v5a_ld_chr1_EUR"
#     assert _ld_table("X", "AFR") == "tkg_p3v5a_ld_chrX_AFR"
#
#
# @pytest.mark.parametrize(("chrom", "pop"), [("23", "EUR"), ("1", "ALL"), ("Y", "EUR")])
# def test_ld_table_rejects_bad_input(chrom: str, pop: str) -> None:
#     with pytest.raises(ValueError):
#         _ld_table(chrom, pop)
#
#
# def test_locuscompare_cis_associations() -> None:
#     factory, log = _factory([(141510, 12345, 17, 7670000, "0.001", "0.2", "0.05")])
#     hits = LocuscompareRepository(factory).cis_associations(141510, 8)
#     assert "eqtl_snp_8 " in log[0][0] and log[0][1] == (141510,)
#     assert hits[0].rs_id == 12345 and hits[0].dataset_id == 8
#
#
# def test_locuscompare_ld_r2_parses_and_dedupes() -> None:
#     factory, log = _factory([("rs100", 0.8), ("rs200", 0.3), ("esv9", 0.9), ("rs111", 1.0)])
#     r2 = LocuscompareRepository(factory).ld_r2("1", 111, "EUR")
#     # 'esv9' skipped (non-rs); the lead rs111 removed so the caller sets it to 1.0.
#     assert r2 == {100: 0.8, 200: 0.3}
#     assert "tkg_p3v5a_ld_chr1_EUR" in log[0][0]
#     assert log[0][1] == ("rs111", "rs111")
#
#
# def test_locuscompare_tissues_with_signal() -> None:
#     def responder(sql: str, params: tuple[object, ...]) -> list[tuple[object, ...]]:
#         if "eqtl_raw" in sql:
#             return [(1, "Whole_Blood", "gtex-v8"), (2, "Liver", "gtex-v8")]
#         if "eqtl_snp_1 " in sql:
#             return [(1e-8,)]
#         return [(0.5,)]  # eqtl_snp_2: not significant
#
#     factory, _ = _routing_factory(responder)
#     assert LocuscompareRepository(factory).tissues_with_signal(7) == [(1, "Whole_Blood", 1e-8)]
#
#
# def test_locuscompare_associations_in_region() -> None:
#     factory, log = _factory([(141510, 12345, 17, 7_670_000, "0.001", "0.2", "0.05")])
#     hits = LocuscompareRepository(factory).associations_in_region("17", 7_660_000, 7_690_000, 8)
#     assert "eqtl_snp_8 " in log[0][0] and "BETWEEN" in log[0][0]
#     assert log[0][1] == ("17", 7_660_000, 7_690_000)
#     assert hits[0].rs_id == 12345
#
#
# def test_locuscompare_associations_for_rsid_targets_correct_shards() -> None:
#     factory, log = _factory([(141510, 12345, 17, 7_670_000, "0.001", "0.2", "0.05")])
#     hits = LocuscompareRepository(factory).associations_for_rsid(12345, [1, 10])
#     tables = [sql for sql, _ in log]
#     assert any("eqtl_snp_1 " in sql for sql in tables)
#     assert any("eqtl_snp_10 " in sql for sql in tables)
#     assert all(params == (12345,) for _, params in log)
#     assert [a.dataset_id for a in hits] == [1, 10]
#
#
# def test_locuscompare_associations_for_rsid_empty_datasets() -> None:
#     factory, log = _factory([])
#     assert LocuscompareRepository(factory).associations_for_rsid(1, []) == []
#     assert log == []  # no query issued when there are no datasets
#
#
# def test_locuscompare_associations_for_rsid_gene_id_fast_path() -> None:
#     """Passing gene_id scopes the query by gene_id too — the fast, indexed path."""
#     factory, log = _factory([(141510, 12345, 17, 7_670_000, "0.001", "0.2", "0.05")])
#     LocuscompareRepository(factory).associations_for_rsid(12345, [1], gene_id=141510)
#     assert "gene_id = %s AND rs_id = %s" in log[0][0]
#     assert log[0][1] == (141510, 12345)
