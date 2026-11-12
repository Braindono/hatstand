"""cc 0.24.0 item 3 (scope A-b2950; curator spec 2026-11-10_cc024-gaps-checks-build-spec.md v2.1): the fire report status is one format.
Each test but the replay guards fails on 0.23.0.
Run: python3 -B tests/test_c240_item3.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _env  # noqa: F401  isolate HOME and HARNESS_* first
import os, time, unittest
from unittest import mock

import test_c220_nudge as C
import test_c225_wake as W25
from test_c220_nudge import D, H, TRIG

RUN = "cse_01Ft3xMWC2ETC3SihY2sLPDU"
entry = W25.entry
STEP = D.TRIG_WAKE_MIN * 60 + 5


class Item3(C.Base):
    holder, pin, do, sync_text = W25.W.holder, W25.W.pin, W25.W.do, W25.W.sync_text     # helpers only, not the 0.22.5 tests

    def setUp(self):
        super().setUp()
        self.op["doorbell"] = {"nudge_per_agent_hour": 60, "nudge_per_pair_hour": 30}
        self.k = 0
        self.t0 = time.time()

    def offer(self):
        """One trigger-offered task to role:secretary, each one past the 10-minute trigger slot."""
        self.k += 1
        with mock.patch.object(D.time, "time", return_value=self.t0 + self.k * STEP):
            r = self.send(self.plain, "role:secretary")
        self.assertIn(TRIG, r["nudge"]["do"])
        return r["nudge"]["msg_id"]

    def ready(self, kind="run_once"):
        self.sec = self.holder()
        self.pin(secretary=entry("secretary", kind=kind))

    def fire(self, reason, relay=False):
        mid = self.offer()
        who = self.reg(host="local_relay%d" % self.k) if relay else self.plain
        r = D.record_result(self.h, who, mid, "woke", reason)
        self.call("harness_inbox", agent=self.sec)        # 0.24.0 (item 5): the holder reads, so R2 never holds the next fire
        return r

    def state(self):
        return D.wake_pin_state(self.h.state(), "secretary", self.h)[1]

    # 3.1: one format, start-anchored; a refused report records nothing and the pin stays
    def test_free_text_reasons_are_refused_with_the_format(self):
        self.ready()
        for bad in ("RemoteTrigger run for role secretary via trigger trig_012gGzBeCsh8unZeB1rkKx1a returned HTTP 404",
                    "returned 404", "404: Not Found", "404 trigger not found", "HTTPS 404", "HTTP/1.1 200 OK", "http 200", "trigger",
                    "HTTP 2000", "HTTP 20", ""):
            with self.subTest(reason=bad):
                mid = self.offer()
                with self.assertRaisesRegex(H.HarnessError, r"reason must start with HTTP <3 digits>"):
                    D.record_result(self.h, self.plain, mid, "woke", bad)
        # 0.24.0 (item 5, R1b): the refused offers stay unreported, so the scan relays them and expiry writes system results; none by the sender
        self.assertEqual([e for e in self.events("nudge.result") if e["actor"] != "system"], [])
        self.assertEqual(self.state(), "ok")

    def test_leading_whitespace_is_trimmed(self):
        self.ready()
        self.assertTrue(self.fire("   HTTP 200").get("reported"))
        self.assertEqual(self.events("nudge.result")[-1]["data"]["status"], 200)
        self.assertEqual(self.state(), "spent")

    # 3.2: any 2xx spends a run_once pin; a recurring pin stays
    def test_any_2xx_spends_a_run_once_pin(self):
        for r in ("HTTP 200", "HTTP 202", "HTTP 204"):
            with self.subTest(reason=r):
                self.setUp()
                self.ready()
                self.fire(r)
                self.assertEqual(self.state(), "spent")

    def test_a_recurring_pin_stays_after_a_2xx(self):
        self.ready("recurring")
        self.fire("HTTP 200")
        self.assertEqual(self.state(), "ok")

    # 3.2: gone statuses stale at once and spend nothing
    def test_404_410_401_403_stale_the_pin_at_once(self):
        for r in ("HTTP 404", "HTTP 410", "HTTP 401", "HTTP 403"):
            with self.subTest(reason=r):
                self.setUp()
                self.ready()
                self.fire(r)
                self.assertEqual(self.state(), "stale")
                self.assertEqual(self.h.state().trig_spent, {})
                with mock.patch.object(D.time, "time", return_value=self.t0 + 20 * STEP):
                    self.assertNotIn("RemoteTrigger", self.do())
                self.assertIn("its trigger failed with HTTP %s" % r[5:], self.sync_text(self.h.state().role_holder("secretary")))

    def test_a_recurring_pin_goes_stale_on_404_too(self):
        self.ready("recurring")
        self.fire("HTTP 404")
        self.assertEqual(self.state(), "stale")

    # 3.2: transient statuses stale only after three failed fires in a row
    def test_one_transient_failure_is_not_stale(self):
        for r in ("HTTP 503", "HTTP 429", "HTTP 408"):
            with self.subTest(reason=r):
                self.setUp()
                self.ready()
                self.fire(r)
                self.assertEqual(self.state(), "ok")
                self.assertEqual(self.h.state().trig_spent, {})

    def test_three_transient_failures_in_a_row_stale_the_pin(self):
        self.ready("recurring")
        self.fire("HTTP 503")
        self.fire("HTTP 429")
        self.assertEqual(self.state(), "ok")
        self.fire("HTTP 408")
        self.assertEqual(self.state(), "stale")

    def test_a_success_resets_the_count(self):
        self.ready("recurring")
        for r in ("HTTP 503", "HTTP 200", "HTTP 503", "HTTP 503"):
            self.fire(r)
        self.assertEqual(self.state(), "ok")
        self.fire("HTTP 500")
        self.assertEqual(self.state(), "stale")

    def test_a_new_pin_starts_clean(self):
        self.ready("recurring")
        self.fire("HTTP 404")
        self.assertEqual(self.state(), "stale")
        self.pin(secretary=entry("secretary", kind="recurring"))
        self.assertEqual(self.state(), "ok")

    # 2b: the first status is read; the Do-line asks for the final one
    def test_500_then_200_reads_500(self):
        self.ready()
        self.fire("HTTP 500 then HTTP 200")
        self.assertEqual(self.events("nudge.result")[-1]["data"]["status"], 500)
        self.assertEqual(self.state(), "ok")                          # failed, nothing spent, no stale mark
        self.assertEqual(self.h.state().trig_spent, {})

    def test_skipped_no_response_becomes_a_relay_request(self):
        self.ready()
        self.reg("envoy", "local_env")                                 # a live relay claimer on this machine
        mid = self.offer()
        r = D.record_result(self.h, self.plain, mid, "skipped", "no_response")
        self.assertTrue(r.get("relay_requested"), r)
        self.assertEqual(len(self.events("nudge.relay_offer")), 1)

    # 3.3: the parsed status is stored
    def test_status_is_stored_as_an_integer(self):
        self.ready()
        self.fire("HTTP 404 trigger gone")
        d = self.events("nudge.result")[-1]["data"]
        self.assertIs(type(d["status"]), int)
        self.assertEqual(d["status"], 404)

    # 3.4: the relayer evidence path uses the same start-anchored rule
    def test_relayer_form_is_start_anchored(self):
        self.ready()
        self.assertTrue(self.fire("HTTP 200 " + RUN, relay=True).get("reported"))
        ev = self.events("nudge.result")[-1]["data"]
        self.assertEqual(ev["status"], 200)
        self.assertEqual(ev["evidence"], {"http": "200", "session": RUN, "statuses": ["200"], "self_reported": True})
        self.assertEqual(self.state(), "spent")

    def test_relayer_bare_200_and_late_status_are_refused(self):
        self.ready()
        for bad in ("200 " + RUN, "took 200 ms HTTP 404 " + RUN, "run " + RUN + " status 404"):
            with self.subTest(reason=bad):
                mid = self.offer()
                with self.assertRaisesRegex(H.HarnessError, r"reason must start with HTTP <3 digits>"):
                    D.record_result(self.h, self.reg(host="local_r%d" % self.k), mid, "woke", bad)
        self.assertEqual(self.events("nudge.result"), [])

    def test_relayer_404_stales_the_pin(self):
        self.ready()
        self.fire("HTTP 404 " + RUN, relay=True)
        self.assertEqual(self.state(), "stale")

    # 3.5: the Do-line says the reason must start with the status
    def test_doline_says_start_with_the_final_status(self):
        self.ready("recurring")
        do = self.do()
        self.assertIn('Start the reason with "HTTP <status>" of the run (its final status).', do)
        self.assertNotIn('Put "HTTP <status>"', do)

    # the shared function itself (used by the relay and wake build)
    def test_fire_status_and_effect(self):
        self.assertEqual(D.fire_status("HTTP 404"), 404)
        self.assertEqual(D.fire_status("  HTTP 202 accepted"), 202)
        self.assertIsNone(D.fire_status("x HTTP 200"))
        self.assertIsNone(D.fire_status("HTTP 2000"))
        self.assertEqual([D.fire_effect(s) for s in (200, 299, 404, 410, 401, 403, 408, 429, 500, 503, 400)],
                         ["woken", "woken", "gone", "gone", "gone", "gone", "failed", "failed", "failed", "failed", "failed"])

    # 3.3 replay guards: events written before 0.24.0 (no `status`) keep the old reader and never stale a pin
    def test_guard_old_events_replay_with_the_old_reader(self):
        for reason, want in (("404 not found", "ok"), ("RemoteTrigger ran", "spent"), ("HTTP 500 then HTTP 200", "spent"),
                             ("HTTP 404", "ok")):
            with self.subTest(reason=reason):
                self.setUp()
                self.ready()
                C.record_v023(self.h, self.plain, self.offer(), "woke", reason)
                self.assertEqual(self.state(), want)

    def test_full_rebuild_and_incremental_path_agree(self):
        with mock.patch.dict(os.environ, {"HARNESS_STATE_CACHE": "1"}):
            self.ready("recurring")
            self.h.state()
            for r in ("HTTP 503", "HTTP 200", "HTTP 404"):
                self.fire(r)
            inc = self.h.state()
        full = H.State(self.h.store.read_all())
        self.assertEqual(inc.trig_fires, full.trig_fires)
        self.assertEqual(len(full.trig_fires[TRIG]), 3)


if __name__ == "__main__":
    unittest.main()
