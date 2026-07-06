# Course crosswalk — *Engineering Scientific Software with AI Agents*
### (a graduate module taught **from** the real locusview build)

> **Diátaxis quadrant:** Explanation (meta) — this is the *teaching layer*. It maps the software
> engineering we actually do while building locusview to **intended learning outcomes (ILOs)** and
> the concrete repo artifacts that demonstrate them. Companion file:
> [`alignment_matrix.md`](alignment_matrix.md).
>
> **Status:** working outline — a *crosswalk + module map*, not yet a full NUS syllabus. No CMS
> course code yet. When Prof. Liu decides to formalize it, run the `designing-courses` skill in full
> (Stages A→E) to produce the syllabus, lectures, practicals, and assessment. ILOs below follow SOLO
> taxonomy and the ≤7-ILO rule.

---

## Why this course is different

Most software-engineering courses teach with toy projects; most bioinformatics courses teach analysis
but not *engineering*. This module's differentiator: **students learn the full software-engineering
lifecycle — and modern AI-agent-native development — by building a real, public bioinformatics data
portal (locusview) that outlives the semester.** The paper trail of the build (PRDs, ADRs, PRs,
retrospectives) *is* the course material. Every claim in a lecture points to a real commit.

**Target student.** Graduate students in bioinformatics / data science / pharmacy informatics who can
write analysis scripts but have never worked on a shared, long-lived codebase or used coding agents
responsibly. Pairs naturally with BMI5110 (which supplies the QTL domain background — see its
Lecture 2 on QTL and Week 6 on eQTL).

**Format (matches Prof. Liu's project-based grad rhythm).** 13 teaching weeks, one 3-hour combined
session/week: *hook (5 min) → concept block + activity (25+5) × 3 → break (10) → build-along / clinic
(60–90) → synthesis (10) → bridge (5)*. Lab time is folded into the session; students build locusview
in teams across the semester.

---

## Intended Learning Outcomes (ILOs)

By the end of the module, a student can:

1. **Explain** the software-engineering lifecycle and its core artifacts (Vision, PRD, ADR, spec,
   plan, retrospective), *justifying why each reduces a specific risk* when software is built by a
   team over time. *(SOLO: Relational)*
2. **Apply** a trunk-based Git workflow — feature branches, pull requests, code review, and continuous
   integration — *to contribute a change safely to a shared codebase.* *(Relational)*
3. **Design** a thin vertical slice (MVP) for a data-intensive application, *decomposing an
   open-ended vision into a scoped, testable increment.* *(Extended Abstract)*
4. **Construct** an automated verification harness (unit tests, TDD on error-prone logic, CI checks)
   *sufficient to make AI-agent-assisted development safe.* *(Relational→Extended Abstract)*
5. **Evaluate** the output of coding agents through code review, *identifying failure modes (silently
   weakened tests, scope creep, secret/data leakage) and applying appropriate guardrails.* *(Extended
   Abstract)*
6. **Create** and document a working feature of a public QTL portal (search / browse / download),
   *producing reference and how-to documentation a peer can follow to reproduce it.* *(Extended
   Abstract)*

*Four of six ILOs sit at Relational or above, as expected for a graduate module.*

---

## The crosswalk: lifecycle step → ILO → repo artifact → assessment

Each row is *constructively aligned*: the outcome we want (ILO), the real thing students do/read that
teaches it (artifact), and where we check it (assessment touchpoint).

| Lifecycle step (see the [lifecycle doc](../explanation/software-engineering-lifecycle.md)) | Primary ILO | Demonstrated by this repo artifact | Assessed via |
|---|---|---|---|
| Understand the problem; write the **Vision** | 1, 3 | `docs/product/vision.md` | Journal, Final defense |
| Spec the WHAT: the **PRD** | 1, 3 | `docs/product/prd.md` (annotated template) | Milestone 1, Final defense |
| Record a decision: **ADR** | 1 | `docs/adr/0001–0005` (Nygard format) | Portfolio (ADR authored) |
| Plan the HOW; the **roadmap** & implementation plans | 3 | `docs/product/roadmap.md`; per-task plans | Milestone demos |
| **Version control** & trunk-based-lite branching | 2 | `CONTRIBUTING.md`; the git history itself | Portfolio (PRs) |
| **Pull requests** & code review | 2, 5 | [PR & branch-protection explainer](../explanation/pull-requests-and-branch-protection.md); [how to review code](../explanation/how-to-review-code.md); PR template; `CODEOWNERS`; review threads | Portfolio, Peer review |
| **Testing & TDD** on error-prone logic | 4 | `tests/` incl. the genomic coordinate-transform test | Milestone 1 (tests pass) |
| **Continuous Integration** | 4 | `.github/workflows/ci.yml` (lint→test→genomics smoke→coverage) | Milestone demos (green CI) |
| **Loop engineering** with agents | 5 | `docs/process/agent-workflow.md`; team Skills | Journal, "Lecture 1" debrief |
| The **safety harness** (guardrails) | 5 | `CODEOWNERS`, `gitleaks`, coverage gate, push protection | Portfolio, Final defense |
| **Build** the thin vertical slice (MVP) | 3, 6 | `src/locusview/…`; Phase-1 feature PRs | Milestone 2, Final build |
| **Documentation-as-teaching** (Diátaxis) | 6 | the `docs/` tree; how-to + reference pages authored | Milestone 2 (docs a peer can follow) |
| **Retrospective** / reflection | 1 | `docs/process/retros/` | Reflective journal |

---

## Module map (13 weeks, tracking the build phases)

| Weeks | Module | Build phase | Focus | ILOs advanced |
|---|---|---|---|---|
| 1–2 | **M0 · Foundations & Process** | Phase 0 | Lifecycle & artifacts; git + PR + CI basics; Vision + PRD; ADRs; the repo as a system | 1, 2, 3 |
| 3–6 | **M1 · The Thin Vertical Slice** | Phase 1 | Ingest one eQTL source → store/index (Parquet/DuckDB/tabix) → search by gene → page → download; TDD on coordinate logic | 3, 4, 6 |
| 7–9 | **M2 · Agentic Development & Safety** | cross-cutting | Loop engineering; reviewing agent output; the guardrail suite; when agents go wrong (real war stories) | 4, 5 |
| 10–12 | **M3 · Breadth, Data Standards & Viz** | Phase 2–3 | Adding sources; harmonization pitfalls (build/effect-allele); regional plots; scaling behind a stable interface | 3, 5, 6 |
| 13 | **M4 · Demo & Retrospective** | — | Team demos; individual feature defense; written retrospective | 1, 3, 6 |

> Agentic development (M2 themes) is *practised every week* from Week 1; M2 is the dedicated deep-dive,
> not its first appearance. This is why ILOs 4 and 5 also light up early in the alignment matrix.

---

## Assessment sketch (project-based; formalize later)

Mirrors Prof. Liu's BMI5110 mix (individual write-up + group work + reflection + defense):

| Component | Weight | ILOs | Note |
|---|---|---|---|
| **Contribution portfolio** (merged PRs + ≥1 authored ADR, with review threads) | 30% | 2, 5, 6 | Individual; evidence of real, reviewed contribution |
| **Team milestone demos** (working software at end of M1 and M3) | 30% | 3, 4, 6 | Group; green CI is a gate |
| **Reflective engineering journal** (weekly, incl. retrospective) | 20% | 1, 5 | Individual; where the "why" is examined |
| **Final feature defense** (design + build + viva of a new slice) | 20% | 3, 5, 6 | Individual; the integrative task |

*Rubrics not yet written.* When formalizing, reuse Prof. Liu's existing presentation and write-up
rubrics in `~/teaching/BMI5110/` rather than inventing new ones.

---

## What's deliberately *not* here yet
A full NUS syllabus (course info, policies, workload budget, weekly readings), lecture outlines,
slide decks, and graded rubrics. Those come from a full `designing-courses` run once the concept is
approved. This file is the **skeleton that keeps the build and the course aligned as we go** — update
it whenever a new artifact lands, so the teaching layer never drifts from the code.
