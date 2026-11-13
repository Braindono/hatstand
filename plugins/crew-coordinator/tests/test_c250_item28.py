"""cc 0.25.0 item 28: wake Do-lines (verify, disable) go to the live envoy first; any other relay role gets one only when no qualifying envoy exists.
Run: python3 -B tests/test_c250_item28.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _env  # noqa: F401  isolate HOME and HARNESS_* first
import time
import unittest
from unittest import mock

import test_c240_item13 as I
from test_c240_item13 import D, H, T1, T2, S1, S2


class Item28(I.C.Base):
    for _n in ("cowork", "admin", "register", "verify", "ready"):
        locals()[_n] = I.Item13.__dict__[_n]
    del _n

    def setUp(self):
        I.C.Base.setUp(self)
        self.op["doorbell"] = {"nudge_per_agent_hour": 60, "nudge_per_pair_hour": 30}
        self.h.role_define("operator", "harness-critic", "harness-ops", carry="none")
        self.sec = self.cowork("secretary")
        self.env = self.reg("envoy", "local_env")
        self.cur = self.reg("curator", "local_cur")
        self.warm(self.env)
        self.warm(self.cur)
        self.k = 0

    def claims(self):
        return [(c["data"]["what"], c["data"]["by"]) for c in self.events("wake.claim")]

    def test_g_envoy_and_curator_live_only_the_envoy_gets_the_verify_line(self):
        self.register()
        self.assertIsNone(D.wake_do(self.h, self.cur))
        self.assertEqual(self.claims(), [])
        line = D.wake_do(self.h, self.env)
        self.assertIn("RemoteTrigger action=get trigger_id=" + T1, line)
        self.assertNotIn("(for the envoy)", line)
        self.assertEqual(self.claims(), [("verify", self.env)])

    def test_h_no_live_envoy_the_curator_gets_it(self):
        self.register()
        self.h.retire(self.env, "t", by="human")
        line = D.wake_do(self.h, self.cur)
        self.assertIn("RemoteTrigger action=get trigger_id=" + T1, line)
        self.assertIn("(for the envoy)", line)

    def test_h_an_envoy_that_is_not_ringable_does_not_hold_the_line_back(self):
        self.register()
        self.h.retire(self.env, "t", by="human")
        self.reg("envoy", None)                                   # a cowork envoy: no local_ id, cannot run it
        self.assertIn("RemoteTrigger action=get", D.wake_do(self.h, self.cur))

    def test_i_an_envoy_in_the_registrants_lineage_is_skipped_and_the_curator_gets_it(self):
        self.register()
        real = H.State.lineage
        env, sec = self.env, self.sec
        with mock.patch.object(H.State, "lineage", lambda st, a: real(st, a) + ([sec] if a == env else [])):   # the envoy descends from the registrant
            self.assertIsNone(D.wake_do(self.h, self.env))
            self.assertIn("RemoteTrigger action=get", D.wake_do(self.h, self.cur))

    def test_k_a_cold_envoy_does_not_starve_the_curator(self):
        self.register()
        D._save(D._sp(self.h, self.env), {"last_call": time.time() - 7200})      # closed or idle: outside the warm window
        self.assertIn("(for the envoy)", D.wake_do(self.h, self.cur))

    def test_k_an_envoy_claim_unreported_after_the_claim_window_passes_the_line_on(self):
        self.register()
        self.assertIn("action=get", D.wake_do(self.h, self.env))                  # the envoy takes it and never reports
        self.assertIsNone(D.wake_do(self.h, self.cur))                            # inside the window: nobody else
        later = time.time() + D.WAKE_CLAIM_S + 1
        self.assertIn("(for the envoy)", D.wake_do(self.h, self.cur, now=later))  # after it: the curator may claim
        self.assertEqual([b for _, b in self.claims()], [self.env, self.cur])

    def test_j_the_disable_line_goes_to_the_envoy_first_too(self):
        self.ready()
        new = self.cowork("secretary", predecessor=self.sec)
        self.register(who=new, trig=T2, session=S2)
        self.assertEqual(D.wake_to_disable(self.h.state()), {T1: "secretary"})
        self.assertIsNone(D.wake_do(self.h, self.cur))
        D.wake_do(self.h, self.env)                                 # the pending T2 verify line first
        line = D.wake_do(self.h, self.env)
        self.assertIn("RemoteTrigger action=update trigger_id=%s enabled=false" % T1, line)
        self.assertNotIn("(for the envoy)", line)
        self.assertEqual(sorted(w for w, _ in self.claims()), ["disable", "verify"])

    def test_j_with_no_envoy_the_disable_line_goes_to_the_curator_marked(self):
        self.ready()
        new = self.cowork("secretary", predecessor=self.sec)
        self.register(who=new, trig=T2, session=S2)
        self.h.retire(self.env, "t", by="human")
        D.wake_do(self.h, self.cur)
        self.assertIn("(for the envoy)", D.wake_do(self.h, self.cur))


if __name__ == "__main__":
    unittest.main()
