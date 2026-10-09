# locusview

**A single, searchable home for publicly available QTL data.** locusview aggregates published
quantitative trait locus (QTL) and GWAS data — bulk-tissue and single-cell — and lets researchers
**search, browse, and download** it from one place, instead of hunting across a dozen scattered
portals.

> **Status: Phase 1 — working portal.** Home page (live dataset catalog + interactive tissue body
> map), Data Browser (cascading QTL/GWAS picker → LD-colored LocusZoom plots), gene pages with
> CSV/TSV download. See [status](docs/process/status.md) and the [roadmap](docs/product/roadmap.md).

This repository is also a **teaching artifact**: it is being built, in the open, as the worked example
for a graduate course on software engineering and AI-agent-native development. If you are a student,
start with [the software-engineering lifecycle explainer](docs/explanation/software-engineering-lifecycle.md).

## Run it locally

From a fresh `git clone` to the site in your browser. There is **no JS build step** — the frontend is
server-rendered Jinja2 + plain JS, so `uv` is the only tooling you need.

### 1. Install uv

[uv](https://docs.astral.sh/uv/) manages the Python version, the virtualenv, and dependencies.

```bash
# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh
# or: brew install uv
```

### 2. Clone and install

```bash
git clone https://github.com/boxiangliulab/locusview.git
cd locusview
uv sync                      # creates .venv and installs everything (~30s)
```

### 3. Configure the database connection

```bash
cp .env.example .env
```

`.env.example` already has the host, port, database name, and user filled in. **You only need to add
the password** — open `.env` and set:

```
LOCUSCOMPARE2_PG_PASSWORD=<ask-the-team>
```

It is deliberately blank in the committed example: this repo is public and `gitleaks` blocks commits
containing secrets. Ask a maintainer for the value.

No SSH tunnel is needed — the app connects straight to the server on port `15432`.

### 4. Start the app

```bash
uv run locusview serve
```

Open **<http://127.0.0.1:8000>**. You should see the Home page with the dataset tables and the
interactive body map.

```
Home          http://127.0.0.1:8000/            dataset catalog + tissue body map
Data Browser  http://127.0.0.1:8000/browser     pick datasets → LocusZoom plots
News          http://127.0.0.1:8000/news        release notes
Health        http://127.0.0.1:8000/health      liveness probe (JSON)
```

`--host` / `--port` override the defaults (`127.0.0.1:8000`). Keep `--host` a *local* address —
it is what the server binds to, not the database it connects to.

### Just want to see the UI, without database access?

Leave the host blank and the app falls back to an empty in-memory repository — every page renders,
the tables and plots are simply empty:

```bash
LOCUSCOMPARE2_PG_HOST= uv run locusview serve
```

### Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Every page returns **500**, log says `password authentication failed` | `LOCUSCOMPARE2_PG_PASSWORD` empty or wrong in `.env` | Set the real password (step 3) |
| `error while attempting to bind on address … can't assign requested address` | `--host` was given a *remote* IP | Use `127.0.0.1` (or `0.0.0.0` to expose on your LAN) |
| Pages load but everything is empty | `LOCUSCOMPARE2_PG_HOST` is blank → in-memory fallback | Restore the host in `.env` |
| `pg8000 … Can't create a connection` / timeout | Port 15432 blocked by your network | Check `nc -vz <host> 15432`; ask about firewall/allowlist |

## Development

```bash
uv run pytest                            # tests — must stay green (90% coverage gate)
uv run ruff check . && uv run mypy       # lint + types (strict)
```

**Layout:** backend Python lives in `src/backend/locusview/` (the `locusview` package — routers, the
`QtlRepository` data-access layer, `web.py`); HTML templates and static assets live in the sibling
`src/frontend/` (`displays/`, `static/`). See [`CLAUDE.md`](CLAUDE.md) for conventions.

You will also need the genomics toolchain (`bcftools`, `tabix`, `bgzip` from HTSlib) for data-ingest
work; the [machine-setup how-to](docs/how-to/) covers a known-good path (a container is recommended).

## Documentation map

We organize docs with [Diátaxis](https://diataxis.fr). See [`docs/README.md`](docs/README.md).

| I want to… | Go to |
|---|---|
| Understand **why** we work this way | [`docs/explanation/`](docs/explanation/) |
| **Do** a specific task | [`docs/how-to/`](docs/how-to/) |
| **Look up** a fact (schema, API) | [`docs/reference/`](docs/reference/) |
| See **product** intent (Vision, PRD, roadmap) | [`docs/product/`](docs/product/) |
| See **UI/UX design** specs and mockups | [`docs/design/`](docs/design/) |
| See **how we work** & use agents | [`docs/process/`](docs/process/) |
| See **decisions** and why | [`docs/adr/`](docs/adr/) |
| See the **course** layer | [`docs/course/`](docs/course/) |
| **Learn** by building (student labs) | `docs/tutorials/` — *planned, not written yet* |

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md). In short: small feature branches, pull requests with green
CI, human review before merge, and **agents write, humans merge**.

## License

[MIT](LICENSE) — open source from commit #1, so students can follow the whole history.
