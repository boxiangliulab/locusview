"""Tests for PostgresQtlRepository (src/backend/locusview/connectpostgres.py), the new
locuscompare2 DB.

Exercised through a fake DB-API connection, so the SQL shape and row-mapping are covered without
touching a live database or the network — same pattern the old (now-commented-out)
LocuscompareRepository tests used.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import pytest

from locusview.connectpostgres import (
    PostgresQtlRepository,
    _gwas_shard_table,
    _phenotype_table,
    _row_to_eqtl,
    _shard_table,
    postgres_connection_factory,
)
from locusview.requestinfo import (
    Dataset,
    EqtlAssociation,
    Gene,
    GwasAssociation,
    GwasDataset,
    QtlContextEntry,
    RepositoryTimeoutError,
)

Row = Sequence[Any]


def test_shard_table_valid() -> None:
    assert _shard_table(1) == "qtl_snp_1"


@pytest.mark.parametrize("bad", [-1, True, "3"])
def test_shard_table_rejects_bad_input(bad: Any) -> None:
    with pytest.raises(ValueError):
        _shard_table(bad)


def test_phenotype_table() -> None:
    assert _phenotype_table(1) == "qtl_snp_1_phenotype"


def test_row_to_eqtl_maps_and_casts_and_rs_id_is_none() -> None:
    # row = (chrom, position, pval, beta, se, gene_id)
    assoc = _row_to_eqtl(8, ("17", 7670000, "0.83", "-0.03", "0.15", "141510"))
    assert assoc == EqtlAssociation(
        dataset_id=8,
        gene_id=141510,
        rs_id=None,  # no per-row rsID lookup — see module docstring
        chrom=17,
        position=7670000,
        pvalue=0.83,
        beta=-0.03,
        se=0.15,
    )


def test_postgres_connection_factory_returns_callable() -> None:
    assert callable(postgres_connection_factory())


# ── fake connection plumbing (mirrors the old LocuscompareRepository test pattern) ─────────────


class _FakeCursor:
    def __init__(self, rows: Sequence[Row], log: list[tuple[str, tuple[Any, ...]]]) -> None:
        self._rows = rows
        self._log = log

    def execute(self, sql: str, params: Sequence[Any] = ()) -> None:
        self._log.append((sql, tuple(params)))

    def fetchall(self) -> Sequence[Row]:
        return self._rows


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


def _routing_factory(
    responder: Any,
) -> tuple[Any, list[tuple[str, tuple[Any, ...]]]]:
    """A fake connection whose returned rows depend on the SQL (for multi-query methods)."""
    log: list[tuple[str, tuple[Any, ...]]] = []

    class _Cur:
        def execute(self, sql: str, params: Sequence[Any] = ()) -> None:
            log.append((sql, tuple(params)))
            self._rows = responder(sql, tuple(params))

        def fetchall(self) -> Any:
            return self._rows

    class _Conn:
        def cursor(self) -> _Cur:
            return _Cur()

        def close(self) -> None:
            pass

    return (lambda: _Conn()), log


def test_socket_timeout_is_translated_and_connection_is_closed() -> None:
    class TimeoutCursor:
        def execute(self, sql: str, params: Sequence[Any] = ()) -> None:
            raise TimeoutError("socket read timed out")

    class TimeoutConnection:
        closed = False

        def cursor(self) -> TimeoutCursor:
            return TimeoutCursor()

        def close(self) -> None:
            self.closed = True

    connection = TimeoutConnection()
    with pytest.raises(RepositoryTimeoutError):
        PostgresQtlRepository(lambda: connection).datasets()
    assert connection.closed is True


# ── datasets() ───────────────────────────────────────────────────────────────


def test_datasets_labels_context_as_level_2_when_present_else_level_1() -> None:
    """The context label is level 2 when the row has one, else level 1 — never both joined
    (see datasets()'s comment)."""
    factory, log = _factory(
        [
            (1, "GTEx_v10", "eQTL", "ALL", "Whole_Blood", None, "GTEx_v10"),
            (3, "CIMA", "caQTL", "EAS", "Whole_Blood", "cMono_CD14", "CIMA"),
        ]
    )
    repo = PostgresQtlRepository(factory)
    assert repo.datasets() == [
        Dataset(1, "Whole_Blood", "GTEx_v10-eQTL-ALL", "GTEx_v10"),
        Dataset(3, "cMono_CD14", "CIMA-caQTL-EAS", "CIMA"),
    ]
    assert "to_regclass" in log[0][0]  # only lists datasets with a materialized shard
    assert "source_project_id" in log[0][0]


# ── gene resolution (via gencode_v39) ───────────────────────────────────────

_TP53_ROW: Row = ("141510", "TP53", "ENSG00000141510.18", "chr17", 7661779, 7677434, "-")


def test_resolve_gene_by_symbol() -> None:
    def responder(sql: str, params: tuple[Any, ...]) -> list[Row]:
        assert "gencode_v39" in sql
        assert params == ("TP53", "TP53", "TP53")
        return [_TP53_ROW]

    factory, _ = _routing_factory(responder)
    gene = PostgresQtlRepository(factory).resolve_gene("TP53")
    assert gene == Gene(
        gene_id=141510,
        symbol="TP53",
        ensembl_id="ENSG00000141510.18",
        chrom="17",  # "chr" prefix stripped to match the shards' bare chrom
        start=7661779,
        end=7677434,
        strand="-",  # real strand from gencode_v39, not "?"
    )


def test_resolve_gene_by_bare_or_versioned_ensembl_id() -> None:
    factory, _ = _routing_factory(lambda sql, params: [_TP53_ROW])
    repo = PostgresQtlRepository(factory)
    for key in ("ENSG00000141510", "ENSG00000141510.18"):
        gene = repo.resolve_gene(key)
        assert gene is not None and gene.gene_id == 141510


def test_resolve_gene_not_found() -> None:
    factory, log = _factory([])
    assert PostgresQtlRepository(factory).resolve_gene("NOPE") is None
    assert "gencode_v39" in log[0][0]


def test_resolve_gene_blank_input_returns_none_without_querying() -> None:
    factory, log = _factory([])
    assert PostgresQtlRepository(factory).resolve_gene("   ") is None
    assert log == []


# ── associations ─────────────────────────────────────────────────────────────


def test_eqtls_for_gene_targets_correct_shards() -> None:
    factory, log = _factory([("17", 7670000, "0.83", "-0.03", "0.15", "141510")])
    hits = PostgresQtlRepository(factory).eqtls_for_gene(141510, [1, 2], limit=50)
    tables = [sql for sql, _ in log]
    assert any("qtl_snp_1 " in sql for sql in tables)
    assert any("qtl_snp_2 " in sql for sql in tables)
    assert all(params == ("141510", 50) for _, params in log)
    assert [a.dataset_id for a in hits] == [1, 2]


def test_eqtls_for_gene_empty_datasets() -> None:
    factory, log = _factory([])
    assert PostgresQtlRepository(factory).eqtls_for_gene(1, []) == []
    assert log == []


def test_cis_associations_gene_id_branch() -> None:
    """eQTL/sQTL-style: phenotype table's gene_id is populated -> match on it directly, then
    enrich with rs_id/ref/alt via the two-step phenotype_key resolution (see docstring)."""

    def responder(sql: str, params: tuple[Any, ...]) -> list[Row]:
        if "d.qtl_type" in sql:
            return [("eQTL",)]  # gene-keyed dataset -> match on gene_id, not peaks
        if "WHERE gene_id = %s" in sql:
            assert params == ("141510",)  # text compare, no ::bigint cast (see docstring)
            return [(7791, "ENSG00000141510.18")]
        if "phenotype_key = ANY" in sql:
            assert params == ([7791],)
            return [("17", 7670000, "0.001", "0.2", "0.05", "C", "T", "rs123", 7791)]
        raise AssertionError(f"unexpected query: {sql}")

    factory, log = _routing_factory(responder)
    hits = PostgresQtlRepository(factory).cis_associations(141510, 1)
    assert hits == [
        EqtlAssociation(
            1, 141510, 123, 17, 7670000, 0.001, 0.2, 0.05, "C", "T", "ENSG00000141510.18"
        )
    ]
    assert any("qtl_snp_1 " in sql for sql, _ in log)


def test_cis_associations_caqtl_position_branch() -> None:
    """caQTL-style: phenotype table's gene_id is NULL everywhere -> resolve the gene's start via
    gencode_v39, then match the peak rows whose (chrom, start, end) contain that start."""

    def responder(sql: str, params: tuple[Any, ...]) -> list[Row]:
        if "d.qtl_type" in sql:
            return [("caQTL",)]  # peak-shaped dataset -> match chrom + peak range
        if "gencode_v39" in sql:
            return [("225972", "MTND1P23", "ENSG00000225972.1", "chr1", 629062, 629433, "+")]
        if "chrom = %s AND start" in sql:
            assert params == ("chr1", 629062, 629062)
            return [(8, "chr1_628997_629498", None)]
        if "phenotype_key = ANY" in sql:
            assert params == ([8],)
            return [("1", 629100, "0.05", "0.1", "0.06", "G", "T", None, 8)]
        raise AssertionError(f"unexpected query: {sql}")

    factory, log = _routing_factory(responder)
    hits = PostgresQtlRepository(factory).cis_associations(225972, 3)
    assert hits == [
        EqtlAssociation(3, 225972, None, 1, 629100, 0.05, 0.1, 0.06, "G", "T", "chr1_628997_629498")
    ]
    # Chromosome first, then the peak range — the rebuilt table's (chrom, start, "end") index.
    peak_sql = next(sql for sql, _ in log if "chrom = %s AND start" in sql)
    assert "split_part" not in peak_sql
    assert 'AND "end" >= %s' in peak_sql


def test_cis_associations_non_caqtl_never_takes_the_peak_branch() -> None:
    """Only caQTL companions have chrom/start/end. A pQTL (or any other type) whose gene_id
    column happens to be empty must still resolve through gencode_v39 -> gene_id, never query the
    peak columns its table doesn't have."""

    def responder(sql: str, params: tuple[Any, ...]) -> list[Row]:
        if "d.qtl_type" in sql:
            return [("pQTL",)]
        if "WHERE gene_id = %s" in sql:
            return []  # gene_id unpopulated for this dataset -> simply no phenotypes matched
        raise AssertionError(f"unexpected query: {sql}")

    factory, log = _routing_factory(responder)
    assert PostgresQtlRepository(factory).cis_associations(141510, 2) == []
    assert not any("chrom = %s AND start" in sql for sql, _ in log)  # no peak lookup
    assert not any("gencode_v39" in sql for sql, _ in log)  # no peak-only gene-coord lookup


def test_phenotypes_for_gene_non_caqtl_never_takes_the_peak_branch() -> None:
    def responder(sql: str, params: tuple[Any, ...]) -> list[Row]:
        if "d.qtl_type" in sql:
            return [("sQTL",)]
        if "SELECT phenotype_id, gene_id" in sql:
            assert params == ("141510",)
            return [("chr17:clu_1:ENSG00000141510.18", "141510")]
        raise AssertionError(f"unexpected query: {sql}")

    factory, log = _routing_factory(responder)
    gene = Gene(141510, "TP53", "ENSG00000141510.18", "17", 7_661_779, 7_677_434, "-")
    summaries = PostgresQtlRepository(factory).phenotypes_for_gene(gene, 2)
    assert [s.phenotype_id for s in summaries] == ["chr17:clu_1:ENSG00000141510.18"]
    assert not any("chrom = %s AND start" in sql for sql, _ in log)


def test_cis_associations_caqtl_unknown_gene_returns_empty_without_shard_query() -> None:
    def responder(sql: str, params: tuple[Any, ...]) -> list[Row]:
        if "d.qtl_type" in sql:
            return [("caQTL",)]
        return []  # gencode_v39 lookup empty -> gene not found at all

    factory, log = _routing_factory(responder)
    assert PostgresQtlRepository(factory).cis_associations(999999, 3) == []
    assert not any("phenotype_key = ANY" in sql for sql, _ in log)


def test_phenotypes_for_gene_eqtl_and_sqtl_match_gene_id_without_shard_query() -> None:
    def responder(sql: str, params: tuple[Any, ...]) -> list[Row]:
        if "d.qtl_type" in sql:
            return [("eQTL",)]
        if "SELECT phenotype_id, gene_id" in sql:
            assert params == ("141510",)
            return [
                ("ENSG00000141510.18", "141510"),
                ("chr17:clu_1:ENSG00000141510.18", "141510"),
            ]
        raise AssertionError(f"unexpected query: {sql}")

    factory, log = _routing_factory(responder)
    gene = Gene(141510, "TP53", "ENSG00000141510.18", "17", 7_661_779, 7_677_434, "-")
    summaries = PostgresQtlRepository(factory).phenotypes_for_gene(gene, 1)
    assert [s.phenotype_id for s in summaries] == [
        "ENSG00000141510.18",
        "chr17:clu_1:ENSG00000141510.18",
    ]
    assert not any("FROM qtl_snp_1 s" in sql for sql, _ in log)


def test_phenotypes_for_gene_caqtl_matches_gencode_start_inside_peak() -> None:
    def responder(sql: str, params: tuple[Any, ...]) -> list[Row]:
        if "d.qtl_type" in sql:
            return [("caQTL",)]
        if "chrom = %s AND start" in sql:
            assert params == ("chr17", 7_661_779, 7_661_779)
            return [(4, "chr17_7661000_7662000", None)]
        raise AssertionError(f"unexpected query: {sql}")

    factory, log = _routing_factory(responder)
    gene = Gene(141510, "TP53", "ENSG00000141510.18", "17", 7_661_779, 7_677_434, "-")
    summaries = PostgresQtlRepository(factory).phenotypes_for_gene(gene, 3)
    assert [s.phenotype_id for s in summaries] == ["chr17_7661000_7662000"]
    assert not any("FROM qtl_snp_3 s" in sql for sql, _ in log)


def test_cis_associations_no_matching_phenotype_returns_empty() -> None:
    def responder(sql: str, params: tuple[Any, ...]) -> list[Row]:
        if "d.qtl_type" in sql:
            return [("eQTL",)]
        if "WHERE gene_id = %s" in sql:
            return []  # gene not tested in this dataset
        raise AssertionError(f"unexpected query: {sql}")

    factory, log = _routing_factory(responder)
    assert PostgresQtlRepository(factory).cis_associations(1, 1) == []
    assert not any("phenotype_key = ANY" in sql for sql, _ in log)


def test_associations_for_phenotype_resolves_key_then_fetches_bounded_window() -> None:

    def responder(sql: str, params: tuple[Any, ...]) -> list[Row]:
        if "WHERE phenotype_id = %s" in sql:
            assert params == ("ENSG00000141510.18",)
            return [(7791, "141510")]
        if "phenotype_key = %s" in sql:
            assert params == (7791, "17", 7_660_000, 7_690_000)
            assert "s.chrom = %s" in sql and "s.position BETWEEN %s AND %s" in sql
            return [("17", 7670000, "0.001", "0.2", "0.05", "C", "T", "rs123")]
        raise AssertionError(f"unexpected query: {sql}")

    factory, log = _routing_factory(responder)
    hits = PostgresQtlRepository(factory).associations_for_phenotype(
        1, "ENSG00000141510.18", "17", 7_660_000, 7_690_000
    )
    assert hits == [
        EqtlAssociation(
            1, 141510, 123, 17, 7670000, 0.001, 0.2, 0.05, "C", "T", "ENSG00000141510.18"
        )
    ]
    assert any("qtl_snp_1 " in sql for sql, _ in log)


def test_associations_for_phenotype_unknown_id_returns_empty() -> None:
    def responder(sql: str, params: tuple[Any, ...]) -> list[Row]:
        if "WHERE phenotype_id = %s" in sql:
            return []
        raise AssertionError(f"unexpected query: {sql}")

    factory, log = _routing_factory(responder)
    assert (
        PostgresQtlRepository(factory).associations_for_phenotype(1, "nonexistent", "17", 1, 2)
        == []
    )
    assert not any("phenotype_key = %s" in sql for sql, _ in log)


def test_associations_for_phenotype_caqtl_null_gene_id_defaults_to_zero() -> None:
    """caQTL-style: phenotype table's gene_id is NULL — falls back to 0 (peaks aren't genes, no
    meaningful gene_id here — see EqtlAssociation's gene_id being non-optional)."""

    def responder(sql: str, params: tuple[Any, ...]) -> list[Row]:
        if "WHERE phenotype_id = %s" in sql:
            return [(8, None)]
        if "phenotype_key = %s" in sql:
            return [("1", 629100, "0.05", "0.1", "0.06", "G", "T", None)]
        raise AssertionError(f"unexpected query: {sql}")

    factory, _ = _routing_factory(responder)
    hits = PostgresQtlRepository(factory).associations_for_phenotype(
        3, "chr1_628997_629498", "1", 628_000, 630_000
    )
    assert hits == [
        EqtlAssociation(3, 0, None, 1, 629100, 0.05, 0.1, 0.06, "G", "T", "chr1_628997_629498")
    ]


def test_ld_r2_unions_both_pair_directions_and_dedupes_with_max() -> None:
    factory, log = _factory(
        [("rs222", 0.5), ("rs333", 0.9), ("rs333", 0.95)]  # rs333 appears both directions
    )
    r2map = PostgresQtlRepository(factory).ld_r2("17", 111, "EUR")
    assert r2map == {222: 0.5, 333: 0.95}
    sql, params = log[0]
    assert '"tkg_p3v5a_ld_chr17_EUR"' in sql
    assert params == ("rs111", "rs111")


def test_ld_r2_excludes_the_lead_itself() -> None:
    factory, _ = _factory([("rs111", 1.0), ("rs222", 0.5)])
    assert 111 not in PostgresQtlRepository(factory).ld_r2("17", 111, "EUR")


def test_ld_r2_skips_non_rs_partner_ids() -> None:
    """PLINK panels can include esv/ss ids alongside rsIDs — those can't map back to our
    integer-keyed rs_id space, so they're dropped rather than crashing."""
    factory, _ = _factory([("esv1234", 0.9), ("rs222", 0.5)])
    assert PostgresQtlRepository(factory).ld_r2("17", 111, "EUR") == {222: 0.5}


def test_ld_r2_unknown_chrom_or_population_returns_empty_without_querying() -> None:
    factory, log = _factory([])
    assert PostgresQtlRepository(factory).ld_r2("99", 111, "EUR") == {}
    assert PostgresQtlRepository(factory).ld_r2("17", 111, "NOPE") == {}
    assert log == []


def test_tissues_with_signal() -> None:
    def responder(sql: str, params: tuple[Any, ...]) -> list[Row]:
        if "qtl_lists" in sql:
            return [(1, "GTEx_v10", "eQTL", "ALL", "Whole_Blood", None, "GTEx_v10")]
        return [(1e-8,)]

    factory, _ = _routing_factory(responder)
    assert PostgresQtlRepository(factory).tissues_with_signal(141510) == [(1, "Whole_Blood", 1e-8)]


def test_associations_in_region() -> None:
    factory, log = _factory(
        [("17", 7670000, "0.001", "0.2", "0.05", "141510", "ENSG00000141510.18")]
    )
    hits = PostgresQtlRepository(factory).associations_in_region("17", 7_660_000, 7_690_000, 8)
    assert "qtl_snp_8 " in log[0][0] and "BETWEEN" in log[0][0]
    assert log[0][1] == ("17", 7_660_000, 7_690_000)
    assert hits[0].chrom == 17 and hits[0].position == 7670000
    assert hits[0].phenotype_id == "ENSG00000141510.18"


def test_associations_in_region_multiple_overlapping_phenotypes() -> None:
    """A region can legitimately span more than one gene's cis-window — see cis_associations'
    docstring and routers/locus.py's _group_by_phenotype, which groups these back apart."""
    factory, _ = _factory(
        [
            ("17", 7670000, "0.001", "0.2", "0.05", "141510", "ENSG00000141510.18"),
            ("17", 7671000, "0.02", "0.1", "0.05", "129195", "ENSG00000129195.16"),
        ]
    )
    hits = PostgresQtlRepository(factory).associations_in_region("17", 7_660_000, 7_690_000, 8)
    assert {a.phenotype_id for a in hits} == {"ENSG00000141510.18", "ENSG00000129195.16"}


def test_phenotype_summaries_in_region_caqtl_matches_peaks_overlapping_the_window() -> None:
    """Region mode must return the peaks whose OWN coordinates overlap the typed window — not the
    ones whose tested variants merely reach into it (those sit up to a cis window, ~1 Mb, away)."""

    def responder(sql: str, params: tuple[Any, ...]) -> list[Row]:
        if "d.qtl_type" in sql:
            return [("caQTL",)]
        if "chrom = %s AND start" in sql:
            # overlap test: peak.start <= window end AND peak.end >= window start
            assert params == ("chr17", 8_661_779, 6_661_179, 50)
            return [(11, "chr17_6665950_6666451", None)]
        raise AssertionError(f"unexpected query: {sql}")

    factory, log = _routing_factory(responder)
    summaries = PostgresQtlRepository(factory).phenotype_summaries_in_region(
        "17", 6_661_179, 8_661_779, 8, 50
    )
    assert [s.phenotype_id for s in summaries] == ["chr17_6665950_6666451"]
    assert summaries[0].lead_position is None and summaries[0].lead_pvalue is None
    peak_sql = next(sql for sql, _ in log if "chrom = %s AND start" in sql)
    # Ordered by position: ordering by the string phenotype_id makes LIMIT return an arbitrary
    # slice of the window instead of its left edge.
    assert "ORDER BY start" in peak_sql and "LIMIT %s" in peak_sql
    # The shard's variant positions are never consulted for this list.
    assert not any("DISTINCT s.phenotype_key" in sql for sql, _ in log)
    assert not any("FROM qtl_snp_8 s" in sql for sql, _ in log)


def test_phenotype_summaries_in_region_non_caqtl_goes_through_gencode() -> None:
    """Gene-keyed datasets have no coordinates in their phenotype table: place them with the
    window's overlapping gencode genes, then match those gene ids."""

    def responder(sql: str, params: tuple[Any, ...]) -> list[Row]:
        if "d.qtl_type" in sql:
            return [("eQTL",)]
        if "gencode_v39" in sql:
            assert params == ("chr17", 7_690_000, 7_660_000)
            return [("141510",), ("141511",)]
        if "gene_id = ANY" in sql:
            assert params == (["141510", "141511"], 50)
            return [("ENSG00000141510.18", "141510")]
        raise AssertionError(f"unexpected query: {sql}")

    factory, log = _routing_factory(responder)
    summaries = PostgresQtlRepository(factory).phenotype_summaries_in_region(
        "17", 7_660_000, 7_690_000, 1, 50
    )
    assert [s.phenotype_id for s in summaries] == ["ENSG00000141510.18"]
    assert not any("chrom = %s AND start" in sql for sql, _ in log)  # no peak columns
    assert not any("DISTINCT s.phenotype_key" in sql for sql, _ in log)


def test_phenotype_summaries_in_region_no_genes_in_window_skips_phenotype_query() -> None:
    def responder(sql: str, params: tuple[Any, ...]) -> list[Row]:
        if "d.qtl_type" in sql:
            return [("eQTL",)]
        if "gencode_v39" in sql:
            return []
        raise AssertionError(f"unexpected query: {sql}")

    factory, log = _routing_factory(responder)
    assert PostgresQtlRepository(factory).phenotype_summaries_in_region("17", 1, 2, 1, 50) == []
    assert not any("gene_id = ANY" in sql for sql, _ in log)


def test_associations_for_rsid_resolves_via_mapping_table() -> None:
    def responder(sql: str, params: tuple[Any, ...]) -> list[Row]:
        if "variant_rsid_mapping_raw" in sql:
            return [("17", 7670000, "T", "C")]
        return [("17", 7670000, "0.001", "0.2", "0.05", "141510")]

    factory, log = _routing_factory(responder)
    hits = PostgresQtlRepository(factory).associations_for_rsid(12345, [1, 2])
    assert [a.dataset_id for a in hits] == [1, 2]
    assert all(a.rs_id == 12345 for a in hits)
    # the mapping-table lookup used "rs12345", and the shard queries used the resolved variant
    assert log[0][1] == ("rs12345",)
    assert ("17", 7670000, "T", "C") in [p for _, p in log[1:]]


def test_associations_for_rsid_unknown_rsid_short_circuits() -> None:
    factory, log = _factory([])
    assert PostgresQtlRepository(factory).associations_for_rsid(999999, [1]) == []
    assert len(log) == 1  # only the mapping-table lookup, no per-shard queries


def test_associations_for_rsid_empty_datasets() -> None:
    factory, log = _factory([])
    assert PostgresQtlRepository(factory).associations_for_rsid(1, []) == []
    assert log == []  # short-circuits before even the mapping-table lookup


def test_resolve_variant_found() -> None:
    factory, log = _factory([("17", 7670000)])
    assert PostgresQtlRepository(factory).resolve_variant(650930) == ("17", 7670000)
    assert log[0][1] == ("rs650930",)


def test_resolve_variant_not_found() -> None:
    factory, log = _factory([])
    assert PostgresQtlRepository(factory).resolve_variant(999999999) is None
    assert len(log) == 1  # one lookup, no further queries


# ── GWAS ─────────────────────────────────────────────────────────────────────


def test_gwas_shard_table_valid() -> None:
    assert _gwas_shard_table(1) == "gwas_snp_1"


@pytest.mark.parametrize("bad", [-1, True, "3"])
def test_gwas_shard_table_rejects_bad_input(bad: Any) -> None:
    with pytest.raises(ValueError):
        _gwas_shard_table(bad)


def test_gwas_datasets_maps_and_filters_ready_shards() -> None:
    factory, log = _factory(
        [
            (1, "Basophil_count", "EUR", "GWAS Catalog", "GCST90002379"),
            (2, "Mean_corpuscular_hemoglobin", "EUR", "GWAS Catalog", "GCST90002390"),
        ]
    )
    repo = PostgresQtlRepository(factory)
    assert repo.gwas_datasets() == [
        GwasDataset(1, "Basophil_count", "EUR", "GWAS Catalog", "GCST90002379"),
        GwasDataset(2, "Mean_corpuscular_hemoglobin", "EUR", "GWAS Catalog", "GCST90002390"),
    ]
    assert "to_regclass" in log[0][0]  # only lists datasets with a materialized shard


def test_gwas_associations_in_region() -> None:
    factory, log = _factory(
        [("1", 10177, "0.39", "-0.00282646", "0.00329265", "A", "C", "rs12345")]
    )
    hits = PostgresQtlRepository(factory).gwas_associations_in_region("1", 10_000, 15_000, 1)
    assert "gwas_snp_1 " in log[0][0] and "BETWEEN" in log[0][0]
    assert "variant_rsid_mapping_raw" in log[0][0]
    assert log[0][1] == ("1", 10_000, 15_000)
    assert hits == [
        GwasAssociation(
            dataset_id=1,
            chrom=1,
            position=10177,
            pvalue=0.39,
            beta=-0.00282646,
            se=0.00329265,
            ref="A",
            alt="C",
            rs_id=12345,
        )
    ]


def test_gwas_associations_in_region_empty() -> None:
    factory, log = _factory([])
    assert PostgresQtlRepository(factory).gwas_associations_in_region("1", 1, 2, 1) == []
    assert "gwas_snp_1 " in log[0][0]


# ── qtl_contexts (body map) ──────────────────────────────────────────────────


def test_qtl_contexts_maps_and_labels() -> None:
    factory, log = _factory(
        [
            (1, "Whole_Blood", None, "GTEx_v10", "eQTL", "ALL"),
            (3, "Whole_Blood", "cMono_CD14", "CIMA", "caQTL", "EAS"),
        ]
    )
    repo = PostgresQtlRepository(factory)
    assert repo.qtl_contexts() == [
        QtlContextEntry(1, "Whole_Blood", None, "GTEx_v10-eQTL"),
        QtlContextEntry(3, "Whole_Blood", "cMono_CD14", "CIMA-caQTL"),
    ]
    assert "to_regclass" in log[0][0]  # only lists contexts with a materialized shard


def test_qtl_contexts_empty() -> None:
    factory, _ = _factory([])
    assert PostgresQtlRepository(factory).qtl_contexts() == []


def test_variant_hits_answers_every_shard_in_one_union_query() -> None:
    def responder(sql: str, params: tuple[Any, ...]) -> list[Row]:
        assert sql.count(" UNION ALL ") == 1
        assert "FROM qtl_snp_1 s JOIN qtl_snp_1_phenotype p" in sql
        assert "FROM qtl_snp_7 s JOIN qtl_snp_7_phenotype p" in sql
        assert params == ("17", 7_676_154, "17", 7_676_154)
        assert "s.se" not in sql  # Search data doesn't show standard errors
        return [
            (1, "17", 7_676_154, 1e-9, 0.5, "141510", "ENSG00000141510.18"),
            (7, "17", 7_676_154, 0.2, 0.1, None, "chr17_7670000_7680000"),
        ]

    factory, log = _routing_factory(responder)
    hits = PostgresQtlRepository(factory).variant_hits("17", 7_676_154, [1, 7])
    assert [(h.dataset_id, h.gene_id, h.pvalue, h.beta, h.se, h.phenotype_id) for h in hits] == [
        (1, 141510, 1e-9, 0.5, None, "ENSG00000141510.18"),
        (7, 0, 0.2, 0.1, None, "chr17_7670000_7680000"),
    ]
    assert len(log) == 1


def test_gwas_variant_hits_one_union_query_threshold_in_sql_no_se_or_rsid() -> None:
    def responder(sql: str, params: tuple[Any, ...]) -> list[Row]:
        assert sql.count(" UNION ALL ") == 1
        assert "FROM gwas_snp_1 s" in sql and "FROM gwas_snp_2 s" in sql
        assert sql.count("AND s.pval < %s") == 2
        assert "s.se" not in sql and "variant_rsid_mapping_raw" not in sql
        assert params == ("17", 7_676_154, 1e-4, "17", 7_676_154, 1e-4)
        return [(2, "17", 7_676_154, 5e-12, 0.2)]

    factory, log = _routing_factory(responder)
    hits = PostgresQtlRepository(factory).gwas_variant_hits("17", 7_676_154, [1, 2], 1e-4)
    assert [(h.dataset_id, h.position, h.pvalue, h.beta, h.se, h.rs_id) for h in hits] == [
        (2, 7_676_154, 5e-12, 0.2, None, None)
    ]
    assert len(log) == 1


def test_gene_phenotype_leads_matches_peaks_or_gene_id_per_shard_in_one_query() -> None:
    def responder(sql: str, params: tuple[Any, ...]) -> list[Row]:
        if "d.qtl_type" in sql:
            assert params == ([1, 3],)
            return [(1, "eQTL"), (3, "caQTL")]
        assert sql.count(" UNION ALL ") == 1 and sql.count("CROSS JOIN LATERAL") == 2
        assert "ORDER BY s.pval LIMIT 1" in sql and "variant_rsid_mapping_raw" in sql
        assert "s.se" not in sql  # the gene search doesn't show standard errors
        # eQTL shard 1 matches the zero-padded gene_id; caQTL shard 3 the peak containing the start.
        assert params == ("012048", "chr17", 43_044_295, 43_044_295)
        return [
            (
                1,
                "ENSG00000012048.23",
                "012048",
                "17",
                43_050_000,
                "C",
                "T",
                "rs8176318",
                1e-6,
                0.4,
            ),
            (
                3,
                "chr17_43040000_43046000",
                None,
                "17",
                "43044000",
                None,
                None,
                None,
                "0.01",
                None,
            ),
        ]

    factory, _log = _routing_factory(responder)
    gene = Gene(12048, "BRCA1", "ENSG00000012048.23", "17", 43_044_295, 43_125_483, "-")
    leads = PostgresQtlRepository(factory).gene_phenotype_leads(gene, [1, 3])
    assert [
        (d, s.phenotype_id, s.gene_id, s.position, s.ref, s.rs_id, s.pvalue, s.beta)
        for d, s in leads
    ] == [
        (1, "ENSG00000012048.23", 12048, 43_050_000, "C", 8176318, 1e-6, 0.4),
        (3, "chr17_43040000_43046000", None, 43_044_000, None, None, 0.01, None),
    ]


def test_batched_lookups_with_no_datasets_skip_the_query() -> None:
    def responder(sql: str, params: tuple[Any, ...]) -> list[Row]:
        raise AssertionError(f"unexpected query: {sql}")

    factory, log = _routing_factory(responder)
    repo = PostgresQtlRepository(factory)
    gene = Gene(141510, "TP53", "ENSG00000141510.18", "17", 7_661_779, 7_677_434, "-")
    assert repo.variant_hits("17", 1, []) == []
    assert repo.gwas_variant_hits("17", 1, []) == []
    assert repo.gene_phenotype_leads(gene, []) == []
    assert log == []


def test_phenotypes_for_gene_zero_pads_gene_ids_below_100000() -> None:
    """Phenotype tables store gene_id zero-padded to 6 digits (BRCA1 = "012048")."""

    def responder(sql: str, params: tuple[Any, ...]) -> list[Row]:
        if "d.qtl_type" in sql:
            return [("eQTL",)]
        if "SELECT phenotype_id, gene_id" in sql:
            assert params == ("012048",)
            return [("ENSG00000012048.23", "012048")]
        raise AssertionError(f"unexpected query: {sql}")

    factory, _log = _routing_factory(responder)
    gene = Gene(12048, "BRCA1", "ENSG00000012048.23", "17", 43_044_295, 43_125_483, "-")
    summaries = PostgresQtlRepository(factory).phenotypes_for_gene(gene, 1)
    assert [s.phenotype_id for s in summaries] == ["ENSG00000012048.23"]
    assert summaries[0].gene_id == 12048


def test_variant_hits_applies_the_pvalue_threshold_in_sql() -> None:
    def responder(sql: str, params: tuple[Any, ...]) -> list[Row]:
        assert sql.count("AND s.pval < %s") == 2
        assert params == ("17", 7_676_154, 1e-5, "17", 7_676_154, 1e-5)
        return []

    factory, _log = _routing_factory(responder)
    assert PostgresQtlRepository(factory).variant_hits("17", 7_676_154, [1, 7], 1e-5) == []


def test_gwas_variant_hits_without_threshold_has_no_pval_filter() -> None:
    def responder(sql: str, params: tuple[Any, ...]) -> list[Row]:
        assert "pval <" not in sql and params == ("17", 1)
        return []

    factory, _log = _routing_factory(responder)
    assert PostgresQtlRepository(factory).gwas_variant_hits("17", 1, [1]) == []
