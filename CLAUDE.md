# CLAUDE.md — locusview

Orientation for any Claude Code session (local, cloud, or a teammate's) and for new contributors.
Keep it current. The live "where we are right now" lives in
[docs/process/status.md](docs/process/status.md).

## Work log — 2026-09-24
- Restored the local PostgreSQL container after an unexpected shutdown. Docker had failed to mount
  its data directory at boot; once the mount was available, PostgreSQL completed crash recovery.
  Both public frontends then returned HTTP 200: locusview on port 33245 and LocusCompare 2 on
  port 33244.
- Moved **Search data** ahead of **Data Browser** in the site navigation. Each QTL phenotype in
  the Search data table now links to Data Browser with its exact `qtl:<dataset_id>` context,
  gene or variant locus, and URL-encoded phenotype ID. Data Browser runs the linked query on
  arrival, selects that phenotype, and loads its LocusZoom plot. If the phenotype is outside the
  initial 50-row summary, the linked row is added so it can still be plotted. GWAS rows have no
  phenotype link.
- Deployed the change in the `locusview:search-data-20260924` Docker image. Verified the public
  Search data and Data Browser pages, a real TP53 phenotype link, and the phenotype-variant API.
  The full test run had 314 passes and one existing failure in
  `tests/test_qtl_data_agent.py::test_reads_selected_skill` (its expected skill text differs from
  the current skill file); coverage was 97.29%. JavaScript syntax and `git diff --check` passed.
- Updated each Data Browser QTL LocusZoom panel header: the blue badge shows the track's actual
  `qtl_type` (for example `sQTL`), and the title shows `source_project_id — context — phenotype`.
  GWAS panel headers are unchanged. Deployed as `locusview:plot-title-20260924`; the public
  browser and updated JavaScript returned HTTP 200, and live track metadata supplied all three
  requested fields.
- Updated the Tutorial to teach the Search data → phenotype link → Data Browser plot path, while
  retaining instructions for direct region and multi-dataset browsing and the Search data JSON
  API. All seven Tutorial tests passed; deployed as `locusview:tutorial-20260924` and verified
  the public `/tutorial` page returns the new content.

## Work log — 2026-09-25
- Loosened letter spacing on the LocusView brand and Home heading, added a subtle text glow, and
  switched blue text and links on light surfaces to the new `#212161` theme color. On the navy
  header and hero, the brand and heading use brighter text for contrast. All 83 focused tests
  passed; deployed `locusview:glow-navy-accent-20260925` and verified five public pages.
- Set the shared navigation bar and the Home hero above its divider to solid `#212161`, with
  light brand, navigation, title, and description colors for readable contrast. The brand icon
  follows the light accent. All 31 focused tests passed; deployed `locusview:nav-hero-navy-20260925`
  and verified the four public pages.
- Bumped locusview to v1.0 in package metadata and the shared application version; the header,
  footer, not-found page, health response, and CLI now use the same version. All 36 focused tests
  passed; deployed `locusview:v1.0-20260925` and verified the public header, footer, and health API.
- Added a space between the Home Associations number and `M+`, and removed the hero description's
  620px width cap so it wraps naturally across the shared content column. Verified both on the
  public Home page.
- Centered all non-first columns in the Home Available QTL and GWAS tables; Dataset and Trait
  remain left-aligned, and the body-map result table keeps its existing alignment. Verified the
  public Home page serves the new table alignment rule.
- Shortened the Home Associations card to whole millions plus a trailing `M+`; the unabridged
  current count remains available on hover. All 21 Home tests passed; deployed
  `locusview:assoc-millions-20260925` and verified the public Home card.
- Centered the four Home statistics cards as a group within the page, leaving the hero heading
  and description left-aligned in their existing positions. All 21 Home tests passed; deployed
  `locusview:stats-center-20260925` and verified the public Home page.
- Aligned the LocusView header brand with the shared content column's left edge, while preserving
  the centered navigation links' positions. All 31 focused tests passed; deployed
  `locusview:brand-align-20260925` and verified the public pages.
- Centered the shared top navigation group, slightly enlarged its brand and page links, and let
  links wrap onto a second row on narrow screens. Enlarged Tutorial's step, table, API, and code text.
  All 64 focused tests passed; deployed `locusview:nav-tutorial-20260925` and verified the public
  Home, Search data, Data Browser, Tutorial, and News pages.
- Made variant Search data results span the same full content width as gene results. The missing
  Lead SNP and Variant column space now goes to Phenotype, while other shared columns keep their widths.
  All 33 Search data tests passed; deployed `locusview:search-width-20260925` and confirmed public
  TP53 and rs1042522 result cards are both 100% wide.
- Set the shared Home, Search data, Tutorial, and News content column to 70% on wide screens;
  it expands smoothly toward the available width on narrow screens, keeping 16px side margins.
  The Home body map's side panel now stacks within the column on small screens. All 31 focused
  page tests passed; deployed `locusview:width70-20260925` and verified all four public pages.
- Deepened the Home hero's blue background above the divider and centered its content vertically
  while keeping the heading, description, and statistics left-aligned within the page column.
  All 21 Home tests passed; deployed `locusview:hero-20260925` and verified the public Home page.
- Enlarged the page titles on Home, Search data, Tutorial, and News. The Home heading now reads
  "LocusView：Explore QTL associations across cell types and tissues" on one line at desktop
  widths. Increased spacing, padding, type size, border emphasis, and shadow on its four live
  statistic cards. Checked desktop and mobile layouts; 31 focused page tests passed. Deployed
  `locusview:titles-20260925` and confirmed all four public pages return HTTP 200.
- Matched the Home, Search data, Tutorial, and News content columns to the Search data page's
  80% viewport width, with 16px side margins on narrow screens. Updated the Home hero to
  "Explore QTL associations across cell types and tissues".
- Home now shows four live QTL statistics: all `qtl_lists` rows, distinct
  `qtl_datasets.qtl_type` values, distinct `qtl_contexts.level_1_context` values with `+` when
  level 2 contexts exist, and association rows across the physical `qtl_snp_<id>` tables.
  Association counts use each append-only shard's `id` sequence so Home does not scan roughly
  9 TB of QTL data on every request. All 151 sequences matched their shard's `max(id)`;
  an exact `count(*)` spot check also matched its sequence. In-progress or failed transactions
  can temporarily advance a sequence ahead of committed rows.
- Deployed `locusview:home-stats-20260925`; the public Home, Search data, Tutorial, and News pages
  returned HTTP 200. At verification, Home showed 151 datasets, 3 QTL types, 51+ contexts,
  and a growing association count. Targeted tests, Ruff on modified code, and mypy passed.
  Full pytest had 317 passes and the existing `test_reads_selected_skill` failure in
  `tests/test_qtl_data_agent.py`.

## What this is
locusview aggregates publicly available **QTL** (quantitative trait locus) data and lets users
**search, browse, and download** it. It is built by Boxiang Liu's lab **and** is a graduate-level
software-engineering teaching example — so docs, ADRs, and PR history are first-class deliverables.

- Repo: <https://github.com/boxiangliulab/locusview> · Board: <https://github.com/orgs/boxiangliulab/projects/5>

## Stack
Python 3.11+ · **uv** (env/deps) · **FastAPI + Jinja2 + HTMX** (no JS build chain) · **pg8000** to the
shared **locuscompare2 Postgres** database · Ruff + mypy (strict) + pytest. Storage is the shared DB,
**not** a locusview-owned store (ADR-0008 supersedes the earlier Parquet/DuckDB plan).
ADR-0008 named a **MySQL** DB; the team replaced it with Postgres in 2026-08 — see the "Database
switch note" in [docs/process/status.md](docs/process/status.md). `pymysql` is still a declared
dependency but is unused by default (the MySQL `LocuscompareRepository` is commented out, not
deleted).

## Run it
```bash
uv sync                                  # env + deps
uv run pytest                            # tests — must stay green (90% coverage gate)
uv run ruff check . && uv run mypy       # lint + types (strict)
uv run locusview serve                   # web app on http://127.0.0.1:8000
```
Data access needs `LOCUSCOMPARE2_PG_*` env vars (the Postgres DB — `LOCUSCOMPARE2_DB_*` is the
superseded MySQL naming, see ADR-0008's update in `docs/process/status.md`). Connect **directly**
to the server on port **15432** (the server's compose publishes `15432:5432`); no SSH tunnel is
needed. Host + credentials are documented in
[docs/how-to/connect-to-locuscompare2-database.md](docs/how-to/connect-to-locuscompare2-database.md);
the password is never committed. For **cloud** Claude Code sessions, allowlist the DB host so the VM
can reach it.

## How we work — READ before changing code
- **Trunk-based-lite + protected `main`.** Never push to `main`. Every change: feature branch → PR →
  green CI → **code-owner review** → squash-merge + delete branch. See
  [docs/explanation/pull-requests-and-branch-protection.md](docs/explanation/pull-requests-and-branch-protection.md).
- **Agents write, humans merge.** Do not self-merge; a human code owner (`CODEOWNERS`) approves.
- Never weaken a test to make CI pass; never commit secrets or large data (`data/` is gitignored;
  `gitleaks` runs). Mark agent-authored commits with `Co-Authored-By`.
- Full process: [docs/process/ways-of-working.md](docs/process/ways-of-working.md) ·
  [docs/process/agent-workflow.md](docs/process/agent-workflow.md).

## Code conventions
- **Layout (2026-08):** backend Python lives under `src/backend/locusview/` (the `locusview`
  package — `routers/`, the data-access layer (`requestinfo.py` = the `QtlRepository` interface +
  fake; `connectpostgres.py` = the real Postgres implementation), `web.py`); HTML templates and
  static assets live in the sibling `src/frontend/` (`displays/`, `static/`), not inside the
  package — see `web.py`'s `_STATIC_DIR` comment for how the two find each other at runtime.
- Read QTL data through the **`QtlRepository`** Protocol (`src/backend/locusview/requestinfo.py`):
  `FakeQtlRepository` for hermetic tests, **`PostgresQtlRepository`** (`connectpostgres.py`) for the
  real DB. **Program to the interface; keep CI hermetic (no network in tests)** — the real DB is
  exercised only in ad-hoc checks. (The MySQL-era `LocuscompareRepository` is commented out in
  `requestinfo.py`, not live code.)
- DB keys are integer-encoded: `gene_id` = the ENSG number (`ENSG00000141510` → `141510`), `rs_id` =
  rsID minus `rs`. Data lives in per-(dataset × context) `qtl_snp_{qtl_lists.id}` shards (+ a
  `qtl_snp_{id}_phenotype` companion) behind the `qtl_datasets` → `qtl_lists` → `qtl_contexts`
  catalog; GWAS mirrors this as `gwas_datasets` → `gwas_lists` → `gwas_snp_{id}`. Gene coords are in
  `gencode_v39`, rsIDs in `variant_rsid_mapping_raw`, LD in `tkg_p3v5a_ld_chr{chrom}_{population}`.
  See `connectpostgres.py`'s module docstring for the full schema.
- **β direction (issue #18) is interpretable on the current DB** — the `qtl_snp_*` shards do carry
  `ref`/`alt`/`maf` (verified live). The old "no effect allele → don't present β direction" rule
  applied to the superseded MySQL `eqtl_snp_*` shards only.
- Docs use **Diátaxis** (tutorials/how-to/reference/explanation) + ADRs in `docs/adr/`. Design specs
  live in `docs/design/` and the UI/UX designer (@liufei-f) is their author — but note `CODEOWNERS`
  does **not** currently encode that: it assigns all of `/src/` (backend *and* `src/frontend/`) to
  the three engineers, and has no entry for `docs/design/`. Add one if designer review should be
  enforced on frontend/design changes.

## Where knowledge lives (the repo is the source of truth)
Decisions → `docs/adr/` · designs → `docs/design/` · process → `docs/process/` · current state &
open threads → `docs/process/status.md` · the teaching layer → `docs/course/`. Prefer these over
chat or machine-local memory — they travel with `git clone` to cloud sessions and teammates.
