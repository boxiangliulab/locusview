# Contributing to locusview

Welcome. This project is built by a small team new to software engineering, in the open, as a
teaching example. That means **how** we contribute matters as much as **what** we contribute. Please
read this once; it takes five minutes and saves everyone hours.

Fuller background: [`docs/process/ways-of-working.md`](docs/process/ways-of-working.md) and
[`docs/process/agent-workflow.md`](docs/process/agent-workflow.md).

## The short version

> **Small branches. Green CI. Human review before merge. Agents write, humans merge.**

## Workflow (trunk-based-lite)

1. **Start from an issue.** Work should be small enough to finish in a day or two. If it's bigger,
   split it.
2. **Branch off an up-to-date `main`:**
   ```bash
   git switch main && git pull
   git switch -c feat/<short-name>      # or fix/<short-name>, docs/<short-name>
   ```
3. **Commit in small steps.** Write clear messages (see below).
4. **Open a pull request** using the template. Fill in *what / why / how tested / output*, and the
   **"did this PR change tests, and why?"** checkbox honestly.
5. **CI must be green** (lint + tests + genomics smoke test + coverage gate) before review.
6. **Get a review.** An engineer (a `CODEOWNERS` owner of `src/`/`tests/`) approves when the change
   *improves the overall health of the codebase* — not when it's flawless.
7. **Merge and delete the branch.** Keep `main` always working.

## Commit messages

Short imperative subject line, optional body explaining *why*. Example:

```
Add gene-symbol resolver to the search endpoint

Users expect to type "TP53" not an Ensembl ID. Resolves via the
metadata catalog; falls back to a "did you mean" list on miss.
```

If a coding agent authored the change, keep the trailer so authorship is transparent:

```
Co-Authored-By: <agent/model name> <noreply@…>
```

## Using coding agents

We use AI coding agents heavily and **responsibly**. The rules that keep this safe:
- **Never auto-merge agent-written code.** A human reviews every diff.
- **Agents must not edit tests to make a build pass.** If behaviour changed, say why in the PR.
- **Never commit secrets or large data.** `gitleaks` and a file-size hook run on every commit; the
  `data/` directory is gitignored. If a hook blocks you, that's the system working — don't bypass it.
- New dependencies or MCP servers are a *decision* — discuss first, record a short ADR.

See [`docs/process/agent-workflow.md`](docs/process/agent-workflow.md) for the full "loop engineering"
method and the reasoning behind each guardrail.

## Decisions

Made a choice that would be expensive or confusing to reverse? Write a short **ADR** in
[`docs/adr/`](docs/adr/) (copy the format of `0001-record-architecture-decisions.md`).

## Local setup

See [`docs/how-to/`](docs/how-to/) for machine setup and running locusview locally.
