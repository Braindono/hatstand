---
name: prune
description: Review corpus health flags, pin/archive, verify. Use for "/prune [project]", "prune corpus".
argument-hint: "[project]"
---

# /prune [project]

D-8b713 + D-d01a5. The agent running /prune is "the lead": apply the rules yourself; call no other role. CI = `$HARNESS_HOME/projects/orchestration/scripts/corpus_index.py` (device_bash; `HARNESS_HOME` else `$HOME/mnt/Exchange`).

1. Before: `python3 CI --pass --by "<sobriquet>" --trigger prune`. Keep its `exit=N hash=H` line.
2. `harness_admin op=health args={bundle:true, project}` writes `projects/<project>/review/<date>-flagged-bundle.md`.
3. Draft: one ephemeral subagent (`model: haiku`) reads only the bundle and returns `| id | flag | tok | PIN/ARCHIVE/KEEP | conf | reason ≤12 words |` plus one summary line.
4. Correct the draft against fixed rules (don't trust its action column):
   - PIN standing rules: layout, backend, naming, roles, procedures, approved roadmaps.
   - ARCHIVE superseded handoff capsules, completed one-off notes, decisions superseded by later facts.
   - KEEP capsules of open handoffs (the harness refuses them anyway), and whenever unsure.
5. Who decides:
   - Operator ran /prune: one `AskUserQuestion` (1/1), recommended option first, ids grouped PIN/ARCHIVE/KEEP, token estimate. The answer is the owner's approval (D-f1cd4).
   - Unattended (nightly, size trigger): never ask. Archive only within the S6 tier (orchestration notes, superseded capsules, orphans); send the rest to each owner as `harness_send kind=review`.
6. Apply: `harness_admin op=archive|pin args={ids, reason, drafter_model, lead_model}`. Reason: leave empty only for superseded capsules and completed notes (auto-filled); decisions and pins need a `"quoted rule line"` for each entry (a bare `none …` is refused since 0.14.6).
7. Verify: `python3 CI --pass --by "<sobriquet>" --trigger prune`. Report its line (exit, hash, tokens saved, archive/pin events) and `--check` counts before → after. That digest feeds the T4 trend.

Size trigger (D-d01a5): a project is ▲ when its flagged tokens ≥ max(500, 20% of its live tokens); /health shows it.
