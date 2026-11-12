"""cc 0.24.0 item 4 (scope A-b2950; curator spec 2026-11-10_cc024-gaps-checks-build-spec.md v2.1): proctor gaps.
4.1 any close of an S0 needs the operator; 4.2 the proctor's restore digest has no capsule; 4.3 a refused case event keeps its grant.
Each test but the guards fails on 0.23.0.
Run: python3 -B tests/test_c240_item4.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _env  # noqa: F401  isolate HOME and HARNESS_* first
import json, unittest

import test_c230_proctor_events as P23
from test_c230_proctor_events import H


class Item4(P23.C.Base):
    # the 0.23.0 class's setUp and helpers only, not its tests
    def setUp(self):
        super().setUp()
        for r in ("proctor", "harness-critic"):
            self.h.role_define("operator", r, "harness-ops", carry="none")
        self.A = self.reg("proctor", "local_A")
        self.crit = self.reg("harness-critic", "local_crit")

    ca, bad, source, open, grant, shadow, classified, case = (P23.P.ca, P23.P.bad, P23.P.source, P23.P.open, P23.P.grant, P23.P.shadow,
                                                              P23.P.classified, P23.P.case)

    def s0(self, shadow_off=True):
        if shadow_off:
            self.shadow(False)
        return self.classified("S0")

    # 4.1
    def test_s0_close_as_fixed_routed_or_wont_fix_needs_the_operator(self):
        x = self.s0()
        self.ca(self.A, action="route", case=x, to="curator")
        for out, kw in (("fixed", {"ref": "commit abc"}), ("routed", {}), ("wont_fix", {})):
            with self.subTest(outcome=out):
                self.bad(r"any close of an S0 case needs the operator.*Hub queue", self.A, action="close", case=x, outcome=out, **kw)
        self.assertIsNone(self.case(x)["closed"])

    def test_s0_close_with_an_approved_case_close_for_that_case_and_outcome_closes(self):
        x = self.s0()
        req = self.ca(self.plain, action="request_close", case=x, outcome="fixed", ref="commit abc", reason="done")
        self.assertEqual(self.grant(req["pending"])["state"], "granted")
        self.assertEqual(self.case(x)["closed"]["outcome"], "fixed")

    def test_an_approval_for_another_case_or_outcome_is_refused(self):
        x, y = self.s0(), self.classified("S0")
        req = self.ca(self.plain, action="request_close", case=x, outcome="wont_fix", reason="r")
        rec = self.h._approval_records()[req["pending"]]
        self.h.store.append("approval.granted", "human", {"id": rec["id"], "channel": "cli-tty", "by": "operator", "state": "granted",
                                                          "result": None, "args_digest": rec["args_digest"]})   # granted, event not yet written
        for case, out in ((y, "wont_fix"), (x, "fixed")):
            with self.subTest(case=case, outcome=out):
                d = {"case": case, "outcome": out, "ref": "r", "reason": "r", "approval": rec["id"], "by": "operator"}
                with self.assertRaisesRegex(H.HarnessError, "approval not granted, used, or for other args"):
                    self.h._case_append("case.closed", None, d, actor="human")
        self.assertIsNone(self.case(x)["closed"])
        self.assertIsNone(self.case(y)["closed"])

    def test_guard_a_non_s0_close_is_unchanged(self):
        y = self.s0() and self.classified("S2")
        self.ca(self.A, action="close", case=y, outcome="fixed", ref="commit abc")
        self.assertEqual(self.case(y)["closed"]["outcome"], "fixed")

    # 4.2
    def test_proctor_restore_digest_has_no_latest_capsule(self):
        txt = self.h.restore_digest(self.h.state(), self.A, "proctor", [])
        txt = txt if isinstance(txt, str) else json.dumps(txt, default=str)
        self.assertNotIn("Latest capsule", txt)
        self.assertIn("State note", txt)
        other = self.h.restore_digest(self.h.state(), self.crit, "harness-critic", [])
        self.assertIn("Latest capsule", other if isinstance(other, str) else json.dumps(other, default=str))

    # 4.3
    def test_a_refused_case_event_keeps_its_grant_and_the_same_args_retry_it(self):
        x = self.s0()
        req = self.ca(self.plain, action="request_close", case=x, outcome="routed", reason="sent to curator")
        g = self.grant(req["pending"])                                     # refused: no case.routed yet
        self.assertEqual(g["state"], "failed")
        self.assertTrue(g["result"].startswith("granted, not yet run: "), g["result"])
        self.assertIn("routed needs a case.routed", g["result"])
        rec = self.h._approval_records()[req["pending"]]
        self.assertEqual(rec["state"], "granted")
        self.assertFalse(rec.get("consumed"))
        self.assertIsNone(rec["expires"])
        self.assertIsNone(self.case(x)["closed"])
        # retry before the cause is fixed: refused again with the present state, grant still kept
        again = self.ca(self.plain, action="request_close", case=x, outcome="routed", reason="sent to curator")
        self.assertEqual(again["state"], "failed")
        self.assertIn("routed needs a case.routed", again["result"])
        self.assertEqual(self.h._approval_records()[req["pending"]]["state"], "granted")
        # other args: never reach the kept grant; a new request is filed and nothing closes
        other = self.ca(self.plain, action="request_close", case=x, outcome="wont_fix", reason="r")
        self.assertIn("pending", other)
        self.assertNotEqual(other["pending"], req["pending"])
        self.assertIsNone(self.case(x)["closed"])
        # cause fixed: the same args retry it, once
        self.ca(self.A, action="route", case=x, to="curator")
        ok = self.ca(self.A, action="request_close", case=x, outcome="routed", reason="sent to curator")
        self.assertEqual(ok["state"], "granted", ok)
        self.assertEqual(self.case(x)["closed"]["outcome"], "routed")
        ev = self.events("case.closed")[-1]
        self.assertEqual((ev["actor"], ev["data"]["approval"], ev["data"]["retry_by"]), ("human", req["pending"], self.A))
        self.assertEqual(len([e for e in self.events("approval.requested") if e["data"]["id"] == req["pending"]]), 1)   # never asked again

    def test_guard_p5b_grant_on_a_moved_case_still_writes_nothing(self):
        x = self.open("S0")
        r = self.ca(self.A, action="propose", case=x, new="S2")
        req = self.ca(self.plain, action="request_severity", case=x, old="S0", new="S3")
        self.grant(req["pending"])
        g = self.grant(r["pending"])
        self.assertEqual(g["state"], "failed")
        self.assertTrue(g["result"].startswith("granted, not yet run: "))
        self.assertEqual(self.h._approval_records()[r["pending"]]["state"], "granted")    # kept, unused
        self.assertEqual(self.case(x)["severity"], "S3")


if __name__ == "__main__":
    unittest.main()
