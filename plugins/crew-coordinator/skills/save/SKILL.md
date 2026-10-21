---
name: save
description: 'Use when: "/save", "before compaction", "save state"; pre-compaction save, no handoff.'
---

# /save

Pre-compaction save without `/handoff`. The role stays held; after compaction a fresh chat runs `/restore <role>` (no path) and finds the role-state note and this capsule.

## 1. Compose
One capsule in HANDOFF-template order minus §0, Next action first, ids not content; the 1,500-token cap is enforced by `check_capsule_budget`.

## 2. Record
`harness_record agent=<your id> kind=capsule offload=true title="save: <role> <YYYY-MM-DD>" tags=["save","role:<role>"] body=<capsule>`. Keep only the returned id afterwards.

## 3. Point the role state at it
`harness_sync agent=<your id> state_note="Next: … | Open: … | Verified: … | Chat: save <capsule id> ~<ctx>k"` (any harness call with `state_note=` works). The role-state context record supersedes the last one.

## 4. Do not
- call `harness_handoff`
- write a capsule file
- release leases
- retire

## 5. Reply (two lines)
```
Saved: <capsule id>, state note <C-id>. Safe to compact.
After compaction: /restore <role>
```
The successor confirms (`confirmed=true`) if the holder shows live.

## 6. No harness tools
Say so. Use the handoff skill §2 or §3 instead.
