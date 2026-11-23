# crew-coordinator modules (operator seat part; the rest of scripts/ is the 0.26 library, owner: curator)
| Module | Purpose | Interface | Depends on | Owner |
|---|---|---|---|---|
| root/harness_grant_helper.py | root-owned signer: list live pending requests, one code, sign each (single-use), apply as his uid, record the consume by digest; shows an approval's action and args in full after checking them against the digest | `approve`, `cutover` (via sudo; sudo's prompt is the password) | stdlib, openssl, /bin/ps, the two modules below | curator |
| root/harness_event_map.py | every human event type, its digest rule, display-only fields, high-risk flag | `event_digest`, `kind_of`, `high_risk`, `canonical` | stdlib | curator |
| root/harness_verify.py | signature checks, accepted-event set, ledger audit (the unpatchable verifier) | `accepted`, `audit`, `load_log` | stdlib, openssl | curator |
| scripts/operator_sign.py | the user-side gate: append refusal, replay filter, request files, apply, apply-all (files applied requests to done/) | `gate_on`, `human_ok`, `human_ctx`, `request_file` (approval requests carry detail {action, args}), `apply`, `apply_all`, `LINE` | root/*.py | curator |
| scripts/seat_guard.py | agents never hold the operator seat; broadcasts skip it | `refuse_if_seat`, `exclude_seat` | stdlib | curator |
| scripts/restore_model_warn.py | model-mismatch banner line from role_models.json | `model_line` | json | curator |
| scripts/seat_setup.py | writes the one-time root install script with the sources inline and the one sudoers drop-in (!use_pty for the signer) | `build`, `write` | root/*.py | curator |
| scripts/hub_feed_op.py | `harness_admin op=timer`: validates timer args and calls the vendored Hub feed timer module | `run_timer(home, args, now)` | scripts/hub_feed_timers.py | curator |
| scripts/hub_feed_timers.py | vendored copy (source sha in its first line) of the Hub feed's timer file logic; changed only through a release | `set_timer`, `sweep` | stdlib | curator |
| tests/test_operator_seat.py, test_operator_grant.py, test_operator_gate.py | guard and model warning; helper, map, verifier, setup script; gate and signed apply | unittest | the modules above | curator |
| scripts/mistake_record.py | 0.27.1: field check for records tagged mistake (What, Found by, Model, Kind, visible or hindsight); fills the session path and transcript line saved by the hook | `is_mistake`, `problems`, `save_pointer`, `pointer_lines` | stdlib | curator |
| scripts/mistake_pointer_hook.py | 0.27.1: PreToolUse hook on harness_record; saves the chat's transcript path and last line under the agent's short id | hook JSON on stdin; writes `_harness/mistake-pointers/` | scripts/mistake_record.py | curator |
| scripts/correction_cues.py | 0.27.1 item 1 (ops-coder): does his message correct the agent; pure, praise, quotes, pasted text and peer messages never match | `match(text)` | stdlib | curator |
| scripts/correction_hook.py | 0.27.1 item 1: UserPromptSubmit hook; on a correction writes a spool line pointing at the agent's previous turn | stdin JSON; spool `_harness/mistake_spool.jsonl` | correction_cues | curator |
| scripts/mistake_ingest.py, scripts/mistake_pointer.py, scripts/mistake_verify.py | 0.27.1 item 1: at sync, spool lines become candidate mistake records (tags mistake, hindsight, candidate); finds the session's real transcript | `ingest(home, resolve_agent, record_fn)`, `find_transcript` | stdlib | curator |
| scripts/open_questions.py | 0.27.1: one open question per topic across chats; remembers key terms of questions put to him, flags a second chat on the same topic within 12 hours | `seen(home, agent, role, terms, now)` | stdlib | curator |
