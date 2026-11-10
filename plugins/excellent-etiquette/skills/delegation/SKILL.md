---
name: delegation
description: "Use when: planning who builds what: spec/worker split, model choice, subagents, waiting."
---

# delegation

- [global] P-36 Dispatch mechanical work (crawl, parse, lint, diff, export, bulk read) to cheaper ephemeral subagents retaining no context; cheapest capable model.
- [global] P-39 For complex tasks the lead writes a spec in specs/, an ephemeral worker executes it, the lead verifies; never trust self-report; lead chat only discusses and proposes (P-35 merged). (P-39, P-35)
- [global] P-40 If Haiku workers keep failing use Sonnet; multi-file packets default to Sonnet, Haiku only single-file mechanical steps with a proof line (refines P-39). Haiku 5.5 first; fall back to Sonnet 5.5 only after a failed proof line or spawn denial, and log each Haiku failure in the role's findings file with refs to the error log (rule 34).
- [global] P-42 No timed check-ins or polling loops; waiting must cost zero tokens.
- [global] P-112 Build only what the task needs: no extra features or unrequested refactors, and never cut validation, error handling, security or accessibility checks, or the tests the task names. Finish with one review pass of your own diff against the task; it does not replace the critic's review.
- [global] P-114 While helpers run, do other useful work; do not sit idle past 5 minutes (the prompt cache expires). If nothing is left, end the turn and let the helper's notice wake you; P-42 still bars polling.
- [global] P-115 Model tiers for helper tasks (a static table; vendor router savings are unverified). Haiku: crawl, parse, lint, diff, export, bulk read, scheduled tasks. Sonnet: multi-file or spec-driven code, edits needing judgment, or a Haiku task after a failed proof line (P-40). Opus: planning, review, adversarial tests, final decisions, anything the operator reads. Unless the operator set another model; any steward model change passes the evals first (D-2a291).
- [global] P-116 Before writing code, climb the smallest-change ladder; on a bug fix find all callers first; when reviewing, add a lean pass and the cost of skipping each finding. Details: references/smallest-change.md.
