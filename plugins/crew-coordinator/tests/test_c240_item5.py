"""cc 0.24.0 item 5 (scope A-b2950; relay-wake spec 2026-11-10_cc024-relay-wake-spec.md v3.2, section 1 and tests W1-W10): task, question
and review always ring. Each W test fails on 0.23.0.
Run: python3 -B tests/test_c240_item5.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _env  # noqa: F401  isolate HOME and HARNESS_* first
import contextlib, os, time, unittest
from unittest import mock

import test_c220_nudge as C
import test_c225_wake as W25
from test_c220_nudge import D, H, TRIG

RUN = "cse_01Ft3xMWC2ETC3SihY2sLPDU"
EV = "delivery: delivered; message_id: a1b2c3d4-0000-4000-8000-0000000000e1"
entry = W25.entry


class Item5(C.Base):
    holder, pin, sync_text = W25.W.holder, W25.W.pin, W25.W.sync_text      # helpers only, not the 0.22.5 tests

    def setUp(self):
        super().setUp()
        self.op["doorbell"] = {"nudge_per_agent_hour": 60, "nudge_per_pair_hour": 30}
        self.t0 = time.time()
        for r in ("harness-critic", "ops-coder"):
            self.h.role_define("operator", r, "harness-ops", carry="none")

    @contextlib.contextmanager
    def at(self, sec):
        with mock.patch.object(D.time, "time", return_value=self.t0 + sec):
            yield

    def send_at(self, sec, frm=None, to="role:secretary", kind="task"):
        with self.at(sec):
            return self.send(frm or self.plain, to, kind=kind)

    def report(self, who, mid, outcome, reason, sec=None):
        if sec is None:
            return D.record_result(self.h, who, mid, outcome, reason)
        with self.at(sec):
            return D.record_result(self.h, who, mid, outcome, reason)

    def skips(self, r):
        return [x["reason"] for x in r.get("nudge_skipped") or []]

    def cowork_secretary(self):
        """A secretary with no local_ id (a Cowork chat) and a recurring wake pin: the trigger is its only route."""
        with mock.patch.dict(os.environ, {"CLAUDE_CODE_HOST_SESSION_ID": ""}):
            a = self.reg("secretary", None)
        self.pin(secretary=entry("secretary", kind="recurring"))
        return a

    def read(self, aid, sec):
        with self.at(sec):
            self.call("harness_inbox", agent=aid)

    # ---- R1
    def test_w1_not_needed_is_refused_with_the_list(self):
        self.holder("curator", "local_cur")
        mid = self.send_at(0, to="role:curator")["nudge"]["msg_id"]
        for bad in ("not needed", "recipient busy", "", "skipped"):
            with self.subTest(reason=bad), self.assertRaisesRegex(H.HarnessError, r"always rings: skipped needs one of these reasons: "
                                                                  r"no_sendmessage, no_remotetrigger, no_listagents, no_response, app_cap, stale_id"):
                self.report(self.plain, mid, "skipped", bad)
        self.assertEqual(self.events("nudge.result"), [])
        self.assertTrue(self.report(self.plain, mid, "skipped", "stale_id: session archived").get("reported"))

    def test_w1_question_and_review_too_but_handoff_keeps_free_text(self):
        self.holder("curator", "local_cur")
        for i, kind in enumerate(("question", "review")):
            mid = self.send_at(100 * i, to="role:curator", kind=kind)["nudge"]["msg_id"]
            with self.assertRaises(H.HarnessError):
                self.report(self.plain, mid, "skipped", "not needed")
        mid = self.send_at(500, to="role:curator", kind="handoff")["nudge"]["msg_id"]
        self.assertTrue(self.report(self.plain, mid, "skipped", "not needed").get("reported"))

    def test_w2_app_cap_becomes_a_relay_request(self):
        self.holder("curator", "local_cur")
        self.holder("envoy", "local_env")                                   # a live relay claimer
        mid = self.send_at(0, to="role:curator")["nudge"]["msg_id"]
        r = self.report(self.plain, mid, "skipped", "app_cap")
        self.assertTrue(r.get("relay_requested"), r)
        self.assertEqual([e["data"]["reason"] for e in self.events("nudge.relay_offer")], ["app_cap"])
        self.assertEqual(self.events("nudge.result"), [])                 # the result slot stays free for the relay

    def test_w2_no_remotetrigger_on_a_task_asks_for_a_relay(self):
        self.holder("curator", "local_cur")
        mid = self.send_at(0, to="role:curator")["nudge"]["msg_id"]
        self.assertTrue(self.report(self.plain, mid, "skipped", "no_remotetrigger").get("relay_requested"))

    # ---- R2
    def test_w3_no_second_wake_while_the_woken_mail_is_unread(self):
        self.cowork_secretary()
        n1 = self.send_at(0)["nudge"]
        self.assertIn(TRIG, n1["do"])
        self.report(self.plain, n1["msg_id"], "woke", "HTTP 200", sec=5)
        r2 = self.send_at(180, frm=self.reg(host="local_s2"))
        self.assertNotIn("RemoteTrigger", str(r2.get("nudge")))
        self.assertEqual(self.skips(r2), ["unread wake pending (%s)" % n1["msg_id"]])
        self.assertEqual(len(self.events("nudge.trigwake")), 1)

    def test_w3_inverse_read_mail_does_not_block(self):
        sec = self.cowork_secretary()
        n1 = self.send_at(0)["nudge"]
        self.report(self.plain, n1["msg_id"], "woke", "HTTP 200", sec=5)
        self.read(sec, 60)
        self.assertIn(TRIG, self.send_at(180)["nudge"]["do"])

    def test_w3_a_failed_fire_blocks_nothing(self):
        self.cowork_secretary()
        n1 = self.send_at(0)["nudge"]
        self.report(self.plain, n1["msg_id"], "woke", "HTTP 503", sec=5)
        self.assertIn(TRIG, self.send_at(180)["nudge"]["do"])

    def test_w4_one_rewake_at_15_min(self):
        self.cowork_secretary()
        n1 = self.send_at(0)["nudge"]
        self.report(self.plain, n1["msg_id"], "woke", "HTTP 200", sec=5)
        r2 = self.send_at(16 * 60)
        self.assertIn(TRIG, r2["nudge"]["do"])
        rw = [e["data"] for e in self.events("nudge.rewake")]
        self.assertEqual([(d["msg_id"], d["n"], d["via"]) for d in rw], [(n1["msg_id"], 1, r2["nudge"]["msg_id"])])
        r3 = self.send_at(18 * 60)                                                       # past r2's 60 s, so only R2 holds it
        self.assertNotIn("RemoteTrigger", str(r3.get("nudge")))
        self.assertIn("unread wake pending (%s)" % n1["msg_id"], self.skips(r3))

    # ---- R3
    def test_w5_one_ring_per_session_refuses_a_relay_after_delivered(self):
        self.holder("curator", "local_cur")
        self.holder("envoy", "local_env")
        n = self.send_at(0, to="role:curator")["nudge"]
        self.report(self.plain, n["msg_id"], "delivered", "row", sec=3)
        offer = next(e["data"] for e in self.events("nudge.offered") if e["data"]["msg_id"] == n["msg_id"])
        r = D._request_relay(self.h, self.h.state(), offer, n["msg_id"], "app_cap")
        self.assertFalse(r.get("relay_requested"))
        self.assertIn("one ring per recipient session", r["refused"])
        self.assertEqual(self.events("nudge.relay_offer"), [])

    # ---- R1b
    def test_w6_a_silent_sender_becomes_a_relay_after_60_s(self):
        cur = self.holder("curator", "local_cur")
        env = self.holder("envoy", "local_env")
        mid = self.send_at(0, to="role:curator")["nudge"]["msg_id"]
        self.assertEqual(D.wake_scan(self.h, now=self.t0 + 59, force=True), [])
        self.assertEqual(D.wake_scan(self.h, now=self.t0 + 61, force=True), [("relay", mid)])
        ro = self.events("nudge.relay_offer")
        self.assertEqual([(e["actor"], e["data"]["reason"], e["data"]["to"]) for e in ro], [("system", "sender_silent", cur)])
        self.assertEqual(D.wake_scan(self.h, now=self.t0 + 90, force=True), [])            # one per message
        with self.at(100):
            line = D.claim_relay(self.h, env, now=self.t0 + 100)
        self.assertIn("SendMessage to local_cur", line)
        self.assertTrue(self.report(env, mid, "delivered", EV, sec=110).get("reported"))
        r = self.report(self.plain, mid, "delivered", "row", sec=120)                     # the sender's late report still counts
        self.assertTrue(r.get("recorded_late"), r)
        self.assertEqual(len(self.events("nudge.result_late")), 1)

    def test_w6_inverse_read_or_reported_mail_gets_no_relay(self):
        cur = self.holder("curator", "local_cur")
        m1 = self.send_at(0, to="role:curator")["nudge"]["msg_id"]
        self.read(cur, 30)
        m2 = self.send_at(200, to="role:curator", frm=self.reg(host="local_s2"))["nudge"]["msg_id"]
        self.report(self.events("nudge.offered")[-1]["data"]["from"], m2, "delivered", "row", sec=205)
        self.assertEqual(D.wake_scan(self.h, now=self.t0 + 400, force=True), [])
        self.assertEqual(self.events("nudge.relay_offer"), [])
        self.assertTrue(m1)

    # ---- R1c
    def test_w7_a_capped_task_gets_a_relay_then_a_counted_miss(self):
        self.op["doorbell"] = {"nudge_per_agent_hour": 60, "nudge_per_pair_hour": 2}
        self.holder("curator", "local_cur")
        env = self.holder("envoy", "local_env")
        for i in range(2):
            n = self.send_at(100 * i, to="role:curator")["nudge"]
            self.report(self.plain, n["msg_id"], "delivered", "row", sec=100 * i + 2)
        r3 = self.send_at(300, to="role:curator")
        self.assertEqual(r3["nudge"], "relay requested (capped:pair; Code to Code)")             # item 11 names the direction
        self.assertEqual(r3["nudge_skipped"][0]["relay"], "relay requested (capped:pair; Code to Code)")
        ro = self.events("nudge.relay_offer")[-1]["data"]
        self.assertEqual((ro["reason"], ro["msg_id"]), ("capped:pair", r3["id"]))
        with self.at(310):
            self.assertIn("SendMessage to local_cur", D.claim_relay(self.h, env, now=self.t0 + 310))
        self.assertTrue(self.report(env, r3["id"], "delivered", EV, sec=320).get("reported"))   # a relay-only message takes the report
        with mock.patch.object(D, "RELAY_PER_SENDER_HOUR", 1):
            r4 = self.send_at(400, to="role:curator")
        self.assertTrue(r4["nudge_skipped"][0]["relay"].startswith("miss (capped:pair; relay cap full"))
        self.assertEqual([(e["data"]["msg_id"], e["data"]["reason"]) for e in self.events("nudge.miss")],
                         [(r4["id"], "capped:pair; relay cap full")])

    def test_w7_handoff_cap_stays_a_bare_skip(self):
        self.op["doorbell"] = {"nudge_per_agent_hour": 60, "nudge_per_pair_hour": 1}
        self.holder("curator", "local_cur")
        self.send_at(0, to="role:curator", kind="handoff")
        r = self.send_at(100, to="role:curator", kind="handoff")
        self.assertNotIn("relay", r["nudge_skipped"][0])
        self.assertEqual(self.events("nudge.relay_offer") + self.events("nudge.miss"), [])

    # ---- W8: fire statuses under R2 (the parse is item 3's fire_status)
    def test_w8_a_404_stales_at_once_and_does_not_block(self):
        self.cowork_secretary()
        n1 = self.send_at(0)["nudge"]
        self.report(self.plain, n1["msg_id"], "woke", "HTTP 404", sec=5)
        self.assertEqual(D.wake_pin_state(self.h.state(), "secretary", self.h)[1], "stale")
        r2 = self.send_at(125)
        self.assertNotIn("unread wake pending", " ".join(self.skips(r2)))

    def test_w8_500_then_200_is_a_failed_fire_and_not_woken(self):
        self.cowork_secretary()
        n1 = self.send_at(0)["nudge"]
        self.report(self.plain, n1["msg_id"], "woke", "HTTP 500 then HTTP 200", sec=5)
        self.assertIn(TRIG, self.send_at(125)["nudge"]["do"])                           # no R2 block
        self.assertEqual(D.wake_pin_state(self.h.state(), "secretary", self.h)[1], "ok")

    def test_w8_transient_counts_reset_by_2xx_and_no_response_is_not_a_failure(self):
        sec = self.cowork_secretary()
        t = [0]

        def fire(reason, outcome="woke"):
            t[0] += 130
            mid = self.send_at(t[0])["nudge"]["msg_id"]
            self.report(self.plain, mid, outcome, reason, sec=t[0] + 2)
            self.read(sec, t[0] + 4)                                                    # read, so R2 never blocks the next fire
            return D.wake_pin_state(self.h.state(), "secretary", self.h)[1]
        self.assertEqual([fire(r) for r in ("HTTP 503", "HTTP 200", "HTTP 503", "HTTP 503")], ["ok"] * 4)
        self.assertEqual(fire("no_response", "skipped"), "ok")
        self.assertEqual(fire("HTTP 503"), "stale")                                     # 503, 503, (no_response), 503
        self.setUp()
        sec = self.cowork_secretary()
        t[0] = 0
        self.assertEqual([fire("HTTP 503"), fire("no_response", "skipped"), fire("HTTP 503")], ["ok", "ok", "ok"])

    def test_w8_fire_doline_names_no_response(self):
        self.cowork_secretary()
        do = self.send_at(0)["nudge"]["do"]
        self.assertIn("No response at all (tool error, network down): report skipped with reason no_response", do)

    # ---- W9: rewake ladder
    def test_w9_rewake_at_15_min_and_1_h_then_nothing(self):
        sec = self.cowork_secretary()
        n1 = self.send_at(0)["nudge"]
        self.report(self.plain, n1["msg_id"], "woke", "HTTP 200", sec=5)
        self.assertEqual(D.wake_scan(self.h, now=self.t0 + 14 * 60, force=True), [])
        self.assertEqual(D.wake_scan(self.h, now=self.t0 + 15 * 60 + 6, force=True), [("rewake1", n1["msg_id"]), ("relay_rewake1", n1["msg_id"])])
        with self.at(15 * 60 + 10):
            lines = D.rewake_do(self.h, self.plain)
        self.assertEqual(len(lines), 1)
        self.assertTrue(lines[0].startswith("Rewake 1 of 2 for %s" % n1["msg_id"]))
        self.assertIn("RemoteTrigger action=run trigger_id=" + TRIG, lines[0])
        self.assertIn("No report is needed for a rewake.", lines[0])
        with self.at(15 * 60 + 20):
            self.assertEqual(D.rewake_do(self.h, self.plain), [])                       # shown once
        self.assertEqual(D.wake_scan(self.h, now=self.t0 + 30 * 60, force=True), [])
        self.assertEqual(D.wake_scan(self.h, now=self.t0 + 60 * 60 + 6, force=True), [("rewake2", n1["msg_id"]), ("relay_rewake2", n1["msg_id"])])
        with self.at(60 * 60 + 10):
            txt = self.sync_text(self.plain)
        self.assertIn("%s to role:secretary still unread after 1 h; holder state: live_wake_pin" % n1["msg_id"], txt)
        self.assertEqual(D.wake_scan(self.h, now=self.t0 + 3 * 3600, force=True), [])
        self.assertEqual([e["data"]["n"] for e in self.events("nudge.rewake")], [1, 2])
        self.read(sec, 3 * 3600 + 10)
        with self.at(3 * 3600 + 20):
            self.assertNotIn("still unread after 1 h", self.sync_text(self.plain))

    def test_w9_a_read_before_15_min_gives_no_rewake(self):
        sec = self.cowork_secretary()
        n1 = self.send_at(0)["nudge"]
        self.report(self.plain, n1["msg_id"], "woke", "HTTP 200", sec=5)
        self.read(sec, 600)
        self.assertEqual(D.wake_scan(self.h, now=self.t0 + 3700, force=True), [])

    # fix 1 (critic m-4f605b30f919 blocker 1): the sender goes idle; a live relay holder carries the rewake
    def test_w9b_an_idle_sender_does_not_strand_the_rewake(self):
        self.cowork_secretary()
        env = self.holder("envoy", "local_env")
        crit = self.holder("harness-critic", "local_crit")
        n1 = self.send_at(0)["nudge"]                                                   # the plain sender: fires, reports, goes idle
        self.report(self.plain, n1["msg_id"], "woke", "HTTP 200", sec=5)
        with self.at(15 * 60 + 6):
            line = D.claim_relay(self.h, env, now=self.t0 + 15 * 60 + 6)
        self.assertTrue(line.startswith("Do: RemoteTrigger action=run trigger_id=" + TRIG), line)
        self.assertIn("rewake 1 of 2 for %s" % n1["msg_id"], line)
        self.assertIn("run with no body", line)
        self.assertIn("No report is needed.", line)
        with self.at(15 * 60 + 30):
            self.assertIsNone(D.claim_relay(self.h, crit, now=self.t0 + 15 * 60 + 30))   # claimed once: done, no second ring
            self.assertEqual(D.rewake_do(self.h, self.plain), [])                       # nor from the sender when it comes back
        self.assertEqual(self.events("nudge.result")[-1]["data"]["outcome"], "woke")    # the result slot is untouched
        self.assertEqual(len(self.events("nudge.result")), 1)

    def test_w9b_a_code_recipient_gets_a_sendmessage_rewake(self):
        cur = self.holder("curator", "local_cur")
        env = self.holder("envoy", "local_env")
        n1 = self.send_at(0, to="role:curator")["nudge"]
        self.report(self.plain, n1["msg_id"], "delivered", "row", sec=3)
        with self.at(15 * 60 + 6):
            line = D.claim_relay(self.h, env, now=self.t0 + 15 * 60 + 6)
        self.assertTrue(line.startswith("Do: SendMessage to local_cur: Mail %s" % n1["msg_id"]), line)
        self.assertIn("Rewake 1 of 2", line)
        self.assertTrue(cur)

    def test_w9b_read_mail_closes_the_rewake_offer_and_nothing_piles_up(self):
        sec = self.cowork_secretary()
        env = self.holder("envoy", "local_env")
        n1 = self.send_at(0)["nudge"]
        self.report(self.plain, n1["msg_id"], "woke", "HTTP 200", sec=5)
        for m in range(61, 400, 5):                                                     # nobody calls for the first hour, then for hours
            D.wake_scan(self.h, now=self.t0 + m * 60, force=True)
        self.assertEqual([e["data"]["n"] for e in self.events("nudge.rewake")], [2])    # both steps due at once: step 2 only
        self.assertEqual([e["data"].get("key") for e in self.events("nudge.relay_offer")], [n1["msg_id"] + "#r2"])
        self.read(sec, 400 * 60)
        with self.at(400 * 60 + 5):
            self.assertIsNone(D.claim_relay(self.h, env, now=self.t0 + 400 * 60 + 5))

    # ---- nb 6
    def test_w10_two_tasks_to_one_code_session_30_s_apart_ring_once(self):
        self.holder("curator", "local_cur")
        n1 = self.send_at(0, to="role:curator")["nudge"]
        self.assertTrue(n1["do"].startswith("Do: SendMessage to local_cur"))
        r2 = self.send_at(30, to="role:curator", frm=self.reg(host="local_s2"))
        self.assertEqual(r2["nudge"], "none (rung under 60 s ago (%s): one ring reads both)" % n1["msg_id"])
        self.assertEqual(len(self.events("nudge.offered")), 1)
        self.assertTrue(isinstance(self.send_at(95, to="role:curator")["nudge"], dict))   # past 60 s it rings again

    def test_w10_inverse_a_read_first_mail_does_not_hold_the_second(self):
        cur = self.holder("curator", "local_cur")
        self.send_at(0, to="role:curator")
        self.read(cur, 10)
        self.assertTrue(isinstance(self.send_at(30, to="role:curator")["nudge"], dict))

    # critic m-da843f8de897 (non-blocking): every R2 / nb 6 skip reason the send path writes is one alarm_scan reads as held mail
    def test_held_reasons_written_are_the_ones_the_alarm_reads(self):
        self.cowork_secretary()
        n1 = self.send_at(0)["nudge"]
        r_nb6 = self.send_at(10, frm=self.reg(host="local_s2"))
        self.report(self.plain, n1["msg_id"], "woke", "HTTP 200", sec=20)
        r_r2 = self.send_at(200, frm=self.reg(host="local_s3"))
        written = self.skips(r_nb6) + self.skips(r_r2)
        self.assertEqual(len(written), 2)
        self.assertTrue(all(w.startswith(D.HELD_REASONS) for w in written), written)
        self.assertEqual([w.startswith(D.HELD_NB6) for w in written], [True, False])

    # ---- Do-line text
    def test_sendmessage_doline_names_app_cap(self):
        self.holder("curator", "local_cur")
        self.assertIn("report skipped with reason app_cap", self.send_at(0, to="role:curator")["nudge"]["do"])


if __name__ == "__main__":
    unittest.main()
