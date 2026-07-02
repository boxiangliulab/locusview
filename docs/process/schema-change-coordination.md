# Schema-change coordination: locusview ↔ locuscompare2

> **Process** doc — how we operate. locusview and locuscompare2 **share one MySQL database**
> (`colotool`), per [ADR-0008](../adr/0008-store-qtl-in-locuscompare2-database.md). One database, two
> applications = **coupling**: a schema change by either side can break the other. This page defines who
> owns what and how changes are coordinated so that doesn't happen.
>
> Facts about the schema: [locuscompare2 database reference](../reference/locuscompare2-database.md).
> Getting a connection: [connection how-to](../how-to/connect-to-locuscompare2-database.md).

---

## 1. Ownership boundary

**locuscompare2 owns the database.** It is the writer and the DDL authority: it created the schema,
runs the ingestion, and its Flask/SQLAlchemy models are the source of truth for table structure.
locusview is, in Phase 1, a **read-only guest**.

| Concern | locuscompare2 (owner) | locusview (guest) |
|---|---|---|
| Table/column DDL (`CREATE`/`ALTER`/`DROP`) | ✅ owns | ❌ never (no DDL grant) |
| Writing QTL/GWAS/coloc rows | ✅ | ❌ Phase 1 · scoped writer only in Phase 5 |
| Reading QTL/expression/annotation | ✅ | ✅ via `locusview_ro` |
| The `user`/PII and app tables | ✅ | ❌ out of reader scope |
| Phase-5 **contribution** tables (`lv_*`) | co-owned; DDL still by owner | ✅ writes via `locusview_rw` |
| locusview read **views** (if adopted) | hosts them | ✅ defines/requests them |

**Rule:** locusview treats the shared schema as an **external contract**, not its own migration
target. locusview never issues DDL against `colotool`. Any structural need locusview has is a
**request to the owner**, tracked as below.

## 2. The coupling risks we are guarding against

- A **rename/drop/retype** of a column locusview reads (e.g. dropping `eqtl_snp_*.beta`, or the
  known `effect_allele_frequency"` typo getting "fixed" without notice) silently breaks serving.
- A change to the **integer-encoding** convention or the **shard-naming** pattern
  (`eqtl_snp_{eqtl_raw_id}`) breaks every query.
- **Capacity/uptime/backup** are now shared concerns — a heavy locuscompare2 job can degrade
  locusview serving (mitigation: read replica; see the how-to).
- **Version drift** from the unpinned `mysql:latest` tag can change behaviour under both apps.

## 3. Change process

### 3a. When locuscompare2 changes the schema (the common case)

1. **Announce before merge.** Any change to a table/column in the [reader's surface](#4-the-read-contract)
   is announced to locusview owners (issue/PR cross-link) **before** it ships — not after.
2. **Classify the change:**
   - *Additive / backward-compatible* (new table, new nullable column, new dataset shard): safe; notify
     so the reference can be updated. No locusview code change required.
   - *Breaking* (rename, drop, type change, encoding/shard-naming change, PII relocation affecting
     grants): requires a coordinated window (§3c).
3. **Update the reference.** The owner (or locusview) updates
   [locuscompare2-database.md](../reference/locuscompare2-database.md) in the same change so docs never
   lag the DB.
4. **Re-grant if needed.** New served shard → the read grant must cover it (how-to §2, Option B), or it
   is invisible to locusview.

### 3b. When locusview needs a schema change

locusview cannot self-serve. File a **schema-change request** to the locuscompare2 owners containing:
the need, the exact columns/tables, backward-compatibility impact, and whether a **view** would satisfy
it without touching base tables (preferred — see §5). The reconciliation gaps in reference §8
(alleles/MAF, ontology context, explicit provenance) are the expected first batch of such requests and
feed **ADR-0006**.

### 3c. Breaking changes — expand/contract, never break-in-place

Use the standard expand/contract (parallel-change) migration so there is always a version both apps can
read:

1. **Expand** — owner adds the new column/table/view **alongside** the old; backfills.
2. **Migrate readers** — locusview switches to the new shape and deploys.
3. **Confirm** — contract tests (§6) green on both sides; verify locusview no longer reads the old shape.
4. **Contract** — owner removes the old column/table.

Never rename/drop in a single step while locusview reads the old name.

## 4. The read contract

The **frozen surface** locusview depends on (breaking changes here trigger §3c):

- Catalog: `eqtl_raw` (`id`, `tissue`, `type`, `url`, `info`) and the source-column-name columns.
- Associations: `eqtl_snp_{eqtl_raw_id}` (`rs_id`, `chrom`, `position`, `gene_id`, `pvalue`, `beta`,
  `se`, `trait_id`) and the `eqtl_snp_{id}` **naming pattern** itself.
- Expression: `gene_median_tpm`, `gene_median_tpm_tissue_relation` (incl. `tissue_id → eqtl_raw.id`).
- Mapping/annotation: `trait_item`, `gencode_v26_hg38`.
- Conventions: the **integer encoding** of gene/rsID/chrom, **GRCh38** build, **autosomes-only**
  coverage, and text-typed `pvalue`/`beta`/`se`.

Anything outside this surface (GWAS/coloc/app tables) is not part of locusview's contract; locusview
must not build read dependencies on it.

## 5. Preferred decoupling: a versioned read view

The lowest-coordination future is for locuscompare2 to expose locusview's read surface as **SQL views**
in a dedicated schema (e.g. `locusview_read`) that hide PII, abstract the shards, and normalize types
(how-to §2). Then:

- locusview depends on the **view contract**, not physical tables — the owner can refactor base tables
  freely as long as the views hold.
- The view schema is **versioned** (`eqtl_association_v1`); a breaking view change ships as `_v2`
  alongside `_v1` (expand/contract at the view layer).

Adopting this is a recommendation to the owners, not a Phase-1 blocker.

## 6. Guardrails (make breakage loud, not silent)

- **Contract tests in locusview CI.** A small suite asserts the read contract (§4): expected tables
  exist, key columns are present and named exactly (including the `effect_allele_frequency"` quirk if
  ever read), a sample gene round-trips through encode→query→decode, and a shard resolves. Run against a
  seeded fixture in CI and, ideally, a nightly job against a real replica. A red contract test is the
  early warning that the owner changed something.
- **Pin the server version.** The live server is **MySQL 8.3.0**, but the backend's compose file uses
  the floating `mysql:latest` tag — replace it with an explicit tag (e.g. `mysql:8.3`) and treat a
  MySQL version bump as a coordinated change.
- **Shared backup/restore ownership.** The owner runs backups; locusview confirms its read surface is
  covered and documents its RPO/RTO expectation.

## 7. Communication

- **Channel:** GitHub issues cross-linked between the two repos, tagged `schema-coordination`; ADRs for
  anything that changes the contract or an invariant.
- **Contacts:** locuscompare2 DB owner (Junbin) ↔ locusview maintainers. Keep the current owner mapping
  in [CODEOWNERS](../../CODEOWNERS)/backlog.
- **Cadence:** announce-before-merge for contract-surface changes; a periodic reconciliation check as
  Phase-1 ingestion and Phase-5 contributions evolve the schema.
