# Backend status: INTERIM, flagged for replacement

| | |
|---|---|
| Current backend | `filesystem-jsonl`: one hash-chained `~/Claude/Projects/Exchange/_harness/events.jsonl` guarded by an advisory `flock` |
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

- **Surface runbook.** Set `HARNESS_SURFACE=code` for envoy, curator and coder chats on the desktop Code tab; `cowork` for Cowork chats. An explicit value always wins. Without it the ctx hook trusts only a desktop-home transcript path (`/Users/<name>/.claude/projects/`, `/home/<name>/.claude/projects/`); cloud paths (`/root/...`, `/sessions/...`) and anything else count as `unknown` and get the smallest window of the model row. `harness_sync` prints `ctx surface: <x> (<explicit|path|unknown>), plan <n>k, handoff <n>k` once per session, and every time it is unknown.
- **Opus Code window** stays 500,000 until measured. To override, add a `ctx_table` row to config.json, e.g. `{"ctx_table": {"claude-opus-5-5": {"window": {"code": 1000000}}}}`. Measure first (last usage record of a long Code chat); do not guess.
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

- Operator commands (shell): `python3 ~/Claude/scripts/transcript_indexer.py install | uninstall | status | search <terms> | spotlight off | purge --session <id>|--all --yes`. Install once; the launch agent keeps it running at low priority. The first run needs sessions to be allowed: registered chats are allowed automatically (ledger), others only if their session id is on a line of `~/Claude/Transcripts/.allow`.
- Files: vault `~/Claude/Transcripts/*.md` (0600, directory 0700), index and state `~/.cache/harness-indexer/` (0700). The index is derived: `rebuild` recreates it from the vault. Nothing is ever sent anywhere.
- Privacy: no tool result, hook or system text, no thinking; secrets redacted before anything is written; a message marked [private]/#private is dropped; agents reach the text only through `harness_recall kind=transcript` (role-gated, fenced as data).
- Tested limit: redaction is pattern-based and best effort, not a guarantee; keep `transcript_roles` short.

## State cache and release-scope gate (0.16.1)

- **State cache.** `Harness.state()` keeps the folded State and refreshes it from the new ledger lines only. Switch off with `HARNESS_STATE_CACHE=0` in the environment of the MCP server or CLI (then every call re-reads the ledger, as in 0.16.0). `verify` always re-reads the whole file. Residual risk: an older byte edited in place plus a later well-formed append is not seen by `state()` until the process restarts; `harness verify` reports it.
- **Release scope.** Release scope (items, version, split or bundle) is the operator's decision. Before a publish: `harness_admin op=release_scope args={plugin, version, items:[...], rationale, approval_ref}`, the operator runs `python3 <harness.py> approve <A-id>`; then `publish_release` accepts the package only if the CHANGELOG section for that version names every item. Rollback of a wrong scope: record a new `release_scope` for the same (plugin, version); the newest wins. Override: `--operator-override REASON` (logged). Gate off: operator.json `"release_scope_gate": false`.

## Context windows by surface (0.16.2, item 11)

The hook's table gives the window per model and surface: claude-opus-5-5 and claude-sonnet-5-5 are 1,000,000 on `code` and 500,000 on `chat` and `cowork`; Haiku is 200,000 everywhere. Plan at 60% and handoff at 80% of that window. **Set `HARNESS_SURFACE=code` for every chat that runs in Claude Code** (envoy, curator, ops-coder, design-coder); without it the surface is `unknown` and the smallest window (500k) applies, so a Code chat is told to hand off at 400k instead of 800k. `harness_sync` prints `ctx surface: ...` while the surface is unknown. A `ctx_table` row in config.json or `ctx_window_by_model` still overrides the table.

## Role-keyed context windows (0.16.3)

`*-coder` roles, `envoy` and `curator` have a 1M window on any surface and model, so they are warned at 600k and told to hand off at 800k. The hook learns the role from the harness banner of the last register/restore/whoami result in the chat; until then the model x surface table applies. Edit the list with `ctx_role_windows` in `Exchange/_harness/config.json` (`{"secretary": 800000}` adds a role; `{}` turns the feature off). `HARNESS_SURFACE=code` is still required for a Code chat's model x surface window (for roles outside the list); the role window does not depend on it. Claude Opus on Code is 500k (unmeasured) again.
