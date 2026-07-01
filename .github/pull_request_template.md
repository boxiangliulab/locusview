<!-- Keep PRs small enough to review in under ~10 minutes. -->

## What
<!-- One or two sentences: what does this PR change? -->

## Why
<!-- The problem/issue this addresses. Link it: Closes #123 -->

## How it was tested
<!-- Commands run, new tests added, manual checks. CI must be green. -->

## Output / evidence
<!-- Paste relevant test output, CLI output, or screenshots. -->

## Checklist
- [ ] CI is green (lint, types, tests + coverage gate, genomics smoke, docker build).
- [ ] **Did this PR change any test? If yes, explain WHY below** — changing a test to make a
      red build green (by weakening a check) is not allowed.
- [ ] No secrets or large data files committed (the hooks should have caught these).
- [ ] An ADR was added under `docs/adr/` if a hard-to-reverse decision was made.
- [ ] If an agent authored changes: marked with `Co-Authored-By` and reviewed by a human.

### If you changed tests, why?
<!-- Explain here. "Added a test for the new behaviour" is good. "Relaxed the assertion so it
     passes" needs a very good reason. -->
