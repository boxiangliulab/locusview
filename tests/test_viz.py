"""Tests for the visualization helpers (LD color scheme + math)."""

from __future__ import annotations

from locusview.viz import LD_LEAD_COLOR, LD_NULL_COLOR, ld_legend, neg_log10_p, r2_color


def test_r2_color_bins() -> None:
    assert r2_color(0.1) == "#463699"
    assert r2_color(0.3) == "#26BCE1"
    assert r2_color(0.5) == "#6EFE68"
    assert r2_color(0.7) == "#F8C32A"
    assert r2_color(0.95) == "#DB3D11"
    assert r2_color(1.0) == "#DB3D11"
    assert r2_color(1.5) == "#DB3D11"  # defensive fall-through (r² should be clamped ≤ 1)


def test_r2_color_lead_and_null() -> None:
    assert r2_color(0.5, is_lead=True) == LD_LEAD_COLOR
    assert r2_color(None) == LD_NULL_COLOR


def test_neg_log10_p() -> None:
    assert neg_log10_p(0.01) == 2.0
    assert neg_log10_p(None) is None
    assert neg_log10_p(0.0) is None  # non-positive → dropped
    assert neg_log10_p(-1.0) is None


def test_ld_legend() -> None:
    legend = ld_legend()
    assert len(legend) == 7  # 5 bins + lead + no-data
    assert legend[-1]["label"] == "no LD data"
    assert legend[-2]["color"] == LD_LEAD_COLOR
