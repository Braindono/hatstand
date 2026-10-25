"""cc 0.17.0 R-040 restore-fidelity drill: generations, held-out questions, ledger cut, exact-match scoring, Wilson
interval, dry run without a model. Run: python3 -B tests/test_c170_r040.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _env  # noqa: F401  isolate HOME and HARNESS_* first
import json, os, sys, tempfile, unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
sys.path.insert(0, HERE)
import harness as H
import restore_drill as R

MODEL = "claude-opus-5-5"


class Drill(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.home = os.path.join(self.tmp, "Exchange")
        os.makedirs(os.path.join(self.home, "_harness"))
        e = mock.patch.dict(os.environ, {"HARNESS_STATE_CACHE": "0"})
        e.start()
        self.addCleanup(e.stop)
        h = H.Harness(self.home)
        h.role_define("operator", "ops-coder", "harness-ops")
        self.p = h.register(project="harness-ops", model=MODEL)["id"]
        h.role_assign("operator", "ops-coder", self.p)
        self.d1 = h.record(self.p, "decision", "Ship the vault writer off by default", "b")["id"]
        self.d2 = h.record(self.p, "decision", "Gate warns before it blocks", "b")["id"]
        h.handoff(self.p, "---\nhandoff: x\n---\n# H\nDecided " + self.d1 + ".\n")
        h.restore("ops-coder", model=MODEL, project="harness-ops", confirmed=True)
        self.s = h.state().role_holder("ops-coder")
        self.late = h.record(self.s, "decision", "A decision made after the restore", "b")["id"]
        v = os.path.join(self.home, "vault", "harness-ops", "ops-coder")
        os.makedirs(v)
        with open(os.path.join(v, "2026-10-25-p.md"), "w") as f:
            f.write('meta: {"agent": "%s"}\n\n## Asks\n\n1. [done] 2026-10-25 10:00:00 · session x\n   > build the writer\n'
                    '2. [open] 2026-10-25 10:01:00 · session x\n   > write the gate\n' % self.p[:8])

    def test_generation_and_held_out_questions(self):
        H_, h, ev = R._events(self.home)
        gens = R.generations(ev, "ops-coder", H.cr)
        self.assertEqual([(g[0], g[1]) for g in gens], [(self.p, self.s)])
        qs = R.questions(ev, self.home, self.p)
        self.assertEqual(sorted(q["a"] for q in qs), sorted([self.d1, self.d2, "done", "open"]))
        self.assertNotIn(self.late, [q["a"] for q in qs])            # the successor's own decision is not a question

    def test_digest_is_cut_at_the_successors_start(self):
        H_, h, ev = R._events(self.home)
        p_, s_, cut = R.generations(ev, "ops-coder", H.cr)[0]
        dg = R.digest_at(self.home, "ops-coder", s_, cut, tempfile.mkdtemp())
        self.assertIn(self.d1, dg)                                    # carried by the capsule
        self.assertNotIn(self.late, dg)                               # recorded after the cut

    def test_score_and_interval(self):
        qs = [{"kind": "decision", "q": "?", "a": "D-12345"}, {"kind": "ask", "q": "?", "a": "open"},
              {"kind": "ask", "q": "?", "a": "done"}]
        r = R.score(qs, 'x {"answers":[{"n":1,"a":"It is D-12345."},{"n":2,"a":"Open, not finished"},{"n":3,"a":"unknown"}]}')
        self.assertEqual((r["right"], r["n"]), (2, 3))
        self.assertEqual(r["by_kind"], {"decision": {"right": 1, "n": 1}, "ask": {"right": 1, "n": 2}})
        self.assertEqual(R.score(qs, "garbage")["right"], 0)
        lo, hi = R.wilson(15, 30)
        self.assertTrue(0.3 < lo < 0.5 < hi < 0.7)
        self.assertEqual(R.wilson(0, 0), (0.0, 0.0))

    def test_dry_run_calls_no_model_and_apply_scores(self):
        calls = []
        dry = R.drill(self.home, "ops-coder", model_fn=lambda p, m: calls.append(p))
        self.assertEqual((dry["generations"][0]["questions"], calls, dry["meets_30"]), (4, [], False))

        def model(p, m):
            calls.append(p)
            return json.dumps({"answers": [{"n": i, "a": "unknown"} for i in range(1, 5)]})
        r = R.drill(self.home, "ops-coder", apply=True, model_fn=model)
        self.assertEqual(len(calls), 1)
        self.assertIn("RESTORE DIGEST", calls[0])
        self.assertEqual((r["total"]["n"], r["total"]["right"]), (4, 0))


if __name__ == "__main__":
    unittest.main()
