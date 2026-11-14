---
name: delegation
description: "Use when: planning who builds what: spec/worker split, model choice, subagents, waiting. General rules: CORE.md."
---

# delegation

- [global] P-112 Build only what the task needs: no extra features or unrequested refactors, and never cut validation, error handling, security or accessibility checks, or the tests the task names. Finish with one review pass of your own diff against the task; it does not replace the critic's review.
- [global] P-114 While helpers run, do other useful work; do not sit idle past 5 minutes (the prompt cache expires). If nothing is left, end the turn and let the helper's notice wake you; polling is barred (CORE.md).
- [global] P-115 Model tiers for helper tasks (a static table; vendor router savings are unverified). Haiku: crawl, parse, lint, diff, export, bulk read, scheduled tasks. Sonnet: packets over 2 files or spec-driven code, edits needing judgment, or a Haiku task after a failed proof line. Opus or Fable only where a role file or his words say so, or for a major redesign (CORE.md). Unless the operator set another model; any steward model change passes the evals first.
- [global] P-116 Before writing code, climb the smallest-change ladder; on a bug fix find all callers first; when reviewing, add a lean pass and the cost of skipping each finding. Details: references/smallest-change.md.
- [global] Haiku first for mechanical work (CORE.md); for a packet over 2 files, split it or give it to Sonnet; log each Haiku failure in the role's findings file with refs to the error log.
