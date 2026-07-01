# Ways of Working

> **Diátaxis quadrant:** Explanation / Reference — *how this team operates day to day*.
> Companion docs: the big picture in
> [`../explanation/software-engineering-lifecycle.md`](../explanation/software-engineering-lifecycle.md);
> the AI-agent specifics in [`agent-workflow.md`](agent-workflow.md).

**Learning objectives.** After reading this you should be able to: name each person's role
(including the two science-background members' *non-code* roles), describe our weekly rhythm, walk a
change from idea to merged pull request, and state our Definition of Ready and Definition of Done.

---

## 1. The team and roles

We are four people, all generalists, deliberately assigning roles so that "who reviews this?" and
"who owns that?" always have an answer. Roles are hats, not job titles — people wear more than one.

| Hat | Who | Owns |
|---|---|---|
| **Engineer** (×2) | *the two engineers* | Code in `src/` and `tests/`; **required reviewers** on all code PRs (`CODEOWNERS`); the merge gate for agent-written code. |
| **Product / PM** (×1) | *the PM* | The PRD, the backlog, prioritization, keeping scope honest. |
| **Domain / science** (×2) | *the two scientists* | Requirements correctness, **test assertions** ("does this locus render at the right position?"), data provenance, validation of scientific claims, the tutorials. |

> **Why give scientists a defined non-code role?** Because the merge gate is only as strong as the
> reviewer, and heavy agent use makes review the bottleneck that keeps us safe. Scientists may not
> review a DuckDB query, but they are the *only* people who can say whether an answer is
> scientifically correct — so they own the assertions and the provenance. Everyone is on the hook
> for quality, in the lane where they're strongest.

---

## 2. Weekly cadence — the *entire* management overhead

Resist adding more ceremony than this. More process is not more professionalism.

| When | Ritual | Length | Purpose |
|---|---|---|---|
| **Monday** | Planning | 30 min | Pick the week's issues from the backlog; agree what "done" means for each. |
| **Daily** | Async standup (written) | 5 min | Each person posts: *done / doing / blocked*. No meeting. |
| **Friday** | Demo + retro | 30 min | Show working software; write ½ page of what we learned into `retros/`. |

---

## 3. From idea to merged change (trunk-based-lite)

1. **An issue exists.** Work starts from a GitHub Issue small enough to finish in a day or two.
2. **Branch.** `git switch -c feat/<short-name>` (or `fix/…`). Branch off an up-to-date `main`.
3. **Work in small commits.** If an agent did the work, it happens in this branch (in Phase 1, in a
   dedicated **git worktree** so parallel agents don't collide).
4. **Open a pull request** using the PR template. Fill in: *what / why / how tested / output*, and
   the **"did this PR change tests, and why?"** checkbox.
5. **CI runs.** Lint + tests + the genomics smoke test + the coverage gate. A red PR cannot merge.
6. **Review.** A required reviewer (an engineer) approves when the change **improves overall codebase
   health** — not when it's perfect. **Agent-written code is never auto-merged.**
7. **Merge and delete the branch.** Keep `main` always releasable.

```
issue ─▶ branch ─▶ small commits ─▶ PR ─▶ CI green ─▶ human review ─▶ merge ─▶ delete branch
```

---

## 4. Definition of Ready / Definition of Done

**Definition of Ready** (before we pull an issue into a week):
- The problem and the "why" are clear and written in the issue.
- It's small enough to finish in ~1–2 days, or it gets split.
- We can state how we'll know it's done (a test, an observable behaviour).

**Definition of Done** (before we call an issue complete):
- Code + tests merged to `main`; CI green.
- Any decision worth remembering is captured in an **ADR**.
- User-facing behaviour is documented (a how-to or reference update).
- If it changed how we *work*, `ways-of-working.md` or `agent-workflow.md` is updated.

---

## 5. Decisions

When a choice would be **expensive or confusing to reverse**, write an **ADR** (`docs/adr/`, Nygard
format). Small, reversible choices don't need one — don't bury the signal. If you're unsure, a
two-sentence ADR beats a forgotten Slack message.

---

## 6. New here?
Start with [`../explanation/software-engineering-lifecycle.md`](../explanation/software-engineering-lifecycle.md),
then do the "set up your machine" and "run locusview locally" how-tos in `docs/how-to/`.
