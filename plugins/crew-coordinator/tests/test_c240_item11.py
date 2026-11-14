"""cc 0.24.0 item 11 (scope A-b2950; relay-wake spec 2026-11-10_cc024-relay-wake-spec.md v3.2, section 2, tests H1-H4): every send whose
kind can ring returns `holder` for each role recipient. Each H test fails on 0.23.0.
Run: python3 -B tests/test_c240_item11.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _env  # noqa: F401  isolate HOME and HARNESS_* first
import os, re, unittest
from unittest import mock

import test_c220_nudge as C
import test_c225_wake as W25
from test_c220_nudge import D, H

entry = W25.entry
CAPSULE = "---\nhandoff: x\n---\n# H\nRoutine handoff.\n"


class Item11(C.Base):
    holder, pin = W25.W.holder, W25.W.pin

    def setUp(self):
        super().setUp()
        self.op["doorbell"] = {"nudge_per_agent_hour": 60, "nudge_per_pair_hour": 30}
        self.h.role_define("operator", "design-system", "harness-ops", carry="none")

    # H1
    def test_h1_after_a_handoff_the_reply_says_handed_off_with_the_capsule(self):
        ds = self.holder("design-system", "local_ds")
        ho = self.h.handoff(ds, CAPSULE)
        r = self.send(self.plain, "role:design-system")
        hs = r["holder"]["design-system"]
        self.assertRegex(hs, r"^handed_off since \d{4}-\d\d-\d\dT\d\d:\d\dZ \(capsule %s\)$" % re.escape(ho["capsule"]))
        self.assertEqual(r["nudge"], "none (no live holder: queued for the next restore; miss counted)")
        self.assertEqual(len([e for e in self.h.store.read_all() if e["type"] == "nudge.miss"]), 1)       # exactly one counted miss
        self.assertEqual(self.events("nudge.offered"), [])                       # the handed-off chat is not rung
        d = self.events("agent.handed_off")[-1]["data"]
        self.assertEqual((d["role"], d["capsule"]), ("design-system", ho["capsule"]))

    def test_h1c_a_successor_register_makes_the_role_live_again(self):     # critic m-7077188521ae: register with a predecessor
        ds = self.holder("design-system", "local_ds")
        self.h.handoff(ds, CAPSULE)
        self.reg("design-system", "local_ds2", predecessor=ds)
        r = self.send(self.plain, "role:design-system")
        self.assertEqual(r["holder"]["design-system"], "live_ringable")
        self.assertIsInstance(r["nudge"], dict)

    def test_h1c_a_restore_makes_the_role_live_again(self):
        ds = self.holder("design-system", "local_ds")
        self.h.handoff(ds, CAPSULE)
        with mock.patch.dict(os.environ, {"CLAUDE_CODE_HOST_SESSION_ID": "local_ds3"}):
            self.h.restore("design-system", model=C.MODEL, project="harness-ops", confirmed=True)
        r = self.send(self.plain, "role:design-system")
        self.assertEqual(r["holder"]["design-system"], "live_ringable")

    def test_h1c_a_plain_register_without_the_role_leaves_it_handed_off(self):
        ds = self.holder("design-system", "local_ds")
        self.h.handoff(ds, CAPSULE)
        self.reg(None, "local_other")
        self.assertTrue(self.send(self.plain, "role:design-system")["holder"]["design-system"].startswith("handed_off since"))

    def test_h1_a_handoff_event_from_before_0_24_still_folds_by_the_agents_role(self):
        ds = self.holder("design-system", "local_ds")
        self.h.store.append("agent.handed_off", ds, {"message": "m-000000000000"})   # 0.23.0 shape: no role, no capsule
        r = self.send(self.plain, "role:design-system")
        self.assertRegex(r["holder"]["design-system"], r"^handed_off since .* \(capsule none\)$")

    # H2
    def test_h2_a_vacant_role(self):
        r = self.send(self.plain, "role:design-system")
        self.assertEqual(r["holder"], {"design-system": "vacant"})
        self.assertEqual(r["nudge"], "none (no live holder: queued for the next restore; miss counted)")
        self.assertEqual(len([e for e in self.h.store.read_all() if e["type"] == "nudge.miss"]), 1)       # exactly one counted miss

    # H3
    def test_h3_a_holder_with_no_local_id_and_a_pin_is_live_wake_pin(self):
        with mock.patch.dict(os.environ, {"CLAUDE_CODE_HOST_SESSION_ID": ""}):
            self.reg("secretary", None)
        self.pin(secretary=entry("secretary", kind="recurring"))
        r = self.send(self.plain, "role:secretary")
        self.assertEqual(r["holder"], {"secretary": "live_wake_pin"})

    # H4
    def test_h4_a_stale_mark_is_live_mail_only(self):
        cur = self.holder("curator", "local_cur")
        n = self.send(self.plain, "role:curator")["nudge"]
        D.record_result(self.h, self.plain, n["msg_id"], "skipped", "stale_id")
        r = self.send(self.reg(host="local_s2"), "role:curator")
        self.assertEqual(r["holder"], {"curator": "live_mail_only (id route closed by a stale mark)"})
        self.assertTrue(cur)

    def test_h4_other_mail_only_reasons(self):
        with mock.patch.dict(os.environ, {"CLAUDE_CODE_HOST_SESSION_ID": ""}):
            self.reg("secretary", None)                                             # no id, no pin
        self.reg("envoy", "local_env", machine="machine-pc")                       # another machine
        r = self.send(self.plain, ["role:secretary", "role:envoy"])
        self.assertEqual(r["holder"], {"secretary": "live_mail_only (no app session id)",
                                       "envoy": "live_mail_only (holder on another machine)"})

    def test_live_ringable_and_only_kinds_that_ring(self):
        self.holder("curator", "local_cur")
        self.assertEqual(self.send(self.plain, "role:curator")["holder"], {"curator": "live_ringable"})
        self.assertNotIn("holder", self.send(self.plain, "role:curator", kind="notice"))
        self.assertNotIn("holder", self.send(self.plain, self.h.state().role_holder("curator")))   # a direct id: no role recipient

    # relay requested names the direction
    def test_a_sender_skip_relay_names_the_direction(self):
        self.holder("curator", "local_cur")
        with mock.patch.dict(os.environ, {"CLAUDE_CODE_HOST_SESSION_ID": ""}):
            cloud = self.reg("envoy", None)
        mid = self.send(cloud, "role:curator")["nudge"]["msg_id"]
        r = D.record_result(self.h, cloud, mid, "skipped", "no_sendmessage")
        self.assertEqual(r["nudge"], "relay requested (Cowork to Code)")
        self.assertEqual(D.direction(self.h.state(), self.plain, cloud), "Code to Cowork")


if __name__ == "__main__":
    unittest.main()
