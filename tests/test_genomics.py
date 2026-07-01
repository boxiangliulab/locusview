"""Tests for genomic coordinate conversions.

Written test-first: these tests *are* the specification for
``locusview.genomics``. They mix hand-picked examples (which document the
intended behaviour) with a property-based test (which checks an invariant across
thousands of generated inputs).
"""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from locusview.genomics import (
    one_based_closed_to_zero_based,
    zero_based_half_open_to_one_based,
)


def test_single_snp_conversion() -> None:
    # A SNP at 1-based position 100 spans [99, 100) in 0-based half-open.
    assert one_based_closed_to_zero_based(100, 100) == (99, 100)


def test_interval_conversion_both_directions() -> None:
    assert one_based_closed_to_zero_based(5, 10) == (4, 10)
    assert zero_based_half_open_to_one_based(4, 10) == (5, 10)


def test_length_is_preserved() -> None:
    start1, end1 = 5, 10
    start0, end0 = one_based_closed_to_zero_based(start1, end1)
    # 1-based closed length == 0-based half-open length == 6 bases.
    assert (end1 - start1 + 1) == (end0 - start0) == 6


@pytest.mark.parametrize(
    ("start", "end"),
    [(0, 5), (1, 0), (-3, 2)],  # start < 1, and end < start
)
def test_invalid_one_based_raises(start: int, end: int) -> None:
    with pytest.raises(ValueError):
        one_based_closed_to_zero_based(start, end)


@pytest.mark.parametrize(
    ("start", "end"),
    [(-1, 5), (5, 4)],  # start < 0, and end < start
)
def test_invalid_zero_based_raises(start: int, end: int) -> None:
    with pytest.raises(ValueError):
        zero_based_half_open_to_one_based(start, end)


@given(
    start=st.integers(min_value=1, max_value=10_000_000),
    length=st.integers(min_value=0, max_value=1000),
)
def test_round_trip_is_identity(start: int, length: int) -> None:
    """Converting 1-based → 0-based → 1-based must return the original interval."""
    end = start + length
    start0, end0 = one_based_closed_to_zero_based(start, end)
    assert zero_based_half_open_to_one_based(start0, end0) == (start, end)
