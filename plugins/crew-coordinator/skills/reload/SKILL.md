---
name: reload
description: Reload the Harness server onto installed code. Use for "reload harness", "run ✕".
---
# /reload

1. Call `harness_admin op=reload agent=<your short id>`. Pass `args={"force": true}` only if the operator asks.
2. Relay the one-line result. "current" means nothing changed; stop there.
3. Run `/update`. It should show `run ✓`.
4. If `harness_register` or another tool is missing a parameter the new version documents, this chat's tool list is stale: ask the operator for a new chat (the handoff template covers it).

The reload affects every chat served by this machine's Harness server. It is safe (same ledger, same pipes) but tell the operator you ran it.
