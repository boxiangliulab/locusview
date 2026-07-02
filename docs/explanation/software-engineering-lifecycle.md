# The Software-Engineering Lifecycle (and how *we* run it)

> **Diátaxis quadrant:** Explanation — read this to *understand why we work the way we do*.
> If you want to *do* a specific task, see `docs/how-to/`; to *look up* a fact, see
> `docs/reference/`; to *learn by building*, see `docs/tutorials/`.

**Audience.** Team members and graduate students who are new to software engineering. No prior
experience assumed. If you have only ever written analysis scripts, start here.

**Learning objectives.** After reading this you should be able to:
1. Explain the difference between *writing code* and *doing software engineering*.
2. Describe the lifecycle as a repeating loop, and name the phase locusview is in.
3. Say, in plain language, what each core artifact is (Vision, PRD, spec, ADR, roadmap, backlog,
   plan, retrospective), *why it exists*, and point to a real example in this repo.
4. Explain our engineering practices — version control, pull requests, code review, testing/TDD,
   continuous integration — and why each reduces a specific risk.
5. Explain how we use coding agents *safely* (the "safety harness"), and what "loop engineering" is.

---

## 1. Coding is not software engineering

Writing a script that runs once on your laptop is **coding**. **Software engineering** is what you
add so that *a team* can keep changing that code *over months or years* without it rotting: shared
understanding of what you're building and why, a way to make changes safely, a way to catch mistakes
automatically, and a written trail of decisions so the next person (often future-you) isn't lost.

A useful one-liner (paraphrasing Google's *Software Engineering at Google*):

> **Software engineering is programming integrated over time and multiplied by people.**

Everything below exists to manage those two multipliers — **time** and **people** — because
locusview will outlive any single sprint and be touched by all four of us plus, eventually, students.

The whole method reduces to three habits. Keep them in mind; every practice in this document is one
of them in a specific costume:

- **Small** — small PRs, small issues, small decisions, small agent loops. Small things are
  reviewable, reversible, and teachable.
- **Verifiable** — every change has an *automatic* check (a test, a linter, CI). This is what makes
  it safe to move fast, and what makes heavy use of AI agents safe at all.
- **Written down as you go** — in the repo, in the moment. The decision you don't write down is a
  decision you will re-litigate in three weeks.

---

## 2. The lifecycle is a loop, not a line

Beginners often imagine software is built like a building: design fully, then build, then done. Real
software is built like a **garden you keep tending** — you go around a loop many times, each time
delivering a small, working slice:

```
        ┌─────────────────────────────────────────────────┐
        │                                                  │
   (1) Understand ──▶ (2) Spec ──▶ (3) Plan ──▶ (4) Build ─┤
   the problem        the WHAT     the HOW      + Verify    │
        ▲                                          │        │
        │                                          ▼        │
        └────────── (6) Retrospect ◀── (5) Ship ◀──────────┘
                    (what did we learn?)
```

We deliberately go around this loop **once per phase**, each phase shipping something real:

| Phase | What ships |
|---|---|
| **Phase 0** *(now)* | The *project itself*: repo, process, docs, product definition. No features. |
| Phase 1 | A thin working slice: search one dataset by gene → view → download. |
| Phase 2 | More datasets + harmonization. |
| Phase 3 | Richer browsing and visualization. |
| Phase 4 | Single-cell QTL. |

> **Why loop instead of build-it-all?** Because the biggest risk on a new team is not "we can't
> write the code" — it's "we built the wrong thing, or built it in a way we can't change." Shipping a
> thin slice early surfaces those problems while they're cheap. This is the single most important
> idea in modern software delivery (see *Accelerate* / DORA in Further Reading).

A key vocabulary word: a **thin vertical slice** (a.k.a. MVP — *minimum viable product*). Instead of
finishing each horizontal layer (all the data, then all the search, then all the UI), you build one
*narrow path straight through every layer* (one dataset → one search → one page → one download). It
forces every layer to exist and talk to each other on day one.

---

## 3. The artifacts — what each document is *for*

Each artifact answers one question and exists to prevent one kind of expensive mistake. The golden
rule: **separate the WHAT from the HOW.** Product docs (Vision, PRD) say *what* and *why*; technical
docs (spec, ADR) say *how*. Mixing them means a scientist can't argue about requirements without
drowning in database choices.

| Artifact | Answers | Why it exists | In this repo |
|---|---|---|---|
| **Vision** | Where are we going in 1–3 years? | Keeps everyone rowing the same direction | `docs/product/vision.md` |
| **PRD** (Product Requirements Doc) | *What* are we building next, for whom, and how do we know it's done? | Turns a fuzzy idea into agreed, testable requirements | `docs/product/prd.md` |
| **Spec / design doc** | *How* will we build it technically? | Catches design problems before code is written | written per-feature in `docs/design/` |
| **ADR** (Architecture Decision Record) | Why did we choose X over Y? | Preserves *reasoning*, so we don't re-argue or blindly reverse decisions | `docs/adr/` |
| **Roadmap** | In what order, roughly when? | Sequences work and sets expectations | `docs/product/roadmap.md` |
| **Backlog / issues** | What are the concrete next tasks? | Breaks big plans into claimable pieces | GitHub Issues |
| **Implementation plan** | Step-by-step, what do I actually do? | Makes execution boring and safe | written per-task before coding |
| **Retrospective** | What did we learn this phase? | Improves the *process*, not just the product | `docs/process/retros/` |

### 3.1 Vision — *the north star*
One page. The problem, who has it, and what success looks like in a few years. Deliberately
inspirational and stable. **Beginner mistake:** writing features here. The vision is not "add a
download button"; it's "researchers stop hunting across a dozen scattered portals."

### 3.2 PRD — *the contract for the next slice*
The Product Requirements Document is where "what does PRD even mean?" becomes concrete. It states:
the **problem**, the **users and their jobs**, **goals & non-goals**, **user stories** ("As a
researcher, I want to type a gene and see its eQTLs so that…"), **functional requirements**, **success
metrics**, and explicit **out-of-scope**. It says *what* and *why*, never *how*. Our `prd.md` ships
as a **template with every section explained** — filling it in is how you learn the artifact.
**Beginner mistake:** silently expanding scope. The "Out of scope" section is the most valuable part.

### 3.3 Spec / design doc — *the how, before the code*
For a non-trivial feature, a short technical design: the approach, the data flow, the interfaces
between parts, error handling, and how it'll be tested. Cheaper to change a paragraph than a
codebase. **Beginner mistake:** skipping it for "obvious" work — obvious work is where unexamined
assumptions hide.

### 3.4 ADR — *the memory of the team*
A tiny numbered markdown file recording one decision: its **context**, the **decision**, and its
**consequences** (Michael Nygard's format). ADRs are the most valuable and least-taught artifact in
real engineering, because they capture *why*. Six months later, "why are we on GRCh38 only?" has a
one-paragraph answer instead of an argument. **We write an ADR whenever a decision would be expensive
or confusing to reverse.** See `docs/adr/`.

### 3.5 Roadmap — *the rough sequence*
The phases above, kept live. Not promises with dates carved in stone — a shared sense of order.

### 3.6 Backlog / issues — *the unit of work*
Big plans are broken into **small issues** (a few hours to a couple of days each). One issue → one
branch → one pull request. **Beginner mistake:** issues the size of a mountain. If it can't be done
in a day or two, split it.

### 3.7 Implementation plan — *make execution boring*
Before touching code on a task, write the handful of steps. Boring execution is safe execution. For
anything involving an agent, the plan ideally starts from a **failing test** (see §5).

### 3.8 Retrospective — *tend the process*
At the end of each phase, half a page: what went well, what hurt, what we'll change. This is how the
*team* improves, and — for us — where the honest "war stories" that make a good course come from.

---

## 4. Engineering practices — each kills a specific risk

| Practice | The risk it removes |
|---|---|
| **Version control (git)** | "I broke it and can't get back." Every state is recoverable. |
| **Trunk-based-lite branching** | Long-lived branches that diverge and become merge nightmares. |
| **Pull requests + code review** | A single person's blind spot shipping to everyone. |
| **Automated tests** | "It worked when I tried it" — untested code silently breaks later. |
| **Test-Driven Development (TDD)** | Writing code that's hard to test, and not knowing when you're done. |
| **Continuous Integration (CI)** | "Works on my machine." CI checks every change on a clean machine. |
| **Config in environment (12-Factor)** | Secrets and machine-specific paths hard-coded into source. |

**Version control & trunk-based-lite.** `main` is the trunk and is always in a working state. You do
work on a **short-lived branch** (`feat/gene-search`, `fix/tabix-index`), open a pull request, get it
reviewed, merge within a day or two, and delete the branch. Short branches ≈ small, easy reviews.

**Pull requests & code review.** A PR is a proposed change plus a conversation. Our review standard
(from Google): **approve when the change improves the overall health of the codebase** — not when
it's flawless. Reviews spread knowledge and catch mistakes; they are not gatekeeping rituals. For a
beginner-friendly deep dive on the PR flow, branch protection, and CODEOWNERS, see
[pull-requests-and-branch-protection.md](pull-requests-and-branch-protection.md).

**Testing & TDD.** A test is code that checks other code, run automatically. **TDD** is the discipline
of writing the *test first* (it fails — "red"), then the code to pass it ("green"), then cleaning up
("refactor"). We use TDD for logic that fails *silently* — the classic example in genomics is
**coordinate math** (0-based vs 1-based, inclusive vs exclusive ends). A wrong coordinate doesn't
crash; it quietly returns the wrong locus. Our very first test targets exactly this.

**Continuous Integration.** Every PR triggers an automatic pipeline that installs dependencies,
lints, and runs the tests on a fresh machine. A red pipeline blocks the merge. Our CI additionally
proves the *real* runtime — it installs `bcftools`/`tabix` and runs a round-trip — so we don't
discover missing system tools halfway through Phase 1.

---

## 5. The agent-native layer — how we build *with* AI

This is where our process differs from a classic textbook, and it's a major reason this journey is
worth teaching. Full details live in [`agent-workflow.md`](../process/agent-workflow.md); the essence
here is the mental model.

**Mental model: a coding agent is an eager, fast, capable *junior engineer* with no memory of
yesterday.** It will do exactly what you ask, very quickly, including the wrong thing very quickly.
So the process *is the safety harness*. Everything in §4 — tests, CI, review — is what lets us hand
work to agents without fear.

**Loop engineering** is our core technique. It is a tight feedback loop:

```
  specify (ideally a failing test)
        │
        ▼
   agent generates a change
        │
        ▼
   verify automatically (tests + lint + CI)  ──fail──▶ feed the failure back ─┐
        │                                                                     │
       pass                                                                   │
        │                                                                     │
        ▼                                                                     │
   HUMAN reviews the final diff  ◀───────────────────────────────────────────┘
        │
        ▼
     merge
```

The quality of the loop is set by the quality of the **verifier**. A vague "make it work" loop
produces vague work; a "make this failing test pass" loop produces exactly the right thing. **The
human is never removed — they hold the merge gate.**

**When to use which agent tool** (rules of thumb, expanded in the agent-workflow doc):
- **A single agent / subagent** — one focused task ("write this function and its test").
- **A workflow (many agents)** — when you want breadth or independent verification: fan out to
  explore/research/review in parallel, then synthesize. (This plan itself was produced by a 6-agent
  research workflow plus an adversarial reviewer.)
- **A Skill** — a reusable, written-down playbook the agent follows ("open-a-PR-our-way").
- **An MCP server** — a connector to a live external system. Add sparingly, least-privilege.
- **git worktrees** — separate working copies so parallel agents don't collide (we adopt these in
  Phase 1, when parallel feature work actually creates collisions).

**The safety harness (non-negotiable):** never auto-merge agent code; the two engineers are required
reviewers (`CODEOWNERS`); tests are protected and a coverage-drop check blocks silently-gutted tests;
secret-scanning and file-size guards stop an agent from committing a token or a multi-gigabyte data
file; agent-authored commits are marked. If you remember one sentence: **agents write, humans merge.**

---

## 6. The repo *is* the course

We organize documentation with **Diátaxis**, which sorts docs into four kinds by what the reader
needs:

| Quadrant | Reader's need | Example here |
|---|---|---|
| **Tutorials** | "Teach me by doing" | `docs/tutorials/` — student labs |
| **How-to** | "Help me do a specific task" | "run locusview locally" |
| **Reference** | "Let me look up a fact" | the data schema, the API |
| **Explanation** | "Help me understand why" | *this document* |

Because we write these artifacts **in the moment** — the PRD when we plan, the ADR when we decide,
the retro when we finish — the paper trail of building locusview *is* the raw material of a graduate
course. The mapping from "lifecycle step" to "learning outcome" to "the artifact that demonstrates
it" lives in [`docs/course/README.md`](../course/README.md).

---

## Further reading (our syllabus, too)
- Michael Nygard, *Documenting Architecture Decisions* (2011) — the ADR pattern.
- *Software Engineering at Google* (Winters, Manshreck, Wright) & Google's Engineering Practices
  (code-review guide).
- *The Twelve-Factor App* — config, dependencies, and deployment hygiene.
- Trunk-Based Development (trunkbaseddevelopment.com).
- Forsgren, Humble, Kim, *Accelerate* — the evidence that small batches + automation win.
- Kent Beck, *Test-Driven Development by Example*.
- Diátaxis (diataxis.fr) — the documentation framework.
