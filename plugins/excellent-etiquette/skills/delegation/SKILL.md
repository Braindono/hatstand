---
name: delegation
description: "Use when: planning who builds what: spec/worker split, model choice, subagents, waiting."
---

# delegation

- [global] P-36 Dispatch mechanical work (crawl, parse, lint, diff, export, bulk read) to cheaper ephemeral subagents retaining no context; cheapest capable model.
- [global] P-39 For complex tasks the lead writes a spec in specs/, an ephemeral worker executes it, the lead verifies; never trust self-report; lead chat only discusses and proposes (P-35 merged). (P-39, P-35)
- [global] P-40 If Haiku workers keep failing use Sonnet; multi-file packets default to Sonnet, Haiku only single-file mechanical steps with a proof line (refines P-39). Haiku 5.5 first; fall back to Sonnet 5.5 only after a failed proof line or spawn denial, and log each Haiku failure in the role's findings file with refs to the error log (rule 34).
- [global] P-42 No timed check-ins or polling loops; waiting must cost zero tokens.
