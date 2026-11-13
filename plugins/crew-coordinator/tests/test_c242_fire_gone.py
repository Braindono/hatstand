"""cc 0.24.2 (RD-0d97a, hotfix lane): a dead wake is seen. A fire report whose reason starts `HTTP <3 digits>` counts toward the failed fires
whatever its outcome (woke, held, skipped); HTTP 400 with persistent_session_gone is stale at once; a plain 400 still takes three; a 2xx resets.
A stale routine gives its holder one register line and the relay stops offering it. Old events (no status on held/skipped) fold as before.
Run: python3 -B tests/test_c242_fire_gone.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _env  # noqa: F401  isolate HOME and HARNESS_* first
import unittest

import test_c241_wake_role as W
from test_c240_item13 import D, H, T1

GONE = "HTTP 400 persistent_session_gone"


class FireGone(W.WakeRole):
    def report(self, outcome, reason):
        n = self.send()["nudge"]   
        r = self.admin(self.plain, "nudge_result", msg_id=n["msg_id"], outcome=outcome, reason=reason)
        self.call("harness_inbox", agent=self.sec)
        return r

    def test_a_held_fire_with_persistent_session_gone_is_stale_at_once(self):
        self.ready()
        self.assertEqual(self.report("held", GONE)["outcome"], "held")
        self.assertEqual(self.state(), "stale")
        self.assertEqual(self.events("nudge.result")[-1]["data"]["status"], 400)

    def test_a_skipped_fire_with_persistent_session_gone_is_stale_at_once(self):
        self.ready()
        self.report("skipped", GONE)
        self.assertEqual(self.state(), "stale")

    def test_a_woke_fire_with_persistent_session_gone_is_stale_at_once(self):
        self.ready()
        self.report("woke", GONE)
        self.assertEqual(self.state(), "stale")

    def test_a_plain_400_still_takes_three_whatever_the_outcome(self):
        self.ready()
        for i, o in enumerate(("held", "skipped", "woke")):
            self.assertEqual(self.state(), "verified", i)
            self.report(o, "HTTP 400 bad request")
        self.assertEqual(self.state(), "stale")

    def test_a_2xx_resets_the_count_and_a_reason_without_a_status_counts_nothing(self):
        self.ready()
        self.report("held", "HTTP 400")
        self.report("held", "HTTP 400")
        self.report("held", "HTTP 200")                     # reset (a skipped 2xx is refused)
        self.report("held", "HTTP 400")
        self.report("skipped", "no_response")            # no status: not counted, not refused
        self.assertEqual(self.state(), "verified")
        self.report("held", "HTTP 400")
        self.report("held", "HTTP 400")
        self.assertEqual(self.state(), "stale")

    def test_a_skipped_task_without_a_status_or_a_code_is_still_refused(self):
        self.ready()
        n = self.send()["nudge"]
        with self.assertRaisesRegex(H.HarnessError, "always rings"):
            self.admin(self.plain, "nudge_result", msg_id=n["msg_id"], outcome="skipped", reason="not needed")
        self.assertEqual(self.state(), "verified")

    def test_a_skipped_report_with_a_2xx_status_is_refused(self):
        self.ready()
        self.report("held", "HTTP 400")
        n = self.send()["nudge"]
        with self.assertRaisesRegex(H.HarnessError, "reported woke, not skipped"):
            self.admin(self.plain, "nudge_result", msg_id=n["msg_id"], outcome="skipped", reason="HTTP 200")
        self.assertEqual([e["data"]["status"] for e in self.events("nudge.result") if e["data"].get("status")], [400])

    def test_a_held_status_never_spends_a_run_once_pin(self):
        self.ready()
        self.report("held", "HTTP 200")
        self.assertEqual(self.state(), "verified")
        self.assertIn(T1, self.do())

    def test_a_stale_routine_gives_the_holder_one_register_line_and_leaves_the_relay(self):
        self.ready()
        self.report("held", GONE)
        text = self.sync(self.sec)
        self.assertEqual(text.count("wake routine for role:secretary is stale"), 1)
        self.assertIn("wake_register", text)
        self.assertNotIn(T1, self.do())
        self.assertNotIn("live_wake_pin", str(D.nudge_basis(self.h.state(), "secretary")) if hasattr(D, "nudge_basis") else "")

    def test_replay_old_events_fold_to_the_same_states(self):
        """Events written before 0.24.2: a held or skipped result has no `status`, so it counts nothing; a woke with a status folds as before."""
        self.ready()
        for o in ("held", "skipped"):
            self.report(o, "no_response" if o == "skipped" else "x")
        evs = self.h.store.read_all()
        full = H.State(evs)
        self.assertEqual(full.trig_fires, {})
        for e in evs:                                          # strip the new status from every held/skipped result: same fold
            if e["type"] == "nudge.result" and e["data"].get("outcome") in ("held", "skipped"):
                e["data"].pop("status", None)
        self.assertEqual(H.State(evs).trig_fires, full.trig_fires)
        self.assertEqual(D.reg_state(full, "secretary")[1], "verified")

    def test_replay_names_the_one_changed_state_a_status_less_held_gone_report_now_stales_the_routine(self):
        """The real ledger's one change (RD-0d97a): the secretary's routine, three held/skipped HTTP 400 persistent_session_gone reports written
        before 0.24.2 (no `status`): verified under 0.24.1, stale under 0.24.2 (the dreamer's stays verified). Same fold here, on a built ledger."""
        self.ready()
        self.report("held", GONE)
        evs = self.h.store.read_all()
        for e in evs:
            if e["type"] == "nudge.result":
                e["data"].pop("status", None)                  # an event as 0.24.1 wrote it
        st = H.State(evs)
        self.assertEqual(D.reg_state(st, "secretary")[1], "stale")
        self.assertEqual(st.trig_fires[T1][-1][2:], (400, True))
        for e in evs:
            if e["type"] == "nudge.result":
                e["data"]["reason"] = "x HTTP 400 persistent_session_gone"      # not start-anchored: not a status
        self.assertEqual(D.reg_state(H.State(evs), "secretary")[1], "verified")


if __name__ == "__main__":
    unittest.main()
