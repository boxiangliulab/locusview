# Project status — locusview

> A **living** "where we are right now" doc — update it whenever phase / PRs / blockers change.
> For durable *decisions* see [`../adr/`](../adr/); for *how we work* see the other
> [`process/`](.) docs; for the roadmap see [`../product/roadmap.md`](../product/roadmap.md).
>
> _Last updated: 2026-07 (see `git log` for precise dates)._

## Phase
**Phase 1 — thin vertical MVP** (search → gene page → browse/download to come). Phase 0 (foundation,
process, docs, CI, guardrails) is complete.

## Shipped (on `main`)
- **Foundation:** repo, Diátaxis docs, ADRs 0001–0008, CI (lint / types / tests + genomics smoke +
  docker build), branch protection, `CODEOWNERS`, the teaching layer (`docs/course/`, explainers).
- **App skeleton:** FastAPI + Jinja2/HTMX, `/health`, config-in-env, `locusview serve`.
- **Data layer:** the `QtlRepository` interface (`FakeQtlRepository` + real `LocuscompareRepository`
  over the shared locuscompare2 DB) and the search query parser.
- **Gene page:** search a gene → its eQTLs across tissues, on real GTEx v8 data via the shared DB.

## In flight (open PRs)
- **#22** — add code owners (Liu Fei, YANG Chen, Wenjing) + assign Liu Fei design/UI ownership.
  _Awaiting review._
- **#23** — **design spec** for the gene-page visualizations (LD-colored regional plot + tissue body
  map). _Under review by @liufei-f (UI/UX)._ Spec: `docs/design/gene-page-visualizations.md`.

## Next up
- **Regional plot (Phase A)** once the design (#23) is signed off: a LocusZoom-style, LD-colored
  Plotly plot (per gene × tissue), then LD click-to-recolor + population selector.
- **Tissue body map (Phase B):** EBI anatomogram SVG (CC-BY) highlighting eQTL tissues.
- Backlog: variant page (#6), download (#7), provenance banner (#8).

## Open items / blockers
- **#18** — the DB has no effect allele → β *direction* is not interpretable; decide how to handle
  (join a variant reference / re-read source / show p-values only).
- **LD covering index** on the `tkg_p3v5a_ld_*` tables (perf for the plot) — DDL on the *shared* DB,
  owner **Junbin**, routed via [`schema-change-coordination.md`](schema-change-coordination.md).
- **Board** (Project #5) is stale — needs a sync (closed issues → Done; add #18 + open PRs).

## Team & roles
- Lead: **@boxiangliu** (Boxiang Liu).
- Engineers: **@gaojunbin** (Junbin Gao — owns the locuscompare2 DB), **@GhostAnderson** (Laurentius),
  **@MickYang2333** (YANG Chen), **@wenjing-gakkilove** (Wenjing).
- UI/UX: **@liufei-f** (Liu Fei — owns `docs/design/` + `src/locusview/templates/`).
- Plus a PM and scientists. All new to software engineering; heavy, guardrailed use of coding agents.
