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
Python 3.11+ · **uv** (env/deps) · **FastAPI + Jinja2 + HTMX** (no JS build chain) · **pymysql** to the
shared **locuscompare2 MySQL** database (ADR-0008) · Ruff + mypy (strict) + pytest. Storage is the
shared DB, **not** a locusview-owned store (ADR-0008 supersedes the earlier Parquet/DuckDB plan).

## Run it
```bash
uv sync                                  # env + deps
uv run pytest                            # tests — must stay green (90% coverage gate)
uv run ruff check . && uv run mypy       # lint + types (strict)
uv run locusview serve                   # web app on http://127.0.0.1:8000
```
Data access needs `LOCUSCOMPARE2_DB_*` env vars (a read-only account). The public read-only **test**
credentials + host are documented in
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
- Read QTL data through the **`QtlRepository`** Protocol (`src/locusview/repository.py`):
  `FakeQtlRepository` for hermetic tests, `LocuscompareRepository` for the real DB. **Program to the
  interface; keep CI hermetic (no network in tests)** — the real DB is exercised only in ad-hoc checks.
- DB keys are integer-encoded: `gene_id` = the ENSG number (`ENSG00000141510` → `141510`), `rs_id` =
  rsID minus `rs`. Data lives in per-tissue `eqtl_snp_{dataset_id}` shards + the `eqtl_raw` catalog;
  gene coords in `gencode_v26_hg38`. **The shards have no effect allele / MAF → do not present β
  *direction*** (issue #18).
- Docs use **Diátaxis** (tutorials/how-to/reference/explanation) + ADRs in `docs/adr/`. Design specs in
  `docs/design/` and web templates are owned by the UI/UX designer (see `CODEOWNERS`).

## Where knowledge lives (the repo is the source of truth)
Decisions → `docs/adr/` · designs → `docs/design/` · process → `docs/process/` · current state &
open threads → `docs/process/status.md` · the teaching layer → `docs/course/`. Prefer these over
chat or machine-local memory — they travel with `git clone` to cloud sessions and teammates.
