"""Genomic coordinate conventions and conversions.

Two coordinate systems dominate genomics, and mixing them is a classic
*silently wrong* bug — no crash, just the neighbouring base, and therefore the
wrong locus in your results:

* **0-based, half-open** — used by BED, UCSC, and Python slicing. The first
  base of a sequence is ``0``, and an interval ``[start, end)`` includes
  ``start`` but not ``end``. Length is ``end - start``.
* **1-based, fully-closed** — used by VCF, GFF/GTF, SAM, Ensembl, and tabix
  region queries. The first base is ``1``, and an interval ``[start, end]``
  includes both ends. Length is ``end - start + 1``.

locusview keeps all *internal* coordinates **1-based closed** (matching the
tabix/VCF formats we ingest). These helpers convert at the boundaries and
**validate their inputs**, so a malformed interval fails loudly here instead of
silently corrupting a query downstream.

This module is the first piece of real logic in the project and exists partly as
a teaching example: see ``tests/test_genomics.py`` for the test-driven
specification, including a property-based round-trip test.
"""

from __future__ import annotations


def one_based_closed_to_zero_based(start: int, end: int) -> tuple[int, int]:
    """Convert a 1-based, fully-closed interval to 0-based, half-open.

    A SNP at 1-based position ``p`` is the interval ``(p, p)`` and becomes
    ``(p - 1, p)`` in 0-based half-open coordinates.

    Args:
        start: 1-based start position (>= 1).
        end: 1-based end position (>= start).

    Returns:
        ``(start0, end0)`` in 0-based half-open coordinates.

    Raises:
        ValueError: if ``start < 1`` or ``end < start``.
    """
    if start < 1:
        raise ValueError(f"1-based start must be >= 1, got {start}")
    if end < start:
        raise ValueError(f"end ({end}) must be >= start ({start})")
    return start - 1, end


def zero_based_half_open_to_one_based(start: int, end: int) -> tuple[int, int]:
    """Convert a 0-based, half-open interval to 1-based, fully-closed.

    Args:
        start: 0-based start position (>= 0).
        end: 0-based end position (>= start; equal means an empty interval).

    Returns:
        ``(start1, end1)`` in 1-based fully-closed coordinates.

    Raises:
        ValueError: if ``start < 0`` or ``end < start``.
    """
    if start < 0:
        raise ValueError(f"0-based start must be >= 0, got {start}")
    if end < start:
        raise ValueError(f"end ({end}) must be >= start ({start})")
    return start + 1, end
