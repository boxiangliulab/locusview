# Roadmap

> A shared sense of *order*, not a set of dated promises. Kept live — update it as reality changes.
> Each phase is a full **spec → plan → build → retrospective** loop that ships something real.

## Delivery phases

| Phase | Theme | Ships | Status |
|---|---|---|---|
| **0** | Foundation & Process | Repo, docs framework, Vision + PRD, ADRs, agent workflow, CI + guardrails, MVP scoping. *No product features.* | **In progress** |
| **1** | Thin Vertical MVP | One bulk eQTL source, searchable by gene/variant/region → gene & variant pages → download. Deployed. | Next |
| **2** | Breadth & Harmonization | Add the eQTL Catalogue compendium + a second modality (sQTL); harmonize builds/identifiers. | Planned |
| **3** | Richer Browse & Visualization | LocusZoom regional plots, filters, tissue browse. | Planned |
| **4** | Single-cell QTL | Activate the cell-type axis reserved in the schema (e.g., OneK1K). | Planned |
| **5** | Community Contributions | Let researchers **upload their own QTL datasets** with curated metadata, **reviewed before publishing**. | Planned |
| Later | Integrations | GWAS colocalization, fine-mapping display, expanded API. | Backlog |

> **Note on sequencing:** Phase 5 depends only on Phase 1's storage/index and the schema — not on
> Phases 2–4 — so it can be pulled earlier if community data becomes the priority. Its exact position
> is deliberately flexible.

## Community contributions (Phase 5) — confirmed requirements

A key long-term goal: locusview accepts **user-contributed QTL datasets**, not just curated ones.
Decisions locked with the team (2026-07):

- **Reviewed before public.** A submission is human-curated (metadata, license, sanity) before it
  becomes searchable/downloadable. Workflow shape: `submitted → validating → in_review →
  published / rejected`.
- **Mandated format + metadata form.** Contributors must provide a defined summary-stats format (the
  eQTL Catalogue tabix TSV schema) plus a web form; non-conforming files are rejected with clear errors.
- **Required metadata fields:** tissue type, **ancestry** *(new schema axis — needs the HANCESTRO
  ontology, distinct from tissue)*, sample size, perturbations (if any), and **license of use**
  (commercial-ok vs non-commercial-only — a machine-readable, filterable field).

*Full design (workflow states, exact field spec/vocabularies, upload security, contributor identity)
is being finalized from a research pass and will land as a contribution design doc + ADR, extending
the [schema principles](../reference/schema.md) with the ancestry and license fields.*

## Data-source roadmap

Which datasets we bring in, and in what order. ⚠ = a known gotcha to handle at ingest.

- **v1 (MVP):** GTEx v8 cis-eQTL (gene-level) via the eQTL Catalogue harmonized/tabix distribution.
- **v2:** eQTL Catalogue full compendium (~130 harmonized datasets — cheapest high-value breadth);
  then GTEx v10 + GTEx sQTL; then eQTLGen (⚠ hg19 → liftover; reports Z-scores, not betas); then
  UKB-PPP pQTL (⚠ confirm re-host terms).
- **v2.5+:** MetaBrain (⚠ redistribution), deCODE pQTL (⚠ non-commercial → likely link-out), GoDMC
  mQTL (⚠ hg19); first pseudobulk single-cell (OneK1K, Perez_2022).
- **Later:** context/dynamic single-cell eQTL (Oelen, Nathan), PsychENCODE, caQTL, more pQTL.
- **Reference/cross-check only — do not primary-ingest (overlap/dedup risk):** QTLbase2, Open Targets
  Platform, GWAS Catalog eQTL, scQTLbase.
- **Skip (legacy/superseded):** GRASP, seeQTL.

## Cross-cutting decisions to make along the way
- **Strategic differentiator:** compete on *breadth* (coverage) or *depth* (harmonization)? Revisit
  at Phase 2 — it reshapes the source roadmap. (Open question in the plan's risk register.)
- **Licensing:** audit each source's redistribution terms before re-hosting; default to **link-out**
  when unclear; keep a per-dataset license field.
- **Harmonization discipline (bake in early):** GRCh38 canonical; explicit effect allele; provenance
  and version pinning on every record.
