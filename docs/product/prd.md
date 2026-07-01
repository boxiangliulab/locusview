# PRD — locusview Phase 1 (Thin Vertical MVP)

> **What a PRD is (read this first).** A *Product Requirements Document* answers: **what** are we
> building next, **for whom**, and **how will we know it's done** — without prescribing **how** to
> build it (that's the technical design's job). Its most important function is to make disagreements
> visible and cheap *before* code makes them expensive. Each section below starts with a short
> *"why this section exists"* note (in quote blocks) so this doubles as a teaching template — when you
> write the next PRD, keep the notes and replace the content.
>
> **Scope:** this PRD covers **Phase 1 only** — the first working slice. Later phases get their own
> PRDs. Status: **DRAFT** for team review.

---

## 1. Problem
> *Why this section exists: to state the specific user pain we're solving now, so every requirement
> can be traced back to it. If a requirement doesn't serve the problem, cut it.*

Researchers cannot answer "what are the eQTLs for this gene, in which tissues?" from a single,
trustworthy, downloadable source. Even for the gold-standard dataset (GTEx), using the data means
navigating a portal built for many purposes, or downloading and parsing large files by hand.

## 2. Users & their jobs
> *Why: requirements make sense only against a real user trying to do a real job ("jobs to be done").*

- **Primary:** a computational biologist interpreting a locus. Job: *"Given a gene, show me its
  significant eQTLs across tissues, and let me download exactly what I'm looking at."*
- **Secondary:** a researcher starting from a variant. Job: *"Given an rsID/position, tell me which
  genes it's an eQTL for."*

## 3. Goals & non-goals
> *Why: naming non-goals is how you prevent scope creep. The non-goals list is the most valuable part
> of a PRD.*

**Goals**
- Ingest **one** bulk eQTL source (GTEx v8 cis-eQTL, gene-level, via the eQTL Catalogue distribution).
- Let a user **search** by gene, variant, or region and **browse** results on a gene page and a
  variant page.
- Let a user **download** exactly the result they're viewing, and link to the bulk files.
- Stamp **provenance** (source, version, build, license) on every page and file.

**Non-goals (Phase 1)**
- Multiple sources or modalities (sQTL/pQTL/single-cell) — Phase 2+.
- Colocalization with GWAS, fine-mapping/PIP visualization, L2G ranking.
- Regional (LocusZoom) plots — Phase 3.
- hg19/multi-build support, accounts, uploads, or locusview-run harmonization.

## 4. User stories
> *Why: stories keep us honest about who benefits. Format: "As a ⟨user⟩, I want ⟨capability⟩ so that
> ⟨outcome⟩."*

- As a biologist, I want to type a gene symbol and see its significant eQTLs across tissues, **so that**
  I can judge whether my variant of interest affects its expression.
- As a biologist, I want to type a variant and see which genes it's an eQTL for, **so that** I can go
  from a GWAS hit to candidate effector genes.
- As any user, I want to download the table I'm looking at as CSV/TSV, **so that** I can use it in my
  own analysis with correct attribution.

## 5. Functional requirements
> *Why: the concrete, checkable behaviours. Each should be testable. These become issues and tests.*

1. **Ingest**: load GTEx v8 cis-eQTL (gene-level, GRCh38) into partitioned Parquet + bgzip/tabix, plus
   a "significant hits" tier for fast browse. Ingest is a documented, re-runnable step.
2. **Search**: a single box resolves gene symbol, Ensembl ID, rsID, `chr:pos[:ref:alt]`, and region
   `chr:start-end`, with typeahead; ambiguous input yields a disambiguation list.
3. **Gene page**: a sortable table of significant eQTLs across tissues (variant, tissue, p-value,
   beta ± SE, MAF, TSS distance). Stable, shareable URL.
4. **Variant page**: reverse lookup listing genes/tissues for which the variant is an eQTL.
5. **Download**: (a) current-view CSV/TSV; (b) a documented REST/JSON endpoint returning the same
   rows; (c) links to per-tissue bulk tabix/Parquet files.
6. **Provenance**: every page and file shows dataset, source, pipeline, genome build, license, and
   access date.

## 6. Success metrics
> *Why: how we'll know Phase 1 worked, in observable terms. Ties to the vision.*

- A new user can go from gene symbol → downloaded eQTL table in **under a minute**, unaided.
- Every displayed number is reproducible from the cited source file (spot-checked against GTEx).
- The gene page for a busy gene loads in **under ~2 seconds**.
- All six functional requirements have passing automated tests, and CI is green.

## 7. Out of scope (explicit)
> *Why: repeating the boundary in its own section stops "just one more thing" from creeping in.*

Everything in Non-goals (§3), plus: performance tuning for billions of rows, production hosting at
scale, and any UI polish beyond a clear, usable results table.

## 8. Open questions (to resolve during design)
> *Why: naming unknowns now prevents them from silently becoming assumptions.*

- Exact "significant" threshold for the fast-browse tier (permutation `p_beta` vs a p-value cutoff)?
- Seed on GTEx v8 specifically, or a single eQTL-Catalogue-native tissue to sidestep the GTEx
  "keep current" clause? (See the licensing risk in the roadmap.)
- Minimum viable typeahead source for gene/variant name resolution.

---
*This PRD says WHAT and WHY. The HOW — storage layout, query strategy, API shape — lives in the Phase-1
design doc and the relevant ADRs.*
