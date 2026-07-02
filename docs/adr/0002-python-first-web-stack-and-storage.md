# ADR-0002: Python-first web stack and file-based storage (provisional)

- **Status:** Accepted (provisional). ⚠ **The storage decision is superseded by
  [ADR-0008](0008-store-qtl-in-locuscompare2-database.md)** (2026-07-02) — QTL data now lives in the
  shared locuscompare2 database, not Parquet/DuckDB/tabix. The **web-stack** choices below
  (FastAPI + Jinja2/HTMX) still stand.
- **Date:** 2026-07-01

## Context
locusview must store, index, and serve potentially hundreds of millions to billions of QTL
association records, offering search by gene/variant/region, browse, and bulk download. But those
records compress to ~30–150 GB and fit on a single NVMe disk — this is a **single-machine problem**,
not a distributed-systems problem. The binding constraint is the *team*: two engineers new to SE,
science-background generalists, leaning on coding agents. We researched how the incumbents (GTEx,
eQTL Catalogue, Open Targets) actually do it: they converge on a columnar/compressed store + a
coordinate-indexed flat-file store + a small metadata layer.

## Decision
Adopt a **Python-first, file-based** stack for the MVP:
- **Storage:** partitioned **Parquet** (analytical) + **bgzip/tabix** flat files (region slices &
  ecosystem interop), with a small **"significant hits"** tier for interactive browse.
- **Engine:** **DuckDB** embedded in-process (no database server).
- **Metadata catalog:** **SQLite** (→ Postgres later if needed).
- **API/UI:** **FastAPI** + **Jinja2 + HTMX** (no JS build chain); **Streamlit** for internal QC.
- **Downloads:** **Cloudflare R2** ($0 egress). **Deploy:** one Hetzner box + Docker Compose + Caddy.

This decision is **provisional**: we recorded it now to move, but we mark it for revisit after we
have actually ingested one dataset (the Phase-1 spike) and can measure rather than guess.

## Consequences
- **+** Lowest barrier for a beginner team; every tool is one agents are fluent in and that teaches
  transferable skills (SQL, columnar data, REST, containers).
- **+** Cheap (~$100–200/mo) and near-zero database operations.
- **+** **Scale-up path preserved:** the API contract and Parquet format don't change; if interactive
  latency degrades we drop in **ClickHouse** behind the *same* endpoints. Every heavy decision stays
  deferrable.
- **−** Some patterns (e.g., DuckDB-in-FastAPI concurrency) need care under multi-worker servers —
  noted for Phase 1 (read-only mode / connection-per-request).
- **−** "Provisional" means we accept we may revise storage details once we measure real data.
