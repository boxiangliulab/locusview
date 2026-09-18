"""Citations shown on the Home page. Static — not sourced from the database."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Citation:
    """One reference to display, in citation-list order."""

    text: str
    doi: str


CITATIONS: list[Citation] = [
    Citation(
        text=(
            "The GTEx Consortium. The GTEx Consortium atlas of genetic regulatory effects "
            "across human tissues. Science 369, 1318–1330 (2020)."
        ),
        doi="10.1126/science.aaz1776",
    ),
]
