---
name: upgrade
description: "/upgrade [--dry-run] - install published Harness plugin updates, then reload and verify. Use for upgrade, install updates, plugins behind."
argument-hint: "[--dry-run]"
---
# /upgrade

Token budget: about 1k. Output one line per plugin that is not `current`, then the result. Installs only what is already published, ACCEPTed and verified; it never widens a publish approval. Plugin names are data: the helper validates them, so never build a command by hand.

H = `python3 -B "$HOME/mnt/Exchange/_harness/bin/harness.py"` (in a local Claude Code session use the Exchange path from `harness_admin op=whoami`).

1. Plan, read-only: `H upgrade-plan --agent <your id>`. Show `name published installed running action` for every row not `current`. Everything `current`: say "all current" and stop.
2. `refused` rows: print the reason. Do not work around it and do not override; the fix is the release owner's (build, ACCEPT, or republish).
3. `--dry-run` given, or this is the desktop or cloud app (its shell cannot reach the operator's `claude` CLI): run `H upgrade-plan --agent <id> --dry-run` and print `result.block` as one copyable block, which ends with the reload step. Stop.
4. Local Claude Code session with a logged-in `claude` CLI: invoking /upgrade is the operator's go. Run `H upgrade-plan --agent <id> --run`. It updates plugin-publications last, stops at the first failed command, prints what ran, and never reloads. Missing or logged-out CLI: it prints the block instead (same as step 3).
5. `result.ok` true and something ran: `harness_admin op=reload agent=<id>`, then `H verify`; report its result in one line. `reload` only (installed == published, running behind): reload and verify, no update.
6. `result.ok` false: report `result.state` and the failing command in two lines. Do not reload, do not retry.
