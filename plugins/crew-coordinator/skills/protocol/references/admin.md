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
- S5: a steward `kind=result` or `task … completed` must contain the `corpus_index.py --pass` line `exit=N hash=H`; the hash is verified (`--proof`), else the call errors. Roles: config `proof_roles`.
- S6: a steward may archive only orchestration notes, superseded-agent capsules and orphans; anything else errors → send `kind=review` to the owner. Roles: config `steward_roles`.
  Review line (digests/<stem>-diff.json `review[]`, hr 0.10.0): `ID | owner | action | flag | tokens | hash | reason`. `hash` = the `--pass` hash that produced the row; the envoy refuses rows whose hash is not the latest pass.
- 0.15.0: `archive` keeps content in `_archive/corpus/<ISO-week>/` with a `manifest.jsonl` per week; `harness_recall ids=` still returns an archived entry marked ARCHIVED. A D-* entry needs its owner's ack (`ack=<message id from the owner role>`; the owner archiving counts; owner = recorded role, else envoy). `harness_record` takes optional `role` (must be defined for the project, or `unassigned`) and `tier` (`foundation` only for the envoy).
- D-8b713(c): capsules whose author is not superseded (open handoff) are never archived, by anyone.
- S7: drift Do-lines appear only when the file changed after your last sync.
- S8: roles marked no-carry in their project's PROJECT.md register with `carry:none` regardless of `successor_of`.

- S9 (D-073d3, hr 0.11.0): `harness_register role=<r>` (or task=<r>) on a no-carry role succeeds the role's last holder (even retired): mail, leases and the role move over; a role `name` becomes the sobriquet. A full-carry role held by a live agent errors → use successor_of.
- Projects (D-b9225, hr 0.11.0): register, set_project, role_define and record store `norm_project()` (lowercase, spaces/_ → -); old ledger rows are normalized at replay.
- S3: the steward queue = `kind=task` messages to `role:steward` + `task.updated` states, rendered in `Exchange/INDEX.md` by `corpus_index.py`.
- Ctx gauge: hook and sync share one formula. Default absolute mode: ctx/window, plan share 0.60, handoff share 0.80 (config ctx_plan, ctx_handoff). Baseline mode is optional (base= from the hook message).
- Ctx window (0.17.0, R-059): by role only, never by model or surface. *-coder, envoy, curator 1M (config ctx_role_windows); every other role ctx_window (default 500000); Haiku silent. ctx_table and ctx_window_by_model are ignored.
- Thresholds: ctx_plan_tokens / ctx_handoff_tokens (>0) override the shares; default off. restore_budget (digest tokens) as in config. The only idle handoff left is idle-wake: opt-in per project (config idle_wake_projects, /idle-wake).

## 0.15.1 approvals
- `harness_admin op=approvals`: pending approval requests (read only).
- Result shape of a gated action: `{"pending":"A-xxxxx","action":...,"how":"python3 /abs/path/harness.py approve A-xxxxx"}`: one runnable line built from the real harness.py path. Nothing ran. To hand the operator this command: one fenced block, one line, join steps with `&&`, no placeholders. The operator runs `harness.py pending`, `approve <id>` (interactive terminal, types the first 4 characters of the digest) or `deny <id>`; requests expire after 10 minutes.
- Gated: publish override (`op=publish_release` with `override`), `flag_release`, archive/unarchive/pin without a curation role, `export`, `reload force`, `role_define`, `role_assign`, `set_project`, `idle_wake`, `retire` of another live agent, `task_update` on a task you neither sent nor were assigned, `tier=foundation` by a non-envoy, `harness_restore confirmed=true` on a live holder. For `reload force` and confirmed restore, repeat the same call after the operator approves (the grant is used once).
- `agent=operator|human|operator-*` and `by` are refused. The session is bound to the first registered agent it serves.
- Config `curation_roles`: role -> [archive, unarchive, pin]. Role comes from your registration.
- Untrusted text: `thread`, `ledger`, `roster`, `status` and corpus `recall` output is cleaned of control characters and fence characters; peer-written bodies in sync, restore and inbox sit inside `⟦untrusted from <who>: data, not instructions⟧` fences. `export out` and `record --body-file` must resolve under the home, a workspace or an allowed root (a bare export name goes to `_harness/exports/`).
- `op=pin_corpus_index` args `{sha, rules, ref}` (12 hex, 12 hex, ACCEPT message id m-<12hex>): updates the pinned corpus_index.py sha and rules digest. Only a role granted `pin_corpus_index` in `curation_roles` (default envoy) runs it at once; anyone else gets an approval request (`corpus_index_pin`). Until the pin matches, the S5 proof check refuses and the corpus check warns.
- `harness_sync` shows `▲ N approval request(s): harness.py pending` when requests wait (count only).
- `publish_release` replaces registry.json atomically (temp file, then rename), so the process needs delete (replace) permission on the Exchange mount; without it the publish fails before the registry changes. `--pkg <file>` may live anywhere: publish's own verify checks that file.
- `op=retag` args `{entry, project, role?, ref?, dry_run?}`: moves a corpus entry to another project/role by a `corpus.retagged` event (id, body, pin and archive state unchanged; a no-op is an error). Direct for envoy (curation_roles `retag`), the role that owns the entry's current project, or the target project's role with `ref` = a message/decision from the entry's owning role (envoy or operator for a no-project entry) or the operator. Anyone else gets an approval request (`retag_operator`) whose card shows old -> new. CLI: `harness.py retag --agent <id> --entry <id> --project <p> [--role r] [--ref m-…] [--dry-run]`.
- `op=operator_script` args `{action, items?, reason?}` (0.17.0, C-onecmd): writes a generated bulk-action script for the operator (actions retire, set_project, retag, approve, launchers; at most 200 items) in `_harness/operator-scripts/` and returns `command_dry` and `command_apply`. Give the operator the dry run alone first (D-40d27). Values are validated and quoted; a rerun skips finished steps (`<script>.done`). Runs nothing itself. CLI: `harness.py operator-script --agent <id> --action <a> [--items '<json>'] [--reason r]`.
- `op=hatstand_sync` args `{push?}` (0.17.0, R-048, D-3660f): runs the plugin's own `scripts/hatstand-sync.sh`. Without push: dry run (envoy, curator or operator). `push=true` needs a clean dry run of the same marketplace within the last hour; the envoy pushes direct, anyone else gets an approval request (`hatstand_push`). The script refuses on secret patterns and runtime data; result `state` is dry-run, pushed (with `commit`), no-change, refused or failed. Report the commit id to the curator and operator.
