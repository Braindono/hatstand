---
name: refresh
description: Light sync, inbox and Do-lines only. Use for "/refresh", "check mail", routine checks.
---

# /refresh

Cheap check between tasks (D-b9225 C4). For plugin health, config or drift use /update.
Run harness_inbox at the start AND at the end of every reply.

1. No short id in context: `harness_register` first.
2. Call `harness_sync agent=<id> do_only=true`. Pass `ctx=<your token estimate>` (and `base=<n>` if the ctx hook message gave one) if you can.
3. Reply with the first line only. Run `harness_inbox` even when sync shows no Do-line; do any other `Do:` lines in order. Answer any mail in the same reply (D-9cc1f). End the reply with a final `harness_inbox`.
4. A `(+N changed …)` line means /update has details; run it only if a Do-line or the operator asks.
