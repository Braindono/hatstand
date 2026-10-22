# Changelog

## 0.16.0 (unreleased): restore carries operator context; 2k digest (group 1 of specs/2026-10-22-cc0160-spec.md)
- Restore digest: new sections "Operator preferences" (rules from the project's OPERATOR-PREFERENCES.md, one line each, cap 600 tokens, `+N more`; a project's aliased folders such as skill-curation and orchestration are searched for a harness-ops role) and "Role intent" (the role's INTENT.md excerpt, cap 300), after "Role"; a missing file prints `(no preferences file)` / `(no INTENT.md)`. Both are fenced as data.
- Digest budget 2000 tokens (was 5000), counted above the inline capsule; the capsule section keeps its own cap. Trims: Decisions top 6 (pins first), Recent commits 4, Owes reply a count plus the 5 newest, shorter last-exchange and unread lines. Config `restore_budget` still overrides.
- Handoff: lease and commit keys for a capsule go through the project-folder resolver (`_lease_key`), as the 0.15.5/0.15.6 capsule-path fixes did for reads and writes.
- Role rename with aliases (group 2, D-85cbc, item 4/4b): data/role-aliases.json (corpus-envoy -> envoy, corpus-steward -> steward, skill-curation-lead -> curator, claude-code -> ops-coder; `until` 2026-11-21). The ledger fold, message labels, role state notes, INTENT folders, config and operator.json role lists, restore gating, the steward prompt, compress reviews and all role-name literals use the new names; old names resolve as input until the end date, then are refused with a pointer. A restore by an old name still goes through the live-holder and gate checks (the mcp layer maps the name first). No new approvals: nothing in the ledger is rewritten.
- data/project-aliases.json: harness-router and harness_router entries removed. orchestration and skill-curation keep their own slug there (their records and agents carry it; the harness-ops folder mapping is in _alias/alias-map.json).
- Send visibility (spec 2026-10-22-bind-send-visibility, envoy ACCEPT m-3303ec74d343): `call.failed` event for failed writes (agent, tool, error, to; no body or title; 3 per agent per minute); counts-only unread line on non-harness tool results (older than 2 min, once per 10 min, from a marker file the server keeps, no ledger replay); `harness_record` without kind/title returns a clear error instead of KeyError('kind'); `bind.mismatch` now records mode, executed and that `bound` is not an authority. bind_mode stays `warn`.
- Tests: hermetic test environment (tests/_env.py, 0.15.6 review item), bundled FOUNDATIONS fixture.

## 0.15.6 (unreleased): archive before overwrite, role/project mismatch, wording
Spec: specs/2026-10-22-cc0156-spec.md. Base: published 0.15.5 (pkg fe4eb1894eef, code aaf84ac750a9).
- P1/P2 archive-instead-of-overwrite: a handoff status rewrite and a model-stamp rewrite first copy the old file to `Exchange/_archive/<YYYY-MM-DD>-handoff-status|handoff-stamp/<path>` with one `MANIFEST.sha256` line (sha256  size  original  archived  reason); a failed copy aborts the rewrite; the rewrite is atomic (mode kept). The stamp rewrite now resolves the capsule through the project-folder resolver (it joined under home, so a capsule in the harness-ops folder was written to the wrong path). P3 stays with corpus_index v5. P4 (lint rule) is a corpus_index `--test-rules` change: not in this release (pinned script; see message to the curator). P5 is docs only: disable, never delete, scheduled tasks (docs/BACKEND.md).
- set_project and roles (N-dacca): `set_project` on a role holder says the role stays in its project and names the `role_define project=<new>` approval (result `warn`, pending approval `note`); `roster` and `verify` flag a holder whose project differs from its role's (`⚠ <agent> holds <role> (project X) but is in Y`; verify key `warnings`); `role_define` with a new project for an existing role moves it and, when the holder is already in that project, re-binds the holder in the same call (`rebound`); otherwise it warns.
- Wording: project_dir order is explicit HARNESS_OPS_ROOT / project_roots, then the legacy home folder, then the alias-map ops folder (0.15.3 order); the 0.15.3 note "legacy wins" holds only when no explicit root is set.

## 0.15.5 (unreleased): context gauge fix, small items, idle re-arm, lint cleanup (WP1 + WP2)
Spec: specs/2026-10-20-cc0155-master-spec.md; curator rulings m-2f799cf488db.
- Surface: `code` only for HARNESS_SURFACE=code or a desktop-home transcript path; cloud and other paths are `unknown` (smallest window). `harness_sync` prints `ctx surface: ...` once per session and whenever unknown, and `ctx unmeasured` when no size was reported.
- PreCompact: marker + one-line stub in the per-user state dir (no ledger call, no handoffs/ write); the next sync/register/restore records it as role-state topic `precompact`.
- `ctx_table` override and the Opus measurement note, surface runbook, approval residual: docs/BACKEND.md.
- Approval `how` is `python3 <abs path of harness.py> approve <id>`. Approval requests require `agent=` (no BOUND fallback).
- State note `topic` (slug, <=24): tag `role-state:<role>:<topic>`; main keeps `role-state:<role>`; restore digest shows other topics as one line with the recall id.
- Restore Role section: `intent:` path and `files:` names (max 5) when projects/<project>/<role>/INTENT.md exists; role_define warns when a no-carry role has none.
- `computer://` links (a `link` field, or a link in text) for the handoff capsule, restore "Latest capsule", claim and status paths, ledger leases, health bundle and export paths.
- WP2f idle-wake: a fire skipped because the operator was active re-arms itself every time (fresh id, so timers never stack); an idle fire hands off and does not re-arm; a handed-off chat never re-arms. Hook text and skills/idle-wake updated.
- WP2g lint cleanup: protocol SKILL.md body 598 tokens (detail moved to references/patterns.md, ladder kept in short form); confcheck hit in references/admin.md reworded. Lint is clean in a properly named dir.
- WP2h publish: the verify at the end of a publish checks the package given by `--pkg` wherever it is; docs say publish needs delete/replace permission on the Exchange mount (atomic registry.json replace).
- Tests: approval `how` runs from a harness-ops path, an Exchange path and a path with spaces.
- WP2i idle-wake cleanup (D-314f2): hook and skill text never ask for delete_trigger or list_triggers; disarm is update_trigger(enabled=false) on the id in the state file; docs say the Idle-handoff cleanup runner removes fired triggers. Re-arm via update_trigger run_once_at NOT shipped: that call's parameters are unconfirmed on both surfaces.
- WP4 doorbell + /listen (H-020): scripts/doorbell.py. `harness_send` / `harness.py send` return an ids-only `nudge` + Do-line for the sender to push (caps 6/sender/h, 3/pair/h, 12/h shared; once per message id; mute/off in operator.json; nudge.sent / nudge.skipped events). `inbox` lists owed replies. `/listen` self-wake (skills/listen): `harness_admin op=listen`; operator.json enables roles (default off); the server computes open tasks from the ledger; arms expire at 12 h / handoff / supersede; 10 min apart, 6 per role per hour; status shows armed roles, next wake, wakes used; a wake can only run inbox and routine coordination (gated tools refused server-side); a `/listen` prompt is never counted as operator activity by idle-wake.
- WP5 /compress (deterministic half, scripts/compress.py, `harness.py compress <start|snapshot|propose|review|apply|verify|restore|lint|tune|resolve>`, skills/compress): dry run by default (writes only compress/<run>/ and a ledger event); snapshot with manifest + sha required before apply; worker proposals validated (verbatim quotes at cited lines); project-lead and corpus-envoy reviews; apply is envoy-only, pins first then moves files to _archive/compressed/<run>/ (never deletes, resolvable by path); apply refused if restore-questions.md changed since the run pin or the script / corpus_index pin / pin set changed since the dry run; verify grades a fresh non-gated agent's answers deterministically (all rule-bearing correct, 0 uncited) and offers snapshot restore on failure; steward `lint` (questions file, pin, cites resolve); bounded feedback log and a tuner that only writes a proposal file; snapshot report lists prunable snapshots (keep 3, cap 200 MB) and never deletes; scheduled run (`start --scheduled`) is report-only, filed to corpus-envoy. Ledger events compress.started/snapshot/proposed/reviewed/applied/verified/restored.
- harness-router is deprecated (operator 10-20): its project alias is gone from the live config.json and _alias/alias-map.json (project_aliases and the Harness_Router path hint). The Harness_Router/harness-hub names in harness.py (FOLDER_NAMES, _HUB_NAMES, LEGACY_LOGS) stay as history resolvers only, because 238 ledger events (77 release.published, 27 lease.claimed) store source paths under `Harness_Router/`.
- WP3 retag (harness side): `harness_admin op=retag` / `harness.py retag` write a `corpus.retagged` event {id, old/new project and role, by, ref, ts}; corpus.py applies the latest retag per entry (project, and role when given) on index build and rebuild; pin and archive state untouched; no-op is an error; dry-run; authority = envoy (curation role `retag`), owning project role, or target project role with a verified `--ref`, else approval request `retag_operator` (card shows old -> new). Project/role validation shared with record(). The retag event shows in export, verify and the model-change re-verify list. The corpus_index.py handler is WP6 (separate S5 sha).

## 0.15.4 (2026-10-14): auto-confirm restore from the holder's fresh capsule
Spec: specs/2026-10-14-auto-confirm-restore.md (operator YES). One item, nothing else bundled.
- `harness_restore confirmed=true` no longer needs an approval when ALL of: the capsule path is explicit and under
  projects/<role's project>/handoffs/; its front matter is `status: open`, project matches, and `from:` names the CURRENT
  holder and the role; the ledger shows the holder committed it through `harness_handoff` (a `handoff capsule` version by
  the holder, holder carries `agent.handed_off`) and the file still has that committed sha (a hand edit falls back);
  the capsule is at most 30 min old and the holder was seen at most 60 min ago; the role is not gated (default
  `corpus-envoy`). Anything else returns the pending approval as before, with `auto_confirm: "not applied: <reason>"`.
- Single use: the restore flips the capsule to `status: accepted by <id> (restore)`; a second restore from it falls back.
- Audit: ledger event `restore.auto` {capsule, capsule_sha, holder, new, role}.
- Thresholds and the gated list come from the per-user operator.json only (`restore_auto`, `restore_auto_capsule_min`,
  `restore_auto_holder_min`, `restore_gated_roles`); the shared config.json cannot widen them.
- Known limit: two simultaneous restores of the same capsule can both pass the check before either flips the status
  (the second one then supersedes the first, exactly as a normal restore does).

## 0.15.3 (2026-10-14): Wave 1, project folders, registry paths, robustness
Project folders (E, R6 blocker for the harness-ops cutover)
- One resolver, `project_dir(home, slug)`, for every path into a project folder (PROJECT.md, handoffs, review, ROLES.md,
  roles-manifest.json, OPERATOR-PREFERENCES.md, orchestration digests, corpus_index.py, health and corpus scans). Order:
  `project_roots[slug]` (operator.json; config.json only under the path ceiling) -> `HARNESS_OPS_ROOT/projects/<slug>` ->
  legacy `<home>/projects/<slug>` when it exists -> `<ops root>/projects/<slug>` when `_alias/alias-map.json` maps the slug
  to harness-ops (ops root: `HARNESS_OPS_ROOT`, else `~/Claude/Code/harness-ops` if present). Legacy wins while both exist, so
  nothing diverges before the old trees are archived. Writes go to the one resolved tree. The ledger, events, registry and
  mailboxes stay in `<home>/_harness`. A slug must match `^[a-z0-9][a-z0-9-]*$`; nothing found names every path tried.
- Capsule and lease paths for a folder outside home are stored as `projects/<slug>/...` and resolved through the same
  function; `..` and symlinks stay refused.
- `record(role=...)` accepts a role defined under the agent's original project when the project is aliased.
Registry (D)
- Publish stores the source path relative to its folder (`Harness_Router/crew-coordinator`). `verify` resolves it against
  HARNESS_HOME and its siblings under both names (Harness_Router, harness-hub), the ops root and ~/mnt; legacy
  `/sessions/*/mnt/<Folder>/...` paths map by suffix. Retired, external, renamed and replaced entries are listed as notes.
  A null pkg_sha (skill-foundry, parsed-job-data) stays a problem until their next publish.
Config (C)
- `brief_hosts` is read from operator.json only; a value in config.json is ignored with a warning.
Robustness (P7)
- Ledger lines that are not JSON objects, or claim type `_corrupt`, are reported by verify, never trusted; `hash_vectors`
  counts them and malformed lines instead of aborting or exempting `_corrupt`.
- retire is idempotent, flags unreadable capsules and unreleased leases, and writes `agent.retired` last.
- handoff checks the lease on an existing capsule before writing anything.
- A multi-path claim validates every path first and is all-or-nothing (a refused path rolls back the others).
- A failed marketplace swap restores the previous live tree.
- MCP: malformed JSON, non-object and bad-id requests get JSON-RPC error replies; oversize lines (4 MB) are drained and
  answered; wait/limit/ttl are clamped; an identical `harness_send` within 60 s is answered, not delivered twice; a footer
  failure no longer turns a committed write into an error.
- ctx_hook: the told-band mark resets when the context falls back (after /compact or a handoff); each hook step has its
  own try and failures go to `harness-ctx-hook.log` in the state dir (20 KB cap).
- inbox ladder: at most 8 rungs of at most 600 s. `#abc` in a thread lookup is a message, not a crash. Corpus search limit
  clamped, `get` takes at most 50 ids.

## 0.15.2 (2026-10-14): hotfix, shared-process bind
- Fixed: chats served by one MCP process (cloud sessions via the device link) were refused once another agent registered
  first. New config `bind_mode` = off | warn | enforce, default warn: a mismatch logs `bind.mismatch` once per pair and
  is allowed. `enforce` keeps the 0.15.1 refusal for a verified one-chat-per-process setup.
- Approval requests are attributed to the agent named on the call, not the process-wide binding (fallback only when
  the call names no agent). Operator-name refusal and all approval gating are unchanged.
- Known limit: with bind_mode off or warn a caller can name another agent for approval attribution; approval grants are exact-args, one-shot, and expire after 10 min.

## 0.15.1 (2026-10-14): Wave 1, identity and approvals

An agent can no longer act as the operator over MCP. The CLI and dashboard keep calling the Harness directly as operator.
- Server-bound identity: the first call that names a registered agent binds the MCP server process to it; a different agent id is refused afterwards. `harness_register` and `harness_restore` rebind to the agent they return; the bound agent's lineage is accepted.
- `agent` values `operator`, `human`, `operator-*` and any `by` argument are refused from MCP on every tool and admin op.
- Approval requests: operator-level actions asked for over MCP (publish override, flag_release, archive/unarchive/pin by a role without the grant, export, confirmed restore of a live holder, retiring another live agent, forced reload, role_define, role_assign, set_project, idle_wake, task_update on another's task, foundation tier by a non-envoy) return `{"pending": "A-xxxxx", ...}` and run nothing.
- New CLI: `harness.py pending`, `approve <id>` (interactive terminal and the 4-character code from the digest), `deny <id>`. Approvals expire after 10 minutes; each runs once and logs `approval.granted` with channel `cli-tty`. `harness_admin op=approvals` lists pending requests.
- New admin ops `flag_release` and `publish_release` (override requests only); both always return a pending request.
- Config `curation_roles` (default corpus-envoy: archive, unarchive, pin; corpus-steward: archive, unarchive) decides who runs these directly. The role comes from registration; a malformed value falls back to the default.
- Gate integrity: an unresolvable `by` on publish or flag is an error, not `human`; the raw caller is logged in the release events; the default package path gets the same code-vs-package check as `--pkg`; `archive ack` must be a message id.
- Health shows `approvals: N pending, M granted (cli-tty k)` and a Do-line when requests wait.

Wave 2:
- `corpus_index.py` is pinned: harness runs it (S5 proof check, corpus check) with `python3 -I` only when its sha256 (12 hex) and the digest of `rules/*.py` match the pin; a mismatch refuses the proof (`S5: corpus_index.py sha X != pinned Y`) and shows one corpus-check warning. Default pin is built in; `harness_admin op=pin_corpus_index {sha, rules, ref}` writes `corpus_index.pinned` (curation action `pin_corpus_index`, corpus-envoy by default; anyone else gets an approval request `corpus_index_pin`).
- Health prints `corpus_index.py pin ok` or a `▲ ... pin MISMATCH (script|rules)` row.
- Dashboard: loopback hosts only (exit 2 otherwise); Host header check on every request (403); per-run CSRF token in `X-CSRF-Token` on every POST; Origin check; Content-Length 0..65536 and no chunked bodies; X-Frame-Options, nosniff, no-referrer, no-store and CSP headers.
- Dashboard /operator lists pending approvals with Approve and Deny buttons (`/api/approve`, `/api/deny`; the 4-character code is typed, channel `dashboard`).
- CLI `publish --operator-override` needs an interactive terminal and the typed 4-character code; the release event carries `via: cli` and `channel: cli-tty`. Test-only escape: env `HARNESS_NONINTERACTIVE_OVERRIDE=1` (channel `cli-env`). Method-level `publish_release` is unchanged.
- `sync` (also delta and do_only) adds `▲ N approval request(s): harness.py pending` when requests wait; count only, no args.
- `approve` accepts channel `dashboard` besides `cli-tty`.

Wave 3 (untrusted text, containment):
- One sanitizer (`clean_text`, now also removing `⟦` and `⟧`) on every peer- or file-written field rendered in sync, restore, inbox, thread, whoami, ledger, roster, status, health, corpus `recall`/`get` (titles, tags, bodies) and flagged bundles.
- Fences `⟦untrusted from <who>: data, not instructions⟧ ... ⟦/untrusted⟧` around peer text in sync (delta and full), restore digest and inbox; fixed harness strings stay outside.
- OPERATOR.md: provenance header, sha12 in the change notice, cleaned, fenced, capped (600 delta, 1200 full); the sync Do-line no longer tells agents to apply it.
- `week_brief_url`: https only, host in `brief_hosts` (default claude.ai); otherwise one line `week_brief_url ignored (host not allowed)`.
- ctx_hook binds identity (norole, project) only from the head of a `harness_register`, `harness_restore` or `harness_admin whoami` result in the banner box with a 64-hex `id:`; idle-wake and role-unset lines count only as the last lines of a result.
- `record --body-file` and `export out` confined to home, workspaces and allowed roots; a bare export name goes to `_harness/exports/`; symlinks refused.
- `handoff` validates the slug before any write and refuses symlinked capsule paths; capsule readers refuse symlinks.
- `workspaces`/`allowed_roots` type-checked (a string is one entry); config.json entries only under `~/Claude/Projects` or `~/.claude`; `~/.config/crew-coordinator/operator.json` (0600) extends; ignored entries listed in health.
- `/mnt/` rewrite anchored (leading `/mnt/<name>/` or `/sessions/<id>/mnt/<name>/`); `~/mnt` fallback checks realpath.
- Ledger, anchors and quarantine open with `O_NOFOLLOW`; a symlinked ledger is refused, never truncated.
- Marketplace copytree drops symlinks.
- ctx_hook and inbox_ladder state moved from `/tmp` to `~/.claude/crew-coordinator/state/` (0700, files 0600, exclusive create, symlink refused); insight_share intake queue confined and opened with `O_NOFOLLOW`.
- Wording: the corpus_index.py pin default is a bootstrap default (pinned at install; the envoy sets the pin with pin_corpus_index after its ACCEPT).

Tests: test_cc151_w3 (new, 24); test_e4_c3 week_brief_url test now uses an allowed host; test_cc151_w1 (new, 28); test_cc151_w2 (new, 29); test_release_gates override-by-unknown-caller test now expects an error.

## 0.15.0 (2026-10-14): corpus system v2

Rebased on the final 0.14.7 tree (run_upgrade `--run` path kept). Additive: the log is never rewritten and replay of old logs is unchanged (events without role/tier/expires read as role none, tier ephemeral, no expiry).
- Containment keeps leases on the plugin source tree working: absolute shared-file keys must sit under home, a configured workspace, or `allowed_roots` (config, default `~/Claude/Projects`); `..` is always refused.
- `corpus.recorded` gains `role`, `tier` (foundation | role-state | ephemeral) and `expires`. Role defaults from the caller's registration, else `unassigned` (never blocked). An explicit `role` must be defined for the project (registry, ROLES.md, roles-manifest.json) or `unassigned`, else the write is rejected with the defined list. `tier=foundation` needs the corpus-envoy as author. `state_note` writes tier role-state and supersedes the previous note. `harness_record` accepts optional `role` and `tier`.
- Expiry: ephemeral note and context get `expires` = write date + `corpus-expiry-days` (OPERATOR-PREFERENCES.md, Exchange root then project file; missing or invalid means 14). Decision, capsule, role-state and foundation: none. Expiry only marks an entry due (`Corpus.due()`, ` due` on cards, `DUE` on full text); nothing is removed.
- Pins: tag `pin` never due. An id cited in the body of a foundation doc (`doc: foundations` front matter or FOUNDATIONS*.md) is treated as pinned unless listed in that doc's `replaces:` header; health honours the same rule.
- Archive keeps content: each archived entry is copied to `_archive/corpus/<ISO-week>/<id>.md` with one `manifest.jsonl` line (id, title, tier, reason, date) per week. Recall by id still returns it, marked ARCHIVED. A D-* entry needs its owner's ack (owner archiving, or `ack=<message id>` from the owner; owner = recorded role, else corpus-envoy) whose body or refs name each entry id and that was sent after the entry was written; an unrelated or older owner message covers nothing; the operator needs none. Existing S6 and D-8b713(c) gates are unchanged.
- `harness_admin op=unarchive id=<id>`: back into the index, `corpus.unarchived` logged, expiry rule restored (note/context +N days, decision none). Unknown or live id is a no-op message. Any registered agent may unarchive (reversible; the event names the actor).
- Index cache gains `role`, `tier`, `expires` columns in place (ALTER TABLE); no rebuild needed.

Tests: test_corpus_v2 (new).

Audit fixes (security and hygiene, from the 0.14.7 harness.py audit; no change to the event format, the log, or any hash rule):
- Paths: a shared-file key with `..` segments, or an absolute key outside home and the configured workspaces, is rejected with a one-line error naming the field (`canonical_path`, `disk_path`; claim checks before it writes the lease). Capsule paths from corpus records, `restore` capsule paths and handoff/review project slugs are checked under the Exchange home; a slug must match `^[a-z0-9][a-z0-9-]*$`. Plugin and `renamed_from` names are checked against `[a-z0-9-]+` before any path is built.
- Actor handling is unchanged on purpose: callers may still pass `human`/`operator` (operator flows depend on it); a proposal goes to the lead separately.
- Symlinks inside a plugin tree are skipped by the package build and by every tree hash alike, so source hash == package hash still holds. A tree without symlinks hashes exactly as before.
- New files are created 0600 and new directories 0700 (ledger, config, anchors, export, quarantine, capsules, handoffs, bundle, archived corpus copies); existing files are never chmod'ed. Registry, package and idle-wake config writes use a unique temp file in the target directory, then an atomic replace.
- Agent-written text (subjects, state notes, message bodies, claim intent, task notes, banner fields, corpus cards, OPERATOR.md) loses control characters and is length-capped before it reaches sync, inbox, banner or hook output. Corpus archive front matter quotes titles that hold a newline, quote or backslash; an archive file name needs a corpus id; the package sha is regex-escaped in the ACCEPT match.
- A message body over 20000 characters is refused with a clear error; `max_hops` is clamped to 1..10.
- Publish: the marketplace stage and previous copy use unique `.stage-<pid>-<ns>` / `.prev-<pid>-<ns>` names, so a leftover from an earlier run never blocks a publish; legacy leftovers are swept, and a removal that fails is returned in the publish result `warn` list instead of being swallowed.
- Efficiency, no behaviour change: the adjective set is built once per call, the plugin's own disk hash is computed once per sync (fingerprint and inventory share it), config is loaded once per sync, and ROLES.md / roles-manifest.json are re-read only when their mtime or size changes.
- The pre-tool-use hook stays fail-open on any error (hooks must not break the session); this is by design and unchanged.
- Not part of this release (deferred): incremental State, log tail reads, a smaller `agent.synced`.
- The `--run` path of `run_upgrade` is unchanged by these fixes and independent of them.

Tests: test_audit_fixes (new).

## 0.14.7 (2026-10-13): drift prevention (A-I, J registry helper)

One version across source (S), package (P), local marketplace and install (I). Additive; the log is never rewritten.
- A publish also regenerates the local marketplace `_harness/marketplace/` (`.claude-plugin/marketplace.json` + `plugins/<name>/`, name from config `marketplace_name`, default `harness-local`) from the registry. Staged beside the live copy and validated (version and code == registry) before anything is written; a mismatch aborts, a ledger failure rolls the swap back.
- B `harness.py verify` (CLI) now also runs the per-plugin check (registry version/code == marketplace == newest `.plugin` sha, `pkg_sha` non-null) and exits 1 on any mismatch; `--plugins-only`. Publish runs it last for the published plugin and reports `verify` (the event is already appended; the exit code carries a failure). `pkg_sha` is required: a publish without a package is refused, override included. The MCP `verify` op (chain only) is unchanged.
- C publish sends one one-line `notice` ("<name> <v> published, reload to load") to agents seen within `fleet_window_h` (not group:all). Health `fleet ▼n/m` shows age; it prints `rolling` and is not a warning until config `plugin_drift_h` (default 6) hours after publish.
- D `harness.py flag <name> --retired [--replaced-by X]` / `--external` (`--off` clears); event `release.flagged`. Health, fleet, operator rows and verify ignore retired entries; external entries are tracked, never required. Registry carries `retired`, `replaced_by`, `external`.
- E/H sync prints `install ▼ <name> <v> -> <v2>: claude plugin marketplace update <m> && claude plugin update <name>@<m>` when `~/.claude/plugins/installed_plugins.json` shows an older install, plus one `src= pkg= installed= running=` line per plugin (full sync: "Running:"; delta: only the fixing action, rebuild / install / reload).
- F verify compares S with the newest package contents (shared ignore list, D-42db5). G `publish --build` builds the `.plugin` from S (sorted members, fixed mtimes/modes), so the package sha is reproducible. `publish --dry-run` runs every check and writes nothing.
- J helper: `Harness.upgrade_plan()` / `harness.py upgrade-plan [--run|--dry-run]` and `run_upgrade()` read the registry, validate names, refuse unapproved plugins, order plugin-publications last, stop at the first failed command. `--run` executes argv lists (no shell) with the claude CLI only when `claude auth status` succeeds; otherwise it prints the commands. The /upgrade skill file is not part of this plugin build.
- Known limits: the shape of `installed_plugins.json` is unverified (absent on cloud and Mac sessions checked); `installed_versions()` returns {} then and `installed=?` is expected. `verify` reports "not yet published to the marketplace" (exit 0) for a plugin with no marketplace entry or dir; the first publish creates it. Legacy tool-name removal moved to 0.14.8.
- Registry code hash for 0.14.6 (30099c464082) is on the old 0.14.5 rule (no data/); the running 0.14.6 server hashes to c5fa9ea456c9. Publishing 0.14.7 from it records the new-rule hash. 0.14.6 is not republished.

Tests: test_drift_prevention (new).

## 0.14.6 (2026-10-13): hardening Wave 1, H-003, H-016, inbox ladder, W42 E4/C3

Wave 1 (write path only; the append-only log is never rewritten, history is reported by `scripts/history_report.py`):
- #8 `lease.expired` event, once per expired claim (State flag `expired_logged`; written by claim and sync).
- #9 `record` rejects a null or unknown project and maps aliases at write from `data/project-aliases.json` (plus optional `_harness/project-aliases.json`).
- #10 `refs` is always a list at write (record and send). #11 host names normalised at write (`MacBookPro.haven.lan` -> `MacBookPro`).
- #12/#13 history report: events without `via`, the unregistered writers behind actors > registrations, string refs, project offenders.
- #16 the 10 legacy tool names are refused in `call()` with a pointer to `harness_admin` (flag `HARNESS_LEGACY_TOOLS=1` / config `legacy_tools`; removal moved to 0.14.8). `tools/list` unchanged.
- A2 `check_reason`: the `none...` bypass is gone (only the harness's own mechanical-prune auto-fill skips the quote check). A3 release gate needs a line `ACCEPT sha=<12 hex>` naming the package sha and no line starting `REJECT`. Tests moved to this form.
- A5 torn last line is quarantined to `_harness/quarantine/` and `log.repaired` is logged; `_tail` never raises. A6 `_require_proof` fails closed without corpus_index.py. A7 `State._apply` skips and counts malformed events (`State.skipped`).
- #4 hash-chain anchors in `<home>/_harness_anchors/anchors.jsonl` (publish, daily, `harness.py anchor`); `verify` compares to the last anchor. Tamper-evidence only, not signing. #6 canonical JSON pinned in docs/EVENTS.md, `data/hash-vectors.json`, `scripts/hash_vectors.py` prints the match count.
- H-003 retire closes the agent's open capsules (or flags them) and flags a missing `model:`.

H-016: sobriquet lists moved to `data/adjectives.md` (134) and `data/nouns.md` (197), append-only; loader drops blanks and duplicates and rejects words not matching `[A-Z][a-z]{2,9}`; stored names untouched and still taken. "Ember" stays a noun (an agent is named "Gilded Ember") and is flagged. Banner shows `<Name> #<id> · <role>`. `data/` is part of the code hash.

Also: `BANNER_RE` matches only the box (the "◆ Name #id" line after a "CREW COORDINATOR" header), so a quoted name in a transcript no longer rebinds a session. Restore step 6 continues through the capsule's Next list.

Inbox ladder (droppable, own module `scripts/inbox_ladder.py`, `tests/test_inbox_ladder.py`): Stop hook reminder when a reply had no `harness_inbox` call; `harness_send` task/question/review returns a `ladder` (15 s, 60 s as 2x30, 120 s as 3x40, each call <= `inbox_max_wait` 45; `inbox-ladder:` in OPERATOR-PREFERENCES.md, `off` disables); notice/result start none; scheduled and Haiku runs skip.

W42: E4a handoff output ends with the lone `restore as <role> from <capsule path>` code block (only when the capsule was written). E4b secretary restore/register ends with the week-brief Do-line (`week_brief_url` from claude/secretary-standing-rules.md, WARN when unset). C3 `remember this` prompts and `operator-decision` decisions queue one INSIGHT notice to role:secretary (hash dedupe, 5/hour, secret filter, `insight-share: off`); C2 `harness.py intake` appends to the skills intake queue.

Tests: test_hardening_w1, test_wordlists, test_inbox_ladder, test_e4_c3 (new).

## 0.14.5 (2026-10-13): restored agent keeps its leases in the edit guard

- Bug: after `harness_restore` the PreToolUse guard compared the lease holder with the SessionStart agent and denied the restored agent's own edits (post-tool-use auto-commit, session-end and pre-compact had the same stale mapping).
- New hook `harness.py hook post-bind` (PostToolUse, matcher `mcp__.*harness_(restore|register)$`): binds the session to the agent in the tool result's banner.
- Fallback `hook_agent()` in pre-tool-use, post-tool-use, session-end, pre-compact: the transcript banner agent is used only if active/idle, not bound to another session, and (spawn_reason restore or same project as cwd). Other holders still deny.
- Reload does not apply a fix to hooks or the server: restart the Code session after installing 0.14.5.
- Test `tests/test_restore_rebind.py` (7).

## 0.14.4 (2026-10-13): ctx table by model and surface (D-5d771, D-8ee87)

- `ctx_hook.py`: built-in table, model prefix x surface. Plan/handoff = 60%/80% of the surface window for Opus/Sonnet 5.5; windows: Sonnet code 1M, chat/cowork 500k; Opus 500k everywhere; unlisted model 200k at 60/80. Haiku is silent: no plan, handoff or cold-cache text, band always ok.
- Surface: `HARNESS_SURFACE`, else transcript path (cowork, then `/.claude/projects/` = code). Unidentified = smallest window (m-fdfde0867a47).
- Config is an optional override: `ctx_table`, flat `ctx_window_by_model`, `ctx_plan_tokens` / `ctx_handoff_tokens` > 0. Built-in token defaults 130k/160k removed (DEFAULT_CONFIG now 0 = no override). `ctx_mode` default absolute.
- `harness.py ctx_band` and `cold()` use `ctx_hook.band_for`/`limits` (one source of truth). Printed text shows plan/handoff k and window.
- Test `tests/test_ctx_table.py`.

## 0.14.3 (2026-10-08): inbox defaults (t-44ab187ed3)

- protocol: default behaviours. `harness_inbox` at start and end of every reply; after a question/task/review, one `harness_inbox wait=45`, then "still waiting on <id>" and end the turn (no loops). Role wake (D-ec4c9) only for waits over a few minutes.
- refresh: step 3 runs `harness_inbox` even with no Do-line; may end with a final `harness_inbox`.
- restore: one-line default note. Test `tests/test_inbox_default.py`. No server code changes.

## 0.14.2 (2026-10-08): release actor

- `publish`: `release.published` actor = the calling agent (`--agent`, resolved id); "human" only when absent/unknown (operator/CLI path). Test added.

## 0.14.1 (2026-10-08): envoy follow-ups

- `publish`: `release.gate_override` is logged with the calling agent as actor (new `--agent`; unknown or absent = "human"). Reason kept.
- Tests: `tests/test_msvcrt_lock.py` exercises the Windows lock path with a mocked `msvcrt` (acquire/release, error release, contention, timeout). Real Windows test pending.
- protocol: fuller wording from 0.13.5 moved to `skills/protocol/references/cli.md`; SKILL.md keeps one pointer.
- `claim` refused by another holder exits 3 (JSON body still on stdout).
- `publish --pkg`: the package is extracted to a temp dir and its code sha must equal the tree's, else HarnessError before anything is written (also with `--operator-override`). Tests: stale 0.13.6 package vs 0.14.0 tree refused; matching package passes. Existing gate tests now use real zip packages.

## 0.14.0 (2026-10-08): hard release gate, P-40, lock fallback

- M2: `publish` refuses (raises, writes nothing) unless `--accept` names a message from role corpus-envoy whose body has >=8 hex of the package sha, that is later than any REJECT naming that sha, with a verifying chain. A missing package also refuses. One override, `--operator-override REASON`, logged as a `release.gate_override` event.
- M3: P-40 blocks a Haiku agent claiming more than 2 files in one call. `harness_claim`/CLI `claim` accept a list of paths. save/SKILL.md prose cut to one line (the cap stays in `check_capsule_budget`). /plan auto-approve is prose only in proper-planning; no code change.
- M6: FileStore lock uses fcntl, else msvcrt.locking, else an O_EXCL lock file with timeout (30s) and stale-lock break (60s). No change on Mac.
- Tests: `tests/test_release_gates.py` (`python3 -B tests/test_release_gates.py`).

## 0.13.6 (2026-10-08): act on WARNs

- protocol: on corpus/lint WARN act yourself and send kind=review to the owner (D-1e728); reply to waiting mail on init/restore (P-89).
- No server code changes.

## 0.13.5 (2026-10-07): restore picker

- `/restore` with no role runs `harness_admin op=roster` and asks via AskUserQuestion which role to take (open capsule or no live holder first, recommended).
- `/restore -v|verbose` prints a "Restore reads" table (file | portion read) before the state lines. Default off (~1k tokens).
- Pending-draft filing procedure moved verbatim to `skills/restore/references/pending-drafts.md`.
- README commands updated. No server code changes.

## 0.13.4 (2026-10-07): /save

- New skill `save` (`/save`): pre-compaction save without `/handoff`. Records one offloaded capsule (tags save, role:<role>), sets the role-state note to point at it, keeps the role held. A fresh chat resumes with `/restore <role>`.
- README commands list gains `/save`.
- protocol SKILL.md §5: one line, `/save` before compaction, `/handoff` to transfer ownership. To stay within the 600-token lint cap, trimmed three phrases there ("Short bodies.", "don't restate", "(self or your predecessor)").
- No server code changes.

## 0.13.3 (2026-10-07): publish records the package and ACCEPT

- F2: `publish` takes `--pkg <.plugin>` (default `<parent>/<name>-<ver>.plugin`) and `--accept <m-id>`. The registry entry and event gain `pkg_sha` (sha256 of the package) and `accept`; notes start with `ACCEPT <m-id>` or `no ACCEPT`. Output carries `warn` for: no package, no ACCEPT, or an ACCEPT body that does not name the package sha8 (warn only, not a block). A bad or unknown accept id is a HarnessError and records nothing.
- F2: Registry write order is build, `registry.json.tmp` + fsync, ledger event, atomic replace. A tmp failure aborts before the event ("registry write failed, publish aborted"); a replace failure says to rerun publish. Republishing an unchanged version rewrites a drifted registry.json and returns `repaired: true`. `registry` view gains `pkg` and `accept`.
- F3: proof_R covers restore of a no-carry role: the given capsule is accepted, other stale open capsules are superseded, each closed name is listed once, and G3 is skipped on restore.
- F4: 0.13.2 G3 changelog line reworded (restore skips G3).

## 0.13.2 (2026-10-06): stale capsules and visible failures

- G1: Widened close-on-takeover. Restore and handoff also supersede open capsules in the project's handoffs/ whose `from: ... #<id8>` author is superseded or retired, even outside the lineage (same rule as orchestration's handoff-stale, D-15566). Status is compared with quotes stripped and lowercased. The accepted capsule and the handoff's own capsule are never touched.
- G2: `_close_capsules` returns `{closed, errors}` instead of swallowing failures. Restore and handoff text gains `capsules superseded: ...` and/or `capsule close skipped: ...` (each capped at 200 chars) only when non-empty. Still non-fatal.
- G3: A no-carry `harness_register` (role with carry=none) also supersedes stale open capsules (`_close_stale`, split out of `_close_capsules`); the card carries `close_res` and the register text gains the same `capsules superseded:` / `capsule close skipped:` lines. Full-carry roles are unchanged. Restore skips G3 (`_skip_g3`) and closes via `_close_capsules`; its close_res merge is a no-op today.
- G4: `HANDOFF_NAME_RE` constant (mirrors corpus_index.py:75) and `_status_is_open`: `open`, `"open"`, `'Open'`, `open # note` are open; `open xyz`, `opened`, `accepted by ...` are not. Used by the stale scan and by `_set_capsule_status`.

## 0.13.1 (2026-10-06): capsule picker and close-on-takeover

- E1: Capsule picker: the newest capsule record in the lineage decides, with no fallback to older ones. A non-open status shows the card plus `(accepted: no open capsule)`.
- E2: Close on takeover: restore marks the capsule it inlines `accepted by <sobriquet> #<id8> (restore)` and every other open capsule of the lineage `superseded by ... <date>`; handoff supersedes older open capsules before writing the new one. Frontmatter status line only, each committed.
- E3: handoff with state_note and no role keeps the handoff and appends `note skipped: agent has no role`.
- E4: restore skill: note that restore closes stale open capsules; do not edit status by hand.
- E5: restore with no task no longer inherits the predecessor's task line; it sets `<role>: restore` (plus `from <capsule>` when a capsule path is given).

## 0.13.0 (2026-10-06): renamed from harness-router (D-b2c05)

Plugin, MCP server key, banner and docs are now crew-coordinator; `harness_*` tool names and the Exchange/_harness data dir are unchanged.
- A1: Paste-safe bootstrap line from handoff (`restore as <role> from Exchange/<rel>`); restore parses `from <path>` into harness_restore `capsule=`.
- A2: Capsule shown on restore: state note written before the capsule record; digest shows the newest open capsule in the role lineage.
- A3: Fewer calls: restore inlines the capsule body when 1500 tokens or less; handoff() takes `state_note=` and does note, capsule, commit, record, idle-wake disarm and send in one call.
- A4: capsule_md path bug: a one-line existing .md path is registered as the capsule; otherwise it must be markdown text, else rejected.
- A5: handoff ensures `model:` in the capsule frontmatter.
- A6: Idle-wake after handoff: handed_off/superseded stops the wake, stale wake replies "·", handoff skill disarms the armed id, server refuses a second handoff.
- A7: Offline idle-wake save: provisional capsule via project_write, up to 3 retries via send_later +60m, nonce, pending drafts restored.
- A8: Idle gap re-arm `max(5, 55 - mins since last prompt)`; is_wrapper anchored to the wrapper header; notification-wrapper match verified.
- A9: restore banner in register format verified (proof case only).
- B1: Adaptive urgent context warning from the last 3 tool outputs; thresholds unchanged.
- B2: harness_handoff rejects a capsule over 1500 tokens with a size reason; nothing written.
- B3: harness_recall and harness_inbox truncate output over 10,000 chars (head 5000 + tail 5000 + marker) via one helper.
- C3: publish_release refreshes Exchange/_harness/bin, then byte-compares every scripts/*.py; any mismatch fails the publish naming the files. The gate catches write failures only after bin/ is already overwritten: re-run publish after fixing.
- C4: publish_release `--renamed-from <old>`: new registry entry gets `renamed_from`, old entry gets `renamed_to`, old version untouched.

## 0.12.4

Token trims, state_note fix, P11 unpin, idle wake v2 (opt-in).
- A1-A3: Removed "Show this banner verbatim" prefix from SessionStart hook context; dropped "(CLI fallback...)" clause from PROTOCOL_CONTEXT into skills/protocol/references/cli.md; "Role unset" proposal moved from SessionStart to the register/sync responses (only when no role is held) (specs/2026-10-01-build-hr-0.12.4.md).
- B: state_note bug: track norole flag from harness_* responses; don't set dirty while norole; clear dirty on "no role held".
- C: P11 proof reads version from .claude-plugin/plugin.json only (no pinned fallback).
- D: Idle wake v2 (opt-in): config idle_wake_projects list, /idle-wake skill (status/on/off), server appends "idle-wake: on (55m)" per project, hook arms send_later with wrapper prompt checks and notification filters (m-8b859870c6db + envoy feedback).

## 0.12.3

Hotfix: the restore skill description had `<role>`, which the Claude app rejects as an XML tag (install failed). Now `[role]`.
- protocol: dropped the dead "Idle wake not armed" line; mcp_server: with_note comment (envoy nits, m-8b859870c6db).

## 0.12.2

/restore, role state note, absolute thresholds; idle wake removed (design specs/2026-09-30-design-hr-0.12.2-restore.md, envoy ACCEPT m-cf06293e74c7 + m-994ab2c379a6).
- Removed: the 0.12.0 idle auto-handoff (send_later arm loop, m-01f27748d13d A). Config idle_handoff_min / idle_min_ctx are ignored, and the hook deletes the stale $TMP state.
- harness_restore (/harness-router:restore <role>): succeeds the holder, transfers live leases, returns banner + 9-section digest (≤restore_budget 5000). A holder seen <10 min ago needs confirmed=true.
- Superseded-writer guard (B5): send/claim/release/commit/record/task_update/group/set_expertise/handoff/state_note refuse a superseded caller.
- state_note= on send/commit/sync/handoff: kind=context role-state record, superseding the last one, ≤1200 chars. A rejected note never fails the main op. The ctx hook reminds once per turn after unsaved state changes (not in steward runs).
- harness_handoff: one-call handoff (optional capsule file + commit + capsule record, kind=handoff to the operator); leases kept unless release=true.
- Stop hook (local): last exchange → restore.slot → digest row 3.
- Thresholds: ctx_plan_tokens 130k / ctx_handoff_tokens 160k win over the pct bands. Cold-cache hint when the last request was >60 min ago and ctx ≥ plan.
- harness_admin: non-object args → clean error.

## 0.12.1

Admin arg guard (C-01dcf; report m-d2317ac727be).
- harness_admin rejects unknown arg keys for every op (ADMIN_ARGS), naming the allowed keys.
- role_assign: vacating needs an explicit vacate=true (CLI --vacate); a missing target is an error, not a silent vacate.

## 0.12.0

Idle auto-handoff (m-8aa482854c3d, design ACCEPTED m-a51f49cdfae2) + role desc display (D-d876b) + per-model ctx window (operator 2026-09-30).
- ctx_hook: per-session idle state; arm-inject on UserPromptSubmit when no wake is armed; captures send_later trigger_id/fire_at (JSON, regex fallback); wake → re-arm / small-chat no-op / unattended handoff; stale wakes (no state, nonce mismatch) → "·"; `[scheduled]` never arms; manual handoff with an armed wake → delete_trigger reminder. Config idle_handoff_min (55), idle_min_ctx (60000); env HARNESS_IDLE_MIN, HARNESS_IDLE_MIN_CTX.
- Ctx window per model: window_for(); Opus 5.5 / Sonnet 5.5 250k, others ctx_window (200k). ctx_band(model=), CLI `ctx-band --model`.
- Roster and role banner show the role desc.
- Handoff skill: unattended line.

## 0.11.0

Role identity (D-073d3, m-09924c941a9d) and project normalization (D-b9225).
- register `role=` (MCP + CLI `--role`): no-carry roles succeed their last holder without successor_of; full-carry roles only when vacant or via successor_of; spawn_reason `role-claim`.
- role_define `name=` (carry=none only): static sobriquet, e.g. "Corpus Steward". resolve() prefers the single live match.
- Project names normalized on write and at replay.
- ctx_band takes `home` explicitly; fallback reads config thresholds (envoy nits 1,2 of m-2cf364ce5d2d).

## 0.10.3
- Hotfix: harness_sync crashed on every marked sync (`int()` of a dict) because the ctx `base` argument was overwritten by the sync-baseline dict. Now kept as `ctx_base_in`.

## 0.10.2

Context baseline sharing (m-fd3228f223ce).
- ctx_band uses ctx_hook's baseline math via shared `band_for()`; sync `base=` stored per agent; config ctx_baseline fallback; defaults 0.7/0.85 (m-fd3228f223ce, N-449a5).
- (b) mixed-id recall splits budget.
- (f) publish archives stale bin/*.py into bin/_archive.
- CLI `ctx-band`.

## 0.10.1
- 4 skill descriptions rephrased without ": " so the app installer stops re-quoting them, which caused a false "reg ≠code" health flag (N-ee0fb). No code change.


## 0.10.0

Token-cost bundle (m-49e2e934e951, verdicts m-24ed8633fe96, accepted m-632730c9d042).
- (a) `harness_recall ids=` resolves event ids to one-line cards: `m-<12hex>` (seq, from, to, subject, thread/hop, read-by, body), `#N` (event), `t-<10hex>` (one line per message), 8-hex actor (registrations, model, project, role, status). `budget` (tokens) sets body truncation (default 400 chars). Corpus ids still return full text; mixed lists work. Replaces orchestration q.py (now interim).
- (b) `/update` delta view appends `corpus_index.py --check --warn-only --project <yours>` ERROR/WARN lines (cap 8); nothing when clean. `full=true` shows all findings including INFO. /refresh is unchanged.
- (c) Skill descriptions ≤100 chars, total 1181 → 797. `whoami` merged into `ledger` (9 skills).
- (d) protocol: "Load only the tools you call; register/sync/inbox/send cover most sessions." Equal trim elsewhere (2550 → 2549 chars). Mentions event-id recall.
- (e) admin.md: S6 review line `ID | owner | action | flag | tokens | hash | reason` (hash = producing --pass hash; corpus_index accepts legacy 6-field lines).
- (f) `publish` of harness-router refreshes `Exchange/_harness/bin/*.py` (corpus_index HARNESS_PY mirror).
- (g) `harness_send` to an assigned `role:x` returns `role_queued: [role:x→Holder]` instead of `delivered_to: []`; empty `delivered_to` is omitted when role-queued or held.
- Review fixes (m-2c6f78504644): /refresh (do_only) no longer runs the corpus check; `harness_recall` treats a bare 8-digit id as an actor prefix (use `#N` for seqs).

## 0.9.1

D-6d252 (token baseline, m-8d2d84f2d579).
- Scoped `/update`: in the delta view, joins / roles / retirements / expertise changes of agents in other projects and corpus cards from other projects collapse to `+N elsewhere: harness_sync full=true`. `full=true` still shows everything. Project names compare case- and separator-insensitively (`Design_System` = `design-system`).
- protocol: routine checks use `/refresh`; `/update` is project-scoped. Handoff §0 keeps `/update` (resume is significant; the first sync carries predecessor capsule ids).
- All skill descriptions ≤150 chars; total 1709 → 1181.
- handoff: bootstrap line now reads "Assume ownership as <role>: register with the Harness as successor of <id> (project <slug>), then read … and follow §0." Registration is authorized by the operator's own paste, so the auto-mode classifier no longer denies `harness_register` as unauthorized persistence (design-system takeover, 09-29). No approval step added. Template §0 step 3 no longer asks the operator to confirm the role.

## 0.9.0

D-4ee13 (S5–S8), D-041c3 (T2, T3), D-b9225 quick fixes, D-8b713 + D-d01a5 (/prune). Pairs with corpus_index.py S1/S3/S4/S5/T1/T4 (orchestration, shipped 09-29).
- T2: `harness_register` (MCP, CLI) errors without `model=`. Hook registration unchanged.
- T3: send to a vacant `role:x` returns `held` + note instead of a silent `delivered_to: []`.
- S5: corpus-steward `result` / task `completed` must carry `exit=N hash=H`; verified via `corpus_index.py --proof`.
- S6: steward archive limited to orchestration notes, superseded capsules, orphans; else error → kind=review.
- S7: drift Do-line only when the file changed after the agent's baseline (fixes the HANDOFF.template false positive). Open-handoff status from the ledger: capsules of non-superseded authors are never archived (D-8b713 c).
- S8: PROJECT.md no-carry roles register `carry:none` whatever `successor_of` says.
- P2 reason auto-filled only when every entry is a superseded capsule or completed note (D-8b713 amendment 3).
- /health per-project status: flagged ≥ max(500, 20% project live) (D-d01a5); config `prune_min_tokens`, `prune_ratio`.
- C1 `whoami` moved in from agent-delegation; ledger drops "who am I". C3 `handoff` moved in from skill-foundry; Do-line and ctx gauge now say /harness-router:handoff. C4 `/refresh` (`harness_sync do_only=true`); /update is for significant change. C5 `/prune` takes the review; /health is read-only. C6 skills renamed: protocol, ledger, review. C7: deferred; not yet confirmed that a commands/ entry keeps a bare /name.
- SessionStart context adds: delegate mechanical steps to haiku; be brief with the operator unless letters-manager or resume-manager.

## 0.8.0

D-15566 handoff safeguards (operator-approved; skill-curation items P1, P2, P4).
- P1: on a successor's first `/update`, when its model differs from the predecessor's, a Do-line lists the predecessor's last N judgment entries (decisions, archive/pin events, `result` messages) to re-verify against source/disk. N = config `verify_last_n` (default 5).
- P2: `archive` and `pin`/unpin require `reason`: quote each entry's rule-bearing line in "…" (checked against the entry text), or start with `none`. Applies to MCP, CLI (`pin --reason`) and the dashboard. `corpus.pinned` now stores `reason`.
- P4: `archive`/`pin` accept `drafter_model` + `lead_model` (CLI `--drafter-model/--lead-model`); a /health review records both on the event. /health skill step 5 updated.
- `harness_register` description: pass `model=` even if a cached schema lacks it.

## 0.7.0

Model provenance (t-88d62a1ac0, operator-approved): model switches across projects left no record of which model authored which entry.
- `harness_register` takes `model` (the agent's exact model id from its env). Stored on the agent record and shown in the banner. Missing → `model: unknown`, and `/update`'s status line shows `· model ?`. CLI `register --model`; the Claude Code hook reads `HARNESS_MODEL`/`ANTHROPIC_MODEL`.
- Successor mismatch: when `successor_of` is set and the model differs from the predecessor's, the banner shows `⚠ model changed: <old> → <new>` and a `note` (tags `model-change lineage`) is recorded in the corpus. Warns, never blocks.
- Write-time stamp: `corpus.recorded` (every `harness_record`, including handoff capsules), `corpus.pinned` and `corpus.archived` carry `model` automatically (`operator` for operator-only ops). No caller action needed.
- Needs a new chat (or reload + fresh tool list) for the `model` param to appear in a chat's cached `harness_register` schema.

## 0.6.1

- **/health** (D-90088): corpus weight in tokens by kind, project and agent; flags `old-decision` (live, ≥3 handoff generations, uncited) and `orphan` (capsule/note nobody cites); `pin` tag exempts. `harness_admin op=health|archive`, CLI `harness.py health|archive`, dashboard page `/health` with tick-to-archive. Archive = `corpus.archived` event; the log is never rewritten.
- **Context gauge hook**: PostToolUse + UserPromptSubmit read the exact context size from the transcript. At 60% the agent is told to plan a handoff, at 75% to report ctx and run /skill-foundry:handoff (once per band, 0 tokens otherwise). `ctx_band` is now a share of `ctx_window` (config, default 200k; env HARNESS_CTX_WINDOW).
- **Corpus project tagging**: `harness_record` defaults `project` to the recording agent's project. The derived index backfills untagged log entries with the author's project as of that point in the log (no log rewrite). 41/66 existing entries now resolve; 25 by pre-project agents stay blank.

## 0.6.0

Roles (D-68eae). No new tools or params: everything is `harness_admin` ops or `to:` strings, so open chats keep working.
- **Roles**: Project → Role → Agent. `op=role_define` (operator: `role`, `project`, `owns` paths/globs, `partners`, `carry` full|none) and `op=role_assign` (operator; one role per agent; sets the agent's project). A role passes to the successor automatically.
- **`to: role:<name>`**: goes to the role's current holder when read. Waits if the role is vacant, and follows succession.
- **Roster**: `op=roster` returns one line per role, `project` filters, `since=<seq>` returns changes only. Tool results get a `◇n` footer when the roster changed. `/update` `joined:` lines carry the project, and your own role assignment shows as a role card.
- **carry=none** roles (e.g. listings-manager): successors get no predecessor capsules and no inherited sync baseline. Mail still passes on.
- **Governance (notify)**: leasing a file an `owns` pattern matches sends a notice to the owning role. The lease is not blocked.
- **Tickets**: `op=task_update` takes `stage` (workflow step), `to` (passes the ticket on with a one-line notice in its thread) and `digest`. `completed` sends a one-line digest to the operator.
- **Auto-reload** (config `auto_reload`, default off): after replying, the server re-execs onto newer code on disk (checked at most every 60 s; refused if the new code fails to import).
- `op=set_project` (CLI `set-project`) corrects an agent's project. Allowed for the agent itself, an agent it succeeded, or the operator. Logs `agent.updated` with `project`/`project_was`.
- CLI: `roster`, `role-define`, `role-assign`, `set-project`.

## 0.5.1

- `harness_admin op=reload` and `/harness-router:reload`: the MCP server re-execs itself on the code now on disk, over the same stdio pipes, so `run ✕` clears without quitting the app or starting a new chat. It refuses when the code is already current (`force` overrides) or when the new code fails to import. Logs `server.stopped` (reason `reload`) then `server.started`.
- stdin is read unbuffered so a reload can't drop queued requests.
- The `/update` restart action and legend point to reload. A new chat is needed only when a chat's cached tool list lacks a tool or param.

## 0.5.0

- /update token diet (D-f0a68): a quiet sync returns one line (`✓ current #seq`, plus a `ctx` gauge when you pass `ctx`, N-449a5). Otherwise the result leads with `Do:` lines, then `Changed:`, with no box. Health rows appear only when their state changes, identity only on the first sync, and predecessor capsules once. `full=true` / `--full` keeps the old card.
- Every harness tool result gets a `⋯ ✉n · ▲restart · ★n · ctx→handoff` footer when something is pending, and nothing otherwise.
- Operator page: `harness serve` → `/operator` (also `/api/operator`). One row per live agent with project, unread, restart, behind-registry and ctx band, sorted by need.
- Version drift: fleet health now compares live peers with the release registry (`fleet ▼k/m`) instead of the majority. It uses each agent's MCP code stamp, which is fresh on every call, and ignores chats not seen within `fleet_window_h` (config, default 12). Agents now report their inventory at registration, not only at /update.
- Registration requires a project (successors inherit it; `HARNESS_PROJECT` is the fallback). `harness_register` takes `project` and returns the banner only, which shows the project.
- `retire` is allowed only for the agent itself, its successor chain, or the operator (`args.target`, CLI `--target`).
- `VERSION` is read from plugin.json. 0.4.2 servers reported "0.3.1".
- N-39193: the corpus `+N` in /update excludes the syncing agent's own entries.
- Removed the bundled `handoff` skill. /handoff now ships only in skill-foundry (`/skill-foundry:handoff`, D-bc60d).

## 0.4.2

- Fix: `Harness` defined `release` twice (lease release and registry publish), so the second shadowed the first. `harness_release` failed with "not a plugin", and the session-end hook silently skipped releasing leases. Renamed the registry method to `publish_release`; the `publish` CLI calls it.

## 0.4.1

- Shared ignore list (D-42db5): `Exchange/_harness/ignore` plus built-in defaults (.DS_Store, ._*, __pycache__/, *.pyc). Code hash, publish, plugin inventory/drift and the corpus indexer skip matching paths; `harness_claim`/`harness_commit` refuse them. Fixes `reg ≠code`.
- plugin.json: removed the invalid HTML-comment key.
- Trimmed the update, harness-review and harness-protocol skill descriptions to ≤200 chars (fewer tokens in every session).
- /handoff: copies the template skeleton verbatim (keeps §0 and `status: open`); shipped from skill-foundry 0.2.1.

## 0.4.0

Add /handoff skill (shipped from skill-foundry; D-30936).
