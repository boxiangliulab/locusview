# ADR-0004: License and repository posture

- **Status:** Accepted
- **Date:** 2026-07-01

## Context
locusview serves *public* data and is being built as an open teaching example for graduate students.
We must choose a software license, repository visibility, and hosting platform on day one — these
gate the `LICENSE` file, whether students can follow the history, and (separately) any *data*
re-hosting terms.

## Decision
- **License: MIT** — a simple, permissive license. Anyone can use, teach from, and build on the code.
- **Repository: public from commit #1**, so students can follow the entire history as it grows.
- **Host: GitHub** — best CI (Actions) and coding-agent tooling, `gh` CLI available, and the platform
  students will most likely meet in industry.

## Consequences
- **+** Maximum openness for a teaching + public-data mission; lowest-friction reuse.
- **+** Public history is itself course material.
- **−** Building in public means mistakes are visible — which we treat as a feature (honest war
  stories), backed by the guardrails in [ADR-0005](0005-agent-driven-workflow.md).
- **Important distinction:** the MIT license covers *our code*. It does **not** grant rights over
  third-party *QTL data*; each dataset's redistribution terms are handled separately (per-dataset
  license field; link-out when unclear). See the [roadmap](../product/roadmap.md).
