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
            "Liu, B. et al. Abundant associations with gene expression complicate GWAS "
            "follow-up. Nature Genetics 51, 768–769 (2019). LocusCompare."
        ),
        doi="10.1038/s41588-019-0404-0",
    ),
    Citation(
        text=(
            "Liu, F. et al. Mitigating inconsistencies in GWAS follow-up analyses with "
            "LocusCompare2. Nature Genetics 57, 2606–2613 (2025)."
        ),
        doi="10.1038/s41588-025-02331-x",
    ),
]
