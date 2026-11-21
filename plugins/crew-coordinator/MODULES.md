# crew-coordinator modules (operator seat part; the rest of scripts/ is the 0.26 library, owner: curator)
| Module | Purpose | Interface | Depends on | Owner |
|---|---|---|---|---|
| root/harness_grant_helper.py | root-owned signer: list live pending requests, one code, sign each (single-use), apply as his uid, record the consume by digest | `approve`, `cutover` (via sudo; sudo's prompt is the password) | stdlib, openssl, /bin/ps, the two modules below | curator |
| root/harness_event_map.py | every human event type, its digest rule, display-only fields, high-risk flag | `event_digest`, `kind_of`, `high_risk`, `canonical` | stdlib | curator |
| root/harness_verify.py | signature checks, accepted-event set, ledger audit (the unpatchable verifier) | `accepted`, `audit`, `load_log` | stdlib, openssl | curator |
| scripts/operator_sign.py | the user-side gate: append refusal, replay filter, request files, apply, apply-all (files applied requests to done/) | `gate_on`, `human_ok`, `human_ctx`, `request_file`, `apply`, `apply_all`, `LINE` | root/*.py | curator |
| scripts/seat_guard.py | agents never hold the operator seat; broadcasts skip it | `refuse_if_seat`, `exclude_seat` | stdlib | curator |
| scripts/restore_model_warn.py | model-mismatch banner line from role_models.json | `model_line` | json | curator |
| scripts/seat_setup.py | writes the one-time root install script with the sources inline | `build`, `write` | root/*.py | curator |
| tests/test_operator_seat.py, test_operator_grant.py, test_operator_gate.py | guard and model warning; helper, map, verifier, setup script; gate and signed apply | unittest | the modules above | curator |
