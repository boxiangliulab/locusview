"""Visualization helpers for the regional plot: the LocusZoom-style LD color scheme and a
little math. Pure functions, unit-tested — the frozen color contract lives here so the API and
any future front-end agree.
"""

from __future__ import annotations

import math

# LocusZoom.js default r² color scheme. Bins are broken at 0.2 / 0.4 / 0.6 / 0.8.
#
# THE 0.2 FLOOR. The 1000G LD tables (`tkg_p3v5a_ld_*`) store only pairs with r² >= 0.2 — PLINK's
# `--ld-window-r2` default. Verified live: MIN(R2) = 0.2 on chr17/chr22 EUR, chr22 AFR, chr21 EAS.
# So a variant *missing* from an LD lookup is not "no data": its r² is simply **below the floor**.
# Colouring those grey painted ~99.7% of a real locus grey and made the lowest bin unreachable.
# We therefore give missing-but-identifiable variants the lowest bin, and reserve grey for variants
# we genuinely cannot look up (no rsID). Caveat: "< 0.2" also absorbs variants absent from the
# panel — the two are indistinguishable from a floored table.
LD_R2_FLOOR = 0.2

LD_LEAD_COLOR = "#f97316"  # the reference/lead variant (orange diamond, per Liu Fei's design)
LD_NO_RSID_COLOR = "#AAAAAA"  # no rsID -> LD cannot be looked up at all
LD_BINS: list[tuple[float, str]] = [
    (0.2, "#463699"),  # indigo   < 0.2 (below the panel floor) / not in panel
    (0.4, "#26BCE1"),  # cyan     0.2–0.4
    (0.6, "#6EFE68"),  # green    0.4–0.6
    (0.8, "#F8C32A"),  # yellow   0.6–0.8
    (1.01, "#DB3D11"),  # red      0.8–1.0
]


def r2_color(r2: float | None, *, is_lead: bool = False, has_rsid: bool = True) -> str:
    """Map an r² value to its LocusZoom color.

    ``r2 is None`` means the LD panel returned no pair for this variant, i.e. its r² is below the
    :data:`LD_R2_FLOOR` — so it takes the lowest bin, not grey. Grey is only for ``has_rsid=False``.
    """
    if is_lead:
        return LD_LEAD_COLOR
    if not has_rsid:
        return LD_NO_RSID_COLOR
    if r2 is None:  # below the panel's 0.2 floor (or absent from the panel)
        return LD_BINS[0][1]
    for upper, color in LD_BINS:
        if r2 < upper:
            return color
    return LD_BINS[-1][1]


def ld_legend() -> list[dict[str, str]]:
    """A legend the front-end can render: label + color per r² bin (plus lead + no-rsID)."""
    labels = [f"< {LD_R2_FLOOR} / not in panel", "0.2–0.4", "0.4–0.6", "0.6–0.8", "0.8–1.0"]
    legend = [{"label": lab, "color": col} for lab, (_, col) in zip(labels, LD_BINS, strict=True)]
    legend.append({"label": "lead", "color": LD_LEAD_COLOR})
    legend.append({"label": "no rsID", "color": LD_NO_RSID_COLOR})
    return legend


def neg_log10_p(pvalue: float | None) -> float | None:
    """−log₁₀(p) for the y-axis. Returns ``None`` for non-positive or absent p (the caller
    drops those points)."""
    if pvalue is None or pvalue <= 0:
        return None
    return -math.log10(pvalue)
