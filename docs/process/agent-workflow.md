# Working with Coding Agents (and doing it safely)

> **Diátaxis quadrant:** Explanation — *why and how we build with AI agents*.
> Big picture: [`../explanation/software-engineering-lifecycle.md`](../explanation/software-engineering-lifecycle.md).
> Team mechanics: [`ways-of-working.md`](ways-of-working.md).

**Learning objectives.** After reading this you should be able to: explain the mental model we hold
for an agent; run a "loop engineering" cycle; choose between a single agent, a workflow, a Skill, and
an MCP server; and list the guardrails that make heavy agent use *safe* — and why each exists.

---

## 1. Mental model: an agent is an eager junior engineer with no memory

A coding agent is **fast, capable, tireless, literal, and forgetful.** It will do what you ask
extremely quickly — including the wrong thing, extremely quickly — and it starts each session
without memory of the last. Two consequences drive everything else:

1. **The process is the safety harness.** Tests, CI, and human review are not bureaucracy; they are
   the mechanisms that let us hand real work to something this fast without getting hurt.
2. **Everything the agent should "remember" must be written down** — in the repo, in Skills, in
   ADRs, in this document. Written knowledge is the agent's long-term memory.

> One sentence to tattoo on the wall: **agents write, humans merge.**

---

## 2. Loop engineering — our core technique

"Loop engineering" is running a **tight, automatically-verified feedback loop** between a
specification and an agent, with a human at the merge gate.

```
  1. SPECIFY      ideally a failing test that encodes "done"
        │
  2. GENERATE     the agent proposes a change
        │
  3. VERIFY       run tests + lint + CI automatically
        │
        ├─ fail ─▶ feed the exact failure back to the agent ──▶ (2)
        │
  4. pass ─▶ HUMAN reviews the final diff ─▶ merge (or send back)
```

**The verifier determines the quality of the output.** This is the whole game:

- Weak spec → "make the search better" → the agent guesses, you get slop.
- Strong spec → "make `test_search_by_gene_returns_sorted_hits` pass" → the agent has an
  unambiguous target and a built-in definition of done.

That's *why* we invest early in tests and CI: they are the loop's verifier. A team that skips tests
doesn't just risk bugs — it removes the thing that makes agent assistance trustworthy.

**Worked example (our Day-4 exercise, captured as "Lecture 1"):** take a real issue → write a
failing test for it → let an agent iterate in its own branch/worktree until CI is green → an engineer
reviews the diff → merge. Then debrief out loud: *where did the agent go wrong, and which guardrail
caught it?* That debrief is the first durable lecture of the course.

---

## 3. Which tool for which job

| Tool | Use it when… | Cost / caution |
|---|---|---|
| **Single agent / subagent** | one focused task with a clear definition of done | cheapest; the default |
| **Workflow (many agents)** | you want breadth or *independent* verification — parallel research, multi-angle review, then synthesis | more tokens; use for scale or confidence, not routine edits |
| **Skill** | a task you'll repeat; encode the team's playbook so every agent does it *our* way | write once; keep updated |
| **MCP server** | the agent must reach a *live external system* (a database, an API) | add sparingly, **least privilege**; each one is attack surface — record the decision in a mini-ADR |
| **git worktrees** | multiple agents editing in parallel would collide on one working copy | adopt in Phase 1; overkill in Phase 0 |

Rule of thumb: **start with the smallest tool that could work.** Reach for a workflow when the task
genuinely needs breadth (cover many files/angles) or confidence (independent adversarial checks) —
not because parallelism feels productive.

---

## 4. The safety harness (why each guardrail exists)

Every guardrail below maps to a specific way an eager, forgetful agent can hurt you.

| Guardrail | The failure it prevents |
|---|---|
| **Human at the merge gate; never auto-merge** | An agent confidently merging subtly-wrong code into `main`. |
| **`CODEOWNERS` → engineers required on `src/` & `tests/`** | "Who was supposed to catch this?" being unanswered. |
| **`tests/` protected + coverage-drop CI gate** | An agent "passing" by *weakening or deleting the test* instead of fixing the code. |
| **`gitleaks` + max-file-size pre-commit hooks** | An agent running `git add .` and committing a secret token or a multi-GB data file. |
| **GitHub secret scanning + push protection** | A leaked credential reaching a public repo (defence in depth behind the hook). |
| **Provisional ADRs for un-lived decisions** | Cargo-culting a decision the team doesn't actually understand yet. |
| **`Co-Authored-By` on agent commits** | Losing track of what a human authored vs an agent — transparency is itself a lesson. |

> **The most dangerous, least obvious one is the test-integrity gate.** A novice reviewer skims a
> green PR and approves; they won't notice that the agent quietly changed `assert result == 42` to
> `assert result is not None`. Coverage gates + protected `tests/` + the PR-template question "did
> this PR change tests, and why?" force that change into the open.

---

## 5. Red flags — stop and get a human

- The agent proposes editing a **test** to make a build pass. (Why did the behaviour change?)
- A diff touches **far more** than the issue described. (Scope creep; split it.)
- The agent wants to add a **dependency or MCP server** you didn't discuss. (Least privilege.)
- You can't explain, in a sentence, **what the change does**. (Then you can't review it — don't merge.)
- The change touches **data licensing, secrets, or deployment**. (Human decision, always.)

---

## 6. Attribution and honesty

Agent-authored commits carry a `Co-Authored-By` trailer. We are transparent, with ourselves and with
students, about what was written by a person and what was written by an agent under human review.
That honesty is part of what makes this a *teachable* way to work, not a magic trick.
