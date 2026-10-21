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
| `agent.registered` | id, sobriquet, expertise, expertise_status, task, surface, project, host, session_id, predecessor, spawn_reason | new ledger entry |
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

Anchors: `<home>/_harness_anchors/anchors.jsonl`, one line `{seq, head, sha256 of "seq:head", ts, reason, host}` per publish and per day. `verify` fails if the log no longer holds the anchored head at the anchored seq. Tamper-evidence against accidental edits and re-chaining only; it is not signing (Wave 2).
