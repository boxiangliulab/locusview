"""Release notes shown on the News page. Static — kept in sync with what's actually shipped
(see docs/process/status.md), not aspirational."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class NewsEntry:
    """One release-notes entry, newest first."""

    date: str  # "Month YYYY"
    title: str
    body: str
    tags: list[str] = field(default_factory=list)
    upcoming: bool = False


NEWS: list[NewsEntry] = [
    NewsEntry(
        date="August 2026",
        title="Data Browser: region & variant search, cross-tissue comparison",
        body=(
            "Search by genomic region or variant, not just gene symbol. A new Data Browser tab "
            "adds a query builder (dataset, tissue, gene/region/variant) and a Cross-Dataset mode "
            "that compares a variant's association strength across every integrated tissue."
        ),
        tags=["Data Browser", "Region search", "Variant search", "Cross-tissue comparison"],
    ),
    NewsEntry(
        date="July 2026",
        title="Regional plot with LD-based coloring",
        body=(
            "The gene page gained a LocusZoom-style regional association plot: variants by "
            "genomic position vs. -log10(p), colored by LD r-squared to a lead variant (click any "
            "point to re-color). LD reference: 1000 Genomes phase 3, selectable population."
        ),
        tags=["Regional plot", "LD coloring", "GTEx v8"],
    ),
    NewsEntry(
        date="July 2026",
        title="locusview v1.0 - initial release",
        body=(
            "Search a gene by symbol or Ensembl id and browse its eQTLs across GTEx v8 tissues, "
            "with CSV/TSV download."
        ),
        tags=["Gene search", "GTEx v8", "CSV/TSV download"],
    ),
    NewsEntry(
        date="Upcoming",
        title="Tissue body map",
        body=(
            "An anatomogram (EBI Expression Atlas, CC-BY) highlighting which tissues have a "
            "significant eQTL for the current gene, click-through to that tissue's regional plot."
        ),
        upcoming=True,
    ),
]
