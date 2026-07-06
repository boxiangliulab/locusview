"""Tests for the search-query parser — the front-door classifier."""

from __future__ import annotations

import pytest

from locusview.search import ParsedQuery, QueryKind, parse_query


def test_rsid() -> None:
    q = parse_query("rs867721319")
    assert q.kind is QueryKind.RSID
    assert q.rsid == "rs867721319"


def test_rsid_case_insensitive() -> None:
    assert parse_query("RS12345").rsid == "rs12345"


def test_ensembl_gene_with_version() -> None:
    q = parse_query("ENSG00000141510.17")
    assert q.kind is QueryKind.ENSEMBL_GENE
    assert q.ensembl_id == "ENSG00000141510"
    assert q.ensembl_version == "17"


def test_ensembl_gene_without_version() -> None:
    q = parse_query("ensg00000141510")
    assert q.kind is QueryKind.ENSEMBL_GENE
    assert q.ensembl_id == "ENSG00000141510"
    assert q.ensembl_version is None


def test_region() -> None:
    q = parse_query("chr1:1000-2000")
    assert q.kind is QueryKind.REGION
    assert (q.chrom, q.start, q.end) == ("1", 1000, 2000)


def test_region_normalises_mito() -> None:
    assert parse_query("chrM:1-100").chrom == "MT"


def test_region_with_start_after_end_is_unknown() -> None:
    assert parse_query("1:2000-1000").kind is QueryKind.UNKNOWN


def test_variant_position_only() -> None:
    q = parse_query("1:12345")
    assert q.kind is QueryKind.VARIANT
    assert (q.chrom, q.position, q.ref, q.alt) == ("1", 12345, None, None)


def test_variant_with_alleles() -> None:
    q = parse_query("chrX:12345:a:g")
    assert q.kind is QueryKind.VARIANT
    assert (q.chrom, q.position, q.ref, q.alt) == ("X", 12345, "A", "G")


def test_gene_symbol_preserves_case() -> None:
    q = parse_query("C1orf112")
    assert q.kind is QueryKind.GENE_SYMBOL
    assert q.gene_symbol == "C1orf112"


@pytest.mark.parametrize("text", ["", "   ", "12345", "!!!", "1:2:3:4:5"])
def test_unrecognised_is_unknown(text: str) -> None:
    assert parse_query(text).kind is QueryKind.UNKNOWN


def test_whitespace_is_trimmed() -> None:
    assert parse_query("  rs42  ") == ParsedQuery(QueryKind.RSID, "rs42", rsid="rs42")
