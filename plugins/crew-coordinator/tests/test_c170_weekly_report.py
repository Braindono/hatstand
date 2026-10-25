"""cc 0.17.0 stage 0, R-052 phase 3: weekly health report. Counts from planted ledger events, sources untouched,
change against the previous report. Run: python3 -B tests/test_c170_weekly_report.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _env  # noqa: F401  isolate HOME and HARNESS_* first
import datetime as dt, json, os, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
import harness as H
import weekly_report as W
from test_c170_c_live import tree_digest

MODEL = "claude-opus-5-5"


class Weekly(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="weekly-")
        self.home = os.path.join(self.tmp, "Exchange")
        os.makedirs(self.home)
        h = H.Harness(self.home)
        h.role_define("operator", "ops-coder", "orch")
        self.coder = h.register(project="orch", model=MODEL)["id"]
        h.role_assign("operator", "ops-coder", self.coder)
        peer = h.register(project="orch", model=MODEL)["id"]
        h.send(peer, "role:ops-coder", "please review", subject="r1", kind="review")
        ap = h.store.append
        ap("nudge.sent", peer, {"msg": "m-1", "to": [self.coder]})
        ap("nudge.skipped", peer, {"msg": "m-2", "reason": "global cap 12/h", "to": [self.coder]})
        ap("nudge.skipped", peer, {"msg": "m-3", "reason": "pair cap 3/h (ping-pong guard)", "to": [self.coder]})
        ap("call.failed", peer, {"tool": "harness_send", "error": "unknown agent 'x'"})
        ap("call.failed", peer, {"tool": "harness_admin", "error": "needs operator approval (scope gate)"})
        ap("approval.denied", "human", {"id": "A-1", "channel": "cli-tty"})
        ap("release.published", peer, {"name": "crew-coordinator", "version": "0.16.2"})
        ap("release.published", peer, {"name": "crew-coordinator", "version": "0.16.3"})
        ap("release.published", peer, {"name": "excellent-etiquette", "version": "0.2.8"})
        ap("release.gate_override", "human", {"name": "crew-coordinator", "version": "0.16.3", "reason": "operator skip"})
        ap("handoff.gate_warn", "human", {"count": 2, "mode": "warn", "source": "vault"})     # 0.17.0 R-080
        ap("handoff.gate_warn", "human", {"count": 1, "mode": "warn", "source": "capsule"})
        ap("handoff.gate_override", "human", {"count": 1, "source": "vault", "reason": "asked twice"})
        ap("agent.handed_off", peer, {"message": "m-9"})
        del h
        self.trend = os.path.join(self.tmp, "trend.jsonl")
        now = dt.datetime.now(dt.timezone.utc)
        with open(self.trend, "w") as f:
            for i, (age, tok) in enumerate(((30, 900), (3, 1000), (1, 800))):     # the 30-day-old pass is outside the window
                f.write(json.dumps({"ts": (now - dt.timedelta(days=age)).isoformat(), "findings": 10 + i, "exit": 1,
                                    "live_tokens": tok, "saved": 100}) + "\n")
        self.ixstate = os.path.join(self.tmp, "state.json")
        with open(self.ixstate, "w") as f:
            json.dump({"files": {"a": {}, "b": {}}, "denied_sessions": ["s1"],
                       "counters": {"dropped_error": 2, "dropped_private": 1, "last_run": 1792882005}}, f)
        self.out = os.path.join(self.tmp, "weekly")

    def run_report(self, **kw):
        return W.report(self.home, self.out, trend_path=self.trend, indexer_state=self.ixstate, **kw)

    def test_counts_and_sources_untouched(self):
        before = tree_digest(self.home)
        md, js, r = self.run_report()
        self.assertEqual(tree_digest(self.home), before)
        L = r["ledger"]
        self.assertEqual((L["nudges"]["sent"], L["nudges"]["skipped"], L["nudges"]["cap_hits"]), (1, 2, 2))
        self.assertEqual(L["nudges"]["skipped_by_reason"], {"global cap": 1, "pair cap": 1})
        self.assertEqual((L["gates"]["failed_calls"], L["gates"]["failed_gate_like"], L["gates"]["denied"]), (2, 1, 1))
        self.assertEqual(L["gates"]["release_gate_overrides"][0]["reason"], "operator skip")
        self.assertEqual((L["gates"]["handoff_gate_warnings"], L["gates"]["handoff_gate_blocked"],
                          L["gates"]["handoff_gate_overrides"]), (2, 0, 1))       # R-080: counted from the ledger now
        self.assertEqual((L["releases"]["count"], L["releases"]["split_ratio"]), (3, 1.5))
        self.assertEqual(L["releases"]["plugins_released_more_than_once"], ["crew-coordinator"])
        self.assertEqual(L["handoffs"]["handed_off"], 1)
        self.assertEqual(r["mail"]["roles"]["ops-coder"]["owed"], 1)
        self.assertEqual((r["indexer"]["redaction_failures"], r["indexer"]["denied_sessions"]), (2, 1))
        self.assertEqual((r["steward"]["passes"], r["steward"]["live_tokens_first"], r["steward"]["live_tokens_last"]), (2, 1000, 800))
        page = open(md).read()
        for needle in ("## 1. Mail per role", "| ops-coder |", "cap hits 2", "handoff gate (events since 0.17.0): warnings 2", "split ratio 1.5", "first report"):
            self.assertIn(needle, page)
        self.assertEqual(json.load(open(js))["week"], r["week"])
        self.assertTrue(os.path.basename(md).startswith("health-"))

    def test_ignores_other_json_in_the_folder(self):
        os.makedirs(self.out)
        with open(os.path.join(self.out, "2026-W43.json"), "w") as f:     # the steward's corpus digest lives here too
            json.dump({"breakdown": {}}, f)
        md, _, _ = self.run_report()
        self.assertIn("first report", open(md).read())

    def test_window_excludes_old_events(self):
        _, _, r = self.run_report(now=dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=30))
        self.assertEqual(r["ledger"]["events"], 0)
        self.assertEqual(r["steward"]["passes"], 0)

    def test_second_report_shows_change(self):
        self.run_report(now=dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=1))
        H.Harness(self.home).store.append("nudge.sent", self.coder, {"msg": "m-4"})
        md, _, _ = self.run_report(now=dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=1))   # next day: a new file
        page = open(md).read()
        self.assertIn("compared with", page)
        self.assertIn("sent 2 (+1)", page)

    def test_missing_indexer_and_trend_are_reported_not_fatal(self):
        md, _, r = W.report(self.home, self.out, trend_path=os.path.join(self.tmp, "none.jsonl"),
                            indexer_state=os.path.join(self.tmp, "none.json"))
        self.assertEqual((r["indexer"]["state"], r["steward"]["state"]), ("absent", "absent"))
        self.assertIn("absent", open(md).read())

    def test_pre_0170_indexer_state_has_no_denied_set(self):
        with open(self.ixstate, "w") as f:
            json.dump({"files": {}, "counters": {"denied": 952}}, f)
        _, _, r = self.run_report()
        self.assertIsNone(r["indexer"]["denied_sessions"])


if __name__ == "__main__":
    unittest.main()
