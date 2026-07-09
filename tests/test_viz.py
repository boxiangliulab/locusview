"""Tests for the visualization helpers (LD color scheme + math)."""

from __future__ import annotations

from locusview.viz import (
    LD_LEAD_COLOR,
    LD_NO_RSID_COLOR,
    LD_R2_FLOOR,
    ld_legend,
    neg_log10_p,
    r2_color,
)


def test_r2_color_bins() -> None:
    assert r2_color(0.1) == "#463699"
    assert r2_color(0.3) == "#26BCE1"
    assert r2_color(0.5) == "#6EFE68"
    assert r2_color(0.7) == "#F8C32A"
    assert r2_color(0.95) == "#DB3D11"
    assert r2_color(1.0) == "#DB3D11"
    assert r2_color(1.5) == "#DB3D11"  # defensive fall-through (r² should be clamped ≤ 1)


def test_r2_color_missing_means_below_the_panel_floor() -> None:
    """The 1000G tables store only r² >= 0.2, so a missing r² is *low LD*, not *no data*.

    Regression test for the bug where ~99.7% of a real locus rendered grey.
    """
    assert LD_R2_FLOOR == 0.2
    assert r2_color(None) == "#463699"  # lowest bin, NOT grey
    assert r2_color(None) != LD_NO_RSID_COLOR


def test_r2_color_lead_and_no_rsid() -> None:
    assert r2_color(0.5, is_lead=True) == LD_LEAD_COLOR
    assert r2_color(None, has_rsid=False) == LD_NO_RSID_COLOR  # cannot look LD up at all
    assert r2_color(0.9, has_rsid=False) == LD_NO_RSID_COLOR
    assert r2_color(0.5, is_lead=True, has_rsid=False) == LD_LEAD_COLOR  # lead wins


def test_neg_log10_p() -> None:
    assert neg_log10_p(0.01) == 2.0
    assert neg_log10_p(None) is None
    assert neg_log10_p(0.0) is None  # non-positive → dropped
    assert neg_log10_p(-1.0) is None


def test_ld_legend() -> None:
    legend = ld_legend()
    assert len(legend) == 7  # 5 bins + lead + no-rsID
    assert legend[0]["label"] == "< 0.2 / not in panel"  # names the panel floor honestly
    assert legend[-1]["label"] == "no rsID"
    assert legend[-2]["color"] == LD_LEAD_COLOR
