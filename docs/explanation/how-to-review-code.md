# How to Review Code

> **Diátaxis quadrant:** Explanation — read this to *understand* how to review a teammate's pull
> request well. Prerequisite context: the [PR flow, branch protection & CODEOWNERS
> explainer](pull-requests-and-branch-protection.md). For our review *standard* in one line, see
> [`../process/ways-of-working.md`](../process/ways-of-working.md).

**Audience.** Someone doing their first code reviews — a college student, or a scientist new to
team software. No assumptions beyond "I can read the code in this repo."

**Learning objectives.** After reading this you should be able to:
1. State, in one sentence, what a code review is *for*.
2. Explain why you should **not** review for style/formatting/types.
3. Work a pull request through a prioritized checklist (Purpose → Correctness → Tests → Clarity).
4. Write review comments with the right **severity** and tone.
5. Choose between **Approve / Comment / Request changes**, and leave the review (GitHub UI or `gh`).

---

## 1. The one-sentence job

> **A code review answers one question: "Will merging this change make the codebase better, and is
> it correct?"** If yes → approve.

It is a *conversation about a proposed change*, not an exam you grade. The professional standard
(from Google's engineering practices): **approve when the change improves the overall health of the
codebase — not when it is flawless.** Perfect is the enemy of merged.

## 2. What review is *not* — let the machines do their job

Every PR in this repo runs **CI**: `ruff` (style + formatting), `mypy` (types), `pytest` (tests +
coverage), a genomics smoke test, and a Docker build. If CI is green, the machines have already
handled indentation, import order, and missing type hints.

So **do not** spend your review on those. Human attention is scarce; spend it on what a linter
*cannot* judge — correctness, design, clarity, and intent. A review that only says "add a space
here" is a wasted review, and it trains the author to tune you out.

> This is *why* we set CI up first: it frees the reviewer to think about the 20% that matters instead
> of the 80% a tool handles.

## 3. What to actually look at — a prioritized checklist

Read the **PR description and the linked issue first** (what is this trying to do?), then go through
the diff asking, roughly in priority order:

1. **Purpose** — does it do what the issue/PRD asked, and *only* that? (Scope creep is a real finding.)
2. **Correctness** — will it actually work? What about the empty / missing / error case? **What does
   CI *not* exercise?** (This is where the best findings live — see §5.)
3. **Tests** — is the new behaviour tested? Do the tests assert *real* things, or were they weakened
   to make the build pass? (Changing `assert x == 42` to `assert x is not None` is a red flag.)
4. **Design & simplicity** — is this the simplest approach that works? Does it match existing patterns
   in the repo?
5. **Readability** — could a newcomer understand it in six months?
6. **Security / data** — secrets, licensing, untrusted input? (Central to Phase-5 uploads; minor for
   internal code.)

A memory hook: **"Purpose, Correctness, Tests, Clarity."** If those four are solid, it is probably an
approve.

## 4. How to write a comment — the human skill

Label each comment's **severity** so the author knows what blocks the merge and what doesn't:

| Prefix | Meaning |
|---|---|
| **`blocking:`** | Must be fixed before merge (a real bug, a missing/weakened test, a security issue). |
| **`nit:`** | Minor / optional (a name, a small style point the linter doesn't catch). Author may take it or leave it. |
| **`question:`** | You're genuinely unsure — *ask*, don't assume. Often your most valuable comment. |
| **`praise:`** | Call out good things. Not fluff — it teaches the author what to keep doing. |

Two rules of tone:
- **Review the code, not the person.** "This function does X…", never "you always…".
- **Prefer questions to commands.** "What happens if the list is empty?" invites the author to think;
  "add a guard clause" just dictates (and might be wrong).

## 5. A worked example — the value is in the gap CI can't see

When the app-skeleton PR (issue #3) was reviewed, CI was fully green and coverage was 100%. Yet the
most valuable comment was a **`question:`**

> *"The app loads its HTML template from a path next to the code. Our CI `docker-build` job **builds**
> the image but never **runs** it — so it wouldn't catch a missing template at runtime. Are we sure
> the `.html` file ships inside the built package? Worth a quick check so `/` doesn't 500 in the
> container."*

Notice what happened: **green CI meant "the checks we wrote passed," not "the code is correct."** A
human reviewer reasoned about the space *between* the checks — exactly the thing automation can't do.
That single question was worth more than a dozen cosmetic notes.

The lesson: **a clean, well-tested PR earns few comments and an approve.** You do not invent problems
to look thorough. Hunt instead for what the tests *don't* cover.

## 6. The verdict — end with one of three

- **Approve** — good to merge. Leaving a few `nit:`s is fine; the author decides on those.
- **Comment** — feedback, but neither a blocking objection nor an explicit yes (e.g. you have one
  `question:` you'd like answered first).
- **Request changes** — something *must* change before merge. Use it for `blocking:` findings.

## 7. How to actually leave the review

**GitHub (web UI):** open the PR → **Files changed** tab → hover a line, click the blue **+**, write
the comment → **Start a review** (this *batches* your comments instead of emailing one per line) →
repeat → **Review changes** (top-right) → pick **Comment / Approve / Request changes** → **Submit**.

**Terminal (`gh` CLI):**
```bash
gh pr view 14            # read the description + conversation
gh pr diff 14            # read the diff
gh pr review 14 --comment          -b "One question inline; otherwise looks great."
gh pr review 14 --approve          -b "LGTM — template ships correctly, tests are solid."
gh pr review 14 --request-changes  -b "Please confirm the template is packaged before merge."
```

**One catch you'll hit immediately:** you **cannot approve your own PR.** GitHub lets you *comment* on
your own PR but an *approval* must come from another code owner. That is branch protection working as
intended (see the [PR/branch-protection explainer](pull-requests-and-branch-protection.md)).

## 8. Practice
- Leave a **Comment** review on an open PR with one or two observations of your own.
- Do a full **Approve/Request-changes** review of a teammate's PR — that is how changes actually reach
  `main` here.

## Further reading
- Google Engineering Practices — *The Code Reviewer's Guide* and *The Standard of Code Review*.
- [The PR flow, branch protection & CODEOWNERS](pull-requests-and-branch-protection.md) (this repo).
