# Release questions

One question per change against the installed release. Answer every one; the gate fails on a blank answer.

## Q-dc40512c approval: case_close
Approval action case_close added. What does the operator see on the card, and what breaks for a caller?
Answer: Scope A-08480 item 2 ("write-time rules"; envoy m-8395ca1d1f98 names the three actions). Any agent files it with `harness_admin op=case args={action:"request_close", case, outcome, ref?, reason}`. The operator sees the usual card: id, requester, action case_close, "no expiry" (NO_EXPIRY, like lesson_curate), and in `harness.py pending` the args (case id, outcome, ref, reason; agent text capped at 120 characters). The code is the first 4 hex of the digest, as for every action. The grant is written first, then one `case.closed` with `approval` set; the close rules are checked before the grant and again under the ledger lock, so a case that moved meanwhile gives state failed and no close. It is the only way to close an S0 case as wont_fix or duplicate. Nothing breaks for an existing caller: no earlier action, argument or event changes. It counts toward the existing 20 pending requests per caller. Tests: tests/test_c230_proctor_events.py P9.

## Q-d78f1296 approval: case_severity
Approval action case_severity added. What does the operator see on the card, and what breaks for a caller?
Answer: Scope A-08480 item 2. Filed by the proctor's `propose` (lowering an S0, which the proctor may not do itself) or by any agent's `request_severity`. Card: id, requester, action case_severity, "no expiry"; `pending` shows case, old, new and the reason (capped). Grant first, then one `case.severity` with `approval`; `old` must still be the current severity at grant time, else the grant is recorded failed ("stale") and no severity event is written. One open proposal per case. Nothing breaks for existing callers. Tests: P5, P5b.

## Q-6e92e89b approval: proctor_shadow
Approval action proctor_shadow added. What does the operator see on the card, and what breaks for a caller?
Answer: Scope A-08480 item 2 (critic N-a5326 blocker 1: shadow is ledger state, not config). Filed with `harness_admin op=proctor_shadow args={on: true|false, reason}`; card: id, requester, action proctor_shadow, minutes left (default TTL); `pending` shows on and the reason. The grant writes `proctor.shadow` {on, approval}. Shadow is ON until the first such grant, so nothing changes for anyone until the operator ends the shadow period. Config files are not read for it. Nothing breaks for existing callers. Tests: P4.

## Q-f5c82766 doline: scripts/harness.py::sync#62a217f1
Do-line text changed in scripts/harness.py::sync (7 line(s)). Which sender acts on it, and what if that sender lacks the tool it names?
Answer: False positive for Do-line text. The 7 changed lines add two plain "Changed" lines, no "Do:" and no tool: (1) "▲ N ignored duplicate request(s) for A-xxxxx" for 24 h after a request left pending (item 1), (2) `_D.proctor_lines`: the proctor holder's queue line "proctor queue: N open (S0 k, S1 m); shadow on|off; samples open s", and "rejected case events: n (newest seq N)" only when a new rejected event appeared since the agent's last sync. Both are wrapped in try/except so a failure shows nothing. No sender acts on them. Tests: tests/test_c230_fixes.py T2, tests/test_c230_proctor_events.py P11, P13.

## Q-10c392a9 event: scripts/doorbell.py::_attach#afa24974
store.append( call, or a function that holds one, changed in scripts/doorbell.py::_attach (7 line(s)): a new field or changed payload on an event type. Who reads it, and is docs/EVENTS.md current?
Answer: No event payload changes. The changed lines are the item 4 early return: a kind=notice send to a live recipient returns `nudge: "none (kind notice starts no wake)"` and writes nothing (no nudge.offered, no nudge.skipped), as before; other non-ringing kinds return as before. The store.append calls further down (nudge.offered) are untouched. EVENTS.md needs no row. Tests: tests/test_c230_fixes.py N1 to N4; tests/test_c212_nudge.py notice test updated to the new reply.

## Q-c13941c4 event: scripts/harness.py::_approve_locked#85bdcdd2
store.append( call, or a function that holds one, changed in scripts/harness.py::_approve_locked (19 line(s)): a new field or changed payload on an event type. Who reads it, and is docs/EVENTS.md current?
Answer: `approval.granted` gains `args_digest` on every grant (item 1). Readers: harness._approval_records (ignores a grant whose digest differs from the FIRST request's; a grant without the field, written before 0.23.0, stays valid), scripts/lesson_cue.py ledger_cue_hashes (same rule), State._case_appr_fold (case actions). For the three case actions the grant is written first and then the case event (`proctor.shadow`, `case.severity`, `case.closed`) through _case_append, so a replay finds the grant before the event it allows; a failed rule check writes the grant with state failed and no case event. EVENTS.md: "Added in 0.23.0" rows for approval.granted (changed), proctor.shadow, case.severity and case.closed. Tests: test_c230_fixes.py T1 to T4, L1 to L3; test_c230_proctor_events.py P4, P5, P5b, P9.

## Q-237aeb0d event: scripts/harness.py::_case_append#33413a8d
store.append( call, or a function that holds one, changed in scripts/harness.py::_case_append (7 line(s)): a new field or changed payload on an event type. Who reads it, and is docs/EVENTS.md current?
Answer: New function, new event types: case.opened, trace.card, case.classified, case.routed, case.severity, case.severity_proposed, case.sample, case.audit_blind, case.audited, case.closed (and proctor.shadow from a grant). It appends with a precheck that runs State.case_error on the fresh State under the ledger lock, the same validator the replay uses. Readers: State (cases, case_by_source, case_cards, case_samples, proctor_shadow, case_rejected), harness case_show / cases_list, doorbell.proctor_lines. Older harness versions skip unknown types on replay. EVENTS.md has a row for every type with its fields, writers and rules. Tests: tests/test_c230_proctor_events.py P1 to P14.

## Q-0792d533 event: scripts/harness.py::request_approval#06f38d70
store.append( call, or a function that holds one, changed in scripts/harness.py::request_approval (11 line(s)): a new field or changed payload on an event type. Who reads it, and is docs/EVENTS.md current?
Answer: The approval.requested payload is unchanged. Added checks before it is written: proctor_shadow args must be {on: bool, reason?}; case_severity and case_close must name an existing case; and wake_pin refuses a plain trig_ string entry (gap 6) and, for the whole request, a dict entry for a role with no live holder, with how to proceed (gap 3). A refused request writes nothing, as before. EVENTS.md: wake.pinned (changed) row. Tests: test_c230_fixes.py G3, G6; test_c225_wake.py legacy test rewritten to the refusal.

## Q-6021e388 event: scripts/harness.py::restore_digest#1cd740f7
store.append( call, or a function that holds one, changed in scripts/harness.py::restore_digest (5 line(s)): a new field or changed payload on an event type. Who reads it, and is docs/EVENTS.md current?
Answer: No event payload changes. For role proctor only, the digest prints "omitted for the proctor: no-carry, blind audits" in place of the state-note body and the Last exchange (critic N-5d433: a restore must not carry the previous instance's case outcomes). The function's existing store.append (lesson.shown) is untouched. Other roles see no change. EVENTS.md needs no row. Test: test_c230_proctor_events.py P13b.

## Q-bcac78a5 event: scripts/harness.py::sync#62a217f1
store.append( call, or a function that holds one, changed in scripts/harness.py::sync (7 line(s)): a new field or changed payload on an event type. Who reads it, and is docs/EVENTS.md current?
Answer: No event payload changes: the 7 lines add two read-only Changed lines (see Q-f5c82766). The sync's existing store.append calls (agent.synced, approval.noticed and the others) are untouched. EVENTS.md needs no row.

## Q-85b87e68 event: scripts/harness.py::wake_pin_apply#92009be8
store.append( call, or a function that holds one, changed in scripts/harness.py::wake_pin_apply (8 line(s)): a new field or changed payload on an event type. Who reads it, and is docs/EVENTS.md current?
Answer: wake.pinned payload unchanged in shape ({role: {trigger, kind, holder, prompt_sha, link?}}); what changes is which entries are accepted: a plain trig_ string is refused (gap 6) and a dict entry for a role with no live holder refuses the whole apply (gap 3; checked again at apply because the holder may have left since the request). Plain-string pins already in the ledger are still read (doorbell.pin_entry legacy branch). Readers: doorbell.pin_entry, wake_pin_state, _wake_trigger, wake_repin_lines. EVENTS.md: wake.pinned (changed) row in "Added in 0.23.0". Tests: test_c230_fixes.py G3, G6; the five pin test files moved to the dict form.
