# Pending drafts (restore step 1)

Check for pending drafts: look for `claude/handoffs/pending-*` in the attached Project and file each `claude/handoffs/pending-*` draft: write it with a device shell to `Exchange/projects/<slug>/handoffs/<date>-<orig-sobriquet>-offline.md`, then harness_commit + harness_record kind=capsule (never harness_handoff: it marks the successor handed off); then project_write the draft back with `status: filed <path>` (do not project_delete: archive, never delete).
   Restore closes stale open capsules (E2); don't edit capsule status by hand.
