# Release questions

One question per change against the installed release. Answer every one; the gate fails on a blank answer.

## Q-d63d97af approval: wake_pin
Approval action wake_pin removed. What does the operator see on the card, and what breaks for a caller?
Answer: No card any more: request_approval('wake_pin') and harness_admin op=wake_pin answer 'removed in 0.24 (D-8ef51): use wake_register'; a pending pre-0.24 request is refused if granted. Callers move to op=wake_register (holder) and op=wake_verify (relay holder). Scope item 13 names it; check_actions exits 0 vs cc0230-release.

## Q-f2140288 doline: scripts/doorbell.py::<module>#10eae92f
Do-line text changed in scripts/doorbell.py::<module> (2 line(s)). Which sender acts on it, and what if that sender lacks the tool it names?
Answer: Module constants only (RELAY_OUTCOMES gains held; timer comments). No Do-line text a sender reads.

## Q-228724b5 doline: scripts/doorbell.py::_do_one#05f8d836
Do-line text changed in scripts/doorbell.py::_do_one (23 line(s)). Which sender acts on it, and what if that sender lacks the tool it names?
Answer: The sender of a ringing kind whose recipient has a trigger. Added: 'run with no body' on every trigger line, and for a verified routine the copied fields (prompt, enabled, session). No RemoteTrigger tool: skip with no_remotetrigger, a relay.

## Q-bcc6dce9 doline: scripts/doorbell.py::relay_do_line#ad8be6ad
Do-line text changed in scripts/doorbell.py::relay_do_line (3 line(s)). Which sender acts on it, and what if that sender lacks the tool it names?
Answer: The relay claimer (a live Code holder of a relay role). The report now offers held, used when the SendMessage result says delivery: queued. Without SendMessage it cannot claim (claimers are local Code holders).

## Q-27eb649f doline: scripts/doorbell.py::relay_trigger_line#fef33b5a
Do-line text changed in scripts/doorbell.py::relay_trigger_line (10 line(s)). Which sender acts on it, and what if that sender lacks the tool it names?
Answer: The relay claimer, as Q-15395c05. The run fields are asked for only for a verified routine; a legacy pin target (fix round 2) reports woke with the status alone.

## Q-d64b3d05 doline: scripts/doorbell.py::rewake_relay_line#e8530f7c
Do-line text changed in scripts/doorbell.py::rewake_relay_line (9 line(s)). Which sender acts on it, and what if that sender lacks the tool it names?
Answer: Any live relay holder (envoy, curator, ops-coder, harness-critic, design-coder on this machine) that claims a rewake offer. SendMessage to the holder's id, or RemoteTrigger run of the role's trigger with no body; no report. A claimer without RemoteTrigger skips it; the sender's own rewake Do-line and the next send stay as carriers.

## Q-a7b6f007 doline: scripts/doorbell.py::wake_do#08bb72b0
Do-line text changed in scripts/doorbell.py::wake_do (47 line(s)). Which sender acts on it, and what if that sender lacks the tool it names?
Answer: A live Code relay holder (relay role, local_ id, this machine): RemoteTrigger get then op=wake_verify, or update enabled=false then op=wake_disabled. Without RemoteTrigger it skips; the claim lapses after 5 min to another holder.

## Q-4ce471b6 doline: scripts/harness.py::<module>#31c5bd95
Do-line text changed in scripts/harness.py::<module> (6 line(s)). Which sender acts on it, and what if that sender lacks the tool it names?
Answer: No Do-line wording changed. The module-level lines are path constants (HOME_CANDIDATES, LEGACY_LOGS, OPS_ROOT_DEFAULT, allowed_roots, PATH_CEILINGS, the desktop config watch) now built with os.path.join; each resolves to the same string (test_c240_item15x under a scratch HOME). Only comment text says <workspace>.

## Q-ddbeb303 doline: scripts/harness.py::sync#f89a049b
Do-line text changed in scripts/harness.py::sync (17 line(s)). Which sender acts on it, and what if that sender lacks the tool it names?
Answer: The envoy, and only the envoy (role check in the compact sync): "⇅ hatstand: <plugin> <version> published <date>, not mirrored: harness_admin op=hatstand_sync (dry run), then push=true". Every envoy chat has harness_admin (MCP or the CLI). It shows until a verified push lands; one line per sync (14b, D-83cb7).

## Q-c9208f94 doline: scripts/release_guard.py::post_check#54f2533a
Do-line text changed in scripts/release_guard.py::post_check (11 line(s)). Which sender acts on it, and what if that sender lacks the tool it names?
Answer: The ok postcheck text gains one line for role:envoy: run harness_admin op=hatstand_sync (dry run), then push=true, and report the commit (D-3660f), naming the published plugin and version. The publisher sees it in the hook output and passes it on; the envoy has harness_admin. A failed postcheck has no such line (item 14 change 1).

## Q-3732cfb2 event: call.failed
Event type call.failed added. Who reads it, and is docs/EVENTS.md current?
Answer: Not a new type: call.failed exists since 0.16.0 (EVENTS.md row, written by mcp_server.py). harness.py now also writes it, actor system, with tool ids_check:<call> when the id check itself raises; the 0.24.0 ids.unverified row says so. Read by weekly_report.py and the proctor trace card, as before.

## Q-db8d10a1 event: ids.unverified
Event type ids.unverified added. Who reads it, and is docs/EVENTS.md current?
Answer: Written by Harness._ids_flag for agent writes with unknown ids (flagged) or an override line (override). Read by the State fold (ids_override_t) for the health line, reason == override exactly. EVENTS.md row added; guard pin updated.

## Q-1fd3169e event: notify.listed
Event type notify.listed added. Who reads it, and is docs/EVENTS.md current?
Answer: Written only by the role secretary (op=notify_listed) when its digest carried the rows. Read by notify._listed (undelivered, decide, dropped). docs/EVENTS.md has the row; hatstand_guard pin updated; P14 passes.

## Q-71474025 event: nudge.miss
Event type nudge.miss added. Who reads it, and is docs/EVENTS.md current?
Answer: Written by doorbell._miss (R1c cap with no relay target or relay cap full; R1b with neither). Read by wake_scan (one per message). EVENTS.md row added. The weekly per-direction count is item 16.

## Q-5bbd7cae event: nudge.result_late
Event type nudge.result_late added. Who reads it, and is docs/EVENTS.md current?
Answer: Written by record_result when the sender reports after a relay's result (R1b), once per message. Never fills the result slot; no reader yet beyond the ledger (item 16 measures). EVENTS.md row added.

## Q-9e595d13 event: nudge.rewake
Event type nudge.rewake added. Who reads it, and is docs/EVENTS.md current?
Answer: Written by _write_rewake (send path or wake_scan). Read by _rewake_due (ladder), rewake_do (sender Do-line) and rewake_lines (sync). EVENTS.md row added.

## Q-d5e11942 event: relay.closed
Event type relay.closed added. Who reads it, and is docs/EVENTS.md current?
Answer: Written by doorbell.close_relays after a message.read (inbox, restore digest). Read by claim_relay/live_claim_line (_closed), relay_notice_lines, and ctx_hook.relay_hook's cheap check. EVENTS.md row added.

## Q-d7cb152c event: release.defect
Event type release.defect added. Who reads it, and is docs/EVENTS.md current?
Answer: Written only through harness_admin op=release_defect by a holder of harness-critic or envoy. Read by State.defect_error (replay, forged rows not applied) and harness.py defects (read-only, fenced). docs/EVENTS.md row added; guard pin updated.

## Q-97a0ecb0 event: scripts/doorbell.py::_attach#aaccbb71
store.append( call, or a function that holds one, changed in scripts/doorbell.py::_attach (49 line(s)): a new field or changed payload on an event type. Who reads it, and is docs/EVENTS.md current?
Answer: Same events; the trigger Do-line passes fields=True for a verified routine. Payloads unchanged.

## Q-0390ef48 event: scripts/doorbell.py::_claim_rewake#be2c856d
store.append( call, or a function that holds one, changed in scripts/doorbell.py::_claim_rewake (28 line(s)): a new field or changed payload on an event type. Who reads it, and is docs/EVENTS.md current?
Answer: New writer of nudge.relay_claim with + key (<msg>#r<n>) under the ledger lock (one claim per key). No result is written.

## Q-fc5b8223 event: scripts/doorbell.py::_miss#cea9f6f6
store.append( call, or a function that holds one, changed in scripts/doorbell.py::_miss (11 line(s)): a new field or changed payload on an event type. Who reads it, and is docs/EVENTS.md current?
Answer: New writer of nudge.miss {msg_id, to, from, reason}, actor system, one per (message, recipient) under the ledger lock.

## Q-7a0a02b5 event: scripts/doorbell.py::_pick_id#f070b005
store.append( call, or a function that holds one, changed in scripts/doorbell.py::_pick_id (7 line(s)): a new field or changed payload on an event type. Who reads it, and is docs/EVENTS.md current?
Answer: nudge.idwake payload unchanged; for the three kinds it is written whenever a cold wake is allowed (R2 replaces the 30-min slot). Handoff keeps the slot (test_c211 moved to handoff).

## Q-871777d9 event: scripts/doorbell.py::_pick_trig#72d924a9
store.append( call, or a function that holds one, changed in scripts/doorbell.py::_pick_trig (10 line(s)): a new field or changed payload on an event type. Who reads it, and is docs/EVENTS.md current?
Answer: nudge.trigwake payload unchanged; for the three kinds no 10-min slot (R2 instead), handoff and result keep it.

## Q-dd40065e event: scripts/doorbell.py::_request_relay#cf42bc43
store.append( call, or a function that holds one, changed in scripts/doorbell.py::_request_relay (24 line(s)): a new field or changed payload on an event type. Who reads it, and is docs/EVENTS.md current?
Answer: nudge.relay_offer gains `fields` (true only when the trigger is a verified routine); a legacy pin in the ok state can now be the trigger target.

## Q-1dcdff78 event: scripts/doorbell.py::_rewake_offer#9f378d8b
store.append( call, or a function that holds one, changed in scripts/doorbell.py::_rewake_offer (15 line(s)): a new field or changed payload on an event type. Who reads it, and is docs/EVENTS.md current?
Answer: New writer of nudge.relay_offer {msg_id, key, rewake, to, to_session, trigger, from, role, to_role, thread, reason rewake_<n>}, actor system, one per key. Read by claim_relay/_claim_rewake and rewake_do. EVENTS.md row added.

## Q-c5435e65 event: scripts/doorbell.py::_write_rewake#48f5223c
store.append( call, or a function that holds one, changed in scripts/doorbell.py::_write_rewake (16 line(s)): a new field or changed payload on an event type. Who reads it, and is docs/EVENTS.md current?
Answer: New writer of nudge.rewake {msg_id, n, role, to, for, via, woken_t}, actor system, once per (message, step).

## Q-b179a213 event: scripts/doorbell.py::alarm_scan#63fee811
store.append( call, or a function that holds one, changed in scripts/doorbell.py::alarm_scan (7 line(s)): a new field or changed payload on an event type. Who reads it, and is docs/EVENTS.md current?
Answer: Same nudge.alarm payload. alarm_scan now also reads nudge.skipped with R2/nb 6 reasons as id offers, so held unread mail can alarm (envoy m-7ffa2d0bcd3c). EVENTS.md row added.

## Q-b8c9a3a7 event: scripts/doorbell.py::claim_relay#0c30cf19
store.append( call, or a function that holds one, changed in scripts/doorbell.py::claim_relay (16 line(s)): a new field or changed payload on an event type. Who reads it, and is docs/EVENTS.md current?
Answer: claim_relay skips closed offers; for a trigger offer it writes nudge.trigwake {role, to, msg_id, trigger, relay: true} after the claim, so the fold links the fire to the routine.

## Q-86c24849 event: scripts/doorbell.py::close_relays#99456a0a
store.append( call, or a function that holds one, changed in scripts/doorbell.py::close_relays (25 line(s)): a new field or changed payload on an event type. Who reads it, and is docs/EVENTS.md current?
Answer: close_relays now also closes rewake offers on a read (relay.closed {msg_id, reason: read}, once per message).

## Q-8dbe84ab event: scripts/doorbell.py::measure_reads#3cd424b9
store.append( call, or a function that holds one, changed in scripts/doorbell.py::measure_reads (58 line(s)): a new field or changed payload on an event type. Who reads it, and is docs/EVENTS.md current?
Answer: New writer of wake.measure {direction, msg_id, carrier, sent_t, fired_t, read_t, seconds_from_sent, seconds_from_fire, ctx_before, reader}, actor system, once per message under the ledger lock; never raises into the read.

## Q-8f0b7ac8 event: scripts/doorbell.py::record_result#7a6c8e6a
store.append( call, or a function that holds one, changed in scripts/doorbell.py::record_result (72 line(s)): a new field or changed payload on an event type. Who reads it, and is docs/EVENTS.md current?
Answer: record_result: a relayer that ever claimed may report once; held needs delivery: queued; a trigger relay reports woke with status (and the item 13 fields for a 2xx). nudge.result payload: evidence may carry relay_trigger.

## Q-1a6afc4c event: scripts/doorbell.py::relay_expire#6d15308b
store.append( call, or a function that holds one, changed in scripts/doorbell.py::relay_expire (4 line(s)): a new field or changed payload on an event type. Who reads it, and is docs/EVENTS.md current?
Answer: relay_expire skips rewake offers, so a rewake never writes a skipped relay_expired result; other offers unchanged.

## Q-fdf62d5e event: scripts/doorbell.py::wake_do#08bb72b0
store.append( call, or a function that holds one, changed in scripts/doorbell.py::wake_do (47 line(s)): a new field or changed payload on an event type. Who reads it, and is docs/EVENTS.md current?
Answer: New writer of wake.claim {trigger, role, what verify|disable, by}, under the ledger lock (one live claim per routine).

## Q-78e2acf9 event: scripts/harness.py::_approve_locked#ab2005ff
store.append( call, or a function that holds one, changed in scripts/harness.py::_approve_locked (12 line(s)): a new field or changed payload on an event type. Who reads it, and is docs/EVENTS.md current?
Answer: Same approval.granted shape as item 4.3; fix round 1 only changes the result text to 'granted, not yet run: <reason>' plus 'the same request retries it'. State stays failed (P5b unchanged).

## Q-af788719 event: scripts/harness.py::_handoff#301e76d7
store.append( call, or a function that holds one, changed in scripts/harness.py::_handoff (3 line(s)): a new field or changed payload on an event type. Who reads it, and is docs/EVENTS.md current?
Answer: agent.handed_off gains role and capsule (path or null). Read by the State fold (role_handoffs) for the send reply's holder state. Older events (message only) fold by the agent's role, capsule none. EVENTS.md row added.

## Q-a0e947dc event: scripts/harness.py::_ids_flag#bd74a0b8
store.append( call, or a function that holds one, changed in scripts/harness.py::_ids_flag (14 line(s)): a new field or changed payload on an event type. Who reads it, and is docs/EVENTS.md current?
Answer: New writer of ids.unverified {call, ref, ids, reason, note?}, actor the calling agent; it never raises into the call.

## Q-430c8e41 event: scripts/harness.py::_ids_gate#8de07745
store.append( call, or a function that holds one, changed in scripts/harness.py::_ids_gate (23 line(s)): a new field or changed payload on an event type. Who reads it, and is docs/EVENTS.md current?
Answer: Writes call.failed only when the check raises (the call then goes on, nothing blocks); no other append.

## Q-e6a846be event: scripts/harness.py::_send#85e94909
store.append( call, or a function that holds one, changed in scripts/harness.py::_send (2 line(s)): a new field or changed payload on an event type. Who reads it, and is docs/EVENTS.md current?
Answer: _send is the 0.23.0 send body renamed, unchanged; message.sent payload unchanged.

## Q-23741737 event: scripts/harness.py::handoff#a8f24196
store.append( call, or a function that holds one, changed in scripts/harness.py::handoff (2 line(s)): a new field or changed payload on an event type. Who reads it, and is docs/EVENTS.md current?
Answer: handoff() is the 0.24.0 item 1 wrapper around _handoff; the only change under it is the agent.handed_off payload above.

## Q-b5646c38 event: scripts/harness.py::hatstand_sync#bf579e94
store.append( call, or a function that holds one, changed in scripts/harness.py::hatstand_sync (25 line(s)): a new field or changed payload on an event type. Who reads it, and is docs/EVENTS.md current?
Answer: hatstand.synced gains verified (true only on exit 0 and a line of the script's own output starting with "hatstand: verified ") and plugins {name: version} from the marketplace plugin.json files. State is now refused when the run exits non-zero with a STOP, even after a pushed commit. Older readers ignore the new fields.

## Q-6797c47f event: scripts/harness.py::inbox#cedb9be4
store.append( call, or a function that holds one, changed in scripts/harness.py::inbox (6 line(s)): a new field or changed payload on an event type. Who reads it, and is docs/EVENTS.md current?
Answer: inbox: after message.read, close_relays (relay.closed) as well as item 16's measure_reads.

## Q-1a8d2dee event: scripts/harness.py::publish_release#a7a3435f
store.append( call, or a function that holds one, changed in scripts/harness.py::publish_release (12 line(s)): a new field or changed payload on an event type. Who reads it, and is docs/EVENTS.md current?
Answer: No event payload changed. publish_release gains a refusal before any event: with --build (dry run too) rule 5e runs on the built package's files and a workspace path raises HarnessError, so nothing is appended. A clean package appends exactly the events it did before.

## Q-796095d1 event: scripts/harness.py::release_defect#810eaa64
store.append( call, or a function that holds one, changed in scripts/harness.py::release_defect (25 line(s)): a new field or changed payload on an event type. Who reads it, and is docs/EVENTS.md current?
Answer: New writer of release.defect {id, plugin, version, found_in, severity, summary, refs, by_role, supersedes}; id and by_role server-set; State.defect_error re-runs inside the ledger lock (racing corrections: one wins, test D4c). No gate, no approval.

## Q-68935bcf event: scripts/harness.py::request_approval#1b001b3e
store.append( call, or a function that holds one, changed in scripts/harness.py::request_approval (16 line(s)): a new field or changed payload on an event type. Who reads it, and is docs/EVENTS.md current?
Answer: request_approval no longer has the wake_pin branch; it raises for wake_pin before anything is written.

## Q-fb6fc184 event: scripts/harness.py::restore_digest#1f969c68
store.append( call, or a function that holds one, changed in scripts/harness.py::restore_digest (26 line(s)): a new field or changed payload on an event type. Who reads it, and is docs/EVENTS.md current?
Answer: restore_digest: the same two calls after its message.read.

## Q-9995f2be event: scripts/harness.py::send#2166f3c0
store.append( call, or a function that holds one, changed in scripts/harness.py::send (1 line(s)): a new field or changed payload on an event type. Who reads it, and is docs/EVENTS.md current?
Answer: Wrapper: id check before _send (refuse mode unless override), then ids.unverified {reason: override} after it; message.sent unchanged. Only agent-facing callers pass ids_check; internal sends do not.

## Q-12313fa8 event: scripts/harness.py::sync#f89a049b
store.append( call, or a function that holds one, changed in scripts/harness.py::sync (17 line(s)): a new field or changed payload on an event type. Who reads it, and is docs/EVENTS.md current?
Answer: No event is appended by the new code in sync: mirror_behind() only reads release.published and hatstand.synced from the events sync already loaded. agent.synced is unchanged.

## Q-dd72675b event: scripts/harness.py::wake_disabled#902e1a0c
store.append( call, or a function that holds one, changed in scripts/harness.py::wake_disabled (8 line(s)): a new field or changed payload on an event type. Who reads it, and is docs/EVENTS.md current?
Answer: New writer of wake.disabled {trigger}, actor the reporting relay holder; only for a trigger in wake_to_disable.

## Q-09c660b5 event: scripts/harness.py::wake_pin_apply#a8d1ec05
store.append( call, or a function that holds one, changed in scripts/harness.py::wake_pin_apply (19 line(s)): a new field or changed payload on an event type. Who reads it, and is docs/EVENTS.md current?
Answer: Removed: wake_pin_apply no longer exists, so wake.pinned is never written again (legacy events stay readable).

## Q-604053a1 event: scripts/harness.py::wake_register#d0d8b244
store.append( call, or a function that holds one, changed in scripts/harness.py::wake_register (13 line(s)): a new field or changed payload on an event type. Who reads it, and is docs/EVENTS.md current?
Answer: New writer of wake.registered {role, holder, trigger, session}, actor the role's current holder (anyone else refused).

## Q-7588f151 event: scripts/harness.py::wake_verify#da7b1d2d
store.append( call, or a function that holds one, changed in scripts/harness.py::wake_verify (36 line(s)): a new field or changed payload on an event type. Who reads it, and is docs/EVENTS.md current?
Answer: New writer of wake.verified {role, trigger, session, holder} or wake.rejected {role, trigger, reason}, actor the verifier.

## Q-4f9dc5fa event: scripts/notify.py::mark_listed#621b45f5
store.append( call, or a function that holds one, changed in scripts/notify.py::mark_listed (27 line(s)): a new field or changed payload on an event type. Who reads it, and is docs/EVENTS.md current?
Answer: New writer of notify.listed {ids, by, dropped}; secretary only, each id once (precheck under the ledger lock). Nothing is deleted; expired rows stay in the ledger.

## Q-a991f776 event: scripts/release_guard.py::post_check#54f2533a
store.append( call, or a function that holds one, changed in scripts/release_guard.py::post_check (11 line(s)): a new field or changed payload on an event type. Who reads it, and is docs/EVENTS.md current?
Answer: release.postcheck payload unchanged ({ok, failures, code_sha, published_seq}); only the returned text gains the Do-line on ok. The published event it names is read, not written.

## Q-539ebdfd event: wake.claim
Event type wake.claim added. Who reads it, and is docs/EVENTS.md current?
Answer: Written by wake_do; read by wake_do (live claims). EVENTS.md row added.

## Q-35242c70 event: wake.disabled
Event type wake.disabled added. Who reads it, and is docs/EVENTS.md current?
Answer: Written by wake_disabled; read by the State fold (wake_disabled, wake_old). EVENTS.md row added.

## Q-c89030ee event: wake.measure
Event type wake.measure added. Who reads it, and is docs/EVENTS.md current?
Answer: Written by doorbell.measure_reads; read by weekly_report.wake_stats (section 8) and by measure_reads (one per message). EVENTS.md row added.

## Q-82127de0 event: wake.pinned
Event type wake.pinned no longer written. Who reads it, and is docs/EVENTS.md current?
Answer: Read by the State fold (wake_pin) and doorbell.wake_pin_state as a legacy pin until stale; hidden once the role has a registration. EVENTS.md row marks it legacy.

## Q-20a8c457 event: wake.registered
Event type wake.registered added. Who reads it, and is docs/EVENTS.md current?
Answer: Read by State._wake_fold -> doorbell.reg_state/_wake_trigger/wake_do/wake_register_do. EVENTS.md row added.

## Q-ef523499 event: wake.rejected
Event type wake.rejected added. Who reads it, and is docs/EVENTS.md current?
Answer: Read by State._wake_fold (state rejected, why) -> wake_reg_lines for the holder. EVENTS.md row added.

## Q-83b9f5dc event: wake.stale
Event type wake.stale added. Who reads it, and is docs/EVENTS.md current?
Answer: Read by State._wake_fold (state stale, field) -> _wake_trigger stops offering it; wake_reg_lines. EVENTS.md row added.

## Q-5f323366 event: wake.verified
Event type wake.verified added. Who reads it, and is docs/EVENTS.md current?
Answer: Read by State._wake_fold (state verified, vseq) -> _wake_trigger, registered_trigger, _fire_check. EVENTS.md row added.

## Q-110bb1ae gate: scripts/harness.py::publish_release
Gate function changed: scripts/harness.py::publish_release. How does the installed simulator still catch a bad tree?
Answer: The gate call (_release_gate, the installed simulator on the candidate) is unchanged and still runs. The new 5e check only adds a refusal earlier in the same function; it cannot turn a failing simulator into a pass.

## Q-6522124c gate: scripts/release_guard.py
Gate file changed: scripts/release_guard.py. How does the installed simulator still catch a bad tree with this change?
Answer: release_guard.py is a post-publish hook, not the simulator. release_sim.py and sim_launcher.py are untouched, so I1/I2 in the simulator still flag every changed local file; the filter applies only to the post-publish check (test_c240_item6 guard).

## Q-dee56b66 gate: scripts/release_sim.py
Gate file changed: scripts/release_sim.py. How does the installed simulator still catch a bad tree with this change?
Answer: One line: the CLI's --home default is os.path.join("~", ...) and resolves to the same folder (GateFiles test reads the expression from the source and compares it byte for byte). No check, threshold or question logic changed.

## Q-44879f38 gate: scripts/retire_guard.py
Gate file changed: scripts/retire_guard.py. How does the installed simulator still catch a bad tree with this change?
Answer: One line: HOME_CANDIDATES built with os.path.join, same three strings at run time. The H1/H2 checks are unchanged; the I9 probes (test_c220_gate, test_c224_sim) pass.

## Q-eb427e74 gate: scripts/sim_launcher.py
Gate file changed: scripts/sim_launcher.py. How does the installed simulator still catch a bad tree with this change?
Answer: One line: the I9 deny_rpm probe command is built from parts and is the same string at run time (GateFiles test). The probe still asks the candidate's H1 to refuse that path; test_c220_gate s4_b2 still fails a hook that drops it.

## Q-180a3e01 write: scripts/ctx_hook.py::relay_hook#0f21d669
File write changed in scripts/ctx_hook.py::relay_hook (1 line(s)). Which path does it write, and what if that path already holds local data the package does not own?
Answer: No file content is written: relay_hook opens <home>/_harness/events.lock in append mode only to probe the flock (LOCK_NB, released at once); the lock file already exists beside the ledger and is never written to.

## Q-5d4ee61a write: scripts/doorbell.py::hook_relay_line#c4c00fea
File write changed in scripts/doorbell.py::hook_relay_line (1 line(s)). Which path does it write, and what if that path already holds local data the package does not own?
Answer: <home>/_harness/nudge_state/<agent>.json: relay_hook_shown (last hook repeat time). The agent's own derived state; excluded from the post-publish check since item 6.

## Q-78342502 write: scripts/doorbell.py::relay_notice_lines#c4c00fea
File write changed in scripts/doorbell.py::relay_notice_lines (1 line(s)). Which path does it write, and what if that path already holds local data the package does not own?
Answer: The same per-agent nudge_state file: relay_notice_shown (msg ids already noticed, bounded to 200).

## Q-b80abc5a write: scripts/doorbell.py::rewake_do#c4c00fea
File write changed in scripts/doorbell.py::rewake_do (1 line(s)). Which path does it write, and what if that path already holds local data the package does not own?
Answer: <home>/_harness/nudge_state/<agent>.json, the agent's own derived state file (rewakes_shown list, bounded to 200). Excluded from the post-publish check since item 6.

## Q-7bdca784 write: scripts/doorbell.py::wake_scan#082c78fb
File write changed in scripts/doorbell.py::wake_scan (1 line(s)). Which path does it write, and what if that path already holds local data the package does not own?
Answer: <home>/_harness/nudge_state/_wake_scan.json, a throttle stamp {last} like _alarm_scan.json. Derived; excluded since item 6.

## Q-bb4eeb4e write: scripts/hatstand_check.py::install#b19c0586
File write changed in scripts/hatstand_check.py::install (3 line(s)). Which path does it write, and what if that path already holds local data the package does not own?
Answer: install writes only into the folder the operator names (default in the write-up: the hooks folder under the git root): the two hooks, the checker, the guard (each via a .tmp file and os.replace), gitconfig and hatstand-hooks.json. It replaces those six names only; any other file in the folder is left alone. Nothing under the harness home is written.

## Q-93ba5217 write: scripts/hatstand_check.py::main#45c1b463
File write changed in scripts/hatstand_check.py::main (1 line(s)). Which path does it write, and what if that path already holds local data the package does not own?
Answer: scan-history --write-baseline writes the baseline JSON (object, rule, line; no matched text) to --baseline or <lists>/hatstand-scan-baseline.json, replacing it. Only on that explicit flag; the curator runs it after the scrub.

## Q-b280eeb0 write: scripts/plugin_update.py::_log#8323d930
File write changed in scripts/plugin_update.py::_log (1 line(s)). Which path does it write, and what if that path already holds local data the package does not own?
Answer: plugin_update.py appends one tab-separated line to <home>/_logs/plugin_update.log (a log the script owns, append mode, never under _harness); only under --apply. Existing lines are never rewritten.
