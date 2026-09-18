# CLAUDE.md — locusview

Orientation for any Claude Code session (local, cloud, or a teammate's) and for new contributors.
Keep it current. The live "where we are right now" lives in
[docs/process/status.md](docs/process/status.md).

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
