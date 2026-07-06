"""Parse a free-text search query into a structured, typed query.

The search box accepts several kinds of input; this module classifies a raw string into
exactly one :class:`QueryKind` and extracts its parts. It is pure logic (no database), so it
is fully unit-tested — see ``tests/test_search.py``.

Supported forms (checked in this order):
  - rsID:          ``rs867721319``
  - Ensembl gene:  ``ENSG00000141510`` (optional ``.N`` version suffix)
  - region:        ``1:1000-2000`` or ``chr1:1000-2000``
  - variant:       ``1:12345`` or ``1:12345:A:G`` (optional ref/alt)
  - gene symbol:   ``TP53`` (fallback)
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum


class QueryKind(StrEnum):
    """The kind of thing a search string refers to."""

    RSID = "rsid"
    ENSEMBL_GENE = "ensembl_gene"
    REGION = "region"
    VARIANT = "variant"
    GENE_SYMBOL = "gene_symbol"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ParsedQuery:
    """A search string classified into a kind, with the relevant parts extracted.

    Only the fields relevant to ``kind`` are populated; the rest stay ``None``.
    """

    kind: QueryKind
    raw: str
    gene_symbol: str | None = None
    ensembl_id: str | None = None  # unversioned, e.g. "ENSG00000141510"
    ensembl_version: str | None = None  # the ".N" suffix digits, if given
    rsid: str | None = None  # normalised, e.g. "rs12345"
    chrom: str | None = None  # normalised: no "chr" prefix; "MT" for mito
    position: int | None = None
    ref: str | None = None
    alt: str | None = None
    start: int | None = None
    end: int | None = None


_RSID = re.compile(r"^rs(\d+)$", re.IGNORECASE)
_ENSEMBL = re.compile(r"^(ENSG\d+)(?:\.(\d+))?$", re.IGNORECASE)
_REGION = re.compile(r"^(?:chr)?([0-9]{1,2}|MT|[XYM]):([0-9]+)-([0-9]+)$", re.IGNORECASE)
_VARIANT = re.compile(
    r"^(?:chr)?([0-9]{1,2}|MT|[XYM]):([0-9]+)(?::([ACGTN]+):([ACGTN]+))?$",
    re.IGNORECASE,
)
_GENE_SYMBOL = re.compile(r"^[A-Za-z][A-Za-z0-9._-]*$")


def _norm_chrom(c: str) -> str:
    c = c.upper()
    return "MT" if c == "M" else c


def parse_query(text: str) -> ParsedQuery:
    """Classify ``text`` into a :class:`ParsedQuery`. Never raises; unrecognised input
    (including start > end regions) returns ``QueryKind.UNKNOWN``."""
    raw = text.strip()
    if not raw:
        return ParsedQuery(QueryKind.UNKNOWN, text)

    if m := _RSID.match(raw):
        return ParsedQuery(QueryKind.RSID, raw, rsid=f"rs{m.group(1)}")

    if m := _ENSEMBL.match(raw):
        return ParsedQuery(
            QueryKind.ENSEMBL_GENE,
            raw,
            ensembl_id=m.group(1).upper(),
            ensembl_version=m.group(2),
        )

    if m := _REGION.match(raw):
        start, end = int(m.group(2)), int(m.group(3))
        if start > end:
            return ParsedQuery(QueryKind.UNKNOWN, raw)
        return ParsedQuery(
            QueryKind.REGION, raw, chrom=_norm_chrom(m.group(1)), start=start, end=end
        )

    if m := _VARIANT.match(raw):
        return ParsedQuery(
            QueryKind.VARIANT,
            raw,
            chrom=_norm_chrom(m.group(1)),
            position=int(m.group(2)),
            ref=m.group(3).upper() if m.group(3) else None,
            alt=m.group(4).upper() if m.group(4) else None,
        )

    if _GENE_SYMBOL.match(raw):
        # Preserve the original case — gene symbols can be mixed-case (e.g. C1orf112).
        return ParsedQuery(QueryKind.GENE_SYMBOL, raw, gene_symbol=raw)

    return ParsedQuery(QueryKind.UNKNOWN, raw)
