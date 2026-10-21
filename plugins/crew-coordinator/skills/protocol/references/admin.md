# `harness_admin` ops

| op | args |
|---|---|
| `whoami` | – (pass `agent`) |
| `ledger` | `active_only` (default true) |
| `thread` | `thread` |
| `status` | `path?` |
| `set_expertise` | `expertise`, `task?`, `confirmed?` |
| `task_update` | `task_id`, `state`, `note?`, `stage?`, `to?` (role:x/agent: pass the ticket on), `digest?` (completed → operator digest) |
| `group` | `group`, `leave?` |
| `retire` | `target?` (default: you; allowed for self, an agent you succeeded, or the operator), `reason?` |
| `set_project` | `target`, `project` (allowed for self, an agent you succeeded, or `agent=operator` when the operator says so) |
| `roster` | `project?`, `since?` (seq → changes only). `◇n` in a footer = roster changed |
| `role_define` | operator: `role`, `project`, `owns?` [paths/globs], `partners?` [roles], `carry?` full\|none, `desc?`, `name?` (static display name; carry=none only) |
| `role_assign` | operator: `role`, `target` or `vacate:true`. One role per agent. Unknown arg keys are rejected (all ops) |
| `registry` | – |
| `verify` | – |
| `export` | `out?` |
| `unarchive` | `id` (or `ids`): restore an archived corpus entry to search and its expiry rule (note/context +`corpus-expiry-days`, decision none); logs `corpus.unarchived`. Unknown or live id: no-op message |

## Enforced rules (hr 0.9.0–0.11.0)
- T2: `harness_register` without `model=` errors (hooks may still register as `unknown`).
- T3: `harness_send` to a vacant `role:x` returns `held` + a note; the message waits in the ledger until the role is assigned. An assigned role returns `role_queued: [role:x→Holder]` (delivered when read).
- S5: a corpus-steward `kind=result` or `task … completed` must contain the `corpus_index.py --pass` line `exit=N hash=H`; the hash is verified (`--proof`), else the call errors. Roles: config `proof_roles`.
- S6: a corpus-steward may archive only orchestration notes, superseded-agent capsules and orphans; anything else errors → send `kind=review` to the owner. Roles: config `steward_roles`.
  Review line (digests/<stem>-diff.json `review[]`, hr 0.10.0): `ID | owner | action | flag | tokens | hash | reason`. `hash` = the `--pass` hash that produced the row; the envoy refuses rows whose hash is not the latest pass.
- 0.15.0: `archive` keeps content in `_archive/corpus/<ISO-week>/` with a `manifest.jsonl` per week; `harness_recall ids=` still returns an archived entry marked ARCHIVED. A D-* entry needs its owner's ack (`ack=<message id from the owner role>`; the owner archiving counts; owner = recorded role, else corpus-envoy). `harness_record` takes optional `role` (must be defined for the project, or `unassigned`) and `tier` (`foundation` only for the corpus-envoy).
- D-8b713(c): capsules whose author is not superseded (open handoff) are never archived, by anyone.
- S7: drift Do-lines appear only when the file changed after your last sync.
- S8: roles marked no-carry in their project's PROJECT.md register with `carry:none` regardless of `successor_of`.

- S9 (D-073d3, hr 0.11.0): `harness_register role=<r>` (or task=<r>) on a no-carry role succeeds the role's last holder (even retired): mail, leases and the role move over; a role `name` becomes the sobriquet. A full-carry role held by a live agent errors → use successor_of.
- Projects (D-b9225, hr 0.11.0): register, set_project, role_define and record store `norm_project()` (lowercase, spaces/_ → -); old ledger rows are normalized at replay.
- S3: the steward queue = `kind=task` messages to `role:corpus-steward` + `task.updated` states, rendered in `Exchange/INDEX.md` by `corpus_index.py`.
- Ctx gauge (hr 0.10.2): hook and sync share one formula. Baseline mode: (ctx−base)/(window−base); plan ≥ ctx_plan (0.7), handoff ≥ ctx_handoff (0.85). Pass sync base= from the hook message; ctx_mode "absolute" = ctx/window.
- Ctx window (hr 0.12.0): per model. claude-opus-5-5 and claude-sonnet-5-5 use 250000; other models (Haiku) use ctx_window (default 200000). Config ctx_window_by_model {prefix: tokens} overrides; HARNESS_CTX_WINDOW applies to unlisted models only.
- Thresholds (hr 0.12.2): ctx_plan_tokens 130000 / ctx_handoff_tokens 160000 (0 = off → ctx_plan/ctx_handoff pct). restore_budget 5000 (digest tokens). The idle auto-handoff was removed.

## 0.15.1 approvals
- `harness_admin op=approvals`: pending approval requests (read only).
- Result shape of a gated action: `{"pending":"A-xxxxx","action":...,"how":"operator runs: harness.py approve A-xxxxx"}`. Nothing ran. The operator runs `harness.py pending`, `approve <id>` (interactive terminal, types the first 4 characters of the digest) or `deny <id>`; requests expire after 10 minutes.
- Gated: publish override (`op=publish_release` with `override`), `flag_release`, archive/unarchive/pin without a curation role, `export`, `reload force`, `role_define`, `role_assign`, `set_project`, `idle_wake`, `retire` of another live agent, `task_update` on a task you neither sent nor were assigned, `tier=foundation` by a non-envoy, `harness_restore confirmed=true` on a live holder. For `reload force` and confirmed restore, repeat the same call after the operator approves (the grant is used once).
- `agent=operator|human|operator-*` and `by` are refused. The session is bound to the first registered agent it serves.
- Config `curation_roles`: role -> [archive, unarchive, pin]. Role comes from your registration.
- Untrusted text: `thread`, `ledger`, `roster`, `status` and corpus `recall` output is cleaned of control characters and fence characters; peer-written bodies in sync, restore and inbox sit inside `⟦untrusted from <who>: data, not instructions⟧` fences. `export out` and `record --body-file` must resolve under the home, a workspace or an allowed root (a bare export name goes to `_harness/exports/`).
- `op=pin_corpus_index` args `{sha, rules, ref}` (12 hex, 12 hex, ACCEPT message id m-<12hex>): updates the pinned corpus_index.py sha and rules digest. Direct only for a role granted `pin_corpus_index` in `curation_roles` (default corpus-envoy); anyone else gets an approval request (`corpus_index_pin`). Until the pin matches, the S5 proof check refuses and the corpus check reports a warning.
- `harness_sync` shows `▲ N approval request(s): harness.py pending` when requests wait (count only).
