# Canonical QTL association schema — principles (Phase 0)

> **Reference** (Diátaxis) — facts to look up. This page records the **load-bearing principles** of
> our internal schema. The **full field list** is deliberately deferred to Phase 1, to be validated
> against real GTEx rows rather than guessed in advance (a decision from the plan's adversarial
> review). The formal, complete schema becomes **ADR-0006** once Phase 1 ingest exists.
>
> ⚠ **Storage update ([ADR-0008](../adr/0008-store-qtl-in-locuscompare2-database.md)):** QTL data is
> stored in the **shared locuscompare2 database**, not a locusview-owned file store. The principles
> below still describe *how we think about a QTL record*, but the concrete schema will be
> **reconciled with the existing locuscompare2 schema** (its DBMS/tables are being documented by
> Junbin — backlog B1) rather than defined from scratch.

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

## Planned extensions for community contributions (Phase 5, forward-compatible)

These come from the Phase-5 [community-contribution design](../design/community-contributions.md).
They are **dataset-level** (they attach to provenance/context, never to the per-row variant/ENSG
key), so recording them as principles now keeps the schema forward-compatible without changing Phase-1
work. Decision recorded in [ADR-0007](../adr/0007-community-contribution-model.md).

6. **Ancestry is a first-class, filterable axis — and it is NOT tissue.** Tissue is the *anatomical
   source of the measurement*; ancestry is the *genetic background of the donors*. They are
   orthogonal. Model ancestry as a **repeatable per-cohort** field
   `ancestries[] = {ancestry_category, ancestry_detail?, hancestro_id?, component_n?}` using the
   GWAS-Catalog 17-category list as the primary facet and optional **HANCESTRO** CURIEs for detail;
   derive `is_multi_ancestry`.

7. **License is machine-readable.** Store an **SPDX** identifier (`license_spdx`, e.g. `CC-BY-4.0`,
   `CC-BY-NC-4.0`, `CC0-1.0`, or `NOASSERTION`) and *derive* the filter facet
   `commercial_use_allowed` (false whenever the ID contains `NC`; **`null` — "unclear" — for
   `NOASSERTION`/`Other`, never silently permissive**), plus `attribution_required` and `license_url`.

8. **The biological-context axis is structured, not free text.** `tissue_id`/`tissue_label`
   (UBERON/CL) and a repeatable `perturbations[]` (`perturbation_type`, `condition_label`, optional
   ontology id, dose, timepoint) — with derived `is_perturbed`. This refines (does not replace) the
   context axis reserved in principle 3.

9. **Provenance widens for contributed data.** Add `study_type`, sample-size fields
   (`n_total`/`n_cases`/`n_controls`/`n_effective`), `qtl_type`, `kind` (`curated` | `contributed`),
   `status`, `needs_curation`, `contributor_id`, `sha256`, `validator_version`, a citation string, and
   an internal accession (`LVxxxxxx`). Contributed and curated rows share one schema and one query
   path; `kind` keeps them distinguishable and independently filterable.

> These are **planned** extensions, not Phase-1 work. The full field types/requiredness are ratified
> when Phase 5 begins (see the design proposal). Recording them now simply prevents a painful schema
> fork later.
