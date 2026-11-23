"""0.27.1 items 3 and 2: mistake record schema refusal and the harness-filled pointer. Run: python3 -B tests/test_mistake_record.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _env  # noqa: F401
import json, os, subprocess, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
import harness as H
import mistake_record as M

GOOD = "What: said 'done' without running the test\nFound by: evaluator\nModel: claude-sonnet-5-5\nKind: claim"


class Pure(unittest.TestCase):
    def test_complete_record_passes(self):
        self.assertEqual(M.problems(["mistake", "visible"], GOOD), [])

    def test_each_missing_field_refused(self):
        for drop, word in (("What:", "What"), ("Found by:", "Found by"), ("Model:", "Model"), ("Kind:", "Kind")):
            body = "\n".join(l for l in GOOD.splitlines() if not l.startswith(drop))
            self.assertTrue(any(word in x for x in M.problems(["mistake", "visible"], body)), drop)

    def test_tag_rules(self):
        self.assertTrue(M.problems(["mistake"], GOOD))
        self.assertTrue(M.problems(["mistake", "visible", "hindsight"], GOOD))
        self.assertEqual(M.problems(["Mistake", "HINDSIGHT"], GOOD), [])

    def test_bad_values_refused(self):
        self.assertTrue(M.problems(["mistake", "visible"], GOOD.replace("evaluator", "somebody")))
        self.assertTrue(M.problems(["mistake", "visible"], GOOD.replace("claim", "vibes")))
        self.assertTrue(M.problems(["mistake", "visible"], GOOD + "\nWhat: second"))
        self.assertTrue(M.problems(["mistake", "visible"], GOOD.replace("said 'done' without running the test", "x")))

    def test_agent_cannot_set_the_pointer(self):
        self.assertTrue(M.problems(["mistake", "visible"], GOOD + "\nSession file: /tmp/x.jsonl"))
        self.assertTrue(M.problems(["mistake", "visible"], GOOD + "\ntranscript line: 4"))

    def test_disguised_pointer_lines_refused(self):
        for bad in ("Session  file: /x", "- Session file: /x", "* Transcript line: 3", "Session\tfile: /x", "\u200bSession file: /x", "\ufeffTranscript line: 3",
                    "Session file\uff1a /x", "**Session file:** /x", "SESSION FILE: /x", "Session: /x", "Line: 4", "\u0405ession file: /x", '"Line": 9', "\u201cTranscript line\u201d: 3"):
            self.assertTrue(M.problems(["mistake", "visible"], GOOD + "\n" + bad), repr(bad))
        self.assertEqual(M.problems(["mistake", "visible"], GOOD + "\nWhere: the session file of the guru"), [])

    def test_string_tags_and_found_by(self):
        self.assertTrue(M.is_mistake("mistake, visible"))
        self.assertEqual(M.problems("mistake, visible", GOOD), [])
        self.assertTrue(M.problems(["mistake", "visible"], GOOD.replace("evaluator", "peer-anything")))
        self.assertEqual(M.problems(["mistake", "visible"], GOOD.replace("evaluator", "peer (guru)")), [])

    def test_pointer_agent_must_be_hex_and_no_symlink_follow(self):
        home = tempfile.mkdtemp(); tp = os.path.join(home, "t.jsonl"); open(tp, "w").write("a\nb\n")
        for bad in ("./../ab", "../../x/yyyy", "ABCDEF12", "abc", ""):
            self.assertFalse(M.save_pointer(home, bad, tp), bad)
        self.assertFalse(os.path.exists(os.path.join(home, "_harness", "ab.json")))
        d = os.path.join(home, M.DIR); os.makedirs(d)
        victim = os.path.join(home, "victim"); open(victim, "w").write("keep")
        os.symlink(victim, os.path.join(d, ".deadbeef.tmp"))
        self.assertTrue(M.save_pointer(home, "deadbeef", tp))
        self.assertEqual(open(victim).read(), "keep")

    def test_line_of_the_act_when_found(self):
        home = tempfile.mkdtemp(); tp = os.path.join(home, "t.jsonl")
        open(tp, "w").write("one\nI claimed the gates were green without running them\nthree\n")
        M.save_pointer(home, "deadbeef", tp)
        a, b = M.pointer_lines(home, "deadbeef", act="I claimed the gates were green without running them")
        self.assertIn("Transcript line: 2 (act text found there)", b)
        open(tp, "a").write('{"tool":"harness_record","body":"I claimed the gates were green without running them"}\n')
        M.save_pointer(home, "deadbeef", tp)
        self.assertIn("Transcript line: 2 (act text found there)", M.pointer_lines(home, "deadbeef", act="I claimed the gates were green without running them")[1])
        self.assertIn("act text was not found", M.pointer_lines(home, "deadbeef", act="something never said anywhere")[1])

    def test_other_tags_untouched(self):
        self.assertFalse(M.is_mistake(["lesson"]))
        self.assertTrue(M.is_mistake("mistake"[:0] or ["mistake"]))


class Harnessed(unittest.TestCase):
    def setUp(self):
        self.d = os.path.realpath(tempfile.mkdtemp())
        self.home = os.path.join(self.d, "home"); os.makedirs(self.home)
        self.h = H.Harness(self.home)
        self.a = self.h.register(project="claude", model="claude-sonnet-5-5")["id"]
        self.tp = os.path.join(self.d, "t.jsonl")
        with open(self.tp, "w") as f:
            f.write('{"a":1}\n{"a":2}\n{"a":3}\n')

    def rec(self, body, tags=("mistake", "visible")):
        return self.h.record(self.a, "note", "t", body, list(tags), tag_check=True)

    def test_refused_record_writes_nothing(self):
        before = len(self.h.state().messages)
        with self.assertRaises(H.HarnessError) as c:
            self.rec("What: oops oops oops")
        self.assertIn("nothing recorded", str(c.exception))
        self.assertEqual(len(self.h.state().messages), before)

    def test_pointer_filled_from_hook_file(self):
        self.assertTrue(M.save_pointer(self.home, self.a, self.tp))
        r = self.rec(GOOD)
        body = self.h.recall(self.a, ids=[r["id"]]) if hasattr(self.h, "recall") else None
        txt = json.dumps(body, default=str)
        self.assertIn(self.tp, txt)
        self.assertIn("Transcript line: 3", txt)

    def test_missing_hook_still_files_and_says_so(self):
        r = self.rec(GOOD)
        txt = json.dumps(self.h.recall(self.a, ids=[r["id"]]), default=str)
        self.assertIn("unavailable", txt)

    def test_stale_pointer_not_used(self):
        M.save_pointer(self.home, self.a, self.tp, now=1.0)
        self.assertIn("unavailable", M.pointer_lines(self.home, self.a)[0])

    def test_hook_script_saves_and_never_fails(self):
        env = dict(os.environ, HARNESS_HOME=self.home)
        script = os.path.join(HERE, "..", "scripts", "mistake_pointer_hook.py")
        inp = json.dumps({"transcript_path": self.tp, "tool_input": {"agent": self.a}})
        p = subprocess.run([sys.executable, "-I", script], input=inp, capture_output=True, text=True, env=env)
        self.assertEqual(p.returncode, 0)
        self.assertTrue(os.path.exists(os.path.join(self.home, M.DIR, self.a[:8] + ".json")))
        p = subprocess.run([sys.executable, "-I", script], input="not json", capture_output=True, text=True, env=env)
        self.assertEqual((p.returncode, p.stdout), (0, ""))

    def test_hook_registered(self):
        hk = json.load(open(os.path.join(HERE, "..", "hooks", "hooks.json")))
        cmds = [h["command"] for m in hk["hooks"]["PreToolUse"] for h in m["hooks"] if "harness_record" in m["matcher"]]
        self.assertTrue(any("mistake_pointer_hook.py" in c for c in cmds))


if __name__ == "__main__":
    unittest.main()
