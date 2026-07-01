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
| Later | Integrations | GWAS colocalization, fine-mapping display, expanded API, accounts. | Backlog |

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
