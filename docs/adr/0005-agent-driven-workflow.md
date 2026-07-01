# ADR-0005: Agent-driven workflow and merge-gate rules

- **Status:** Accepted
- **Date:** 2026-07-01

## Context
We use AI coding agents heavily. Agents are fast, capable, literal, and forgetful — they will
implement the wrong thing quickly and confidently, and they can "pass" a task by weakening its test.
For a beginner team building in public, we need the *process* to be the safety harness, and we need it
written down (agents have no memory between sessions).

## Decision
Adopt **loop engineering** as the core method (*specify a failing test → agent generates → verify
automatically → feed failures back → repeat until green → **human reviews the final diff***), with a
non-negotiable safety harness:
- **Agents write, humans merge.** Never auto-merge agent-authored code.
- **`CODEOWNERS`:** the two engineers are required reviewers on `src/` and `tests/`.
- **Test integrity:** `tests/` is protected; a **coverage-drop CI gate** and a PR-template question
  ("did this PR change tests, and why?") catch silently-weakened tests.
- **Secret/data guardrails:** `gitleaks` + a max-file-size pre-commit hook, plus GitHub secret
  scanning + push protection, so an agent can't commit a token or a multi-GB data file.
- **Least-privilege MCP:** add at most one MCP server, only for a genuine live external need.
- **Attribution:** agent-authored commits carry a `Co-Authored-By` trailer.

## Consequences
- **+** Heavy agent use becomes *safe*, because every change is automatically verified and
  human-reviewed; this is the core teachable practice of the project.
- **+** Guardrails are instrumented (CI, hooks, CODEOWNERS), not just asserted in prose.
- **−** Review is the bottleneck and depends on competent reviewers — hence the defined engineer
  reviewer role and scientists' non-code assurance role (see
  [ways-of-working](../process/ways-of-working.md)).
- Full method and the reasoning per guardrail: [`agent-workflow.md`](../process/agent-workflow.md).
