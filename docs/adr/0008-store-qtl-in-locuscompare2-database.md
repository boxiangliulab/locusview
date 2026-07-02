# ADR-0008: Store QTL data in the shared locuscompare2 database

- **Status:** Accepted (reuse model). **Supersedes the storage decision in
  [ADR-0002](0002-python-first-web-stack-and-storage.md)**; open implementation items delegated (below).
- **Date:** 2026-07-02

## Context
The lab already operates a database behind **www.locuscompare2.com** (the locus-comparison /
colocalization tool; Liu et al., *Nature Genetics*, 2024) that already holds QTL data. Rather than
build a separate file-based analytical store for locusview (as proposed in ADR-0002: partitioned
Parquet + DuckDB + tabix), we can reuse that existing, populated database — inheriting its data,
schema, and operational footing.

The team confirmed the **reuse model: share the same database instance** (not merely copy the schema
or use it as a design reference). locusview will read from — and, for later write paths, write to —
the same database that powers locuscompare2.

## Decision
1. **locusview uses the same database instance as locuscompare2 as its QTL datastore.** It is the
   single source of truth for QTL datasets shared across the lab's tools.
2. This **supersedes the storage/query decision in ADR-0002** (Parquet + DuckDB + tabix + Cloudflare
   R2 for the analytical layer). The **application stack from ADR-0002 is unchanged** — FastAPI +
   Jinja2/HTMX remain; only where/how QTL data is stored and queried changes.
3. The canonical-schema work ([docs/reference/schema.md](../reference/schema.md), earmarked ADR-0006)
   and the Phase-5 contribution model ([ADR-0007](0007-community-contribution-model.md)) will be
   **reconciled against the locuscompare2 schema** rather than defined independently.

## Open items — owner: **Junbin** (tracked in [backlog](../process/backlog.md), item B1)
These were required before Phase-1 storage work could start; the decision above stands regardless.
**Documented via issue #1** (the code-level facts are now reverse-engineered from `locuscompare2_backend`):
- ✅ Identify the **DBMS** and version → **MySQL 8.0.x / InnoDB**, schema `colotool`
  ([reference §1](../reference/locuscompare2-database.md#1-dbms-and-version)).
- ✅ **Document the schema** for locuscompare2's QTL data into `docs/reference/` →
  [locuscompare2 database reference](../reference/locuscompare2-database.md) (catalog+shard model,
  integer-encoded keys, tables, keys, read recipe, and a reconciliation table vs our
  [schema principles](../reference/schema.md)).
- ✅ Provide locusview a **connection and access model** (least-privilege read-only serving role; a
  separate scoped Phase-5 writer) →
  [connection how-to](../how-to/connect-to-locuscompare2-database.md).
- ✅ Define **schema-change coordination** (migrations, ownership) →
  [schema-change coordination](../process/schema-change-coordination.md).

**Still needs a human decision** (data owners) before code depends on it: the authoritative host +
issued credentials, pinning the MySQL version, and the allele/MAF + PII-isolation questions — see
[reference §9](../reference/locuscompare2-database.md#9-open-questions-for-the-data-owners-needs-human).

## Consequences
- **+** Reuse an existing, populated QTL database — potentially skipping much of the Phase-1 ingestion
  effort and giving locusview real data immediately.
- **+** One source of truth shared with locuscompare2; consistency across the lab's tools; less new
  infrastructure to build and operate.
- **−** **Coupling:** two applications now depend on one database. Schema changes must be coordinated
  or one app can break the other; capacity, uptime, and backups become shared concerns. This is the
  main risk and the reason least-privilege access + change-coordination (the open items) matter.
- **−** **Supersedes the file-based analytical design.** Earlier specifics tied to Parquet/DuckDB/tabix
  (embedded in-process queries, tabix region slices, the ClickHouse scale-up path, R2 downloads) no
  longer apply as written and will be re-derived once the locuscompare2 schema and DBMS are known.
- **−** Phase-1 storage work is **blocked on the open items** above (owner: Junbin).
- **Teaching note:** this is the ADR lifecycle in action — ADR-0002 is not deleted or rewritten; it is
  marked *superseded in part*, preserving the original reasoning and showing how the decision evolved.
