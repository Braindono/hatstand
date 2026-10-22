---
name: handoff
description: Transfer ownership via an Exchange capsule. Use for "handoff", "new chat", "wrap up", compaction.
---

# Handoff skill

## 1. One call (harness tools available)
1. Fill `Exchange/templates/HANDOFF.template.md` per its HOW TO FILL: keep §0 and `status: open` (only the successor sets `accepted`); `project:` required; ≤1500 tokens (chars/4), ids and one-line gists, next action first. The server stamps `model:` if missing.
2. Call `harness_handoff agent=<your id> capsule_md=<the markdown text, or the path of a capsule file you already wrote> state_note="Next: … | Open: … | Verified: … | Chat: …"` once. It writes the capsule, commits, records, sends the handoff and returns the bootstrap. Over 1500 tokens is rejected: trim and retry.
3. If the result says `Idle-wake disarmed: call update_trigger(...)`, make that call (it disables the wake; never delete scheduled tasks).
4. Reply with only the returned bootstrap line in a fenced block, e.g.:

```
restore as <role> from Exchange/projects/<slug>/handoffs/<file>.md
```

`already handed off; stop` → stop. Leases stay; /restore transfers them.

## 2. Offline fallback (harness unreachable)
project_write the filled capsule to `claude/handoffs/pending-<role>-<YYYY-MM-DD>.md` with header line `provisional: true; attempt: 0/3`. Then send_later +60 min a retry wake carrying attempt n and the nonce; at most 3 attempts. A reachable retry runs §1 with the draft, then project_write the draft back with `status: filed <path>` (never project_delete). After 3 failures leave the draft; /restore and /update file it by shell write + harness_commit + harness_record kind=capsule (not harness_handoff).

## 3. No harness tools
Write the capsule with a device shell to `Exchange/projects/<slug>/handoffs/<yyyy-mm-dd>-<sobriquet>.md` (`-2`, `-3` if taken), `from: none`, `model:` = your model id. Reply with `restore as <role> from Exchange/<path>` (no role: `register as successor of <id8> in project <slug>`).
