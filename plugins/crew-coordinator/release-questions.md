# Release questions

One question per change against the installed release. Answer every one; the gate fails on a blank answer.

## Q-238250e5 doline: scripts/harness.py::<module>#416d4c8f
Do-line text changed in scripts/harness.py::<module> (1 line(s)). Which sender acts on it, and what if that sender lacks the tool it names?
Answer: The changed text is the sync Changed-list overflow wording (CHANGED_CAP, '+N more (harness_sync full=true)' and the counted joins, role moves and threads, each naming full=true). The sender is the agent that called harness_sync itself, so it always has the tool the line names; there is no relay or other-tool step in it, and nothing breaks if the caller ignores the hint (it only sees fewer lines).

## Q-b05a0d18 doline: scripts/harness.py::sync#2a132c79
Do-line text changed in scripts/harness.py::sync (32 line(s)). Which sender acts on it, and what if that sender lacks the tool it names?
Answer: The changed text is the Changed-list overflow line in sync (`+N more (harness_sync full=true)`), now computed after decision cards (new D- cards) and task lines are set aside as never cut; the sender that acts on it is the agent that called harness_sync itself, which by definition holds harness_sync. There is no relay or other-tool step: if the caller ignores the hint it only sees fewer peer lines (decision cards, task lines, operator and config lines are always shown), and nothing breaks.

## Q-a95070d9 event: hook.barepath
Event type hook.barepath added. Who reads it, and is docs/EVENTS.md current?
Answer: hook.barepath (agent, role, paths, exts, sha) is written by the Stop hook in scripts/harness.py (check in scripts/barepath.py) when a final reply names a local .md, .pdf or .docx path and no SendUserFile or Artifact publish ran that turn. Readers: none in code; it is an audit event for the operator and critic, and carries counts, extensions and a hash, never the path. docs/EVENTS.md is current: it has new rows for message.read (via), owed.closed, result.measured, hook.virtue and hook.barepath.

## Q-218c5fab event: hook.virtue
Event type hook.virtue added. Who reads it, and is docs/EVENTS.md current?
Answer: hook.virtue (agent, role, sha, mailed, chars) is written by the new UserPromptSubmit hook (scripts/ctx_hook.py virtue) when a prompt contains the word virtue. Readers: none in code; the mail it sends goes to role:secretary as one notice from sender system with session, role, prompt sha and length and no prompt excerpt, so the event itself is an audit record for the operator. docs/EVENTS.md is current: it has new rows for message.read (via), owed.closed, result.measured, hook.virtue and hook.barepath.

## Q-a7b07401 event: owed.closed
Event type owed.closed added. Who reads it, and is docs/EVENTS.md current?
Answer: owed.closed (msg_id, key role:<r> or agent id, role, reason?) is written by Harness.owed_close (harness_admin op=owed_close) when a role dismisses an owed item addressed to it. Readers: State fold (st.owed_closed), then doorbell owed_replies, open_task, _closed_for in wake_scan and _wake_block, and _answered (returns 'closed'). docs/EVENTS.md is current: it has new rows for message.read (via), owed.closed, result.measured, hook.virtue and hook.barepath.

## Q-f9d2f53b event: result.measured
Event type result.measured added. Who reads it, and is docs/EVENTS.md current?
Answer: result.measured (tool, calls, bytes, max) is written by the MCP server through Harness.measure and measure_flush, one event per tool every 25 calls or 30 minutes and at server stop or reload, actor system. Readers: none in code; it exists for the next token audit to rank results by size without reading text. docs/EVENTS.md is current: it has new rows for message.read (via), owed.closed, result.measured, hook.virtue and hook.barepath.

## Q-195a35ec event: scripts/ctx_hook.py::virtue_check#a8ee9289
store.append( call, or a function that holds one, changed in scripts/ctx_hook.py::virtue_check (41 line(s)): a new field or changed payload on an event type. Who reads it, and is docs/EVENTS.md current?
Answer: virtue_check still writes the same hook.virtue event (agent, role, sha, mailed, chars) and one notice to role:secretary from sender system; round 3 only extends the mail text with the step the secretary can take (ask the operator in its own chat whether he named a virtue; record it as a design imperative or drop the notice) and still carries no prompt text. Readers: the secretary's inbox for the mail, none in code for the event; docs/EVENTS.md is current (the hook.virtue row names the step; no field change).

## Q-a8b487a2 event: scripts/doorbell.py::_attach#5725e4ae
store.append( call, or a function that holds one, changed in scripts/doorbell.py::_attach (18 line(s)): a new field or changed payload on an event type. Who reads it, and is docs/EVENTS.md current?
Answer: _attach (18 lines) changes only which sends get a relay or a ring: a result or handoff reply rings, relays and rewakes like an ask when the recipient asked on that thread or its role has a verified wake routine; the events it writes (nudge.offered, nudge.relay_offer, nudge.rewake) keep their fields. No new field or event type; readers are the sender's own tool result and the wake scan. docs/EVENTS.md needs no change.

## Q-115b4487 event: scripts/doorbell.py::_request_relay#43e524b7
store.append( call, or a function that holds one, changed in scripts/doorbell.py::_request_relay (4 line(s)): a new field or changed payload on an event type. Who reads it, and is docs/EVENTS.md current?
Answer: _request_relay writes nudge.relay_offer with unchanged fields; the 4 changed lines only keep it from refusing "one ring per recipient session" when the earlier delivered/woke nudge.result carries a to_session of another recipient (single-recipient offers). Readers: relay holders via claim_relay and the relay expiry/alarm scans; docs/EVENTS.md is current (the nudge.result round 3 row says one relay is offered per message).

## Q-41f127e6 event: scripts/doorbell.py::alarm_scan#0a95243d
store.append( call, or a function that holds one, changed in scripts/doorbell.py::alarm_scan (2 line(s)): a new field or changed payload on an event type. Who reads it, and is docs/EVENTS.md current?
Answer: alarm_scan writes nudge.alarm, nudge.alarm_armed and nudge.alarm_closed with unchanged fields; the 2 changed lines read results through _drop_partial, so one recipient's per-recipient nudge.result (to_session) no longer counts as the whole send being reported until every recipient session has reported. Readers of the alarm events are unchanged (the envoy sync line and mail). docs/EVENTS.md is current (nudge.result round 4 row names the alarm reader); NOT VERIFIED: I did not run the scan with a two-recipient send.

## Q-2ca5fbdc event: scripts/doorbell.py::claim_relay#762c6f87
store.append( call, or a function that holds one, changed in scripts/doorbell.py::claim_relay (4 line(s)): a new field or changed payload on an event type. Who reads it, and is docs/EVENTS.md current?
Answer: claim_relay writes nudge.relay_claim and nudge.relay_released with unchanged fields; its two precheck loops now stop a claim or release only on a nudge.result that closes this offer (_closes: a whole-message result, or one whose to_session is this offer's recipient), so another recipient's report no longer blocks the claim. Readers: the relay holders and the relay scans; docs/EVENTS.md is current (nudge.result round 4 row: a recipient's result closes only its own relay offer).

## Q-a2a5dcf4 event: scripts/doorbell.py::record_result#96481a7c
store.append( call, or a function that holds one, changed in scripts/doorbell.py::record_result (27 line(s)): a new field or changed payload on an event type. Who reads it, and is docs/EVENTS.md current?
Answer: record_result writes nudge.result with no new field in round 4 (to_session is the round-3 field); the changes are that a per-recipient report leaves the send pending (_pop_pending is skipped until every recipient session has reported) and the readers drop partial results through _drop_partial, so the unreported, expiry, alarm and wake-block scans (_first_results, _results, alarm_scan) do not take one recipient's result for the whole send. docs/EVENTS.md is current (nudge.result round 4 row). NOT VERIFIED: the reader at doorbell.py line 670 and the nudge.rewake/relay close readers at 1780-1900 were not all traced for use of the filtered results.

## Q-6c684c9c event: scripts/doorbell.py::relay_expire#f3454527
store.append( call, or a function that holds one, changed in scripts/doorbell.py::relay_expire (5 line(s)): a new field or changed payload on an event type. Who reads it, and is docs/EVENTS.md current?
Answer: relay_expire writes relay.closed {msg_id, reason read|expired} with unchanged fields; its duplicate check now treats a nudge.result as closing the offer only when it is a whole-message result or carries this offer's to_session, so another recipient's report no longer stops the expiry of an unanswered offer. Readers: claim_relay and the relay view, the weekly report; docs/EVENTS.md is current (relay.closed row plus the nudge.result round 4 text on expiry).

## Q-0cfd0bbe event: scripts/harness.py::_measure_write#7f4fbb8b
store.append( call, or a function that holds one, changed in scripts/harness.py::_measure_write (4 line(s)): a new field or changed payload on an event type. Who reads it, and is docs/EVENTS.md current?
Answer: _measure_write writes the new result.measured event (see Q-f9d2f53b), popping the in-memory counter for one tool. Readers: none in code, the next audit. docs/EVENTS.md is current: it has new rows for message.read (via), owed.closed, result.measured, hook.virtue and hook.barepath.

## Q-2be7ebab event: scripts/harness.py::_read_by_reply#ecd2b7f1
store.append( call, or a function that holds one, changed in scripts/harness.py::_read_by_reply (18 line(s)): a new field or changed payload on an event type. Who reads it, and is docs/EVENTS.md current?
Answer: _read_by_reply writes message.read {ids, via: 'reply_to'} for the addressee when its reply_to names a mail it was addressed to and had not read; the new via field is optional. Readers: State fold (read_by), inbox, owed and wake scans, wake.measure and relay.closed through measure_reads and close_relays. docs/EVENTS.md is current: it has new rows for message.read (via), owed.closed, result.measured, hook.virtue and hook.barepath.

## Q-5c032696 event: scripts/harness.py::_recall_marks_read#a9b2cdef
store.append( call, or a function that holds one, changed in scripts/harness.py::_recall_marks_read (17 line(s)): a new field or changed payload on an event type. Who reads it, and is docs/EVENTS.md current?
Answer: _recall_marks_read is new and writes message.read {ids, via: "recall"} for an addressee (lineage, group or role) who recalls an m- id they had not read; it never raises and is called from recall after event cards. Readers: State fold (read_by), inbox, owed and wake scans, measure_reads and close_relays. docs/EVENTS.md is current: the message.read row now names via "recall"; this is also what clears a cut inbox mail.

## Q-fb8faeee event: scripts/harness.py::_send#7f44faed
store.append( call, or a function that holds one, changed in scripts/harness.py::_send (16 line(s)): a new field or changed payload on an event type. Who reads it, and is docs/EVENTS.md current?
Answer: _send (16 lines) drops the old ladder hint from the send result and, when reply_to is set, calls _read_by_reply (message.read via reply_to) plus measure_reads and close_relays, so existing wake.measure and relay.closed events can follow. message.sent keeps its fields. docs/EVENTS.md is current: it has new rows for message.read (via), owed.closed, result.measured, hook.virtue and hook.barepath.

## Q-0832b384 event: scripts/harness.py::hook#51ed6083
store.append( call, or a function that holds one, changed in scripts/harness.py::hook (40 line(s)): a new field or changed payload on an event type. Who reads it, and is docs/EVENTS.md current?
Answer: hook (40 lines) now appends the new hook.barepath event from the Stop hook (once per message, marker file per agent), switches the reminder to inbox_reminder, and adds the compaction-successor state block to the SessionStart output. Readers of hook.barepath: none in code (audit). docs/EVENTS.md is current: it has new rows for message.read (via), owed.closed, result.measured, hook.virtue and hook.barepath.

## Q-f09388fd event: scripts/harness.py::inbox#e6cc6264
store.append( call, or a function that holds one, changed in scripts/harness.py::inbox (25 line(s)): a new field or changed payload on an event type. Who reads it, and is docs/EVENTS.md current?
Answer: inbox still writes message.read {ids} with no new field; round 4 only changes which ids go in: a cut mail (over 1,000 characters, not task/question/review/handoff/expects_reply/operator) is left unread, except at its second listing when its recipient has no ask waiting on it (via _cut_listed), when it is marked read with the pointer kept. Readers: State fold read_by, owed and wake scans, measure_reads and close_relays (which get only the read ids). docs/EVENTS.md is current for the recall rule (message.read row, round 4: a truncated recall marks nothing read; budget= raises the cut); the second-listing read is not described in EVENTS.md, which is fine as no event field changed.

## Q-2fad1771 event: scripts/harness.py::owed_close#2de3c351
store.append( call, or a function that holds one, changed in scripts/harness.py::owed_close (34 line(s)): a new field or changed payload on an event type. Who reads it, and is docs/EVENTS.md current?
Answer: owed_close (harness_admin op=owed_close) still writes owed.closed {msg_id, key, role, reason?} only for items addressed to the caller; mail whose sender is in OPERATOR ("human", "operator"), his tasks included, is now skipped and returned as `refused_operator_mail` with a reason, with no event written. Readers: State fold owed_closed, then owed_replies, open_task, wake scans and _answered; docs/EVENTS.md is current (owed.closed row, round 3 refusal sentence).

## Q-ca4c10fe event: scripts/harness.py::publish_release#bf4f6d28
store.append( call, or a function that holds one, changed in scripts/harness.py::publish_release (14 line(s)): a new field or changed payload on an event type. Who reads it, and is docs/EVENTS.md current?
Answer: publish_release (14 lines) adds an optional hotfix field to release.published (the RD id) when --hotfix waived the cadence check, and the notes gain 'cadence waived by RD-id'; with --operator-override it now prints a warning that --hotfix was ignored (no event change). Reader: the State fold hotfix_used (a defect is used once). docs/EVENTS.md is current: the release.published row lists the optional hotfix field.

## Q-ff748044 event: scripts/harness.py::restore_digest#5544147f
store.append( call, or a function that holds one, changed in scripts/harness.py::restore_digest (9 line(s)): a new field or changed payload on an event type. Who reads it, and is docs/EVENTS.md current?
Answer: restore_digest (9 lines): the 'Owes reply' section lists operator asks first, then oldest first, each with its age, at most 5 lines plus '+N more owed (harness_admin op=thread)', and prints one WARN line when the inbox-ladder preference is present and ignored. The events it appends (read markers for shown mail) keep their fields. docs/EVENTS.md needs no change.

## Q-9403298c event: scripts/harness.py::sync#2a132c79
store.append( call, or a function that holds one, changed in scripts/harness.py::sync (32 line(s)): a new field or changed payload on an event type. Who reads it, and is docs/EVENTS.md current?
Answer: The only store.append in sync is the unchanged agent.machine event; the 32 changed lines concern the Changed list (decision cards and task lines kept out of the cap, the fence counted as two lines, +N more line), so no event or payload changed. No reader impact; docs/EVENTS.md needs no change.

## Q-fae30826 event: scripts/mcp_server.py::main#cddbbb3d
store.append( call, or a function that holds one, changed in scripts/mcp_server.py::main (1 line(s)): a new field or changed payload on an event type. Who reads it, and is docs/EVENTS.md current?
Answer: main (1 line) calls h.measure_flush() before server.stopped, so pending result.measured counters are written at server stop. Readers: none in code (audit). docs/EVENTS.md is current: it has new rows for message.read (via), owed.closed, result.measured, hook.virtue and hook.barepath.

## Q-5744544a event: scripts/mcp_server.py::reexec#cddbbb3d
store.append( call, or a function that holds one, changed in scripts/mcp_server.py::reexec (1 line(s)): a new field or changed payload on an event type. Who reads it, and is docs/EVENTS.md current?
Answer: reexec (1 line) calls h.measure_flush() before the server.stopped event (reason reload), so result.measured counters are not lost on a reload. Readers: none in code (audit). docs/EVENTS.md is current: it has new rows for message.read (via), owed.closed, result.measured, hook.virtue and hook.barepath.

## Q-e8a35681 gate: hooks/hooks.json
Gate file changed: hooks/hooks.json. How does the installed simulator still catch a bad tree with this change?
Answer: hooks/hooks.json gains one entry for 0.27.2: a PostToolUse command attach_hook.py on matcher mcp__.*publish_files.*|Artifact (timeout 5); no existing hook is touched and no PostToolUseFailure entry is added. The installed simulator still catches a bad tree through its own checks on the scratch copy (setup, I1 to I9, including the gate-file rule I7c, which fails unless a scope item carries the exact phrase 'Gate file changed: hooks/hooks.json', and this release's scope has it). The attach hook decides nothing in 0.27.2: it writes shape lines and never prints.

## Q-110bb1ae gate: scripts/harness.py::publish_release
Gate function changed: scripts/harness.py::publish_release. How does the installed simulator still catch a bad tree?
Answer: The change adds a hotfix argument: _check_hotfix runs first and refuses (HarnessError) a flag that is not a recorded S1 or S2 defect of this plugin that names the published version and is unused; it waives only _check_release_cadence, while _check_accept_gate and _check_release_scope still run before it, and --operator-override ignores it. The installed simulator is unchanged (release_sim.py is not in the diff) and still runs the candidate's publish on a scratch copy of the ledger (I1 and I2 hash before and after, I7 with scripts/harness.py named as a gate file in the CHANGELOG); a bad hotfix path is refused with nothing written.

## Q-420b1ec7 hook: UserPromptSubmit::::python3 "${CLAUDE_PLUGIN_ROOT}/scripts/ctx_hook.py" virtue
Hook changed: UserPromptSubmit matcher ''. Which tool calls does it now see, and what if it fails?
Answer: It sees every UserPromptSubmit event (matcher ''), not tool calls: a command running ctx_hook.py virtue that acts only when the prompt contains virtue(s). Scheduled runs, notification wrappers and cross-session messages are skipped, and it is once per distinct prompt per session. On any failure it logs through _log, prints nothing and exits 0, so the prompt is never blocked; at worst no secretary notice or hook.virtue is written.

## Q-d986ae7d write: scripts/harness.py::_cut_listed#f9acbfed
File write changed in scripts/harness.py::_cut_listed (3 line(s)). Which path does it write, and what if that path already holds local data the package does not own?
Answer: It writes `<home>/_harness/nudge_state/cut_listed_<agent id, first 64 chars>.json` (store.dir is home/_harness; the folder is the runtime state folder listed in release_guard RUNTIME_PREFIXES, not the plugin package), a JSON map of cut mail id to listing count, via a temp file `<path>.<pid>.tmp` and os.replace, at most 300 entries. An existing file is read and overwritten with the updated counts; if it holds invalid JSON or a non-dict, it is treated as empty and replaced; if it cannot be read or written, the exception is swallowed and the mail is simply not aged (stays unread until recalled), with no ledger event and no data lost beyond that file. It is written on every inbox listing that contains a cut mail (mark_read on), also for mail that is not yet aged. NOT VERIFIED: a leftover .tmp file is not cleaned when os.replace fails.

## Q-6f4878c7 write: scripts/harness.py::hook#97adc474
File write changed in scripts/harness.py::hook (1 line(s)). Which path does it write, and what if that path already holds local data the package does not own?
Answer: The Stop hook writes the marker file harness-barepath-<first 8 of agent id> in the hook state dir (HARNESS_STATE_DIR, default ~/.claude/crew-coordinator/state, mode 0700), holding the reply sha so one message logs one event, via _atomic_write (mkstemp plus os.replace, mode 0600). A file already at that path is replaced; if it held something foreign it is read as a digest, so at worst the event is logged once more, and errors are swallowed (the hook never blocks).

## Q-3e0c324d write: scripts/inbox_ladder.py::_write_flag#1b8fdfb7
File write changed in scripts/inbox_ladder.py::_write_flag (2 line(s)). Which path does it write, and what if that path already holds local data the package does not own?
Answer: inbox_ladder.py is deleted in 0.26.0 and its code moved to scripts/inbox_reminder.py (same behaviour, not new); see Q-a8c3dea5. Nothing in the removed file writes any more.

## Q-ad381b9e write: scripts/inbox_ladder.py::state_dir#ed200c35
File write changed in scripts/inbox_ladder.py::state_dir (1 line(s)). Which path does it write, and what if that path already holds local data the package does not own?
Answer: inbox_ladder.py is deleted in 0.26.0 and state_dir moved unchanged to scripts/inbox_reminder.py (same HARNESS_STATE_DIR or ~/.claude/crew-coordinator/state, 0700); see Q-dfebec39. The old file writes nothing now.

## Q-75bfb166 write: scripts/inbox_ladder.py::take_reminder#f1d165f4
File write changed in scripts/inbox_ladder.py::take_reminder (1 line(s)). Which path does it write, and what if that path already holds local data the package does not own?
Answer: inbox_ladder.py is deleted in 0.26.0 and take_reminder moved unchanged to scripts/inbox_reminder.py; see Q-afd9c04f. The old file writes nothing now.

## Q-a8c3dea5 write: scripts/inbox_reminder.py::_write_flag#e509e1d3
File write changed in scripts/inbox_reminder.py::_write_flag (2 line(s)). Which path does it write, and what if that path already holds local data the package does not own?
Answer: _write_flag writes harness-inbox-reminder-<session id> in the state dir (HARNESS_STATE_DIR, default ~/.claude/crew-coordinator/state), created O_EXCL, O_NOFOLLOW, mode 0600; moved unchanged from inbox_ladder. If a regular file already exists there it is unlinked and replaced; a symlink there is refused (OSError, caught) and no reminder is queued.

## Q-dfebec39 write: scripts/inbox_reminder.py::state_dir#4f984e42
File write changed in scripts/inbox_reminder.py::state_dir (1 line(s)). Which path does it write, and what if that path already holds local data the package does not own?
Answer: state_dir creates and chmods to 0700 the directory HARNESS_STATE_DIR or ~/.claude/crew-coordinator/state (moved unchanged from inbox_ladder). An existing directory is kept as is, only its mode is set to 0700 when owned by the user; files inside are not touched, and OSError is swallowed.

## Q-afd9c04f write: scripts/inbox_reminder.py::take_reminder#0beb1dfd
File write changed in scripts/inbox_reminder.py::take_reminder (1 line(s)). Which path does it write, and what if that path already holds local data the package does not own?
Answer: take_reminder reads the flag harness-inbox-reminder-<session id> in the state dir and unlinks it once to return the one reminder line (moved unchanged from inbox_ladder). It writes nothing; a symlink or missing file returns None, and the unlink only removes the package's own flag name.

## Q-b409722b event: scripts/doorbell.py::_attach#9fdf66ff
store.append( call, or a function that holds one, changed in scripts/doorbell.py::_attach (55 line(s)): a new field or changed payload on an event type. Who reads it, and is docs/EVENTS.md current?
Answer: _attach keeps the fields of the events it writes (nudge.offered, nudge.relay_offer, nudge.rewake, nudge.skipped, nudge.miss) but adds new reason texts: nudge.miss reasons retired_no_successor (covered mail to a retired chat's id), no_route (a recipient nothing can reach), handed_off (covered mail to the id of a chat that handed off and is not restored yet; the send result says it is queued) and doorbell_error (the doorbell failed while handling a send, one miss per covered recipient, best effort), plus the relay offer reason route_closed and the skipped texts "no route: ..." and "id route closed by a stale mark". Readers: the sender's tool result, the alarm scan (HELD_REASONS reads nudge.skipped), wake_scan and weekly_report (nudge.miss), claim_relay and the relay scans (nudge.relay_offer). docs/EVENTS.md is current (nudge.miss row updated at 956c7a0 and 4b25548, re-pinned).

## Q-6408195b event: scripts/doorbell.py::_request_relay#0d0893e4
store.append( call, or a function that holds one, changed in scripts/doorbell.py::_request_relay (4 line(s)): a new field or changed payload on an event type. Who reads it, and is docs/EVENTS.md current?
Answer: _request_relay writes nudge.relay_offer with unchanged fields; the changed lines make its "already reported" refusal compare only against the same recipient's own to_session key (offer._key, set when the report is per recipient), so another recipient's or a whole-message delivery no longer blocks a missing recipient's relay. Readers: claim_relay and the relay scans. docs/EVENTS.md is current: the nudge.result round 3 row says a refused recipient's skip still asks for its relay after another's delivery and that a recipient's result closes only its own relay offer.

## Q-cb39ac1a event: scripts/doorbell.py::claim_relay#b6a45c24
store.append( call, or a function that holds one, changed in scripts/doorbell.py::claim_relay (4 line(s)): a new field or changed payload on an event type. Who reads it, and is docs/EVENTS.md current?
Answer: claim_relay writes nudge.relay_claim and nudge.relay_released with unchanged fields; its two "already reported" prechecks now call _closes with the offer's to_session and to, so only a nudge.result for that recipient's key (session id, or agent-id prefix) stops its claim, not another recipient's result. Readers: relay holders and the relay scans. docs/EVENTS.md is current: the nudge.result round 3 row (to_session, a recipient's result closes only its own relay offer).

## Q-ed1c6499 event: scripts/doorbell.py::record_result#47cfdcd5
store.append( call, or a function that holds one, changed in scripts/doorbell.py::record_result (38 line(s)): a new field or changed payload on an event type. Who reads it, and is docs/EVENTS.md current?
Answer: record_result writes nudge.result with a new optional to_session (the recipient's session id, or the first 8 characters of its agent id), from the new `to` argument; the result is unique per (message, recipient), a whole-message skipped report after some per-recipient ones is redirected to the first recipient not yet covered, and a per-recipient report leaves the send pending until all have reported. It also now asks for a relay on a skipped app_cap or no_remotetrigger for every nudge kind, result and handoff included (RELAY_ASK_RING). Readers: the unreported, expiry, alarm and wake-block scans via _drop_partial and _rkeys, the relay scans, and the State fold. docs/EVENTS.md is current (updated at 956c7a0): the item 5 row no longer says handoff and result keep their rules, and the whole-report redirect is documented.

## Q-17f922ec event: scripts/doorbell.py::relay_expire#64218bb1
store.append( call, or a function that holds one, changed in scripts/doorbell.py::relay_expire (5 line(s)): a new field or changed payload on an event type. Who reads it, and is docs/EVENTS.md current?
Answer: relay_expire writes relay.closed {msg_id, reason} and nudge.miss (relay_expired) with unchanged fields; its duplicate check now takes the offer's to_session and to, so another recipient's nudge.result no longer counts as already closing this offer (a relay.closed still does). Readers: claim_relay, the relay view and the weekly report. docs/EVENTS.md is current: the relay.closed row and the nudge.result round 3 text ("a recipient's result closes only its own relay offer").

## Q-afe567b5 event: scripts/harness.py::hook#ab662d79
store.append( call, or a function that holds one, changed in scripts/harness.py::hook (41 line(s)): a new field or changed payload on an event type. Who reads it, and is docs/EVENTS.md current?
Answer: The only event the changed hook appends is hook.barepath {agent, role, paths, exts, sha}, which the installed 0.25.0 does not write at all; the Stop hook writes it when a final reply names a local .md, .pdf or .docx path and no file was sent or artifact published, at most once per session (agent) per day. The other changes (compaction-successor state text, inbox_reminder replacing inbox_ladder) append no event. Readers: none in code (audit event for the operator and critic). docs/EVENTS.md is current: the hook.barepath row has the fields and the once-per-session-per-day rule.

## Q-4fa9ff74 event: scripts/harness.py::inbox#cd2de7bc
store.append( call, or a function that holds one, changed in scripts/harness.py::inbox (75 line(s)): a new field or changed payload on an event type. Who reads it, and is docs/EVENTS.md current?
Answer: inbox still writes message.read {ids} with no new field, but now only for mail shown whole within the output limit (a new full argument raises it); mail past the limit stays unread and is returned in a new not_shown field of the tool result (not an event), and a cut mail stays unread until recalled whole, except one listed a second time with no waiting recipient or whose waiting asker has already answered, which is marked read. Readers of message.read: the State fold (read_by), the owed and wake scans, measure_reads and close_relays. docs/EVENTS.md is current for the event (message.read row, via recall covers the cut mail); not_shown is a result field and not documented there, which is correct for an events file.

## Q-2f44a84d event: scripts/harness.py::restore_digest#a5b37a5b
store.append( call, or a function that holds one, changed in scripts/harness.py::restore_digest (11 line(s)): a new field or changed payload on an event type. Who reads it, and is docs/EVENTS.md current?
Answer: The 11 changed lines only reorder the "Owes reply" section (owed_order, oldest first, each with its age via owed_age, at most OWED_LINES shown and a "+N more owed (harness_admin op=owed lists every id)" line); the message.read append for shown unread mail is unchanged, so no event or field changed. Readers of that message.read are the same as before (State fold read_by, owed and wake scans, measure_reads, close_relays). docs/EVENTS.md needs no change and is current for message.read.

## Q-5c0858e0 write: scripts/harness.py::hook#5cb5f093
File write changed in scripts/harness.py::hook (1 line(s)). Which path does it write, and what if that path already holds local data the package does not own?
Answer: The Stop hook writes the bare-path marker harness-barepath-<first 8 characters of the agent id> in the hook state dir ($HARNESS_STATE_DIR or ~/.claude/crew-coordinator/state, created 0700), mode 0600, through h._atomic_write (mkstemp in the same folder, fsync, os.replace), with today's date (YYYY-MM-DD) as content; the installed 0.25.0 writes no such file. It reads the file first and writes only when its content is not today's date, so an existing file (including one the package does not own, or an older date) is replaced whole without any ownership check, and a same-day file is left alone and no event is written. A write error is swallowed by the hook's try/except and, because the write comes before the hook.barepath append, no event is written for that run (read from code, not run).

## Q-dfa9fde4 doline: scripts/doorbell.py::rewake_relay_line#b3be313c
Answer: The change adds the `rewake: "extra"` branch (a relay for one more recipient of a send whose sender never reported). The line is returned only by claim_relay (the single caller), so the actor is the live local relay-role holder (default envoy, curator, ops-coder, harness-critic, design-coder; never the steward) that just claimed the offer, not the original sender. Its text is "SendMessage to <to_session>: Mail <id> from <role>, thread <t>. Run harness_inbox." or, with no session id, RemoteTrigger run with no body; both end "No report is needed". A holder with no SendMessage has no report-skipped path here (that exists only in the reported relay line, which asks for outcome delivered|held|refused_by_app); the RemoteTrigger form says "No RemoteTrigger tool here: skip it". Nothing is written, the mail waits, and at the 65 min relay TTL relay_expire closes the offer for that recipient (relay.closed expired plus a nudge.miss relay_expired), so the failure shows in the ledger.

## Q-67f32d5d event: scripts/doorbell.py::_attach#f04a6700
Answer: _attach's own event appends (nudge.offered, nudge.skipped, nudge.idwake) are unchanged; the change is that each `nudge_mail_only` entry in the send result gains a `key` (the recipient id), which attach_nudge's new _render_outcomes/_outcomes uses to build the new `nudge_outcomes` result field. That field is a send-result field, not a ledger event; the readers of the events it is built from are _outcomes, wake_scan, alarm_scan and weekly_report. docs/EVENTS.md is current for the events (nudge.offered, nudge.skipped unchanged), but it does not mention `nudge_outcomes` or the mail-only `key`; they are documented in docs/delivery-invariants.md item 7 instead (grep of EVENTS.md for "nudge_outcomes" finds nothing).

## Q-e1f00b14 event: scripts/doorbell.py::_close_dead#f808246b
Answer: relay.closed (reason trigger_dead) gains the optional `to` (the offer's recipient), and its once-precheck now matches on (message, recipient) or a legacy close without `to`. Readers: _closed (whole-message closes, those without `to`), _closed_pairs (closes with `to`), relay_expire, claim_relay, _close_dead's own precheck, the trigger_dead check near line 2815, and relay_notice_lines. docs/EVENTS.md is current: the `relay.closed` row lists `to?`, reason trigger_dead, and says a close without `to` (pre-0.26.0) covers the whole message.

## Q-8fcad4cd event: scripts/doorbell.py::_request_relay#cbdd02f2
Answer: nudge.relay_offer gets a new variant: when a message already has an offer for another recipient, this recipient gets its own offer with key `<msg>#x<agent8>`, `rewake: "extra"`, reason sender_silent and fields msg_id, to, to_session, trigger, from, role, to_role, thread; "already" is now judged per (message, recipient). Readers: _relay_view, wake_scan (relayed_p), claim_relay, relay_expire (now treats rewake "extra" as a reportless offer), _outcomes and relay_notice_lines. docs/EVENTS.md is current: the nudge.relay_offer (changed, item 5) row names the key form, `rewake: "extra"`, reason and "no report needed", and the item 5 fix 1 row lists key, rewake, trigger, to_role.

## Q-d02651f2 event: scripts/doorbell.py::alarm_scan#f9a1afda
Answer: nudge.alarm_closed gains the optional `to`, and the alarm de-duplication and close checks are now per (message, recipient), with a close lacking `to` still closing every recipient's alarm of that message. Readers: alarm_scan (alarmed, a_closed) and alarm_lines (shut); weekly_report only counts nudge.miss. docs/EVENTS.md is current (the nudge.alarm_closed row is updated; the nudge.alarm row now says one per message and recipient, fixed at 16b4626).

## Q-d5c7c13e event: scripts/doorbell.py::claim_relay#0403e12f
Answer: No event shape changed here: nudge.relay_claim, nudge.relay_released and nudge.trigwake are written with the same fields; the change is that claim_relay now reads _closed_pairs and skips an offer already closed for that recipient, and can claim `extra` offers. Readers of the claim are _relay_view, _capped, relay_notice_lines, live_claim_line and the report path. docs/EVENTS.md is current: the nudge.relay_claim rows give msg_id, by, to_session, key, and the extra/rewake offer behaviour is in the nudge.relay_offer rows.

## Q-b5cbae9e event: scripts/doorbell.py::close_relays#e695814b
Answer: relay.closed (reason read) now carries `to`, the recipient who read, so a read closes only that recipient's offer rather than the whole message. Readers: _closed_pairs and _done (used by claim_relay and relay_expire), the once-prechecks of relay_expire and _close_dead, and relay_notice_lines; _closed ignores closes that have `to`. docs/EVENTS.md is current: the `relay.closed` row states `to?` and that the close covers that recipient only.

## Q-5cb5398f event: scripts/doorbell.py::relay_expire#2dbc14a2
Answer: relay.closed (reason read or expired) now carries `to`; the nudge.miss relay_expired write is unchanged, and the already-closed test and the done-set are per (message, recipient) via _closed_pairs, with `extra` offers also expired. Readers: _closed_pairs, _done in claim_relay and relay_expire, the _once precheck, relay_notice_lines, and weekly_report (counts nudge.miss). docs/EVENTS.md is current: the `relay.closed` row covers `to?`, reasons read, trigger_dead and expired, and the nudge.miss row covers relay_expired.

## Q-76e9af93 doline: scripts/doorbell.py::<module>#9b08748e
Do-line text changed in scripts/doorbell.py::<module> (1 line(s)). Which sender acts on it, and what if that sender lacks the tool it names?
Answer: The changed line is the module constant TRIGGER_DO_LINES = False, not text a sender receives. No sender acts on it; its effect is that no RemoteTrigger Do-line is built, so a sender without the RemoteTrigger tool is no longer asked to skip anything.

## Q-c04d5476 doline: scripts/doorbell.py::rewake_relay_line#ec36bb9d
Do-line text changed in scripts/doorbell.py::rewake_relay_line (4 line(s)). Which sender acts on it, and what if that sender lacks the tool it names?
Answer: The relay holder that claim_relay or the rewake claim hands the line to (a live local relay role). With the flag off, the two RemoteTrigger forms return None and only the SendMessage forms (which name a local_ session) are returned, text unchanged; a holder without SendMessage reports skipped no_sendmessage as before. The offer is spent without a line; its mail waits in the inbox.

## Q-21fec34f doline: scripts/doorbell.py::wake_do#010d42ff
Do-line text changed in scripts/doorbell.py::wake_do (2 line(s)). Which sender acts on it, and what if that sender lacks the tool it names?
Answer: wake_do (verify and disable Do-lines for a wake routine) now returns None at its top while the flag is off, so no holder is handed a RemoteTrigger verify or disable line; the caller already treats None as no line. A holder without the tool no longer has to skip.

## Q-778ee9a4 doline: scripts/harness.py::sync#9ba3906e
Do-line text changed in scripts/harness.py::sync (4 line(s)). Which sender acts on it, and what if that sender lacks the tool it names?
Answer: No Do-line text changes in sync: the four added lines are a try block that calls ingest_mistake_spool and swallows any error. The Do-lines sync prints are unchanged, and fewer of them appear because wake_do returns None.

## Q-6c8169f9 event: scripts/doorbell.py::wake_do#010d42ff
store.append( call, or a function that holds one, changed in scripts/doorbell.py::wake_do (2 line(s)): a new field or changed payload on an event type. Who reads it, and is docs/EVENTS.md current?
Answer: No event shape changes: the early return only skips the existing wake.claim append, which is now unreachable while the flag is off. Readers of wake.claim (wake_do itself, the relay views) see no new claims. There is no docs/EVENTS.md change to make.

## Q-9b0976e0 event: scripts/harness.py::sync#9ba3906e
store.append( call, or a function that holds one, changed in scripts/harness.py::sync (4 line(s)): a new field or changed payload on an event type. Who reads it, and is docs/EVENTS.md current?
Answer: The new try block calls ingest_mistake_spool, which files candidate records through the existing _record writer (note entries tagged mistake, hindsight, candidate); no new event type or field. Readers: harness_recall, the guru's weekly verifier, the corpus index. docs/EVENTS.md is unaffected.

## Q-c7e4e983 hook: PreToolUse::mcp__.*harness_record::python3 "${CLAUDE_PLUGIN_ROOT}/scripts/mistake_pointer_hook.py"
Hook changed: PreToolUse matcher 'mcp__.*harness_record'. Which tool calls does it now see, and what if it fails?
Answer: It sees every harness_record call from any chat (the matcher ends in harness_record) and reads only tool_input.agent and transcript_path. It saves the transcript path and last line under the agent's 8-hex id. It is fail-open: any error or the 5 s timeout lets the call through with no output; the record is then filed with the pointer lines saying unavailable.

## Q-c47f4119 hook: UserPromptSubmit::::python3 "${CLAUDE_PLUGIN_ROOT}/scripts/correction_hook.py"
Hook changed: UserPromptSubmit matcher ''. Which tool calls does it now see, and what if it fails?
Answer: It sees every prompt he sends in any chat (empty matcher; it is not a tool call). Only on a correction cue it appends one spool line and prints one context line telling the agent a candidate was filed. Any error, a symlinked spool or the 5 s timeout exits 0 with no output: the prompt always proceeds and nothing is filed.

## Q-15ddd425 write: scripts/correction_hook.py::run#77fc2d3b
File write changed in scripts/correction_hook.py::run (1 line(s)). Which path does it write, and what if that path already holds local data the package does not own?
Answer: It creates one mark file per correction under <home>/_harness/mistake_seen/ (exclusive create, no symlink follow, mode 0600) and appends to <home>/_harness/mistake_spool.jsonl. Existing spool lines are never rewritten; an existing mark file means the correction was already filed and nothing is written; a symlink is refused.

## Q-e966ce4b write: scripts/mistake_ingest.py::ingest#1db3064d
File write changed in scripts/mistake_ingest.py::ingest (3 line(s)). Which path does it write, and what if that path already holds local data the package does not own?
Answer: At sync it renames mistake_spool.jsonl to mistake_spool.claimed (atomic), appends unresolved lines back to the spool, appends filed lines to mistake_spool.done.jsonl and refused ones to mistake_spool.rejected.jsonl, creates mistake_seen/<key>.filed (exclusive), and removes the claimed file at the end. Nothing is overwritten: appends only, symlinks refused, a leftover .claimed file from a crash is processed first.

## Q-d67a9381 write: scripts/mistake_record.py::_safe_dir#8323d930
File write changed in scripts/mistake_record.py::_safe_dir (1 line(s)). Which path does it write, and what if that path already holds local data the package does not own?
Answer: It creates the folder <home>/_harness/mistake-pointers if missing (makedirs, exist_ok) and refuses if that path is a symlink. An existing folder and its files are left as they are.

## Q-c2601825 write: scripts/mistake_record.py::save_pointer#eb3d04a2
File write changed in scripts/mistake_record.py::save_pointer (2 line(s)). Which path does it write, and what if that path already holds local data the package does not own?
Answer: It writes <home>/_harness/mistake-pointers/<8-hex agent id>.json through an exclusive, no-follow temp file (mode 0600) and os.replace, so only that agent's own pointer file is replaced (a symlink at the final name is replaced, never followed). Only a lowercase hex agent id of 8 or more characters is accepted. Other files in the folder are untouched; a crash can leave one small .tmp file.

## Q-8985ecfe write: scripts/open_questions.py::_seen_locked#6a980903
File write changed in scripts/open_questions.py::_seen_locked (2 line(s)). Which path does it write, and what if that path already holds local data the package does not own?
Answer: It rewrites <home>/_harness/open_questions.jsonl (key terms of recent questions, never the question text) through an exclusive no-follow temp file and os.replace under a flock on open_questions.jsonl.lock. The file belongs to this feature; rows that are not valid (bad time, not an object) are dropped on the rewrite; a symlink at the name is not read and is replaced, never followed.

## Q-6fd7407a doline: scripts/harness.py::sync#51aacbf7
Do-line text changed in scripts/harness.py::sync (5 line(s)). Which sender acts on it, and what if that sender lacks the tool it names?
Answer: The new text is a sync Do-line, 'dated switch <name> ends <date> (in N days): renew it in the config or let it end', added by dated_switches.do_lines inside a try/except. The sender that acts on it is the agent that called harness_sync (the curator or the envoy, who owns renewals); it names no tool, only a config edit that the operator or the envoy makes. A sender without that access skips it: nothing breaks, the switch ends silently as designed, and the line shows only while a config date is 14 days or fewer away.

## Q-6ae6d8c5 event: scripts/harness.py::request_approval#d48d3dcb
store.append( call, or a function that holds one, changed in scripts/harness.py::request_approval (2 line(s)): a new field or changed payload on an event type. Who reads it, and is docs/EVENTS.md current?
Answer: No event type and no payload field changed: request_approval still appends approval.requested with the same fields. The change only refuses an archive or pin request earlier, by running apply's own gate and reason check before the append. Readers of approval.requested are unaffected; docs/EVENTS.md is current (no new event, no new field).

## Q-1cf5a81b event: scripts/harness.py::sync#51aacbf7
store.append( call, or a function that holds one, changed in scripts/harness.py::sync (5 line(s)): a new field or changed payload on an event type. Who reads it, and is docs/EVENTS.md current?
Answer: No event type and no payload field changed in sync: the 5 changed lines add the dated-switch Do-line text and read the same events. The append calls in sync keep their types and fields. docs/EVENTS.md is current (no new event, no new field).

## Q-f45291b0 event: scripts/idcheck.py::ended_once#251ea6f6
store.append( call, or a function that holds one, changed in scripts/idcheck.py::ended_once (4 line(s)): a new field or changed payload on an event type. Who reads it, and is docs/EVENTS.md current?
Answer: No event payload changed: idcheck.ended_once still appends one hook.observe_end per (hook, agent, date) with the same fields. What changed is only how 'ended' is decided: dated_switches.is_on (on through the date, empty or malformed means ended) instead of a direct date comparison. docs/EVENTS.md is current.

## Q-80907fa1 hook: PostToolUse::mcp__.*publish_files.*|Artifact::python3 "${CLAUDE_PLUGIN_ROOT}/scripts/attach_hook.py"
Hook changed: PostToolUse matcher 'mcp__.*publish_files.*|Artifact'. Which tool calls does it now see, and what if it fails?
Answer: It sees every PostToolUse call whose tool name matches mcp__.*publish_files.* or is, or starts with, Artifact (the regex also matches ArtifactComments and ArtifactData, which write nothing). Only a publish that touches the attach marker file on the Hub artifact produces a line. If the hook fails (bad input, missing or locked home, any exception) it exits 0 and prints nothing, so no tool call is blocked or changed; a missing line is then the only effect.

## Q-ed2b06fd write: scripts/attach_hook.py::_log#b19b196e
File write changed in scripts/attach_hook.py::_log (2 line(s)). Which path does it write, and what if that path already holds local data the package does not own?
Answer: _log appends one line to <home>/_harness/attach_failures.jsonl (created if missing, no-follow, mode 0600); it is called only when the attach messages are switched on (config attach_messages, off by default in 0.27.2), so nothing is written by default. An existing file keeps its lines; the new line is appended. A symlink at that name is refused; any error is swallowed.

## Q-26098147 write: scripts/attach_hook.py::log_shape#06eac3b3
File write changed in scripts/attach_hook.py::log_shape (2 line(s)). Which path does it write, and what if that path already holds local data the package does not own?
Answer: log_shape appends one line (time, event, tool name, python type, key names, verdict; never response text) to <home>/_harness/attach_shapes.jsonl, created with mode 0600, no-follow, under a non-blocking flock. When the file passes 500 lines it rewrites the last 500 through a temp file and os.replace. The file is this feature's own; a missing or read-only home, a symlink or a locked file means no line and exit 0.

## Q-77684c23 write: scripts/attach_state.py::record#c2eb429d
File write changed in scripts/attach_state.py::record (3 line(s)). Which path does it write, and what if that path already holds local data the package does not own?
Answer: record writes <home>/_harness/attach_state.json (which operation the next attach toggle needs) through a temp file in the same folder and os.replace, creating the folder if missing. Only this file is replaced; other files in _harness are not touched. In 0.27.2 it is reached only when attach messages are on, so by default nothing is written.

## Q-58b9ab13 write: scripts/dated_switches.py::warn_once#e676512b
File write changed in scripts/dated_switches.py::warn_once (2 line(s)). Which path does it write, and what if that path already holds local data the package does not own?
Answer: warn_once appends one line 'malformed date for <switch>: <value> (switch treated as ended)' to <home>/_harness/dated_switches.log, creating the folder if needed, only when that exact line is not already in the file; the file is this feature's own and an existing one keeps its lines. Any failure is silent and nothing goes to stdout.
