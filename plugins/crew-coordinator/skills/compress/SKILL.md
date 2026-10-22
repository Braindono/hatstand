---
name: compress
description: "Use when: /compress [project]; shrink a corpus safely, archive never delete."
---

# /compress [project] [--stage …] [--apply]

CLI: `python3 <plugin>/scripts/harness.py compress <action> --project <p> --agent <id> [--run c-…] [--file …]`. Default `start` = dry run: inventory, chunk plan, worker spec, report. Nothing is changed.

Flow (each stage is a separate action; stop after each):
1. `start`. Before propose, the project lead and envoy write `projects/<p>/restore-questions.md` (`## Q1: …`, `cites:`, `expect:`). The worker never writes or edits it; the run pins its sha.
2. `snapshot` (required before apply).
3. Propose: run cheap ephemeral workers per chunk from `WORKER-SPEC.md`, then `propose --file proposal-*.json` (quotes must be verbatim).
4. `review --file decisions.json` by the project lead and by the envoy (accept / reject / edit).
5. `apply` (envoy only; pins first, then moves files to `_archive/compressed/<run>/`; never deletes).
6. `verify --file answers.json` by a FRESH non-gated agent with no snapshot access. Bar: all rule-bearing answers correct, 0 uncited. Fail → `restore` is offered.

Always dry-run first; a changed script, corpus_index pin or pin set forces a new dry run. `lint` (steward) checks the questions file and its cites; the steward never runs restore tests. `tune` only writes a proposal; rules change through the S5 gate.
Scheduled run: `start --scheduled` files a report to envoy.
