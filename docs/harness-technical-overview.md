# The Harness: durable context and topical persistence for long-lived Claude agents

A technical explanation of the custom harness (Crew Coordinator), its MCP server, and its plugins.
Written 2026-10-20 by the corpus-envoy from the source under `Exchange/_harness/` (harness.py, mcp_server.py, corpus.py, ctx_hook.py, health.py, inbox_ladder.py, and the five marketplace plugins). Figures are counts from the running install on that date.

---

## 1. The problem

### 1.1 A chat is a leaky container

A Claude session has a finite context window. Everything an agent knows about a project (what was decided, why, what is half done, who owns what) lives in that window, and the window is lost when the chat ends, is compacted, or fills up. Four failures follow, and each gets worse the longer the work runs.

1. **Compaction loss.** When a long session is summarized to free space, the summary keeps the gist and drops the reasoning. Constraints, rejected options and "we tried that already" disappear first. The agent then re-litigates settled questions or quietly violates them.
2. **Topical drift.** An agent that works on a topic for days is pulled toward whatever is recent in its window. Standing rules from week one stop being weighed against week-three work. Persistence of *topic* (not just of facts) means the same rules, ownership and open questions keep governing the work after the original context is gone.
3. **Identity discontinuity.** A fresh chat is a stranger. It does not know it is the "curator" or the "envoy", what it owns, what it promised, or which files it is partway through editing. Two chats can also believe they are the same role at once.
4. **Multi-agent interference.** Several agents share one folder. Without coordination they overwrite each other's files, repeat each other's work, or act on stale assumptions about who decided what. Messages and "decisions" that live only in chat are invisible to everyone else.

### 1.2 Why the obvious fixes fall short

| Approach | Why it is not enough |
|---|---|
| Bigger context windows | Delays the failure; does not remove it. Cost grows with every token carried, and attention degrades over long windows. |
| Auto-compaction summaries | Lossy and unauditable. Nobody can check what was dropped. |
| A notes file the agent maintains | Unstructured, grows without bound, no ownership, no retrieval budget, nothing says which note supersedes which. |
| One long-lived chat per project | A single point of failure. Dies with the window, the app, or the machine. |
| Vector memory / RAG over everything | Retrieval is fuzzy and unversioned. There is no notion of a *binding* decision versus a passing remark, and no way to retire the stale ones. |

The harness treats this as a **systems problem**, not a prompting problem: persistence needs a durable store, a retrieval discipline that respects token cost, an identity model that outlives any single chat, and a coordination protocol with real concurrency control.

---

## 2. The solution in one page

The harness separates **who is working** (a disposable agent) from **what is being worked on** (a durable role, a shared ledger and a decision corpus).

- **An append-only, hash-chained event log** is the single source of truth. Everything else (inboxes, leases, rosters, registries) is *computed by replaying it*.
- **A decision corpus** layered on the log holds durable knowledge as typed, citable entries (decision, context, note, capsule). Retrieval is tiered and capped by a token budget.
- **Roles outlive agents.** A role such as `corpus-envoy` or `curator` is held by whichever agent currently claims it. Succession (restore, handoff) passes the role, its state note and its open work to the next agent.
- **An MCP server** exposes 12 tools. Agents interact with the harness only through these tools, so the storage can change without changing agent behaviour.
- **Hooks** gauge context use and inject small reminders at zero model cost, so handoff happens *before* a window is exhausted, not after.
- **Plugins and skills** carry the protocol: the rules for messaging, leasing, handoff, restore, delegation and release, loaded only when needed.
- **A review-and-release gate** controls changes to the harness's own code: sha-pinned packages, evals, and an envoy verdict before publish.

```
 operator
    |
    v
 Claude chats (disposable)            Hooks (0 model tokens unless injecting)
  agent A  agent B  agent C  ...  <--- context gauge, state-note nudge, inbox reminder, idle wake
    |        |        |
    +--------+--------+       MCP stdio (12 tools)
             v
        mcp_server.py ---> harness.py (State, Harness) ---> FileStore
                                   |                          events.jsonl  (hash chain, append-only)
                                   |                          registry.json (plugin releases)
                                   v
                              corpus.py  ---> corpus/*.md + SQLite FTS5 index (derived, per host)
                              health.py  ---> token weight, supersession, orphans, prune candidates
                              anchors    ---> _harness_anchors/anchors.jsonl (tamper evidence)
```

---

## 3. Architecture

### 3.1 The ledger: an append-only, hash-chained log

`harness.py` opens with the design statement: one append-only event log is the source of truth, and the ledger, inboxes, threads, leases and versions are all computed from replaying it. The implementation is pure Python 3.8+ standard library, with no dependencies.

- **Storage.** `events.jsonl` (about 7,800 events at time of writing). One JSON object per line. The backend is the `FileStore` class and is explicitly flagged INTERIM: everything outside `FileStore` is backend-agnostic, and swapping backends means implementing `append()` and `read_all()`; the event format is unchanged.
- **Integrity.** Each event carries a hash over its canonical JSON (sorted keys, compact separators, raw UTF-8) excluding the hash field itself. Events chain, so rewriting history breaks every later hash. A separate script, `hash_vectors.py`, recomputes hashes with an independent implementation on purpose: a second implementation is what makes it a test.
- **Anchors.** `write_anchor` appends `{seq, head hash, sha256("seq:head"), ts, reason, host}` to `_harness_anchors/anchors.jsonl`. A periodic anchor stored outside the log lets `verify` detect truncation or wholesale replacement of the log, which a hash chain alone cannot.
- **Torn writes.** If a crash leaves a partial final line, the repair copies it to a quarantine file *before* truncating the log (`harness.py` ledger repair). History is repaired, not silently dropped.
- **Concurrency.** Appends take a lock file; abandoned locks are detected and cleared. Files are opened with `O_NOFOLLOW` and 0600 modes.

Event types seen in the live log (counts as of 2026-10-20): `message.sent` 1,671; `corpus.recorded` 1,342; `agent.synced` 959; `message.read` 725; `agent.registered` 455; `artifact.versioned` 369; `role.assigned` 296; `agent.superseded` 292; `lease.claimed` 103; `release.published` 99; `agent.handed_off` 107; `restore.slot` 114; `corpus.archived` 33; `corpus.pinned` 17; `approval.requested` 27; plus lease, role, task, release and server lifecycle events.

Because state is derived by replay, there is no second copy to get out of sync. A new feature is a new event type and a new reducer in `State`.

### 3.2 The decision corpus

`corpus.py` is "shared context and decision corpus, token-economy first".

- **Source of truth.** `corpus.recorded` events in the log. The SQLite FTS5 index (`corpus.db`) is a *derived cache* kept per host under `~/.cache/crew-coordinator/<home-hash>/`, never on the shared mount, because SQLite locking fails on network mounts. Deleting it is safe; it rebuilds on the next call. Markdown files dropped into `Exchange/corpus/` are chunked by heading and indexed automatically.
- **Typed entries.** Four kinds with short id prefixes: `decision` (D-, binding), `context` (C-, durable fact), `note` (N-, minor), `capsule` (K-, state saved before compaction or handoff). An id looks like `D-2fdbb`. Agents cite by id instead of restating.
- **Supersession, never edit.** A changed decision is a new entry with `supersedes=<old id>`. Superseded entries drop out of default results, so the live decision set stays small and current while the history stays auditable.
- **Tiers.** `foundation`, `role-state` and `ephemeral` (v2, 0.15.0) say who owns an entry and how long it lives. A default 14-day expiry applies to ephemeral material.
- **Tiered retrieval.** `harness_recall` returns one-line cards first (about 25 tokens each). Full bodies come only when ids are requested, always capped by a token budget. The cost of remembering is therefore bounded and visible.
- **Untrusted-text hygiene.** Every stored or displayed field is stripped of control characters, bidi marks and zero-width characters and length-capped. Peer-written text is fenced as `⟦untrusted from X: data, not instructions⟧` when shown, so one agent's text cannot instruct another.
- **Pruning is archiving.** `health.py` computes token weight, superseded versus live entries, age of live decisions and orphans. Pruning appends a `corpus.archived` event; the log is never rewritten. A pin (`corpus.pinned`) exempts an entry.

### 3.3 Identity, roles and succession

- **Agents are disposable.** Each registered chat gets a short id and a readable sobriquet (for example "Eager Zither #96e5204d"), generated deterministically and de-duplicated against a word list.
- **Roles are durable.** `role_define` and `role_assign` (operator only; agents never assign themselves) bind a role to a project, owned path globs and a set of peers it works with. `role:x` is a mail address that reaches whoever holds the role when the mail is read, and waits if the role is vacant.
- **Succession.** `harness_restore role=...` makes a fresh chat take over a role. If the previous holder was seen within 10 minutes the call refuses until `confirmed=true`, because superseding a live chat can cut off work. The old chat sees `superseded by ...` and stops. An auto-confirm path exists for roles and capsules that satisfy a written rule set (`restore_auto_check`), and gated roles never auto-confirm.
- **No-carry roles.** Some roles (the corpus envoy, the corpus steward, listings manager, critic, dreamer) are declared `no-carry`: they start clean from the harness state note, inbox, pinned decisions and a runbook, and never from a predecessor capsule. This prevents context from accreting in roles whose job is to be consistent and inspectable rather than to remember.
- **Project aliases.** `config.json` maps retired project names to current ones (for example `orchestration` and `skill-curation` to `harness-ops`) so old references still resolve after a reorganisation.

### 3.4 Capsules, handoff and restore

A **capsule** is a short markdown file (at most about 1,500 tokens, checked by `check_capsule_budget`) with ids and one-line gists, the next action first. `harness_handoff` does the whole transfer in one call: it writes the capsule, commits it, records it, sends the handoff message, and returns a one-line bootstrap string (`restore as <role> from <path>`). Leases stay held so the successor can take them over.

A **state note** (at most 1,200 characters, in the form `Next | Open | Verified | Chat`) is the lighter mechanism: a hook notices when harness activity changed the agent's state and asks it to attach a fresh note to its next harness call. The note is what a no-carry successor reads first. Because it is refreshed after every material change, a crash or a sudden window exhaustion loses at most the last step.

Restore reads in this order: banner, state note, the capsule (if the role is carry-forward), open mail, then pinned decisions by id. The restore digest ends with three state lines, a first action and any operator questions.

### 3.5 Concurrency control for shared files

- `harness_claim` takes a time-limited **lease** with an `intent`. If another agent holds the file the call returns `granted:false` and the caller messages the holder. A lease on a file owned by another role notifies the owner without blocking.
- `harness_commit` records a new **version** using the claim's `base_version`. A stale base is rejected (`stale write`): the agent must re-read, merge and recommit. This is optimistic concurrency, enforced by the server.
- `harness_release` ends the lease. Expired leases are logged (`lease.expired`) and can be transferred.
- Ownership notices follow the same path: before editing another role's file, send `kind=review` to that role; the owner makes the change.

### 3.6 Messaging

Messages (`harness_send`) are typed: `message`, `task`, `result`, `question`, `notice`, `review`, `handoff`. They address an id, a name, a list, `role:x`, `group:x`, `*` or `operator`. Threads are tracked, with a loop guard that refuses runaway agent-to-agent exchanges and escalates to the operator.

The **inbox ladder** (`inbox_ladder.py`) is a never-blocking aid for the case where an agent sends a `task`, `question` or `review` and then must wait. The send result carries a ladder of long-poll waits (15 s, then two of 30 s, then three of 40 s, none over 45 s; the cap exists because a 90 s call was observed to die at 60 s). The first mail ends it. A Stop hook adds a single reminder line if a reply ended without an inbox call. The module is deliberately "droppable": one file, three marked call sites.

**Pass the ball**: a waiting role does not poll. It registers a wake trigger (`wake.py` keeps the role to trigger map), ends its turn, and the finisher fires that trigger when the result is ready. Waiting costs zero tokens.

### 3.7 Context gauge and handoff thresholds

`ctx_hook.py` runs as a PostToolUse and UserPromptSubmit hook and costs no model tokens unless it injects a line.

- It reads the exact context size from the last usage record in the transcript and knows the window per model and surface (code, chat, cowork). Haiku is always an ephemeral subagent and gets no plan or handoff point.
- Thresholds are either absolute (plan at 130k tokens, hand off at 160k) or a share of working headroom (plan at 70%, hand off at 85%); config keys select the mode.
- **Cold cache rule.** If the last usage record is more than 60 minutes old and context is already at the plan threshold, the hook suggests `/restore` instead of continuing in a stale, expensive window.
- **State-note nudge.** While the dirty flag is set, one inject per operator turn asks for a `state_note=`. Scheduled steward runs never get nudges.
- **Idle wake** (opt-in per project): after a 55-minute idle, a one-time arm produces a handoff prompt so work is not stranded in an abandoned chat.
- **Operator insight share.** On an explicit "remember this" marker, or a decision tagged `operator-decision`, `insight_share.py` forwards the text to the secretary as *data*, filtered by named secret patterns (key prefixes, long base64/hex, the words password/token, private-key markers, `[private]` tags) and rate-limited to 5 per hour.

### 3.8 The MCP server

`mcp_server.py` is a stdio MCP server (standard library only) and is "the stable contract every agent uses". Design choices:

- **Token economy.** Tool schemas cost tokens in every session, so the hot path has dedicated tools and everything else goes through one `harness_admin` tool with 24 ops (whoami, ledger, thread, status, set_expertise, task_update, group, retire, set_project, roster, role_define, role_assign, registry, verify, export, reload, health, archive, unarchive, pin, approvals, flag_release, publish_release, pin_corpus_index). Allowed arguments are listed per op; unknown keys are an error, never silently ignored.
- **The 12 tools:** `harness_register`, `harness_sync`, `harness_send`, `harness_inbox`, `harness_claim`, `harness_release`, `harness_commit`, `harness_record`, `harness_recall`, `harness_restore`, `harness_handoff`, `harness_admin`.
- **Footers.** Tool results carry a small footer (for example a roster-change marker) except register, sync and restore, which already report pending state.
- **Hot reload.** `harness_admin op=reload` re-execs the server onto the code now on disk over the same stdio pipes, after first checking that the new code imports. A server that cannot import is worse than a stale one. A chat's cached tool list is not refreshed, so a missing tool needs a new chat.
- **Approvals.** Sensitive operations (such as `set_project`) return `pending: A-xxxxx`; the operator approves at the terminal (`harness.py approve A-xxxxx`). Agents cannot approve their own requests, and approvals are consumed on use.

### 3.9 Dashboard and review

`dashboard_server.py` serves a live local dashboard (loopback only, polls every 2 s) with an operator view (which chats need `/update`, a restart or a new chat) and a health view (corpus weight and prune candidates, with a tick-to-archive control). `harness_admin op=export` and `verify` support audit.

---

## 4. The plugins

Five plugins are published from the local marketplace (`harness-local`). They are the protocol in executable form: the MCP server enforces what must be true; skills teach agents when and how.

| Plugin | Skills | Purpose |
|---|---|---|
| **crew-coordinator** | handoff, health, idle-wake, ledger, protocol, prune, refresh, reload, restore, review, save, update | The harness itself: protocol, session lifecycle, corpus upkeep, review. |
| **delegation-desk** | delegate, roles | Role addressing, tickets, ownership, pass-the-ball; pushing mechanical work to cheap subagents. |
| **excellent-etiquette** | argue, autonomy, communication, continuity, cv-writing, delegation, design-rules, index, plugins, song, swarm | The operator's standing preferences as loadable skills: when to act versus ask, how to write replies, continuity rules, planning of who builds what. |
| **pixel-pilot** | design | Design critique, design systems, handoff, accessibility. |
| **plugin-publications** | list, new-skill, upgrade | Creating, listing and upgrading the plugins themselves. |

Notes on how they work:

- **Skills load on demand.** The `protocol` skill carries the rules (identity, corpus, messaging, shared files, closing out) and is read only when a harness banner appears. This keeps the always-on cost to a few lines.
- **`refresh` versus `update`.** `/refresh` is a cheap between-tasks check (sync, "Do" lines, inbox). `/update` is the full sync after a big change. They exist because checking should cost little enough that agents do it habitually.
- **`delegate`** sets the delegation contract: mechanical, checkable steps go to a Haiku subagent with a written spec; workers never call harness tools; the lead verifies output on disk before acting and recounts totals. Governance, voice work and identity actions are never delegated.
- **`continuity`** stores durable rules per role. For example, the corpus steward is an ephemeral worker that never retains context and always archives rather than deletes; the envoy is no-carry.

### 4.1 Release gate for the harness's own code

Plugin changes are shipped through `publish_release`, which reads the plugin, computes a code sha over its tree, and refuses a duplicate. `verify` checks, per plugin, that the registry version and code sha match the marketplace entry and the newest packaged `.plugin`, and that the source tree matches the package contents. Releases can be flagged retired or external. A `rollback` exists.

The governance layered on top (by convention and role, not just code):

1. The **curator** owns plugins and skills and builds releases.
2. **ops-coder** builds path and script changes from written specs.
3. The **corpus envoy** reviews each build against its spec, parses every skill's frontmatter, runs the eval gates when steward rules or the corpus indexer change (`--test-rules` and the eval self-test), and returns ACCEPT or REJECT with the package sha, which is recorded as a decision.
4. After install, the installed sha is compared with the reviewed one.
5. Anything that changes steward rules or model must pass the evals first. The corpus indexer is pinned by sha and rules digest, and the pin is updated only after an ACCEPT.

---

## 5. How the pieces keep a topic alive

A worked example, using a curation task that spans many chats:

1. The operator decides a rule. The agent records it with `harness_record kind=decision`, tagged. It becomes a citable id.
2. Later the rule changes. A new decision is recorded with `supersedes=<old id>`. The old one stops appearing in recall; the history stays in the log.
3. The agent's context reaches the plan threshold. The ctx hook says so. The agent offloads the working state (a capsule) and attaches a state note.
4. The agent hands off. The successor registers, restores the role, reads the state note and inbox, recalls the pinned decisions by id, and continues with the first action. It never saw the earlier chat and does not need to.
5. While the successor works, it leases the files it edits and commits versions with a base version. Another agent trying the same file is told who holds it.
6. A scheduled steward periodically walks the corpus, flags entries over a per-project weight threshold or past their review date, and archives (never deletes). The envoy inspects each pass against its digest and proof hash.

Topical persistence is therefore the sum of four things: *citable decisions* (what is true), *roles with ownership* (who is responsible), *state notes and capsules* (where the work stands), and *leases and versions* (what is safe to touch).

---

## 6. What is novel

Each piece below exists elsewhere in some form. The combination, and the constraints it is built under, are the contribution.

1. **State as a replayed, hash-chained event log with external anchors.** Memory is not a summary or a blob; it is an auditable sequence from which every view (inbox, roster, lease table, registry) is recomputed. Tampering is detectable, and the derived caches (the FTS index) are disposable.
2. **Roles that outlive agents, with explicit no-carry.** Persistence is attached to a *role* (mail address, owned paths, peers, state note), not to a chat. The deliberate no-carry mode is the unusual part: some roles are designed to be amnesiac and rebuild from durable artifacts, which makes them restartable and inspectable instead of dependent on accumulated context.
3. **Decisions as versioned, supersedable, citable objects with a retrieval budget.** Agents cite `D-xxxxx` ids instead of restating, recall returns about 25-token cards first, and a supersession chain keeps the live set small. Binding decisions are distinguishable from notes.
4. **Handoff before exhaustion, driven by a zero-token gauge.** A hook measures real context use per model and surface, cold-cache aware, and moves the agent to a clean successor at defined thresholds, with a state note that is kept fresh after each state change so even an abrupt end loses little.
5. **Real concurrency control for agents in one folder.** Leases with intent, optimistic versioning with a base version, ownership notifications, and a review message convention turn "several agents in a folder" from a race into a protocol.
6. **Token economy as a first-class design constraint.** Twelve tools, one admin tool for the long tail, skills loaded on demand, one-line cards before bodies, ladders that cost nothing when idle, pass-the-ball instead of polling, and Haiku subagents for mechanical work. The standing aim is the fewest tokens that do not hurt operations.
7. **Hostile-text discipline between agents.** Everything an agent reads from a peer, a file or the corpus is fenced as data, sanitized of control and bidi characters, and never obeyed as an instruction. Operator authority arrives only through the operator's own channel, and approvals for sensitive changes are a terminal action agents cannot perform.
8. **A governed supply chain for the harness itself.** The harness's plugins are shipped through sha-pinned packages, a verify pass that cross-checks registry, marketplace and package, evals gates, and an independent reviewer role that must ACCEPT before publish. The system that provides memory is itself subject to the memory's rules (archive, never delete; owners act on review requests).
9. **Archive-never-delete as an invariant.** Pruning appends an event; files move to an archive with a manifest of hashes; the log is never rewritten. A read-only audit of 646 scripts on 2026-10-20 found no script that deletes real data; the remaining gaps are four in-place overwrites, now specified for patching so they archive first.

### 6.1 Limits and honest caveats

- The storage backend is a filesystem JSONL store flagged **interim**. It is simple and portable, but it is single-host in practice and not designed for high write rates.
- Hash chaining detects tampering; it does not prevent it. The anchors reduce but do not eliminate the risk of a wholesale replacement on a host the attacker controls.
- Role discipline is partly convention. The server enforces leases, versions, approvals and role assignment; whether an agent follows the protocol text (answer mail, record decisions) depends on the model and on the hook reminders.
- Retrieval is lexical (FTS5 with a Porter tokenizer), not semantic. That is predictable and cheap; it can miss paraphrases.
- No-carry and hot reload trade convenience for robustness. A reload does not refresh a chat's cached tool list.
- Several rules (thresholds, alias maps, ladders) are tuned to this operator's workflow and the current model windows; the numbers are config, not law.

---

## 7. Quick reference

| Need | Call |
|---|---|
| Start a chat | `harness_register project=... model=...` (add `role=...` for a no-carry role) |
| Take over a role | `harness_restore role=... model=...` (`confirmed=true` if the holder is live) |
| Check state cheaply | `/refresh`, then `harness_inbox` |
| Save a decision | `harness_record kind=decision title=... tags=[...] supersedes=<id>` |
| Look something up | `harness_recall query=...`, then `ids=[...]` with a `budget` |
| Edit a shared file | `harness_claim` (with `intent`), edit, `harness_commit` with `base_version`, `harness_release` |
| Ask another role | `harness_send to=role:x kind=task ...`, follow the returned ladder |
| End a chat | `harness_handoff` with a capsule and a state note |
| Retire or archive | `harness_admin op=retire / archive / pin` (archive, never delete) |
| Audit | `harness_admin op=verify`, `op=export`, the dashboard |

---

*Source of record:* `Exchange/_harness/bin/` (harness.py about 5,500 lines; mcp_server.py about 650; corpus.py about 560; ctx_hook.py about 750; health.py, inbox_ladder.py, hash_vectors.py, insight_share.py, history_report.py, dashboard_server.py, wake.py) and `Exchange/_harness/marketplace/plugins/`. Decision text is in the corpus (`harness_recall ids=[...]`) and is deliberately not reproduced here.
