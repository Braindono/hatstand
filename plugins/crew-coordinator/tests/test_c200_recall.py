"""cc 0.20.0 (D-b28d7): (c) recall ids= with query=, (d) the recall-miss loop. Run: python3 -B tests/test_c200_recall.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _env  # noqa: F401
import json, os, shutil, sys, tempfile, time, unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import harness as H
import mcp_server as M
import recall_signal as RS

MODEL = "claude-sonnet-5-5"
TOPICS = ["release gate checklist", "pigeon feeding schedule", "ledger backup rotation", "tulip planting depth", "compaction handoff rules",
          "kettle descaling steps", "harbour tide table", "bicycle chain lubrication"]


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.home = os.path.join(self.tmp, "Exchange")
        os.makedirs(os.path.join(self.home, "_harness"))
        e = mock.patch.dict(os.environ, {"HARNESS_STATE_CACHE": "0", "HARNESS_HOME": self.home, "HARNESS_STATE_DIR": os.path.join(self.tmp, "state")})
        e.start()
        self.addCleanup(e.stop)
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.h = H.Harness(self.home)
        for role in ("curator", "envoy"):
            self.h.role_define("operator", role, "harness-ops")
        self.a = self.h.register(project="harness-ops", model=MODEL)["id"]
        self.h.role_assign("operator", "curator", self.a)
        self.b = self.h.register(project="harness-ops", model=MODEL)["id"]
        self.h.role_assign("operator", "envoy", self.b)
        self.ids = [self.h.record(self.a, "note", t, f"Body about {t}. " * 3, ["misc"])["id"] for t in TOPICS]

    def miss(self, kind=None):
        return [e for e in self.h.store.read_all() if e.get("type") == "recall.miss" and (kind is None or e["data"]["kind"] == kind)]


class IdsWithQuery(Base):
    def test_title_first_then_top_hits_and_the_text(self):
        t = self.h.recall(ids=[self.ids[0]], query="release gate checklist", agent=self.a)["text"]
        lines = t.splitlines()
        self.assertTrue(lines[0].startswith(f"requested {self.ids[0]} not · release gate checklist"), lines[0])
        self.assertIn("in the top hits", lines[0])
        self.assertTrue(lines[1].startswith("top "))
        self.assertIn("Body about release gate checklist", t)               # the full text still follows
        self.assertEqual(self.miss(), [])

    def test_without_query_the_reply_is_unchanged(self):
        t = self.h.recall(ids=[self.ids[0]], agent=self.a)["text"]
        self.assertTrue(t.startswith(self.ids[0]), t[:60])
        self.assertNotIn("requested", t)

    def test_a_lesson_title_stays_out_of_the_plain_line(self):
        l = self.h.record(self.a, "note", "Lesson: secret title words", "What happened: x\nCause: y\nWhen: z\nRule: Check it.", ["lesson", "role:all"])["id"]
        t = self.h.recall(ids=[l], query="secret title words", agent=self.a)["text"]
        first = t.splitlines()[0]
        self.assertIn("lesson (see the text below)", first)
        self.assertNotIn("secret title", first)

    def test_a_ruled_out_entry_keeps_its_label(self):
        dd = self.h.record(self.a, "decision", "Use horses", "x", ["pin"])["id"]
        r = self.h.record(self.a, "note", "Rejected idea zebra", f"Option: zebra\nReason: stripes\nDecision: {dd}", ["ruled-out"])["id"]
        t = self.h.recall(ids=[r], query="zebra", agent=self.a)["text"]
        self.assertTrue(t.startswith("REJECTED, not advice · requested " + r), t[:80])

    def test_K1_a_ruled_out_note_is_not_listed_among_the_top_hits(self):          # critic M4 K1
        d = self.h.record(self.a, "decision", "Widget cache rebuild runs weekly", "The widget cache rebuild runs weekly.", ["pin"])["id"]
        r = self.h.record(self.a, "note", "widget cache rebuild nightly", f"Option: nightly rebuild of the widget cache\nReason: too slow\nDecision: {d}", ["ruled-out"])["id"]
        t = self.h.recall(ids=[d], query="how often does the widget cache rebuild run", agent=self.a)["text"]
        self.assertNotIn(r, t)

    def test_state_note_ids_get_titles(self):
        d = self.h.record(self.a, "decision", "Ship on Friday only", "x", ["pin"])["id"]
        out = self.h._title_ids(f"see {d} and {d} again, also D-00000 and m-123456789012")
        self.assertIn(f"{d} (Ship on Friday only) and {d} again", out)
        self.assertIn("D-00000 and", out)
        self.assertEqual(self.h._title_ids(f"{d} (already) x"), f"{d} (already) x")


class Detector(Base):
    K = RS.SUSPECT_K

    def test_wrong_but_resolving_id_is_suspect(self):
        self.h.recall(ids=[self.ids[1]], query="release gate checklist", agent=self.a)       # asked for the pigeon note, meant the gate one
        m = self.miss("suspect")
        self.assertEqual(len(m), 1)
        self.assertEqual(m[0]["data"]["ids"], [self.ids[1]])
        self.assertEqual(m[0]["data"]["k"], 5)

    def test_unresolved_id(self):
        self.h.recall(ids=["N-00000"], query="anything at all", agent=self.a)
        self.assertEqual(self.miss("unresolved")[0]["data"]["ids"], ["N-00000"])
        self.h.recall(ids=["N-00001"], agent=self.a)                                         # without query: still unresolved
        self.assertEqual(len(self.miss("unresolved")), 2)

    def test_no_fire_set(self):
        self.h.recall(ids=[self.ids[0]], query="release gate checklist", agent=self.a)       # a correct id with its query
        self.h.recall(ids=[self.ids[0]], agent=self.a)                                       # no query: the detector is blind, no fire
        self.h.recall(query="harbour tide", agent=self.a, offset=0)
        self.h.recall(query="harbour tide", agent=self.a, offset=1)                          # paging
        self.h.recall(query="harbour tide table", agent=self.a)                              # refinement
        self.h.recall(query="harbour tide table", agent=self.b)                              # a second agent asks the same thing
        self.h.recall(query="harbour tide table", agent=self.b, limit=5)
        self.assertEqual([k for k in (e["data"]["kind"] for e in self.miss()) if k != "repeat"], [])
        self.assertEqual(len(self.miss("repeat")), 1)                                        # only b repeating its own search

    def test_a_bigger_limit_is_not_a_repeat(self):                                 # critic M4
        self.h.recall(query="kettle descaling", agent=self.a, limit=5)
        self.h.recall(query="kettle descaling", agent=self.a, limit=10)
        self.assertEqual(self.miss("repeat"), [])

    def test_asking_for_a_superseded_entry_on_purpose_is_not_a_suspect(self):     # critic M4
        new = self.h.record(self.a, "note", "release gate checklist v2", "newer text", ["misc"], supersedes=self.ids[0])["id"]
        self.h.recall(ids=[self.ids[0]], query="release gate checklist", agent=self.a)
        self.assertEqual(self.miss("suspect"), [])
        self.assertIn("1 ids asked for on purpose", self.h.recall_report(1)["text"])
        self.h.recall(ids=[self.ids[1]], query="release gate checklist", agent=self.a)   # a live wrong id still fires
        self.assertEqual(len(self.miss("suspect")), 1)

    def test_recall_report_json_zero_and_planted(self):
        z = self.h.recall_report(1, as_json=True)
        self.assertEqual(len(z["weeks"]), 1)
        self.assertEqual((z["weeks"][0]["calls"], z["weeks"][0]["id_requests"], sum(z["weeks"][0]["miss"].values()), z["top_missed"]), (0, 0, 0, []))
        self.assertEqual(self.h.recall_report(1)["text"].splitlines()[0], "no recall calls counted in this window")
        self.h.recall(ids=[self.ids[1]], query="release gate checklist", agent=self.a)
        j = self.h.recall_report(2, as_json=True)
        self.assertEqual(len(j["weeks"]), 2)
        w = j["weeks"][0]
        self.assertEqual((w["id_requests"], w["with_query"], w["miss"]["suspect"]), (1, 1, 1))
        self.assertEqual(j["top_missed"][0]["n"], 1)
        self.assertEqual(self.h.recall_report(99, as_json=True)["weeks"].__len__(), 12)

    def test_cli_recall_report(self):
        import subprocess
        self.h.recall(ids=["N-00000"], query="x y", agent=self.a)
        env = dict(os.environ, HARNESS_HOME=self.home)
        r = subprocess.run([sys.executable, "-B", os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts", "harness.py"),
                            "--home", self.home, "recall-report", "--json"], capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout)["weeks"][0]["miss"]["unresolved"], 1)
        r2 = subprocess.run([sys.executable, "-B", os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts", "harness.py"),
                             "--home", self.home, "recall-report"], capture_output=True, text=True, env=env)
        self.assertIn("unresolved 1", r2.stdout)

    def test_the_same_agent_repeating_a_search_is_a_repeat(self):
        self.h.recall(query="kettle descaling", agent=self.a)
        self.assertEqual(self.miss("repeat"), [])
        self.h.recall(query="Descaling kettle", agent=self.a)                                # same words, other order and case
        self.assertEqual(len(self.miss("repeat")), 1)

    def test_a_repeat_after_the_window_does_not_fire(self):
        self.h.recall(query="kettle descaling", agent=self.a)
        p = os.path.join(self.h.store.dir, RS.STATS)
        old = [json.loads(x) for x in open(p)]
        for v in old:
            v["t"] -= RS.REPEAT_SECS + 5
        open(p, "w").write("\n".join(json.dumps(v) for v in old) + "\n")
        self.h.recall(query="kettle descaling", agent=self.a)
        self.assertEqual(self.miss("repeat"), [])

    def test_catch_and_false_alarm_rates_at_k5(self):
        right = wrong = 0
        for i, t in enumerate(TOPICS):
            n0 = len(self.miss("suspect"))
            self.h.recall(ids=[self.ids[i]], query=t, agent=self.a)                          # the correct id with its own question
            right += len(self.miss("suspect")) - n0
            n0 = len(self.miss("suspect"))
            self.h.recall(ids=[self.ids[(i + 3) % len(TOPICS)]], query=t, agent=self.a)       # a wrong id with that question
            wrong += len(self.miss("suspect")) - n0
        self.assertEqual(right, 0)                                                           # false alarms on correct requests
        self.assertGreaterEqual(wrong / len(TOPICS), 0.6)                                    # catch rate

    def test_agent_reported_miss_and_the_report(self):
        self.h.recall_miss_reported(self.a, "tulip depth", [self.ids[3]], "returned the wrong note")
        self.assertEqual(self.miss("reported")[0]["data"]["note"], "returned the wrong note")
        with self.assertRaises(H.HarnessError):
            self.h.recall_miss_reported(self.a, "", [], "x")
        self.h.recall(ids=[self.ids[0]], query="release gate", agent=self.a)
        self.h.recall(ids=[self.ids[1]], agent=self.a)
        t = self.h.recall_report(1)["text"]
        self.assertIn("2 id requests, 50% with query=", t)
        self.assertIn("reported 1", t)

    def test_the_tool_passes_agent_and_miss(self):
        r = M.call(self.h, "harness_recall", {"agent": self.a[:8], "ids": [self.ids[1]], "query": "release gate checklist", "miss": "wrong note last time"})
        self.assertIn("requested", r["text"])
        self.assertEqual(len(self.miss("reported")), 1)
        self.assertEqual(len(self.miss("suspect")), 1)                  # the detector saw the same request
        self.assertIn("ALWAYS add query=", [t for t in M.TOOLS if t[0] == "harness_recall"][0][1])

    def test_no_agent_still_counts_and_logs_as_system(self):
        self.h.recall(ids=["N-00000"], query="x y")
        self.assertEqual(len(self.miss("unresolved")), 1)

    def test_a_failing_stats_file_never_breaks_recall(self):
        os.makedirs(os.path.join(self.h.store.dir, RS.STATS))                                # a directory where the file should be
        t = self.h.recall(ids=[self.ids[0]], query="release gate", agent=self.a)["text"]
        self.assertIn("requested", t)


if __name__ == "__main__":
    unittest.main()
