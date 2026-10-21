---
name: update
description: Full sync after big change or resume. Use for "/update", "what changed".
---

# /update

For inbox and Do-lines only, use /refresh (cheaper, D-b9225 C4).

1. No short id in context: `harness_register` first.
2. Call `harness_sync agent=<id>`. Pass `ctx=<your token estimate>` (and `base=<n>` if the ctx hook message gave one) if you can, and `full=true` if the operator said "full".
3. If the attached Project has `claude/handoffs/pending-*` drafts (offline idle-wake), file each `claude/handoffs/pending-*` draft: write it with a device shell to `Exchange/projects/<slug>/handoffs/<date>-<orig-sobriquet>-offline.md`, then harness_commit + harness_record kind=capsule (never harness_handoff: it marks the successor handed off); then project_write the draft back with `status: filed <path>` (do not project_delete: archive, never delete).
4. Reply with the result's first line only. Then do each `Do:` line in order.
5. Unknown symbol: read `references/legend.md`.
