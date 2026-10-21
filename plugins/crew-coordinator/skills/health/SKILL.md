---
name: health
description: Read-only corpus report (token weight, stale, orphans). Use for "/health", "corpus health".
---

# /health (read-only)

1. Call `harness_admin op=health agent=<id>`; add `args.project` or `args.agent` if the operator named one.
2. Reply with the result verbatim (a code block). Add nothing unless asked.
3. Don't archive or pin from here. A `▲` (overall, or a project in `projects ▲`) means run `/prune [project]`.
4. Visual: `harness.py serve` → http://127.0.0.1:7717/health.

Flags: `old-decision` = live decision, author ≥N handoff generations back, cited nowhere (no entry, no latest handoff). `orphan` = capsule/note from a handed-off agent that nothing cites. Project ▲ (D-d01a5): flagged tokens ≥ max(500, 20% of project live). Config (`_harness/config.json`): `health_generations` 3, `health_min_tokens` 1500, `health_ratio` 0.2, `prune_min_tokens` 500, `prune_ratio` 0.2, `project_aliases` {}.
