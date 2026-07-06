# Pull Requests, Branch Protection & CODEOWNERS

> **Diátaxis quadrant:** Explanation — read this to *understand* how a team changes shared code
> without breaking it. The few commands below are illustrative (just enough to see the shape);
> task-specific setup how-tos will live in [`docs/how-to/`](../how-to/). For our team's roles and
> cadence, see [`../process/ways-of-working.md`](../process/ways-of-working.md).

**Audience.** Written for someone new to team software development — a college student, or anyone who
has written code alone but never on a shared codebase. No prior git experience beyond "I can commit"
is assumed.

**Learning objectives.** After reading this you should be able to:
1. Explain *why* teams don't edit the official code directly, using the idea of a protected `main`.
2. Walk a change through the full **pull-request (PR) flow**: branch → commit → PR → CI → review → merge.
3. Explain what **branch protection** enforces and why rules beat good intentions.
4. Explain what a **CODEOWNERS** file does and why we made engineers owners of `tests/`.
5. Point to the real files in this repository that implement all three.

---

## 1. The problem: one shared, always-important copy

Picture your study group sharing **one Google Doc that _is_ your final, graded essay**. If everyone
types directly into it at once, three things go wrong:

- Someone **overwrites** another person's paragraph.
- Someone **pastes half-finished work** the night before the deadline, and now the whole essay looks
  broken.
- Something breaks and **nobody can tell who changed what, or when.**

Software has the same problem — but worse, because a single bad line can take down a running website.
So professional teams protect **the one official copy of the code** and route *every* change through a
small, safe ritual.

In git, that official copy is the **`main` branch**. The rule we live by:

> **Nobody edits `main` directly. Every change arrives through a reviewed, tested pull request.**

The three tools in this document are how that rule is made real:

| Tool | One-line job |
|---|---|
| **Pull-request (PR) flow** | The safe *path* every change travels (branch → PR → checks → review → merge). |
| **Branch protection** | The *lock* that makes that path the **only** way into `main`. |
| **CODEOWNERS** | The rule that the **right expert** must approve the parts they own. |

---

## 2. The pull-request (PR) flow — the ritual for making a change

A **branch** is a separate *line of work* — technically a lightweight named pointer to your own
commits, **not** a copy of all the files. It lives only on your machine until you *push* it; after
that, teammates can see it too. (Think of it as drafting in your own copy of the shared Doc before
proposing the edits back.) Because everyone works on their own branch, people can build in parallel;
when a branch merges, git either combines the changes automatically or flags a **merge conflict** for
a human to resolve. A **pull request** is you saying:

> *"Here are my proposed changes. Please review them, and if they're good, **pull** them into `main`."*

Here is the whole loop. The example is a real locusview task — issue **#3, "app skeleton"**:

```
 main  ●───────────────────────────────────────────●   ← official, always-working
        \                                          /
         \ (1) branch off                         / (5) merge back in, delete branch
          ●────●────●   feat/app-skeleton   ●────●
          (2)  (3)  (4)  commit → open PR → CI + human review happen here
```

1. **Branch off `main`.**
   ```bash
   git switch main && git pull          # start from the latest official version
   git switch -c feat/app-skeleton      # create + switch to your sandbox branch
   ```
2. **Do the work in small commits.** Small commits are easy to read and easy to undo.
3. **Open a PR.** Push the branch and open the pull request:
   ```bash
   git push -u origin feat/app-skeleton   # `origin` = the nickname for the shared GitHub copy
   gh pr create                           # fills in our PR template automatically
   ```
   The PR is a web page showing the exact **diff** (what changed, line by line) plus your description:
   *what / why / how tested* — that's what
   [`.github/pull_request_template.md`](../../.github/pull_request_template.md) prompts you for.
4. **Automated checks + a human review happen on the PR:**
   - **Continuous Integration (CI)** runs automatically — see
     [`.github/workflows/ci.yml`](../../.github/workflows/ci.yml): lint, type-check, tests + coverage,
     a genomics smoke test (a tiny end-to-end check that the `bgzip`/`tabix` genomics tools actually
     run), and a Docker build. A red ✗ means "not ready — don't merge."
   - A **teammate reviews the diff** and either approves or requests changes. (How to *do* that review
     well: [how-to-review-code.md](how-to-review-code.md).)
5. **Merge, then delete the branch.** Once CI is green *and* a human approves, you merge. Your changes
   are now part of `main`; the branch has done its job and is deleted.

### Why bother? Three concrete payoffs
- **A second set of eyes catches bugs cheaply** — before they reach everyone.
- **CI proves it works _before_ it's official.** Real example from this repo: our first push failed the
  Docker-build check (`OSError: License file does not exist`). On a PR, that ✗ blocks the merge — so
  `main` would *never* have gone broken. That is the whole point.
- **The PR page is a permanent record** of what changed and *why* — future-you (and this project's
  students) can read the reasoning behind every change.

---

## 3. Branch protection — the rule that *enforces* the ritual

Everything in §2 is just *etiquette* until you make it *mandatory*. **Branch protection** is a setting
on the `main` branch that puts a lock on it, with rules such as:

- 🚫 **No direct pushes** — you *must* go through a PR.
- ✅ **CI must be green** — the required checks must pass before the merge button is enabled.
- 👀 **At least one approving review** — from someone who isn't the author.
- 🔒 **No force-pushes or branch deletion** — a *force-push* rewrites history; disallowing it (and
  deletion) means commits can't be silently erased.

The analogy: it's the difference between *"please don't edit the final essay directly"* (a polite
request everyone ignores at 2 a.m.) and **the document is actually locked so you _can't_** (a rule the
computer enforces). Rules beat intentions, because intentions get tired and rushed.

> **One nuance about admins.** By *default*, these rules do **not** apply to repository admins — an
> admin can still direct-push, which is a deliberate escape hatch. They apply to admins too only if you
> also turn on **"Do not allow bypassing the above settings."** So "the only way into `main`" is true
> for everyone *except* admins, unless you opt into that stricter setting.

> **A subtle but important ordering point.** Turn protection on **after** CI has run at least once (so
> the rule can point at a check that actually exists) and **after** the initial *scaffolding* (the first
> setup commits, before the rules are on). And if you *do* enable "Do not allow bypassing," do it once
> the team has ≥1 non-admin reviewer with write access — otherwise a solo owner can lock themselves out
> of their own `main`. This is why, in this project, the first commits went straight to `main`
> (bootstrap), and protection was switched on only once the pipeline was green.

---

## 4. CODEOWNERS — *who* must review *which* files

On anything bigger than a toy project, "get one review" isn't enough — you want the *right* person to
review the *right* code. A [`CODEOWNERS`](../../CODEOWNERS) file is a simple map from **file paths →
the people responsible for them.** When a PR touches those paths, GitHub *automatically* requests a
review from those owners; and if branch protection requires code-owner review, the PR cannot merge
until an owner approves.

In plain English, our file says things like:

```
/src/     @owner        # application code must be reviewed by an engineer
/tests/   @owner        # so must the tests — and that line is the clever one
```

Back to the essay: it's the rule *"any edit to the statistics section must be signed off by the stats
major."* The person who knows that part best is guaranteed to look.

> **Why we made engineers owners of `tests/` — a guardrail specific to working with AI agents.** A
> coding agent can make a failing build "pass" by quietly **weakening a test** instead of fixing the
> underlying bug (e.g. changing `assert result == 42` to `assert result is not None`). Requiring an
> engineer to approve any change under `tests/` forces a human to look and ask *"wait — why did this
> test change?"* Combined with a coverage check and the "did this PR change tests, and why?" box in our
> PR template, it keeps our test suite honest. See
> [`../adr/0005-agent-driven-workflow.md`](../adr/0005-agent-driven-workflow.md).

**One requirement to remember:** a code owner must actually have **write access** to the repository.
Listing someone who can't push means the entry doesn't take effect (GitHub flags it as an error in the
CODEOWNERS view) — and if branch protection then *requires* code-owner review, no valid owner can
approve and every PR gets stuck. This is a real gotcha: a reviewer with only *read* access can leave
comments, but their approval does **not** count toward a required review. So the order is:
(1) add the person as a collaborator with write access → (2) list them in `CODEOWNERS` → (3) turn on
"require review from Code Owners."

---

## 5. How the three fit together

```
                 ┌───────────────────────── main (protected) ─────────────────────────┐
   you ──branch──▶  feat/... ──commit──▶ Pull Request ──▶ CI green? ──▶ owner approves? ──▶ merge
                 └──────────────────────────────────────────────────────────────────────┘
                     PR flow = the path        branch protection = the lock
                                               CODEOWNERS = who must approve
```

The three, in a line: the **PR flow** is the path, **branch protection** is the lock that makes it the
only way in (for non-admins), and **CODEOWNERS** decides who must sign off on what they own.

In one sentence: **to change the official code, you open a pull request, and it cannot merge until the
tests pass and the right person approves.** That single sentence is most of how professional teams keep
a shared codebase healthy — and it is how locusview works.

---

## 6. Red flags — stop and get a human
- A PR edits a **test** to turn a red build green. (Why did the expected behaviour change?)
- A diff touches **far more** than its issue described. (Scope creep — split it.)
- You **can't explain in one sentence what the change does.** (Then you can't review it — don't merge.)
- The change touches **secrets, data licensing, or who has access.** (Human decision, always.)

---

## Where this lives in the repo
- The path: this doc + [`../process/ways-of-working.md`](../process/ways-of-working.md) +
  [`../../CONTRIBUTING.md`](../../CONTRIBUTING.md).
- The template: [`../../.github/pull_request_template.md`](../../.github/pull_request_template.md).
- The checks: [`../../.github/workflows/ci.yml`](../../.github/workflows/ci.yml).
- The owners: [`../../CODEOWNERS`](../../CODEOWNERS).
- The reasoning: [`../adr/0005-agent-driven-workflow.md`](../adr/0005-agent-driven-workflow.md).

## Further reading
- Google Engineering Practices — *How to do a code review* & *The standard of code review*.
- GitHub Docs — *About protected branches* and *About code owners*.
- Trunk-Based Development (trunkbaseddevelopment.com) — why short-lived branches beat long ones.
