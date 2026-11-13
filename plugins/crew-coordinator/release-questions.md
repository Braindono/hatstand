# Release questions

One question per change against the installed release. Answer every one; the gate fails on a blank answer.

## Q-0d04cad2 doline: scripts/doorbell.py::wake_do#9683a5a5
Do-line text changed in scripts/doorbell.py::wake_do (18 line(s)). Which sender acts on it, and what if that sender lacks the tool it names?
Answer: The sender is the live relay holder (envoy first, item 28) that gets the verify or disable Do-line in its own harness tool result; it runs RemoteTrigger get or update and reports wake_verify or wake_disabled. A sender without RemoteTrigger skips it, as the line says (no tool here: skip it). The claim then times out after WAKE_CLAIM_S (5 min) and another relay holder may claim it. Nothing blocks; the routine stays pending or undisabled.

## Q-d93e6a2b event: hook.onecmd
Event type hook.onecmd added. Who reads it, and is docs/EVENTS.md current?
Answer: hook.onecmd (agent, role, blocks, tokens, sha) is written by the Stop hook in observe mode for envoy, curator, ops-coder and steward. Readers: none in code; it is an audit event for the operator and critic (the first-week fail definition reads it). docs/EVENTS.md is current: its rows name hook.onecmd, nudge.alarm_closed and relay.closed (reasons read, trigger_dead, expired).

## Q-cf2a0411 event: nudge.alarm_closed
Event type nudge.alarm_closed added. Who reads it, and is docs/EVENTS.md current?
Answer: nudge.alarm_closed (msg_id, reason reply|read) is written by the alarm scan when the addressee replied on the thread or read the mail. Readers: alarm_scan and alarm_lines (a closed alarm no longer lists or re-fires); the nudge.alarm event itself is kept. docs/EVENTS.md is current: its rows name hook.onecmd, nudge.alarm_closed and relay.closed (reasons read, trigger_dead, expired).

## Q-1f4482e1 event: scripts/doorbell.py::_close_dead#18118c6c
store.append( call, or a function that holds one, changed in scripts/doorbell.py::_close_dead (18 line(s)): a new field or changed payload on an event type. Who reads it, and is docs/EVENTS.md current?
Answer: _close_dead writes relay.closed {msg_id, reason trigger_dead} (new reason value, no new field) and one nudge.miss per message and recipient, both by system and once per message (precheck). Readers of relay.closed: _closed (msg_id only) and its four consumers, relay_expire and _dead_relay_mids, so a new reason is accepted; nudge.miss feeds the sender_silent skip and weekly_report.py. A system nudge.result is never written, so the sender's later report still counts. docs/EVENTS.md is current: its rows name hook.onecmd, nudge.alarm_closed and relay.closed (reasons read, trigger_dead, expired).

## Q-3be12b84 event: scripts/doorbell.py::claim_relay#f6e0b956
store.append( call, or a function that holds one, changed in scripts/doorbell.py::claim_relay (3 line(s)): a new field or changed payload on an event type. Who reads it, and is docs/EVENTS.md current?
Answer: claim_relay (3 lines) now closes a dead offer at claim time through _close_dead instead of claiming it: relay.closed trigger_dead plus nudge.miss (see Q-1f4482e1). No new field on the claim event. docs/EVENTS.md is current: its rows name hook.onecmd, nudge.alarm_closed and relay.closed (reasons read, trigger_dead, expired).

## Q-fc9d3f3f event: scripts/doorbell.py::wake_do#9683a5a5
store.append( call, or a function that holds one, changed in scripts/doorbell.py::wake_do (18 line(s)): a new field or changed payload on an event type. Who reads it, and is docs/EVENTS.md current?
Answer: wake_do writes the existing wake.claim event with the same fields; only who may claim changed (envoy first while warm, item 28). No new field, no new event type. Reader: wake_do itself and the claim timeout check. docs/EVENTS.md is current: its rows name hook.onecmd, nudge.alarm_closed and relay.closed (reasons read, trigger_dead, expired).

## Q-362974aa write: scripts/ctx_hook.py::relay_hook#4cc23f07
File write changed in scripts/ctx_hook.py::relay_hook (1 line(s)). Which path does it write, and what if that path already holds local data the package does not own?
Answer: relay_hook (1 line) now returns None and writes no file; the relay Do-line comes only from the claiming holder's own harness tool result (item 23). Nothing is written, so there is no local data to clash with.

## Q-0686291d write: scripts/harness.py::hook#efb4e23d
File write changed in scripts/harness.py::hook (1 line(s)). Which path does it write, and what if that path already holds local data the package does not own?
Answer: The Stop hook writes one marker file harness-onecmd-<first 8 of agent id> (mode 0600) in the hook state dir (HARNESS_STATE_DIR, default ~/.claude/crew-coordinator/state, mode 0700), holding the last message digest so one message warns once. The file is the package's own per-agent marker; if a file of that name already exists its content is read as a digest and overwritten, and an unreadable or foreign one only causes a repeated warning (errors are swallowed, the hook never blocks).

## Q-f8ea5a37 event: hook.askgate
Event type hook.askgate added. Who reads it, and is docs/EVENTS.md current?
Answer: hook.askgate (agent, role, verdict allow|would_block|block, tokens, section) is written by scripts/ask_gate.py on every evaluated operator question. Readers: none in code; it is the audit event for the observe week (rates by role); counts and a verdict only, never the question text. docs/EVENTS.md is current (it lists it).

## Q-6559dc0b event: hook.idcheck
Event type hook.idcheck added. Who reads it, and is docs/EVENTS.md current?
Answer: hook.idcheck (agent, role, id, verdict, tokens) is written by the PostToolUse hook after harness_send and harness_record for every cited corpus id. Readers: none in code; the audit event for the observe week (unknown and superseded rates). docs/EVENTS.md is current (it lists it).

## Q-5460c863 event: scripts/ask_gate.py::log_event#ffba85de
store.append( call, or a function that holds one, changed in scripts/ask_gate.py::log_event (9 line(s)): a new field or changed payload on an event type. Who reads it, and is docs/EVENTS.md current?
Answer: log_event writes the new hook.askgate event (see Q-f8ea5a37); no other event or field changes. It never raises and writes only when an agent id is known. docs/EVENTS.md is current (it lists it).

## Q-f30bf818 event: scripts/doorbell.py::relay_expire#8af8b9d6
store.append( call, or a function that holds one, changed in scripts/doorbell.py::relay_expire (18 line(s)): a new field or changed payload on an event type. Who reads it, and is docs/EVENTS.md current?
Answer: relay_expire now writes nudge.miss (reason relay_expired) plus relay.closed (reason expired) instead of a system nudge.result. relay.closed readers: _closed (msg_id only) and its four consumers, relay_expire and _dead_relay_mids, so a new reason is accepted; nudge.miss feeds the sender_silent skip and weekly_report.py; the alarm scan reads unread state, not the result (stated in the CHANGELOG, item 34). docs/EVENTS.md is current (it lists it).

## Q-fe3d16dc event: scripts/harness.py::inbox#05ee5225
store.append( call, or a function that holds one, changed in scripts/harness.py::inbox (2 line(s)): a new field or changed payload on an event type. Who reads it, and is docs/EVENTS.md current?
Answer: inbox (2 lines) only switches to the shared unread function (item 30); the events it appends (read markers) keep their fields. No new field or event type. docs/EVENTS.md needs no change.

## Q-d3641ae9 event: scripts/harness.py::register#e5432027
store.append( call, or a function that holds one, changed in scripts/harness.py::register (10 line(s)): a new field or changed payload on an event type. Who reads it, and is docs/EVENTS.md current?
Answer: register (10 lines) now writes agent.superseded {id, successor} for the chat's idle hook-made id when a role agent registers (item 31); same event type and payload as the compaction lineage use since 0.14. Reader: the State fold (lineage, status). docs/EVENTS.md already lists agent.superseded.

## Q-25656e30 event: scripts/harness.py::restore#111830bb
store.append( call, or a function that holds one, changed in scripts/harness.py::restore (14 line(s)): a new field or changed payload on an event type. Who reads it, and is docs/EVENTS.md current?
Answer: restore (14 lines) changes the auto_confirm check (item 29: gates from the ledger, a per-role lock and a holder re-check at registration) and shares item 31's idle-id supersede. It appends the same events as before (agent.registered, agent.superseded, capsule status versions); no new field or type. docs/EVENTS.md needs no change.

## Q-df82b55f event: scripts/harness.py::restore_digest#8fce41f3
store.append( call, or a function that holds one, changed in scripts/harness.py::restore_digest (15 line(s)): a new field or changed payload on an event type. Who reads it, and is docs/EVENTS.md current?
Answer: restore_digest (15 lines) reads the shared unread and owed functions (item 30) so the digest, banner and inbox agree; it appends nothing new (the changed line count is reading code). No new field or event type.

## Q-e8a35681 gate: hooks/hooks.json
Gate file changed: hooks/hooks.json. How does the installed simulator still catch a bad tree with this change?
Answer: The installed simulator still catches a bad tree: the release sim's own checks (setup, I1 to I9) ran against this tree and pass, including I7 once the scope names hooks/hooks.json (items 18 and 32 now name it); the guard test test_guard_hooks_json_unchanged was re-pinned on purpose (the CHANGELOG names the four added entries); no gate function or sim file is edited by this release.

## Q-29a6e625 hook: PostToolUse::mcp__.*harness_(send|record)$::python3 "${CLAUDE_PLUGIN_ROOT}/scripts/harness.py" hook idcheck
Hook changed: PostToolUse matcher 'mcp__.*harness_(send|record)$'. Which tool calls does it now see, and what if it fails?
Answer: PostToolUse after harness_send or harness_record (matcher mcp__.*harness_(send|record)$) runs scripts/harness.py hook idcheck. It sees only those two tool calls of the harness server, reads the cited ids in the sent or recorded text, prints at most one line under 40 tokens and logs hook.idcheck. If it fails the exception is swallowed: the hook prints nothing, never blocks, and the send or record has already happened.

## Q-b2977a02 hook: PreToolUse::AskUserQuestion|mcp__.*AskUserQuestion|SendUserMessage|mcp__.*SendUserMessage|mcp__.*harness_send::python3 "${CLAUDE_PLUGIN_ROOT}/scripts/ask_gate.py" pre
Hook changed: PreToolUse matcher 'AskUserQuestion|mcp__.*AskUserQuestion|SendUserMessage|mcp__.*SendUserMessage|mcp__.*harness_send'. Which tool calls does it now see, and what if it fails?
Answer: PreToolUse (matcher AskUserQuestion, SendUserMessage and harness_send, with the mcp__ prefixes) runs ask_gate.py pre. It sees operator-facing questions: AskUserQuestion, SendUserMessage, and harness_send to the operator (it exits first on a harness_send not to the operator and on text without a question mark). In 0.25.0 it is observe-only: it logs hook.askgate and never denies. On failure (missing or bad gates.json, error) it allows, writes to stderr and does not block.

## Q-3b6617b1 hook: SessionStart::startup|resume|clear|compact::python3 "${CLAUDE_PLUGIN_ROOT}/scripts/ask_gate.py" session
Hook changed: SessionStart matcher 'startup|resume|clear|compact'. Which tool calls does it now see, and what if it fails?
Answer: SessionStart (startup, resume, clear, compact) runs ask_gate.py session, which in 0.25.0 injects nothing into harness chats (the facts index is not injected; item 32). It sees only the session start event. If it fails it prints nothing and the session starts normally (timeout 10 s).

## Q-19528d68 hook: Stop::::python3 "${CLAUDE_PLUGIN_ROOT}/scripts/ask_gate.py" stop
Hook changed: Stop matcher ''. Which tool calls does it now see, and what if it fails?
Answer: Stop (every Stop event) runs ask_gate.py stop. It sees the final assistant message of the chat (transcript read capped at 400 kB), checks it for an operator question, is observe-only (logs hook.askgate, never blocks) and honours stop_hook_active. If it fails or times out (10 s) the Stop completes normally; the existing Stop hook (restore slot, one-command check) is separate and unaffected.

## Q-774b691f event: hook.observe_ended
Event type hook.observe_ended added. Who reads it, and is docs/EVENTS.md current?
Answer: hook.observe_ended (hook askgate|idcheck, until) is written at most once a day per hook by ask_gate.py and the id check after their observe_until date. Readers: none in code; it is the audit event telling the operator the observe period is over so the date gets renewed or the mode switched. docs/EVENTS.md is current (its hook.observe_ended row is there).

## Q-d2217e5a event: scripts/doorbell.py::_attach#516922a9
store.append( call, or a function that holds one, changed in scripts/doorbell.py::_attach (2 line(s)): a new field or changed payload on an event type. Who reads it, and is docs/EVENTS.md current?
Answer: _attach (2 lines) only treats a mail from the named system sender like one from the operator for the nudge attach: no nudge is attached to it. No new field or event type; the events it appends are unchanged. docs/EVENTS.md needs no change.

## Q-14234eb1 event: scripts/doorbell.py::alarm_scan#b6bc8fcb
store.append( call, or a function that holds one, changed in scripts/doorbell.py::alarm_scan (22 line(s)): a new field or changed payload on an event type. Who reads it, and is docs/EVENTS.md current?
Answer: alarm_scan now sends its nudge.alarm notice to role:envoy as the named sender "system" instead of "operator" (item 39); the mail event keeps its fields, only the from value is the new constant, and the notice is never nudged, owed or id-checked. No new event type. Readers of the mail: the envoy's inbox. docs/EVENTS.md needs no change (a sender value, not a field).

## Q-2af39f70 event: scripts/harness.py::_send#eeb92451
store.append( call, or a function that holds one, changed in scripts/harness.py::_send (2 line(s)): a new field or changed payload on an event type. Who reads it, and is docs/EVENTS.md current?
Answer: _send (2 lines) accepts the sender "system" without a roster agent and writes the message event with from "system"; same event, same fields. Readers: the State fold and inbox as for any message; the system sender is skipped by owed_replies, the nudge and the id check. docs/EVENTS.md needs no change.

## Q-0ba44a7e event: scripts/harness.py::hook#dc7e9865
store.append( call, or a function that holds one, changed in scripts/harness.py::hook (60 line(s)): a new field or changed payload on an event type. Who reads it, and is docs/EVENTS.md current?
Answer: harness.py hook (60 lines) in this release writes hook.idcheck and hook.onecmd (new events, rows present), session.bound and agent.resumed (existing, unchanged payloads), and now hook.observe_ended for the id check via idcheck.ended_once (see Q-774b691f). Readers: the State fold for the existing two; the new ones are audit events. docs/EVENTS.md is current (its hook.observe_ended row is there).

## Q-648c5ce5 event: scripts/idcheck.py::ended_once#fbd25f2b
store.append( call, or a function that holds one, changed in scripts/idcheck.py::ended_once (19 line(s)): a new field or changed payload on an event type. Who reads it, and is docs/EVENTS.md current?
Answer: ended_once writes hook.observe_ended {hook, until} once per day per hook (see Q-774b691f) and nothing else. Readers: none in code (audit). docs/EVENTS.md is current (its hook.observe_ended row is there).

## Q-5e36e611 write: scripts/idcheck.py::ended_once#ce175923
File write changed in scripts/idcheck.py::ended_once (2 line(s)). Which path does it write, and what if that path already holds local data the package does not own?
Answer: ended_once writes one marker file observe_ended_<hook> (hook askgate or idcheck) in the ledger store's own folder, holding the date of the last event, so the event is written once a day. The marker is written FIRST and the event only if that write succeeded, so an unwritable marker means no event at all, never a repeat on every call. Only the package writes that name; if a file of that name exists its date is read and overwritten (foreign content only causes one extra event); a write error is swallowed and the hook stays silent.
