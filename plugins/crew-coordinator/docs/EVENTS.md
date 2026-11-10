# Event log format

The log has one JSON object per line. `hash = sha256(canonical JSON of the event without "hash")`, where canonical means sorted keys and no whitespace. `prev` is the hash of the event before it; the first event's `prev` is 64 zeros.

```json
{"v":1,"seq":12,"ts":"2026-09-23T14:05:11.204Z","t":1790172311.204,"type":"message.sent",
 "actor":"<agent id>","data":{...},"prev":"<hash of seq 11>",
 "via":{"t":"mcp|cli|hook","v":"0.2.1","code":"<12-char plugin code hash>","host":"<hostname>","pid":1234},
 "hash":"<this hash>"}
```

| type | data | effect |
|---|---|---|
| `agent.registered` | id, sobriquet, expertise, expertise_status, task, surface, project, host, machine, session_id, predecessor, spawn_reason | new ledger entry. 0.22.1: `machine` is a 16-hex hash of a stable machine id (the hostname is not one); a nudge reaches a session id only on the same machine |
| `agent.machine` | agent, machine, host | 0.22.1 (A-4d611): the agent's own sync recorded its machine id (a salted 16-hex hash); its host becomes an alias of that machine |
| `agent.updated` | id, expertise?, task?, expertise_status?, project?, project_was? | confirm or correct expertise; correct project (set_project) |
| `role.defined` | role, project, owns, partners, carry, desc | operator defines/updates a role |
| `role.assigned` | role, agent (null = vacant), via? | operator binds a role, or succession passes it on |
| `agent.superseded` | id, successor | compaction lineage |
| `agent.compacting` | id, trigger | marker written before compaction |
| `agent.idle` / `agent.resumed` / `agent.retired` | id, reason? | status |
| `agent.synced` | id, seq, config (fingerprint), summary | an `/update` checkpoint; the next sync is incremental from `seq` |
| `server.started` / `server.stopped` | host, pid, version, code, home, plugin_root | MCP server lifecycle (actor `system`) |
| `corpus.recorded` | id, kind, title, body, tags, project, refs, supersedes, offload, sha | corpus entry (the source for corpus.db) |
| `release.published` | name, kind, version, code, notes, required, path | release registry entry (actor `human`) |
| `session.bound` | session_id, agent | maps a Claude Code session to its current agent |
| `agent.model_set` | agent, model, source, session_id, t_obs | 0.19.0 (R-121): the model the chat's transcript shows; every change is recorded and the observed model wins over a declared one |
| `agent.session_retired` | agent, successor, sessions, host | 0.19.0 (D-b751f): the predecessor's session ids were listed in `_harness/retired_sessions.json` (written once the successor's `agent.registered` and `session.bound` are both in the log) |
| `lesson.curated` | id, hash, by, content_hash?, keys?, cue_hash?, approval? | 0.19.0 (R-122): written only by a granted operator approval (`lesson_curate`); valid while the lesson's content hash (title, body, tags, project, role) still equals `hash`. 0.20.0 (A-2b70b item 5): with cue object keys `{paths, tools, mode}` the approval carries them, `content_hash` is the content hash and `hash` binds content and keys together, so a change to either voids the curation; a curation without keys is unchanged. 0.20.0 M2: `cue_hash` (sha256 over id, When, Rule and canonical keys) and `approval` (the `A-` id of the granted lesson_curate request); the granted `approval.granted` event is now written BEFORE the lesson.curated events it allows, and scripts/lesson_cue.py uses a cue only if a curated event's `cue_hash` is vouched for by that earlier grant of a request carrying the same When, Rule and keys |
| `concept.linked` | entry, concept, role (`about`\|`applies`\|`mentions`), by | 0.20.0 (A-2b70b item 2): links an entry to an ontology concept beside the entry (the entry, its tags and any curation hash are untouched); written by the entry's own role or author, the curator or the envoy; `by` is the writer's role, set by the server; the concept id and the entry are checked; the latest link per entry and concept wins |
| `concept.unlinked` | entry, concept, by | 0.20.0: removes that link; same gate |
| `lesson.shown` | agent, role, ids | 0.19.0 (R-122): the curated lessons one restore digest printed; one event per restore |
| `lesson.cued` | session_id, host_session_id, tool, lesson, mode, matched, input_sha, ts | 0.19.0 (R-113): one firing of the lesson cue hook (ingested from `_harness/cue_spool.jsonl` on sync) |
| `recall.miss` | kind (suspect, unresolved, repeat or reported), ids, query, k, hits, role, note | 0.20.0 (D-b28d7 d): a lookup that missed. suspect: an id request with query= whose id is not in the top k=5 hits for that query; unresolved: the id is not in the corpus; repeat: the same agent repeated the same search within 10 minutes; reported: the agent said so (`harness_admin op=recall_miss`). The call counts live in the derived file `_harness/recall_stats.jsonl`; `op=recall_report` prints the weekly numbers |
| `lookup.cued` | ts, session_id, entry, tokens, query_sha | 0.20.0 (D-b28d7 a): one auto-lookup hint injected at a prompt (ingested from `_harness/lookup_spool.jsonl` on sync; the hook ships off) |
| `notify.queued` | id, kind (`result`\|`operator`\|`approval`), thread, ref, actor, text, due, at, state (`issue`\|`hold`\|`fold`), batch, dropped, approval?, expires? | 0.21.0 (A-ae352 item 1): one push decision, written under the ledger lock. `issue`: the acting agent's own result carried the `notify` Do-line; `hold`: quiet hours (released with the first allowed push after them); `fold`: daily cap reached (released with the next allowed push). `batch` lists held or folded ids that ride in this push, `dropped` lists held approvals that had expired. The text is built from fixed fields only (role or name, kind, ids, for approvals the action and minutes left; a subject comes last, quoted, at most 60 characters). Deduped triggers write nothing. Policy: config.json key `notify` |
| `notify.sent` | id, by | 0.21.0: the agent that was handed the Do-line reports it called PushNotification (`harness_admin op=notify_sent`); only that agent may report, once. Issued but unsent after `digest_after_minutes` is listed for the secretary digest |
| `session.titled` | agent, role, name, title | 0.21.0 (A-ae352 item 5): the agent reports its chat title `ROLE - Sobriquet` (`harness_admin op=session_titled`); accepted only when it equals, as a whole string and case-insensitively, the title for the reporting agent's own current role and name. Role and name are stored apart; the title is never split on the dash |
| `session.title_declined` | agent, role, name, expected | 0.21.0: the agent could not set the title (tool absent in the CLI or cloud, or the app declined); its nudges stay on the migration rule |
| `session.title_refused` | agent, role, name, claimed, expected | 0.21.0: a reported title that was not the reporting agent's own (H1); refused with an error |
| `nudge.offered` | msg, msg_id, from, to, thread, roles, by_id, hids, by_trigger | 0.21.1 (item 4): a send returned a nudge Do-line (the offer, not a delivery). Renamed from `nudge.sent`. `by_id` marks recipients addressed by app session id. 0.22.0 (item 6): written only for recipients with an id or trigger Do-line; `titled` is gone (no title is an address) |
| `nudge.sent` | msg, from, to | legacy name of `nudge.offered` (before 0.21.1); readers count it as an offer |
| `nudge.result` | msg, msg_id, by, for, outcome, reason, evidence | 0.21.1: the sender reports `harness_admin op=nudge_result` outcome delivered, held or skipped (woke accepted, unused); once per message. 0.22.2 (A-0ce70 item 3): `by` = the reporter, `for` = the offer's sender; a relaying agent (not the sender) may report only when its reason carries an HTTP status and a run session id (`cse_…`/`session_…`), kept as `evidence` {http, session, self_reported: true}; the harness checks the shape, not the run. 0.22.3 (A-8a3da): a non-sender may report only delivered, woke or refused_by_app; on a relayed message only the recorded claimer, with evidence {delivery, message_id, self_reported} from the SendMessage result; the HTTP/session form counts only on a trigger-offered message. by=system with reason relay_expired or read_before_relay when a relay offer had no result after 30 min |
| `nudge.relay_offer` | msg_id, to, to_session, from, role, thread, reason | 0.22.3 (A-8a3da item 2): the sender reported skipped no_sendmessage / no_listagents for a recipient role holder with a local_ app session id on this machine (not stale). Does not fill the result slot. Max 30 per sender per hour; one per message |
| `nudge.relay_claim` | msg_id, by, to_session | 0.22.3 (item 3): a live local holder of a relay role (operator.json doorbell.relay_roles, default envoy, curator, ops-coder, harness-critic, design-coder; never the steward), not the recipient, not capped, took the offer under the ledger lock and got one fixed-field SendMessage Do-line; round-robin among warm holders for 2 min, then any holder |
| `nudge.relay_released` | msg_id, by, reason, claimer | 0.22.3 (item 1): the claimer reported refused_by_app; the offer is open again. 0.22.3b: by=system, reason claim_timeout, claimer=<id> when a claim had no report 5 min after it was made; that claimer does not get the same message back |
| `nudge.relay_capped` | agent, until | 0.22.3 (item 1): a relayer the app refused takes no claims until `until` (60 min) or its next delivered report. 0.22.5 (item 4): the weekly report counts these per relayer (`refused_by_app`, `refused_by_relayer`) |
| `nudge.unreported` | msg, msg_id, by, offered_t | 0.21.1: an offer older than the sender's PREVIOUS harness call that still has no result; a later result wins. Offers with no later sender call are counted as pending, not unreported |
| `nudge.stale_id` | msg_id, to, host_session_id | 0.21.1 (v4): written when the sender reports `nudge_result` skipped with a reason starting `stale_id`; that app session id is not offered again until a `nudge.stale_cleared` follows. 0.21.2: read from the last 4 MB of the ledger only; the ledger is the only record of the mark |
| `nudge.stale_cleared` | agent, host_session_id | 0.21.1 (T1): the recipient made a harness call from that app session after it was marked stale; the id route is open again for every sender |
| `nudge.idwake` | to, host_session_id | 0.21.1 (v4): an id-addressed nudge to a cold recipient (last harness call over 1 h ago); at most 1 per recipient per 30 min over all senders; counted apart from offers |
| `nudge.trigwake` | role, to, msg_id, trigger | 0.21.2 (item 1): a nudge Do-line told the sender to fire the role's pinned `trig_` wake trigger (only if SendMessage did not deliver); at most 1 per role and per trigger id per 10 min over all senders; written when offered; counted apart from offers |
| `nudge.trigwake_released` | msg_id | 0.21.2 (item 1): the sender reported `delivered` for an offer that carried a trigger line, so no trigger ran; that wake slot is free again |
| `wake.pinned` | entries {role: trig_... \| {trigger, kind, holder, prompt_sha, link?}} | 0.21.2 (item 1, critic B1): the operator approved `harness_admin op=wake_pin`, a snapshot of wake.json; the doorbell reads triggers only from the latest one (actor human), never from the file. `{}` unpins every role. 0.22.5 (A-797e1 item 3): an entry is a plain `trig_` string (legacy: recurring, no holder, prompt unchecked) or {trigger, kind: recurring\|run_once, holder = the role's agent id at pin time, prompt_sha}. The request carries the prompt text and the harness refuses any text that is not the wake template with the role filled in; the text itself is not stored. The prompt is SELF-REPORTED by the requester: the operator's comparison in the cloud UI is the real control. A pin is stale when its holder is no longer the role's holder and spent when a run_once pin has a reported fire (a `woke` report on a message offered through its trigger, from the sender or a relayer, that does not name an HTTP status other than 200; the number after "HTTP" counts); the doorbell leaves both out of the Do-line and the sync line names the role needing a re-pin |
| `approval.requested` / `approval.granted` / `approval.denied` / `approval.expired` / `approval.consumed` | id, action, args, args_digest, caller, requested, expires (requested); id, channel, by, state, result (granted); id, channel (denied); id (expired, consumed) | operator approvals: an agent asks, the operator grants or denies at the terminal with the digest code; a request lapses (expired) at its TTL; a deferred grant is used once (consumed). Documented in 0.22.0; written since 0.13 |
| `approval.noticed` | id | 0.19.0 (R-120): a failed approval was shown to its requester once (documented in 0.22.0) |
| `release.sim` | plugin, version, code_sha, ok, checks, failed, questions, open_questions, seconds | 0.22.0 (gate G): the installed simulator ran on a candidate before a publish. A log, never a pass token: G reruns it on every publish |
| `release.postcheck` | ok, failures, code_sha, published_seq | 0.22.0 (hook H3): local data checked right after a publish against the list G saved before it |
| `release.drift` | code_sha, root | 0.22.0 (drift check D): the running copy's code sha is in no published or gate-passed entry; one per distinct sha, with a notice to role:curator and role:envoy |
| `release.drift_explained` | code_sha, reason, by | 0.22.0 (D): the curator or envoy explained a drift (`harness_admin op=drift_explain`); publish stops refusing on it |
| `release.gate_override` | name, version, pkg_sha, accept, reason, caller, failed | an operator override passed the publish gates (written since 0.14; documented in 0.22.0). 0.22.0 adds `failed`: the simulator checks it overrode |
| `nudge.alarm` | msg_id, role, to, from, cond (`unread`\|`skipped`\|`unreported`), reason, age_min, suppressed | 0.22.0 (item 7): a nudge whose offer carried an id Do-line, to a holder active within `alarm_active_min` of the send or the scan, went unread past `alarm_unread_min`, or came back skipped for a reason that is not a cap, or unreported. One per message, at most `alarm_per_role_hour` per role; `suppressed` counts the hits the hourly cap held back. Mails role:envoy (ids only) after `alarm_mail_after_days` |
| `nudge.alarm_armed` | t | 0.22.0 (item 7): the first alarm scan; alarms only log until `alarm_mail_after_days` have passed since this time |
| `group.joined` / `group.left` | agent, group | fan-out groups |
| `message.sent` | id, thread, parent, hop, from, to, to_resolved, kind, subject, body, refs, priority, expects_reply, max_hops? | message; `task` and `handoff` kinds also open a task |
| `message.read` | ids | read receipts |
| `task.updated` | task, state, note | A2A-style task state |
| `lease.claimed` / `lease.renewed` / `lease.released` / `lease.transferred` | path, lease_id, ttl, intent, base_version, from/to | exclusive, time-limited claims |
| `artifact.versioned` | path, version, sha, note, source (`manual`\|`auto`) | optimistic version counter |

## Mapping to A2A (Agent2Agent v1.0)

| Harness | A2A concept |
|---|---|
| ledger entry (id, sobriquet, expertise) | Agent Card (identity plus skills) |
| message with `kind=task`/`handoff` | Task, with states submitted → working → input-required → completed/failed/canceled/rejected |
| message body | Message part |
| `refs` plus `artifact.versioned` | Artifact |

This mapping lets the future local orchestrator expose the network over A2A without changing the log.

## Shared-file keys

Paths become `<workspace-folder-name>/<relative path>`, so `/Users/btf/Claude/Projects/Harness_Router/spec.md` (Mac) and `~/mnt/Harness_Router/spec.md` (Cowork VM) resolve to the same key, `Harness_Router/spec.md`. More shared roots go under `"workspaces"` in `_harness/config.json` or in `HARNESS_WORKSPACES`.

## Config fingerprint

Recorded at registration and at every sync. Each item is a SHA-256 hash of: the plugin's version and code tree, `Exchange/_harness/config.json`, `Exchange/OPERATOR.md`, `~/.claude/settings.json`, `~/.claude/plugins/installed_plugins.json`, `~/.claude/CLAUDE.md`, and any `"watch"` paths. The fingerprint carries `_host`. Machine-local items are compared only against a snapshot from the same host. `/update` also compares the running server's code hash with the code on disk, and from the CLI it compares the `via.code` of the agent's last MCP-written event (the "restart needed" check). Pre-0.2 ledgers (`Harness_Router/_harness/events.jsonl`) are never used as a home. If one gains events, `/update` reports a split ledger.

## Canonical JSON and test vectors (pinned in 0.14.6)

The hash input is the event without its `hash` key, serialised as: object keys sorted (by code point) at every level, separators `,` and `:` with no whitespace, non-ASCII written as raw UTF-8 (not `\uXXXX` escapes), numbers as Python's `repr` (`1.0`, `0.1`, `1e-07`), strings with only the JSON-required escapes (`\"`, `\\`, control characters). In Python: `json.dumps(ev, sort_keys=True, separators=(",", ":"), ensure_ascii=False)`, then SHA-256 of the UTF-8 bytes.

`data/hash-vectors.json` holds events with their canonical string and hash (empty data, nested keys, unicode, escapes, floats). `python3 scripts/hash_vectors.py` recomputes them with its own canonicaliser and prints `<n>/<total> match`; `--log <events.jsonl>` recomputes every event in a log. Any other implementation must produce the same hashes for all vectors.

## Added in 0.14.6

| type | data | effect |
|---|---|---|
| `lease.expired` | path, lease_id, holder, expires_t, ttl | written once (actor `system`) when a claim's ttl has run out; State sets `expired_logged` on the lease |
| `log.repaired` | bytes, offset, sha256, quarantine | a torn last line was moved to `_harness/quarantine/` and cut off; earlier events are never rewritten |
| `call.failed` | agent (8 hex), tool, error (clean text, max 200), to (send only, max 60) | 0.16.0: a write tool (send, record, commit, task_update, claim, handoff) failed; actor `system`; never a body, title or other argument; at most 3 per agent per minute; best effort. State ignores it (unknown types are skipped on replay) |
| `bind.mismatch` | bound, agent, tool, mode, executed, bound_is | 0.16.0: now says `mode` (warn) and `executed: true` (warn mode runs the call under the agent named in `agent=`; it is not a rejection). `bound` is the first agent this server process saw and is not an authority |

## Added in 0.23.0 (scope A-08480)

| type | data | effect |
|---|---|---|
| `approval.granted` (changed) | + args_digest | item 1: the grant names the digest the operator saw; a grant whose digest differs from the FIRST `approval.requested` of that id is ignored. A later `approval.requested` with an id already in use is ignored (shown as "N ignored duplicate request(s)"); scripts/lesson_cue.py folds the same way. Grants written before 0.23.0 carry no digest and stay valid |
| `nudge.result` (changed) | evidence + statuses | item 3 gap 2: a relayer's evidence keeps `http` (acceptance unchanged) and adds `statuses`, the fire statuses parsed as for a sender: an HTTP form (`HTTP 404`, `HTTP <404>`, `HTTP status 404`, `HTTP error 500`, `HTTP code 403`, `http_status=404`, `HTTP-404`, `HTTP/2 404`, `HTTPS 404`) or a 4xx/5xx followed by a status phrase (`404 not found`). A `woke` spends a run_once pin when a status is 200 or none is named. The spent set is folded in State (gap 4), not read from a ledger tail |
| `wake.pinned` (changed) | entries {role: {trigger, kind, holder, prompt_sha, link?}} | item 3 gaps 3 and 6: a request or apply with a plain `trig_` string is refused, and so is a dict entry for a role with no live holder (checked at request and at apply). Plain-string pins already in the ledger are read as before |
| `proctor.shadow` | on, approval, by | item 2: written only by the grant of approval `proctor_shadow`; shadow is ON before the first. The value in force at an event's seq is the one used, at write and on replay |
| `case.opened` | case (`X-`), source {seq?, msg_id?, entry?}, source_seq, severity S0-S3, magnitude {recoverability, radius, cost} 1-5, family?, summary, forced?, self_reported, by, instance, sessions | item 2: any registered agent opens a case on one ledger event; the same event (by any key) returns the first case. recoverability 5 forces S0 (`forced: irreversible`) |
| `trace.card` | card (`TC-`), case, subject, preceding [{seq, type, ok}], label "ledger events only", rule_ids, rationale, diff {path, sha}?, source self\|peer, supersedes?, self_reported, by, instance, sessions | item 2: `preceding` is the subject's last 5 ledger events at or before the case's source, set by the server. Self card by the subject; peer card by envoy, harness-critic, proctor, secretary or curator. Never a diff's content |
| `case.classified` | case, cause (rule\|reasoning\|execution\|environment), contributing ≤2, owner (a defined role), family?, shadow, by, instance, sessions | item 2: proctor only; one per instance (chat line) per case; `shadow` set by the server |
| `case.routed` | case, to, backlog_ref?, by, instance, sessions | item 2: proctor only; refused while shadow is on; `to` = the classified owner |
| `case.severity` | case, old, new, reason, approval?, self_reported, by, instance, sessions | item 2: `old` must be the current severity (checked under the ledger lock). The proctor raises any and lowers S1/S2; never lowers an S0. The operator changes any through approval `case_severity` (no expiry); the grant is written before the event |
| `case.severity_proposed` | case, old S0, new, reason, approval, self_reported, by, instance, sessions | item 2: the proctor's proposal to lower an S0; files the `case_severity` request; one open proposal per case |
| `case.sample` | sample (`S-`), cases [1-30], expires_t (≤14 days), by, instance, sessions | item 2: harness-critic only; a case is in at most one open sample |
| `case.audit_blind` | case, sample, cause, owner, severity, by, instance, sessions | item 2: proctor only, on a case in an open sample, by an instance not involved in it (chat line through compaction links, or app session ids, meet a classifier, severity, proposal or close writer); one per instance per case |
| `case.audited` | case, sample?, verdict uphold\|overturn, of_seq, reason, self_reported, by, instance, sessions | item 2: needs this instance's earlier blind; same involvement rule; never changes the case |
| `case.closed` | case, outcome fixed\|routed\|wont_fix\|duplicate\|shadow, ref?, reason, approval?, self_reported, by, instance, sessions | item 2: needs a classification. In shadow the proctor closes only as `shadow`, and an S0 case stays open. An S0 closed as wont_fix or duplicate needs approval `case_close`. `duplicate` names another open case of equal or higher severity; `routed` needs a routed event; `fixed` needs a ref |

`by`, `instance` and `sessions` are set by the server, never taken from input. Case events are written through `harness_admin op=case` only (`harness.py cases` is read-only). On replay a case event that breaks an order rule is not applied and is counted (`rejected case events` in sync); who may write rests on `actor`, which any process can set. Agent free text (summary, rationale, reason) is one line, capped and printed fenced.

Anchors: `<home>/_harness_anchors/anchors.jsonl`, one line `{seq, head, sha256 of "seq:head", ts, reason, host}` per publish and per day. `verify` fails if the log no longer holds the anchored head at the anchored seq. Tamper-evidence against accidental edits and re-chaining only; it is not signing (Wave 2).

Unread marker (0.16.0, not a ledger event): `harness-unread-<agent8>.json` {n, oldest} in the per-user hook state dir, rewritten by the server after a send (recipients) and a read (reader). Counts and a timestamp only. The hook reads it to print one `✉N unread mail` line on a non-harness tool result when mail is older than 2 minutes, at most once per 10 minutes per chat. It does not poll or wake an idle chat.
