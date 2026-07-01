# Canonical QTL association schema — principles (Phase 0)

> **Reference** (Diátaxis) — facts to look up. This page records the **load-bearing principles** of
> our internal schema. The **full field list** is deliberately deferred to Phase 1, to be validated
> against real GTEx rows rather than guessed in advance (a decision from the plan's adversarial
> review). The formal, complete schema becomes **ADR-0006** once Phase 1 ingest exists.

## The shape
One row = one **(variant, molecular trait, biological context)** association. The internal format is
based on the **eQTL Catalogue** column schema, extended with structured context and provenance so
that bulk and single-cell QTL can live in one table without a schema fork.

## Load-bearing principles (decide now, honour forever)

1. **Keys are stable identifiers, not display names.**
   - Variant key: normalized `variant_id = chrom:pos:ref:alt`, biallelic, left-aligned & parsimonious
     (via `bcftools norm`). `rsid` is a *non-key attribute* (rsIDs merge and change).
   - Gene key: **unversioned Ensembl `ENSG`**. The `.NN` version suffix is kept for provenance but is
     not the join key; the gene *symbol* is display-only.

2. **Effect direction is explicit — this kills the #1 cross-dataset bug.**
   Always store `effect_allele` explicitly and express `beta` **relative to `alt`**. Different
   sources report different statistics (GTEx: NES; eQTLGen: Z-scores; others: beta/SE) against
   different alleles; without an explicit effect allele, merging silently produces wrong signs.

3. **Reserve a biological-context axis from day one** (`is_single_cell`, tissue ontology
   `tissue_uberon`, cell-type ontology `cell_type_cl`, condition `condition_efo`). Bulk fills only
   `tissue_uberon`; single-cell later fills the rest — **no schema migration required.** Do *not*
   over-build these fields against bulk-only data now.

4. **Provenance travels with every record.** Pin `genome_build` (always `GRCh38` internally),
   keep original coordinates + a `harmonization_code`, and record `pipeline_version`, source dataset,
   version, and access date. Results change materially between source versions.

5. **Genome build is canonical GRCh38.** Any hg19 source is lifted with `bcftools +liftover` (never
   naive coordinate liftover on summary statistics), with the original build retained. *(Liftover is
   a Phase-2 concern; the MVP source is already GRCh38.)*

## Why record principles but not the full field list yet
The MVP seed (GTEx v8 gene-level) lacks most single-cell / fine-mapping / SPDI fields, so a full
~50-field schema would be untestable speculation. Principles above are *testable now*; the exhaustive
field list, types, and required/optional flags will be pinned in Phase 1 against real rows and frozen
in ADR-0006.
