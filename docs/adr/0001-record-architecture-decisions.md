# ADR-0001: Record architecture decisions

- **Status:** Accepted
- **Date:** 2026-07-01

## Context
We are a team new to software engineering, building in the open, and using AI agents that have no
memory between sessions. Decisions made in chat or in someone's head are forgotten and re-argued.
Newcomers (and students) have no way to learn *why* the codebase looks the way it does.

## Decision
We will record significant, hard-to-reverse decisions as **Architecture Decision Records (ADRs)** —
short, numbered markdown files in `docs/adr/`, using Michael Nygard's format (Context / Decision /
Consequences). We write an ADR when a choice would be **expensive or confusing to reverse**; small,
reversible choices do not need one. ADRs are immutable once accepted — to change a decision, write a
new ADR that supersedes the old one (and note it in both).

## Consequences
- **+** The team and future contributors (and students) can see the reasoning behind every major
  choice; agents can be pointed at ADRs as durable memory.
- **+** Cheap to write (half a page), so the discipline is sustainable.
- **−** Requires the habit of pausing to write one; we mitigate this with a "scaffold-an-ADR" Skill.
- We keep the set **lean** — an ADR for every trivial choice would bury the signal.

*Reference: Michael Nygard, "Documenting Architecture Decisions" (2011).*
