# Backlog (pre-GitHub)

> Until the GitHub repo + Project board are set up, we track open work here. Each item becomes a
> **GitHub Issue** when we migrate (see [ways-of-working](ways-of-working.md)). Keep items small and
> assign an owner. This is a lightweight stand-in, not a permanent home.

## Open

| ID | Item | Owner | Blocks / context |
|---|---|---|---|
| **B1** | **Document the locuscompare2 database for locusview reuse.** Identify the DBMS + version; dump and annotate the QTL schema into `docs/reference/` (tables, columns, keys, how datasets/associations/tissues/studies are modelled); provide locusview a scoped connection + access model (read-only for serving, a separate write path for Phase-5); and define schema-change coordination between the two apps. | **Junbin** | Blocks Phase-1 storage work. Decision: [ADR-0008](../adr/0008-store-qtl-in-locuscompare2-database.md). |

## Done
_(empty — move items here with the resolving PR/ADR when closed)_
