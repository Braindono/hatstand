# Backend status: INTERIM, flagged for replacement

| | |
|---|---|
| Current backend | `filesystem-jsonl`: one hash-chained `~/Claude/Exchange/_harness/events.jsonl` (before 0.18.0: `~/Claude/Projects/Exchange`) guarded by an advisory `flock` |
| Status | **INTERIM.** Approved as the easiest path to a working system. Not the long-term design. |
| Flag locations | `BACKEND_STATUS` in `scripts/harness.py`, the MCP server `instructions`, every ledger result, and the dashboard header badge |

## Why it will be replaced

1. **Reach.** Only agents that can see the folder can take part: Claude Code, and Cowork on this Mac. claude.ai web/mobile and other machines cannot.
2. **Locking.** `flock` is advisory and may not hold across the Cowork VM mount, network shares, or synced folders (iCloud, Dropbox). Concurrent writers there can fork the chain. `verify` detects forks but cannot prevent them.
3. **Scale.** Every read replays the full log, O(n). That is comfortable up to roughly 10,000 events, and then it slows.
4. **Latency.** Inbox long-polling watches the file's mtime every 200 ms. That is fine locally but is not push delivery.

## What stays when it is replaced

- The **MCP tool contract** (`harness_*` tools). Agents will not notice the swap.
- The **event format**: `seq`, `ts`, `type`, `actor`, `data`, `prev`, `hash`. An existing log can be replayed into any new backend as-is.
- The **projection logic** (`State`) and the **dashboard**.

## Replacement contract

A new backend implements three methods and is passed to `Harness(store=…)`:

```python
class Store:
    def append(self, etype: str, actor: str, data: dict) -> dict: ...  # atomic; sets seq/ts/t/prev/hash
    def read_all(self) -> list[dict]: ...                               # ordered by seq
    def changed_since(self, marker) -> tuple[bool, marker]: ...         # cheap change detection for long-poll
```

The candidates (local SQLite MCP, NATS JetStream, Cloudflare Durable Object) are explained separately.

## Migration

```
python3 scripts/harness.py export --out migrate.jsonl
python3 scripts/harness.py verify           # must be ok=true before migrating
# new backend: replay migrate.jsonl in seq order, preserving hashes; verify the head hash matches
```

## Surface and approval notes (0.15.5)

- **Surface.** Since 0.17.0 (R-059) the surface no longer changes any context window, so `HARNESS_SURFACE` is optional; the hook still detects it (explicit value, else a desktop-home or Cowork transcript path) for other uses.
- **Windows by model** were removed in 0.17.0 (R-059): see "Context windows by role".
- **PreCompact stub.** The hook writes one marker file `harness-precompact-<session>-<time>-<rand>.json` (temp file, then link; never overwritten) in `~/.claude/crew-coordinator/state/` and makes no ledger call. The next `harness_sync`, `harness_register` or `harness_restore` turns it into a role-state record under topic `precompact`. It fails open and never writes anywhere else.
- **Approval attribution.** Approval requests now need `agent=<short id>`; there is no fallback to the process binding. Residual: `agent=` is self-declared, so the harness has no per-chat authentication.
- **Publish permission.** `publish_release` swaps registry.json with an atomic replace, so the Exchange mount must allow delete/replace for the publishing process. The verify at the end of a publish checks the package given by `--pkg`, wherever it is; a later plain `verify` still looks for the newest package beside the source.
- **Idle-wake and scheduled tasks (D-314f2).** Plugin code and skills never delete scheduled tasks. Each arm leaves one fired, disabled one-shot trigger; the Idle-handoff cleanup runner removes them. Disarming uses `update_trigger(enabled=false)` on the id in the state file.
- **Doorbell and /listen (0.15.5).** A `harness_send` of kind task/question/review/handoff/result returns `nudge` {line (ids only), to, msg_id, thread, cap_state, do}: the sending chat pushes it with SendMessage (Code to Code wakes an idle chat in about 4 s; Cowork chats are not reachable, the mail waits). Every nudge or skip is a ledger event (`nudge.sent`, `nudge.skipped {reason}`). Caps (defaults): 6 per sender per hour, 3 per pair per hour (both directions), 12 per hour across roles (nudges plus wakes). `/listen` is off by default and operator-owned. In `~/.config/crew-coordinator/operator.json`:
  `{"doorbell": {"off": false, "mute_roles": [], "nudge_per_agent_hour": 6, "nudge_per_pair_hour": 3, "global_per_hour": 12}, "listen": {"roles": ["ops-coder"], "interval_min": 10, "max_per_hour": 6, "expire_h": 12}}`.
  `harness_admin op=listen args={action: status|arm|wake|rearm|end}`: the server computes the open task from the ledger, checks caps and expiry, and returns `arm`/`rearm` yes or no; arms end at 12 h, handoff or supersede. During a wake only inbox, send, sync, recall, task_update, notes and read-only admin run; everything gated is refused. `harness_admin op=status` shows armed roles, next wake and wakes used this hour. Fallback without MCP: `harness.py inbox --agent <id> --peek` (lists owed replies).
- **curation_roles and retag (0.15.5).** The default `curation_roles` gives envoy `["archive","unarchive","pin","pin_corpus_index","retag"]`. A config.json that already sets `curation_roles` overrides the default, so add `"retag"` to the envoy's list there; until then the envoy's retag falls back to an approval request.


## Archive, roles and checklist notes (0.15.6)

- **Archive before overwrite (P1/P2).** Rewriting a handoff capsule (status or model stamp) first copies the old file to `<home>/_archive/<YYYY-MM-DD>-handoff-status/` or `-handoff-stamp/`, keeping the home-relative path, and appends a `sha256  size  original  archived  reason` line to that folder's `MANIFEST.sha256`. If the copy fails the rewrite does not happen. Never delete these folders; a human or the steward prunes by archiving.
- **Scheduled tasks (P5).** Disable, never delete. Idle-wake already follows this (D-314f2); the same rule covers any scheduled task a skill or script touches.
- **Cutover checklist: roster before/after.** Run `harness_admin op=roster` (and `verify`, which lists `warnings`) before and after moving a role or its holder. `set_project` moves an agent only; the role moves with `role_define project=<new>`. A `⚠ ... holds <role> (project X) but is in Y` line is the signal to finish the move.

## Role renames (0.16.0, D-85cbc)

- `data/role-aliases.json` maps old role names to new ones: corpus-envoy -> envoy, corpus-steward -> steward, skill-curation-lead -> curator, claude-code -> ops-coder (D-bd8f8). The ledger fold maps old names everywhere, so history, message labels (`role:corpus-envoy`) and role state replay under the new names; no event is rewritten and no approval is needed.
- Input with an old name (`register role=`, `restore role=`, `harness_send to=role:x`, `role_define`, `role_assign`, `record role=`) resolves to the new role until the `until` date in that file (2026-11-21); after it the old name is refused with a pointer to the new one. Names read from config (`curation_roles`, `steward_roles`, `proof_roles`, `restore_gated_roles`) and operator.json (`listen.roles`) are mapped the same way.
- Role state notes filed under an old tag (`role-state:corpus-envoy`) and `<project>/<old role>/INTENT.md` folders are still found. The steward prompt `[scheduled] corpus-steward pass` and `[scheduled] steward pass` are both recognised; renaming the schedule command and prompt text is a separate step for the envoy's gates (corpus_index.py --test-rules, run_jobs.py eval --self-test).
- Removing an alias entry from the file undoes the rename for input; the fold keeps mapping history.

## Transcript indexer (0.16.2)

- Operator commands (shell): `python3 ~/Claude/scripts/transcript_indexer.py install | uninstall | status | search <terms> | spotlight off | purge --session <id>|--all --yes`. Install once; the launch agent keeps it running at low priority. The first run needs sessions to be allowed: registered chats are allowed automatically (ledger), others only if their session id is on a line of `~/Claude/Transcripts.noindex/.allow`.
- Files: vault `~/Claude/Transcripts.noindex/*.md` (0600, directory 0700), index and state `~/.cache/harness-indexer/` (0700). The index is derived: `rebuild` recreates it from the vault. Nothing is ever sent anywhere.
- Spotlight (0.17.0): the `.noindex` folder name keeps the vault out of Spotlight; the `.metadata_never_index` marker alone is ignored on macOS 26.7.1. `install` unloads the agent, renames an old `~/Claude/Transcripts` to the new root (never copies or deletes), leaves a symlink at the old path for one release, and pins the root in the plist (`INDEXER_ROOT`). `spotlight off` writes the marker, then probes with mdfind (`--probe-seconds`, default 30) and warns if Spotlight still finds a new file there.
- `status` counts distinct denied sessions, shows `last_run_at` and `state_path`, and reports `state_error` when the state file cannot be read (a pass then refuses to run rather than re-index into the vault twice).
- Privacy: no tool result, hook or system text, no thinking; secrets redacted before anything is written; a message marked [private]/#private is dropped; agents reach the text only through `harness_recall kind=transcript` (role-gated, fenced as data).
- Tested limit: redaction is pattern-based and best effort, not a guarantee; keep `transcript_roles` short.

## State cache and release-scope gate (0.16.1)

- **State cache.** `Harness.state()` keeps the folded State and refreshes it from the new ledger lines only. Switch off with `HARNESS_STATE_CACHE=0` in the environment of the MCP server or CLI (then every call re-reads the ledger, as in 0.16.0). `verify` always re-reads the whole file. Residual risk: an older byte edited in place plus a later well-formed append is not seen by `state()` until the process restarts; `harness verify` reports it.
- **Release scope.** Release scope (items, version, split or bundle) is the operator's decision. Before a publish: `harness_admin op=release_scope args={plugin, version, items:[...], rationale, approval_ref}`, the operator runs `python3 <harness.py> approve <A-id>`; then `publish_release` accepts the package only if the CHANGELOG section for that version names every item. Rollback of a wrong scope: record a new `release_scope` for the same (plugin, version); the newest wins. Override: `--operator-override REASON` (logged). Gate off: operator.json `"release_scope_gate": false`.

## Context windows by role (0.17.0, R-059; replaces the 0.16.2 surface table and the 0.16.3 role overlay)

The window depends on the agent's ROLE only (operator rule D-2b929: the model never sets a context threshold). `*-coder` roles, `envoy` and `curator` have 1,000,000 tokens; every other role, and a chat whose role the hook has not learned yet, has 500,000. Plan at 60% and handoff at 80% of that window, so 600k/800k and 300k/400k. Neither the model (Sonnet, Opus, Fable) nor `HARNESS_SURFACE` changes a window; Haiku stays silent (ephemeral subagent). The hook learns the role from the harness banner of the last register/restore/whoami result in the chat. `harness_sync` prints `ctx window: <n>k (role <r> | default ...), plan <n>k, handoff <n>k` once per session.

Config (`Exchange/_harness/config.json`): `ctx_role_windows` edits the 1M list (`{"secretary": 800000}` adds a role; `{}` sends every role to the default); `ctx_window` sets the default window (500,000); `ctx_plan` / `ctx_handoff` the shares; `ctx_plan_tokens` / `ctx_handoff_tokens` absolute thresholds. `ctx_table` and `ctx_window_by_model` are ignored since 0.17.0.

## Eval loop scripts (0.17.0, zero model tokens)
- Weekly health report: `python3 scripts/weekly_report.py` writes `health-<week>_<date>.md` and `.json` to `<ops root>/projects/orchestration/digests/weekly/` (read-only on the Exchange: role numbers come from a temp copy). A rerun on the same day replaces that day's file.
- Corrections harvester: `python3 scripts/corrections_harvester.py --dry-run` (counts only), then without `--dry-run` to write candidate case files to `<ops root>/projects/skill-curation/eval-candidates/<date>/`. Reads only the indexer vault. Run by the curator or the operator: the files hold operator chat text (redacted).
- C-live: `python3 tests/c_live.py --ab <published tree>/scripts <build tree>/scripts --out <file>` before each stage ACCEPT (lint needs HARNESS_HOME set; the test suite runs with it unset).

## Confinement (0.17.0, R-053)
- Path ceiling for config.json `workspaces`, `allowed_roots`, `project_roots`: ~/Claude/Projects, ~/.claude/crew-coordinator, ~/.claude/plugins. Anything else goes in `~/.config/crew-coordinator/operator.json` (mode 0600).
- `watch` and `plugin_dirs` are read from operator.json only.
- An MCP publish override is confined to the home, workspaces and allowed roots; the CLI publish is not.
- Warnings name the file and key (`config.json workspaces[0] ignored: outside the ceiling`), never the path.

## Vault, handoff gate, lessons and the digest ceiling (0.17.0, stage 2)

- Vault: `Exchange/vault/<project>/<role>/<date>-<agent>.md`, distilled from the indexer output only (never raw jsonl), redacted on input and output, written at handoff (config `vault: on`, ships off) and as an untagged checkpoint at PreCompact and `/save`. Operator purge: `transcript_indexer.py purge --session ID --vault --yes` (tombstone + `.purged.jsonl`). Recall: `harness_recall kind=vault`.
- Handoff gate: config `handoff_gate: warn|block` (ships warn); events `handoff.gate_warn|gate_blocked|gate_override`. Override: `harness_handoff gate_override="<reason>"`.
- Lessons: `kind=note` + tag `lesson` + `What happened: / Cause: / Rule:` lines + `role:<role>|role:all`; digests show curator or operator lessons only. `harness.py lessons-view` generates docs/lessons.md. Digest section: newest 3, 90 tokens in all; `role:all` = agent roles (the operator's seat shows `role:operator` only). `restore_pin_cap` is 15: 20 breached rule A for four roles once lessons were imported into a simulated copy (10-25); raise it only by operator config.
- Digest ceiling (P-2.9, rule A, envoy m-1797922f9c76): C-live `--ab` measures one snapshot with the old and the new tree and fails the stage (exit 2) when a role's restore digest above the inline capsule grows past old x `digest_growth_max` (1.2), exceeds `digest_caps` (envoy and curator 1794), exceeds `restore_budget` (2000), or is cut at the budget. `digest_ceiling_tokens` (int, or role -> int with `*`) is the operator's absolute override in place of the growth rule (D-2b929).
- Tried and dropped: a fixed per-role table (one day's baseline + 20%). On 10-25 it failed roles whose code did not change their digest: the dreamer (0 pins) grew 793 -> 964 tokens from mail traffic alone between 10-24 and 10-25. An absolute baseline mixes traffic with code growth; do not reintroduce it as a default.

## Release checklist (0.17.0, stage 3)

- Hatstand sync (standing rule D-c92cb, 0.18.0 R-097): the corpus and the ledger are never published to Hatstand. Before every push, hatstand-sync.sh runs the secret scan and hatstand_guard.py (paths, ledger-shape lines, live corpus titles); a hit stops the push. Never weaken or bypass either check; a new fixture exemption needs the envoy's review and a CHANGELOG line.
- Final ACCEPT: second reviewer from another model family (ee P-107); canary install to one role first (R-044).
