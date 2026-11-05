"""cc 0.22.2 (scope A-0ce70, curator spec 2026-11-05_cc0222-wake-build-spec.md): Cowork wake line and relayed nudge reports, T1-T5.
T6 is the existing suite plus the release simulator. Run: python3 -B tests/test_c222_wake.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _env  # noqa: F401  isolate HOME and HARNESS_* first
import os, time, unittest
from unittest import mock

import test_c220_nudge as C
from test_c220_nudge import D, H, TRIG

NOT_URGENT = "Do not skip this step because the mail is not urgent."
RUN = "cse_01Ft3xMWC2ETC3SihY2sLPDU"


class T(C.Base):
    def pinned_secretary(self, host=None):
        self.h.wake_pin_apply("operator", {"secretary": TRIG})
        with mock.patch.dict(os.environ, {"CLAUDE_CODE_HOST_SESSION_ID": ""}):
            return self.reg("secretary", host)

    def report(self, who, mid, outcome="woke", reason=""):
        return self.call("harness_admin", op="nudge_result", agent=who, args={"msg_id": mid, "outcome": outcome, "reason": reason})

    # T1
    def test_t1_no_chat_id_trigger_line_says_not_urgent_and_no_listagents(self):
        self.pinned_secretary()
        do = self.send(self.plain, "role:secretary")["nudge"]["do"]
        self.assertTrue(do.startswith("Do: RemoteTrigger action=run trigger_id=" + TRIG))
        self.assertIn(NOT_URGENT, do)
        self.assertNotIn("ListAgents", do)
        self.assertNotIn("SendMessage", do)
        self.assertNotIn("only if", do)                     # no chat id: the trigger stands alone, unconditional

    # T1/T2 (item 2): the billing hedge is gone; the subscription sentence stays
    def test_t1_line_keeps_subscription_sentence_and_no_billing_doubt(self):
        self.pinned_secretary()
        do = self.send(self.plain, "role:secretary")["nudge"]["do"]
        self.assertIn("runs under the Claude subscription, never with an API key", do)
        for w in ("billing", "bill ", "cost", "metered", "usage"):
            self.assertNotIn(w, do.lower())

    # T2
    def test_t2_with_chat_id_the_trigger_is_conditional_on_non_delivery(self):
        self.pinned_secretary("local_sec")
        do = self.send(self.plain, "role:secretary")["nudge"]["do"]
        first, second = do.split(" ; ")
        self.assertTrue(first.startswith("Do: SendMessage to local_sec:"))
        self.assertTrue(second.startswith("Do: RemoteTrigger action=run trigger_id=" + TRIG))
        self.assertIn("only if the SendMessage step above did not deliver or the session holds it", second)
        self.assertIn(NOT_URGENT, second)
        self.assertNotIn(NOT_URGENT, first)
        self.assertNotIn("ListAgents", do)

    # T3
    def test_t3_a_notice_to_a_pinned_role_gets_no_trigger_line(self):
        self.pinned_secretary("local_sec3")
        r = self.send(self.plain, "role:secretary", kind="notice")
        self.assertNotIn("RemoteTrigger", str(r.get("nudge") or ""))
        self.assertNotIn(NOT_URGENT, str(r))

    # T4
    def test_t4_relayer_with_evidence_is_accepted_with_by_and_for(self):
        self.pinned_secretary()
        mid = self.send(self.plain, "role:secretary")["nudge"]["msg_id"]
        relay = self.reg(host="local_envoy")
        r = self.report(relay, mid, reason="HTTP 200 " + RUN)
        self.assertTrue(r.get("reported"), r)
        ev = self.events("nudge.result")[-1]["data"]
        self.assertEqual(ev["by"], relay)
        self.assertEqual(ev["for"], self.plain)
        self.assertNotEqual(ev["by"], ev["for"])
        self.assertEqual(ev["evidence"], {"http": "200", "session": RUN, "self_reported": True})

    def test_t4_relayer_without_evidence_or_with_bad_status_is_refused(self):
        self.pinned_secretary()
        relay = self.reg(host="local_envoy")
        mid = self.send(self.plain, "role:secretary")["nudge"]["msg_id"]    # one offer: a refused report records nothing
        for bad in ("woke it", RUN, "HTTP 200", "HTTP abc " + RUN, "HTTP 2000 " + RUN, "HTTP 20 " + RUN,
                    "HTTP 200 cse_", "HTTP 200 xcse_01Ft3xMWC2ETC3"):
            with self.assertRaises(H.HarnessError, msg=bad) as cm:
                D.record_result(self.h, relay, mid, "woke", bad)
            self.assertIn("only the sender of", str(cm.exception))
        self.assertEqual(self.events("nudge.result"), [])

    def test_t4_status_digits_inside_the_session_id_do_not_count(self):
        self.assertIsNone(D.relay_evidence("cse_01Ab200Cd99"))
        self.assertEqual(D.relay_evidence("run cse_01Ab200Cd99 status 404"), {"http": "404", "session": "cse_01Ab200Cd99"})
        self.assertEqual(D.relay_evidence("session_01Ft3xMWC2 HTTP 200")["session"], "session_01Ft3xMWC2")

    def test_t4_the_sender_reports_as_before_without_evidence(self):
        self.pinned_secretary()
        mid = self.send(self.plain, "role:secretary")["nudge"]["msg_id"]
        r = self.report(self.plain, mid, outcome="skipped", reason="no_remotetrigger")
        self.assertTrue(r.get("reported"), r)
        ev = self.events("nudge.result")[-1]["data"]
        self.assertEqual((ev["by"], ev["for"]), (self.plain, self.plain))
        self.assertNotIn("evidence", ev)

    def test_t4_one_result_per_message_whoever_reports_first(self):
        self.pinned_secretary()
        mid = self.send(self.plain, "role:secretary")["nudge"]["msg_id"]
        relay = self.reg(host="local_envoy")
        self.assertTrue(self.report(relay, mid, reason="HTTP 200 " + RUN).get("reported"))
        self.assertTrue(self.report(self.plain, mid, outcome="skipped", reason="x").get("already_reported"))
        self.assertEqual(len(self.events("nudge.result")), 1)

    # T5
    def _unreported(self, tag):
        c = self.reg("curator", "local_cur" + tag)
        self.warm(c)
        s = self.reg(host="local_s" + tag)
        mid = self.send(s, "role:curator")["nudge"]["msg_id"]
        self.h.store.append("nudge.unreported", "system", {"msg": mid, "msg_id": mid, "by": s})
        self.call("harness_inbox", agent=c)
        return mid, self.reg(host="local_relay" + tag)

    def test_t5_a_refused_relay_leaves_the_unreported_alarm(self):
        mid, relay = self._unreported("5a")
        with self.assertRaises(H.HarnessError):
            D.record_result(self.h, relay, mid, "delivered", "rang it")
        self.assertEqual([x["cond"] for x in D.alarm_scan(self.h, force=True) if x["msg_id"] == mid], ["unreported"])

    def test_t5_an_evidenced_relay_clears_the_unreported_alarm(self):
        mid, relay = self._unreported("5b")
        D.record_result(self.h, relay, mid, "delivered", "HTTP 200 " + RUN)
        self.assertEqual([x for x in D.alarm_scan(self.h, force=True) if x["msg_id"] == mid], [])


if __name__ == "__main__":
    unittest.main()
