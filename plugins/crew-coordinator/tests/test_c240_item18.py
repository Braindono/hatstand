"""cc 0.24.0 item 18 (scope A-b2950; relay-wake spec 2026-11-10_cc024-relay-wake-spec.md v3.2, section 4, tests RL1-RL9): the relay Do-line
comes first and repeats until handled, a read closes the relay, late and held reports count, the sender hears only of an unclaimed relay,
Cowork targets ring through their verified routine, and the PostToolUse hook claims in the main chat only. Each RL test fails on 0.23.0.
Run: python3 -B tests/test_c240_item18.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _env  # noqa: F401  isolate HOME and HARNESS_* first
import io, json, os, time, unittest
from contextlib import redirect_stdout
from unittest import mock

import test_c220_nudge as C
import test_c223_relay as R
from test_c220_nudge import D, H
import ctx_hook as CH

EV = R.EV
HELD = "delivery: queued; message_id: 2aa5b7b3-1c2a-4318-9641-07d75f23529e"
T9 = "trig_DESIGNSYSTEMwake01"
S9 = "session_01DesignSystemChat"
YEAR2 = time.strftime("%Y-%m-%dT00:00:00Z", time.gmtime(time.time() + 2 * 365 * 86400))


class Item18(C.Base):
    holders, nudge, ask, poll, mid_of, ev = R.R.holders, R.R.nudge, R.R.ask, R.R.poll, R.R.mid_of, R.R.ev   # helpers only

    def setUp(self):
        super().setUp()
        self.op["doorbell"] = {"nudge_per_agent_hour": 60, "nudge_per_pair_hour": 30}
        for r in ("harness-critic", "ops-coder", "steward", "design-system"):
            self.h.role_define("operator", r, "harness-ops", carry="none")
        with mock.patch.dict(os.environ, {"CLAUDE_CODE_HOST_SESSION_ID": ""}):
            self.cloud = self.reg("secretary", None)                 # a sender that cannot ring
        self.cur = self.reg("curator", "local_cur")                  # the recipient
        self.warm(self.cur)
        e = mock.patch.dict(os.environ, {"HARNESS_HOME": self.home})
        e.start()
        self.addCleanup(e.stop)

    def first_line(self, aid):
        r = self.call("harness_inbox", agent=aid, peek=True)
        txt = r.get("text") if isinstance(r, dict) and isinstance(r.get("text"), str) else str(r.get("relay") or "")
        return txt.split("\n", 1)[0]

    def hook_inp(self, aid, sid="s-main", **kw):
        inp = dict({"session_id": sid, "tool_name": "Read", "tool_input": {}, "tool_response": "x", "hook_event_name": "PostToolUse",
                    "transcript_path": "/x/projects/p/%s.jsonl" % sid}, **kw)
        p = CH.note_path(inp)
        CH.save_note(p, dict(CH.load_note(p), agent=aid[:8]))
        return inp

    # RL1
    def test_rl1_the_claimers_next_three_results_start_with_the_same_doline_until_it_reports(self):
        a, = self.holders("envoy")
        mid = self.nudge()
        self.ask(mid)
        lines = [self.first_line(a) for _ in range(3)]
        self.assertTrue(lines[0].startswith("Do: SendMessage to local_cur: Mail %s" % mid), lines[0])
        self.assertEqual(len(set(lines)), 1)
        self.assertEqual(len(self.ev("nudge.relay_claim")), 1)                     # the same claim, never a new one
        D.record_result(self.h, a, mid, "delivered", EV)
        self.assertNotIn("Do: SendMessage", self.first_line(a))

    # RL2
    def test_rl2_a_read_before_any_claim_closes_the_relay(self):
        a, = self.holders("envoy")
        mid = self.nudge()
        self.ask(mid)
        self.call("harness_inbox", agent=self.cur)                                 # the recipient reads first
        self.assertEqual(self.ev("relay.closed"), [{"msg_id": mid, "to": self.cur, "reason": "read"}])      # round 7 (class A): the close names its recipient
        self.assertIsNone(self.poll(a))
        self.assertEqual(self.ev("nudge.relay_claim"), [])
        self.assertEqual(D.relay_notice_lines(self.h, self.h.state(), self.cloud, now=time.time() + 700), [])
        D.relay_expire(self.h, now=time.time() + D.RELAY_TTL_S + 5)
        self.assertEqual(self.ev("nudge.result"), [])                              # 0.25.0 (item 34): never a system result
        self.assertEqual(self.ev("nudge.miss"), [])                                # and a read-closed offer gets no spurious miss
        self.assertEqual(len(self.ev("relay.closed")), 1)

    def test_rl2_a_read_after_the_claim_stops_the_repeat(self):
        a, = self.holders("envoy")
        mid = self.nudge()
        self.ask(mid)
        self.assertIn(mid, self.first_line(a))
        self.call("harness_inbox", agent=self.cur)
        self.assertNotIn("Do: SendMessage", self.first_line(a))
        self.assertEqual(self.ev("nudge.relay_released"), [])                      # no release, no re-offer

    # RL3
    def test_rl3_a_timed_out_claimers_late_report_is_accepted_once(self):
        a, b = self.holders("envoy", "harness-critic")
        mid = self.nudge()
        self.ask(mid)
        self.assertIn(mid, self.poll(a))
        self.assertIn(mid, D.claim_relay(self.h, b, now=time.time() + D.RELAY_CLAIM_S + 5))
        self.assertTrue(D.record_result(self.h, a, mid, "delivered", EV).get("reported"))
        self.assertTrue(D.record_result(self.h, b, mid, "delivered", EV).get("already_reported"))
        with self.assertRaisesRegex(H.HarnessError, "an agent that claimed its relay"):
            D.record_result(self.h, self.reg("ops-coder", "local_oc"), mid, "delivered", EV)

    # RL4
    def test_rl4_held_with_delivery_queued_is_accepted(self):
        a, = self.holders("envoy")
        mid = self.nudge()
        self.ask(mid)
        self.poll(a)
        with self.assertRaises(H.HarnessError):
            D.record_result(self.h, a, mid, "held", EV)                            # held needs delivery: queued
        self.assertTrue(D.record_result(self.h, a, mid, "held", HELD).get("reported"))
        r = self.ev("nudge.result")[-1]
        self.assertEqual((r["outcome"], r["evidence"]["delivery"]), ("held", "queued"))

    # RL5
    def test_rl5_the_sender_hears_only_after_10_min_unclaimed_and_unread(self):
        mid = self.nudge()                                                           # no relay holder at all
        self.ask(mid)
        st = self.h.state()
        self.assertEqual(D.relay_notice_lines(self.h, st, self.cloud, now=time.time() + 9 * 60), [])
        self.assertEqual(D.relay_notice_lines(self.h, st, self.cloud, now=time.time() + 11 * 60),
                         ["relay for %s not claimed in 10 min, mail still unread" % mid])
        self.assertEqual(D.relay_notice_lines(self.h, st, self.cloud, now=time.time() + 12 * 60), [])   # once
        with mock.patch.object(D, "SAME_SESSION_S", 0):                             # a second task to the same chat at once (item 5 nb 6 off)
            m2 = self.nudge()
        self.ask(m2)
        self.call("harness_inbox", agent=self.cur)
        self.assertEqual(D.relay_notice_lines(self.h, self.h.state(), self.cloud, now=time.time() + 11 * 60), [])

    def test_rl5_a_claimed_relay_gives_no_notice(self):
        a, = self.holders("envoy")
        mid = self.nudge()
        self.ask(mid)
        self.poll(a)
        self.assertEqual(D.relay_notice_lines(self.h, self.h.state(), self.cloud, now=time.time() + 11 * 60), [])

    # RL6
    def test_rl6_cowork_to_cowork_rings_the_recipients_verified_routine(self):
        with mock.patch.dict(os.environ, {"CLAUDE_CODE_HOST_SESSION_ID": ""}):
            ds = self.reg("design-system", None)
        a, b = self.holders("envoy", "harness-critic")
        self.call("harness_admin", agent=ds, op="wake_register", args={"trigger": T9, "session": S9})
        self.call("harness_admin", agent=a, op="wake_verify", args={"trigger": T9, "prompt": "Run harness_inbox.", "enabled": True,
                                                                    "session": S9, "kind": "run_once", "run_at": YEAR2})
        n = self.call("harness_send", agent=self.cloud, to="role:design-system", body="b", subject="s", kind="task")["nudge"]
        self.assertIn(T9, n["do"])
        r = D.record_result(self.h, self.cloud, n["msg_id"], "skipped", "no_remotetrigger")   # a Cowork sender has no RemoteTrigger
        self.assertTrue(r.get("relay_requested"), r)
        self.assertEqual(r["nudge"], "relay requested (Cowork to Cowork)")
        line = D.claim_relay(self.h, b)
        self.assertTrue(line.startswith("Do: RemoteTrigger action=run trigger_id=%s" % T9), line)
        self.assertIn("run with no body", line)
        with self.assertRaisesRegex(H.HarnessError, "reports the run result's fields"):
            D.record_result(self.h, b, n["msg_id"], "woke", "HTTP 200")
        res = D.record_result(self.h, b, n["msg_id"], "woke", "HTTP 200",
                              fire={"prompt": "Run harness_inbox.", "enabled": True, "session": S9})
        self.assertTrue(res.get("reported"))
        self.assertEqual(self.ev("nudge.result")[-1]["status"], 200)

    # fix round 2 (envoy m-74dd4985787a): with no verified routine, a relay falls back to a legacy pin in the ok state only
    def legacy_cowork(self, kind="recurring"):
        with mock.patch.dict(os.environ, {"CLAUDE_CODE_HOST_SESSION_ID": ""}):
            ds = self.reg("design-system", None)
        C.legacy_pin(self.h, {"design-system": C.WP("design-system", kind=kind)})
        return ds

    def cowork_relay(self):
        n = self.call("harness_send", agent=self.cloud, to="role:design-system", body="b", subject="s", kind="task")["nudge"]
        return n, D.record_result(self.h, self.cloud, n["msg_id"], "skipped", "no_remotetrigger")

    def test_fix2_an_ok_legacy_pin_is_a_relay_target_and_needs_no_fields(self):
        self.legacy_cowork()
        a, = self.holders("envoy")
        n, r = self.cowork_relay()
        self.assertTrue(r.get("relay_requested"), r)
        line = D.claim_relay(self.h, a)
        self.assertTrue(line.startswith("Do: RemoteTrigger action=run trigger_id=%s" % C.TRIG), line)
        self.assertNotIn("prompt:", line)
        self.assertTrue(D.record_result(self.h, a, n["msg_id"], "woke", "HTTP 200").get("reported"))

    def test_fix2_a_stale_legacy_pin_is_not_a_relay_target(self):
        ds = self.legacy_cowork()
        self.reg("design-system", None, predecessor=ds)                               # the holder changed: the pin is stale
        self.holders("envoy")
        n = self.call("harness_send", agent=self.cloud, to="role:design-system", body="b", subject="s", kind="task").get("nudge")
        self.assertNotIsInstance(n, dict)                                             # no route at all; nothing to relay
        self.assertEqual(self.ev("nudge.relay_offer"), [])

    def test_fix2_a_spent_run_once_legacy_pin_is_not_a_relay_target(self):
        self.legacy_cowork(kind="run_once")
        a, = self.holders("envoy")
        n, _ = self.cowork_relay()
        D.claim_relay(self.h, a)
        D.record_result(self.h, a, n["msg_id"], "woke", "HTTP 200")                    # the one run spends it
        self.call("harness_inbox", agent=self.h.state().role_holder("design-system"))
        self.assertEqual(D.wake_pin_state(self.h.state(), "design-system", self.h)[1], "spent")
        st = self.h.state()
        self.assertIsNone(D._relay_target(self.h, st, {"to": [st.role_holder("design-system")], "hids": [None]}))

    def test_fix2_a_pending_registration_keeps_the_legacy_pin_as_a_target(self):
        ds = self.legacy_cowork()
        self.call("harness_admin", agent=ds, op="wake_register", args={"trigger": T9, "session": S9})
        st = self.h.state()
        self.assertEqual(D._relay_target(self.h, st, {"to": [ds], "hids": [None]}), (ds, None, C.TRIG))

    # fix round 2 (critic m-24a05fd9f266): a rewake's mail has a woke result; the hook still claims it until it is read or claimed
    def test_fix2_the_hook_claims_a_rewake_whose_mail_has_a_result(self):
        a, = self.holders("envoy")
        mid = self.nudge()
        self.h.store.append("nudge.result", self.cloud, {"msg": mid, "msg_id": mid, "by": self.cloud, "for": self.cloud,
                                                          "outcome": "woke", "reason": "HTTP 200", "status": 200})
        self.rewake_offer(mid)
        self.assertIsNone(CH.relay_hook(self.hook_inp(a)))                        # 0.25.0 (item 23): a hook never claims
        self.assertEqual(self.ev("nudge.relay_claim"), [])
        self.assertIn("Rewake 1 of 2", D.attach_relay(self.h, a, {"text": "x"})["text"])   # the holder's own harness result does
        self.call("harness_inbox", agent=self.cur)

    # RL7
    def test_rl7_a_read_call_deep_in_a_long_turn_carries_the_claimed_doline(self):
        a, = self.holders("envoy")
        mid = self.nudge()
        self.ask(mid)
        self.assertIsNone(CH.relay_hook(self.hook_inp(a)))                          # 0.25.0 (item 23): never from a hook
        self.assertEqual(self.ev("nudge.relay_claim"), [])
        line = D.attach_relay(self.h, a, {"text": "x"})["text"]                     # only in the claiming holder's own harness result
        self.assertTrue(line.startswith("Do: SendMessage to local_cur: Mail %s" % mid), line)
        self.assertEqual([d["by"] for d in self.ev("nudge.relay_claim")], [a])

    def test_rl7_main_puts_it_first_in_additional_context(self):
        a, = self.holders("envoy")
        mid = self.nudge()
        self.ask(mid)
        buf = io.StringIO()
        with mock.patch.object(CH.sys, "stdin", io.StringIO(json.dumps(self.hook_inp(a)))), redirect_stdout(buf):
            CH.main()
        self.assertNotIn(mid, buf.getvalue())                                       # 0.25.0 (item 23): after-Bash hook output carries no relay line
        self.assertEqual(self.ev("nudge.relay_claim"), [])

    def test_rl7_guard_no_open_offer_means_no_claim_and_no_line(self):
        a, = self.holders("envoy")
        self.assertIsNone(CH.relay_hook(self.hook_inp(a)))
        self.assertEqual(self.ev("nudge.relay_claim"), [])

    def test_rl7_guard_an_answered_or_read_relay_costs_the_hook_no_import(self):
        a, = self.holders("envoy")
        mid = self.nudge()
        self.ask(mid)
        self.poll(a)
        D.record_result(self.h, a, mid, "delivered", EV)
        with mock.patch.object(H, "Harness", side_effect=AssertionError("the hook built a Harness")):
            self.assertIsNone(CH.relay_hook(self.hook_inp(a, sid="s-other")))

    # fix round 1 (critic m-fef22c88e380 blocker 1): a read or claimed rewake is closed for the hook; a busy lock is skipped
    def rewake_offer(self, mid, key_n=1):
        self.h.store.append("nudge.relay_offer", "system", {"msg_id": mid, "key": "%s#r%d" % (mid, key_n), "rewake": key_n,
                                                            "to": self.cur, "to_session": "local_cur", "from": self.cloud, "role": "secretary",
                                                            "thread": "t", "reason": "rewake_%d" % key_n})

    def test_fix1_a_read_rewake_costs_the_hook_no_import(self):
        a, = self.holders("envoy")
        mid = self.call("harness_send", agent=self.plain, to="role:curator", body="b", subject="s", kind="task")["id"]
        self.rewake_offer(mid)
        self.call("harness_inbox", agent=self.cur)                                    # the mail is read
        with mock.patch.object(H, "Harness", side_effect=AssertionError("the hook built a Harness")):
            self.assertIsNone(CH.relay_hook(self.hook_inp(a)))

    def test_fix1_a_claimed_rewake_costs_the_hook_no_import(self):
        a, = self.holders("envoy")
        mid = self.call("harness_send", agent=self.plain, to="role:curator", body="b", subject="s", kind="task")["id"]
        self.rewake_offer(mid)
        self.h.store.append("nudge.relay_claim", a, {"msg_id": mid, "key": mid + "#r1", "by": a, "to_session": "local_cur"})
        with mock.patch.object(H, "Harness", side_effect=AssertionError("the hook built a Harness")):
            self.assertIsNone(CH.relay_hook(self.hook_inp(a)))

    def test_fix1_an_unread_unclaimed_rewake_is_still_claimed(self):
        a, = self.holders("envoy")
        mid = self.call("harness_send", agent=self.plain, to="role:curator", body="b", subject="s", kind="task")["id"]
        self.rewake_offer(mid)
        self.assertIsNone(CH.relay_hook(self.hook_inp(a)))
        self.assertIn("Rewake 1 of 2", D.attach_relay(self.h, a, {"text": "x"})["text"])

    def test_fix1_a_busy_ledger_lock_is_skipped_not_waited_on(self):
        import fcntl
        a, = self.holders("envoy")
        mid = self.nudge()
        self.ask(mid)
        with open(os.path.join(self.home, "_harness", "events.lock"), "a") as lf:
            fcntl.flock(lf, fcntl.LOCK_EX)
            t0 = time.time()
            self.assertIsNone(CH.relay_hook(self.hook_inp(a)))
            self.assertLess(time.time() - t0, 1.0)
            fcntl.flock(lf, fcntl.LOCK_UN)
        self.assertIsNone(CH.relay_hook(self.hook_inp(a)))                           # 0.25.0 (item 23): the hook never claims

    # RL8
    def test_rl8_the_hook_repeats_at_most_once_per_2_min_and_stops_after_the_report(self):
        a, = self.holders("envoy")
        mid = self.nudge()
        self.ask(mid)
        t0 = time.time()
        with mock.patch.object(D, "RELAY_CLAIM_S", 900):                           # a long claim, to see the repeat step
            self.assertIn(mid, D.hook_relay_line(self.h, a, now=t0))
            self.assertIsNone(D.hook_relay_line(self.h, a, now=t0 + 60))
            self.assertIn(mid, D.hook_relay_line(self.h, a, now=t0 + 125))
            self.assertIsNone(D.hook_relay_line(self.h, a, now=t0 + 130))
            D.record_result(self.h, a, mid, "delivered", EV)
            self.assertIsNone(D.hook_relay_line(self.h, a, now=t0 + 300))
        self.assertEqual(len(self.ev("nudge.relay_claim")), 1)

    def test_rl8_the_hook_stops_after_the_recipient_reads(self):
        a, = self.holders("envoy")
        mid = self.nudge()
        self.ask(mid)
        t0 = time.time()
        with mock.patch.object(D, "RELAY_CLAIM_S", 900):
            self.assertIn(mid, D.hook_relay_line(self.h, a, now=t0))
            self.call("harness_inbox", agent=self.cur)
            self.assertIsNone(D.hook_relay_line(self.h, a, now=t0 + 200))

    # RL9
    def test_rl9_a_helper_subagents_tool_calls_never_claim(self):
        a, = self.holders("envoy")
        mid = self.nudge()
        self.ask(mid)
        self.assertIsNone(CH.relay_hook(self.hook_inp(a, agent_id="agent-helper-1")))
        self.assertIsNone(CH.relay_hook(self.hook_inp(a, transcript_path="/x/projects/p/s-main/subagents/agent-1.jsonl")))
        self.assertEqual(self.ev("nudge.relay_claim"), [])
        self.assertIsNone(CH.relay_hook(self.hook_inp(a)))                           # 0.25.0 (item 23): nor does the holder's own hook
        self.assertIn(mid, D.attach_relay(self.h, a, {"text": "x"})["text"])         # its next harness result does

    # timers (spec section 4 point 7, v3 nb 1)
    def test_timers(self):
        self.assertEqual((D.RELAY_CLAIM_S, D.RELAY_TURN_S, D.RELAY_TTL_S, D.RELAY_SILENT_S), (120, 30, 3900, 60))


if __name__ == "__main__":
    unittest.main()
