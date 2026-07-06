"""Visualization helpers for the regional plot: the LocusZoom-style LD color scheme and a
little math. Pure functions, unit-tested — the frozen color contract lives here so the API and
any future front-end agree.
"""

from __future__ import annotations

import math

# LocusZoom.js default r² color scheme. Bins are broken at 0.2 / 0.4 / 0.6 / 0.8.
LD_LEAD_COLOR = "#9632B8"  # the reference/lead variant (drawn as a diamond)
LD_NULL_COLOR = "#AAAAAA"  # no LD data — distinct from low r²
LD_BINS: list[tuple[float, str]] = [
    (0.2, "#463699"),  # indigo   0.0–0.2
    (0.4, "#26BCE1"),  # cyan     0.2–0.4
    (0.6, "#6EFE68"),  # green    0.4–0.6
    (0.8, "#F8C32A"),  # yellow   0.6–0.8
    (1.01, "#DB3D11"),  # red      0.8–1.0
]


def r2_color(r2: float | None, *, is_lead: bool = False) -> str:
    """Map an r² value to its LocusZoom color. ``None`` → grey; the lead → purple."""
    if is_lead:
        return LD_LEAD_COLOR
    if r2 is None:
        return LD_NULL_COLOR
    for upper, color in LD_BINS:
        if r2 < upper:
            return color
    return LD_BINS[-1][1]


def ld_legend() -> list[dict[str, str]]:
    """A legend the front-end can render: label + color per r² bin (plus lead + no-data)."""
    labels = ["0.0–0.2", "0.2–0.4", "0.4–0.6", "0.6–0.8", "0.8–1.0"]
    legend = [{"label": lab, "color": col} for lab, (_, col) in zip(labels, LD_BINS, strict=True)]
    legend.append({"label": "lead", "color": LD_LEAD_COLOR})
    legend.append({"label": "no LD data", "color": LD_NULL_COLOR})
    return legend


def neg_log10_p(pvalue: float | None) -> float | None:
    """−log₁₀(p) for the y-axis. Returns ``None`` for non-positive or absent p (the caller
    drops those points)."""
    if pvalue is None or pvalue <= 0:
        return None
    return -math.log10(pvalue)
