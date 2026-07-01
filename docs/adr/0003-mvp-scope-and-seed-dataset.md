# ADR-0003: MVP scope and seed dataset

- **Status:** Accepted
- **Date:** 2026-07-01

## Context
The full vision (all public QTL, bulk + single-cell, search/browse/download) is a multi-year
platform. New teams that try to build everything at once fail. We need a **thin vertical slice**:
one narrow path through every layer, end-to-end, to surface integration risk early and deliver a real
win. We also need a *seed dataset* that is trustworthy, cleanly licensed, and low-friction to ingest.

## Decision
Phase 1 delivers a thin vertical slice over **one** bulk source: **GTEx v8 cis-eQTL, gene-level (`ge`),
taken from the eQTL Catalogue harmonized/tabix distribution.** The slice is: ingest → store/index →
search (gene/variant/region) → gene page + variant page → download, with provenance on everything.
(See the [PRD](../product/prd.md) for the full requirement list and non-goals.)

Rationale: GTEx is the recognized gold standard (community trust); taking it *via* eQTL Catalogue
gives a clean, community-standard schema, GRCh38 coordinates, tabix indexing, and pre-computed
credible sets, so ingest is a thin *adapter* rather than a reprocessing pipeline. v8 (not v10) is
stable, universally pinned, and fully harmonized.

## Consequences
- **+** Fast, credible first release; the pipeline is proven on clean data before messy sources arrive.
- **+** Adopting the eQTL Catalogue schema now makes the v2 compendium nearly free to add later.
- **−** GTEx has a "keep current" clause; if that creates friction, a single eQTL-Catalogue-native
  tissue is a technically identical fallback (tracked as a PRD open question).
- **Deferred:** all other sources/modalities, colocalization, fine-mapping viz, single-cell — by design.
