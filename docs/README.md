# Documentation

We organize documentation with **[Diátaxis](https://diataxis.fr)** — a framework that sorts docs by
what the reader needs *right now*. Knowing which quadrant you're writing (or reading) keeps docs
useful instead of a pile of half-overlapping pages.

| Quadrant | Reader need | Voice | Folder |
|---|---|---|---|
| **Tutorials** | "Teach me by doing" (learning-oriented) | encouraging, step-by-step, guaranteed to work | [`tutorials/`](tutorials/) |
| **How-to guides** | "Help me do a specific task" (task-oriented) | terse, imperative, assumes some knowledge | [`how-to/`](how-to/) |
| **Reference** | "Let me look up a fact" (information-oriented) | precise, exhaustive, dry | [`reference/`](reference/) |
| **Explanation** | "Help me understand why" (understanding-oriented) | discursive, gives context and trade-offs | [`explanation/`](explanation/) |

**The one rule:** don't mix quadrants in a single page. A tutorial that stops to explain trade-offs
loses the beginner; a reference page with a pep talk is useless for lookup. Link across quadrants
instead.

### Project-specific folders (not Diátaxis quadrants, but docs-as-code)
- [`product/`](product/) — Vision, PRD, roadmap (the *what* and *why*).
- [`process/`](process/) — ways of working, agent workflow, retrospectives (*how we operate*).
- [`adr/`](adr/) — Architecture Decision Records (*why we chose what we chose*).
- [`course/`](course/) — the teaching layer that maps the build to learning outcomes.

> **Caution (a lesson we wrote into the plan):** Diátaxis is a *sorting scheme*, not a mandate to
> write four pages for every feature. Start with the one quadrant a change actually needs (usually a
> how-to, plus an ADR if a real decision was made) and grow the others as things stabilize.
