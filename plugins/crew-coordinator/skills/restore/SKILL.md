---
name: restore
description: Take over a role in a fresh chat without a handoff. Use for "/restore [role]", "restore as".
---

# /restore [role] [-v|verbose] [from <path>]

Accept "restore as <role> from <path>"; pass capsule=<path> to harness_restore.

1. Pending drafts: if the attached Project has `claude/handoffs/pending-*`, file them per `references/pending-drafts.md`.
2. No role given: `harness_admin op=roster` for the attached project, then AskUserQuestion listing that project's roles (max 4 options + Other). Order: role with an open capsule or no live holder first, labelled "(Recommended)"; number n/N; add a confidence tag. Role given: skip the picker.
3. Call `harness_restore role=<role> model=<your exact model id> capsule=<path>` if a path was given. If the holder is live, ask the operator once; on yes, repeat with `confirmed=true`. Restore closes stale open capsules (E2); don't edit capsule status by hand.
4. MCP register: show the banner. Hook sessions: the app shows it; don't repeat it. Pass its short id as `agent` from now on. Default: `harness_inbox` at start and end of every reply.
5. Verbose (-v/verbose; default off, ~1k tokens): before the state lines print a "Restore reads" table: file/capsule/pref path | portion read (<=2 quoted lines: capsule section 3 State and 5 Next, state note, prefs rule ids, decision ids).
6. Reply with 3 state lines, the first next action, and any questions from the digest. Then continue through the capsule's Next list in order, doing each item that needs no operator decision; stop only at a decision gate or when the list is empty. Answer any waiting mail in this same reply, no approval (P-89, D-9cc1f).
7. Open linked files only when a step needs them. When the hook says "State changed", add `state_note=` to your next harness call.
