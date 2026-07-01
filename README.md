# locusview

**A single, searchable home for publicly available QTL data.** locusview aggregates published
quantitative trait locus (QTL) data — bulk-tissue and single-cell — and lets researchers **search,
browse, and download** it from one place, instead of hunting across a dozen scattered portals.

> **Status: Phase 0 — Foundation.** We are building the *project* (repository, process, docs, and
> product definition) before building product features. There is no working portal yet. See the
> [roadmap](docs/product/roadmap.md).

This repository is also a **teaching artifact**: it is being built, in the open, as the worked example
for a graduate course on software engineering and AI-agent-native development. If you are a student,
start with [the software-engineering lifecycle explainer](docs/explanation/software-engineering-lifecycle.md).

## Quickstart (developers)

> Full, verified steps live in [`docs/how-to/`](docs/how-to/). The short version:

```bash
# 1. Install uv (https://docs.astral.sh/uv/) if you don't have it, then:
uv sync                      # create the virtual env and install dependencies
uv run pytest                # run the test suite
uv run locusview             # run the app (a placeholder until Phase 1)
```

You will also need the genomics toolchain (`bcftools`, `tabix`, `bgzip` from HTSlib) for Phase 1;
the [machine-setup how-to](docs/how-to/) covers a known-good path (a container is recommended).

## Documentation map

We organize docs with [Diátaxis](https://diataxis.fr). See [`docs/README.md`](docs/README.md).

| I want to… | Go to |
|---|---|
| Understand **why** we work this way | [`docs/explanation/`](docs/explanation/) |
| **Do** a specific task | [`docs/how-to/`](docs/how-to/) |
| **Look up** a fact (schema, API) | [`docs/reference/`](docs/reference/) |
| **Learn** by building (student labs) | [`docs/tutorials/`](docs/tutorials/) |
| See **product** intent (Vision, PRD, roadmap) | [`docs/product/`](docs/product/) |
| See **how we work** & use agents | [`docs/process/`](docs/process/) |
| See **decisions** and why | [`docs/adr/`](docs/adr/) |
| See the **course** layer | [`docs/course/`](docs/course/) |

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md). In short: small feature branches, pull requests with green
CI, human review before merge, and **agents write, humans merge**.

## License

[MIT](LICENSE) — open source from commit #1, so students can follow the whole history.
