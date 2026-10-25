"""LADDER (droppable) tests: inbox discipline and listening ladder. Delete with scripts/inbox_ladder.py to drop it.
Run: python3 -B tests/test_inbox_ladder.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _env  # noqa: F401  isolate HOME and HARNESS_* first
import json, os, subprocess, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(HERE, "..", "scripts")
sys.path.insert(0, SCRIPTS)
import harness as H
import inbox_ladder as L

MODEL = "claude-sonnet-5-5"


class Plan(unittest.TestCase):
    def test_default_rungs_and_chunks(self):
        self.assertEqual(L.DEFAULT_RUNGS, (15, 60, 120))
        self.assertEqual(L.INBOX_MAX_WAIT, 45)
        p = L.plan()
        self.assertEqual(p, [[15], [30, 30], [40, 40, 40]])
        self.assertEqual(L.total_seconds(p), 195)
        self.assertEqual(sum(len(r) for r in p), 6)

    def test_chunks_never_exceed_max_wait(self):
        for mw in (5, 10, 20, 30, 45, 60):
            for rungs in ((15, 60, 120), (7, 100, 333), (1, 59, 61)):
                for r, ch in zip(rungs, L.plan(rungs, mw)):
                    self.assertTrue(all(0 < c <= mw for c in ch), (mw, r, ch))
                    self.assertEqual(sum(ch), r)

    def test_config_line(self):
        self.assertEqual(L.parse_ladder(None), (15, 60, 120))
        self.assertEqual(L.parse_ladder("off"), ())
        self.assertEqual(L.parse_ladder("10, 30"), (10, 30))
        self.assertEqual(L.parse_ladder("nonsense"), (15, 60, 120))
        self.assertEqual(L.max_wait({"inbox_max_wait": 20}), 20)
        self.assertEqual(L.max_wait({}), 45)

    def test_run_stops_at_first_mail(self):
        seen = []
        def inbox(w):
            seen.append(w)
            return {"count": 1 if len(seen) == 3 else 0}
        r = L.run(inbox, L.plan(), "m-1")
        self.assertEqual((seen, r["calls"], r["end"]), ([15, 30, 30], 3, None))
        self.assertEqual(r["waited_s"], 75)

    def test_run_all_empty_ends_with_still_waiting(self):
        seen = []
        r = L.run(lambda w: seen.append(w) or {"count": 0}, L.plan(), "m-abc")
        self.assertEqual((len(seen), r["waited_s"], r["end"]), (6, 195, "still waiting on m-abc"))

    def test_off_skips(self):
        self.assertIsNone(L.ladder_hint("task", "m-1", L.parse_ladder("off")))

    def test_conditions(self):
        self.assertTrue(all(L.applies(k) for k in ("task", "question", "review")))
        self.assertFalse(any(L.applies(k) for k in ("notice", "result", "message", "handoff")))     # (a)
        self.assertTrue(L.is_unattended("[scheduled] corpus-steward pass"))                          # (c)
        self.assertTrue(L.is_unattended("hello", "claude-haiku-4-5"))
        self.assertTrue(L.is_unattended("hello", None, {"HARNESS_UNATTENDED": "1"}))
        self.assertFalse(L.is_unattended("hello", MODEL, {}))
        self.assertIsNone(L.ladder_hint("task", "m-1", (15,), model="claude-haiku-4-5"))


class SendHint(unittest.TestCase):
    def setUp(self):
        self.home = os.path.join(tempfile.mkdtemp(), "h")
        os.makedirs(self.home)
        self.h = H.Harness(self.home)
        self.a = self.h.register(project="orchestration", model=MODEL)["id"]
        self.b = self.h.register(project="orchestration", model=MODEL)["id"]

    def test_task_has_ladder_notice_has_none(self):         # (a)
        r = self.h.send(self.a, self.b, "do x", kind="task")
        self.assertEqual(r["ladder"]["waits"], [15, 30, 30, 40, 40, 40])
        self.assertEqual(r["ladder"]["end"], f"still waiting on {r['id']}")
        self.assertEqual(sum(r["ladder"]["waits"]), 195)          # 0.17.0 (R-055): total_s dropped, the waits say it
        self.assertNotIn("rungs", r["ladder"])
        self.assertLess(len(r["ladder"]["how"]), 100)
        for k in ("notice", "result", "message"):
            self.assertNotIn("ladder", self.h.send(self.a, self.b, "fyi", kind=k))
        self.assertIn("ladder", self.h.send(self.a, self.b, "q?", kind="question"))

    def test_pref_off_and_custom(self):
        open(os.path.join(self.home, "OPERATOR-PREFERENCES.md"), "w").write("- inbox-ladder: off\n")
        self.assertNotIn("ladder", self.h.send(self.a, self.b, "do x", kind="task"))
        open(os.path.join(self.home, "OPERATOR-PREFERENCES.md"), "w").write("inbox-ladder: 10,50\n")
        self.assertEqual(self.h.send(self.a, self.b, "do y", kind="task")["ladder"]["waits"], [10, 25, 25])


class StopReminder(unittest.TestCase):
    def setUp(self):
        self.home = os.path.join(tempfile.mkdtemp(), "h")
        os.makedirs(self.home)
        self.h = H.Harness(self.home)
        self.a = self.h.register(project="orchestration", model=MODEL, session_id="s-1")["id"]
        self.h.store.append("session.bound", self.a, {"session_id": "s-1", "agent": self.a})
        self.tmp = tempfile.mkdtemp()
        L_ = L._flag("s-1")
        if os.path.exists(L_):
            os.unlink(L_)

    def transcript(self, user, tools):
        p = os.path.join(self.tmp, "t.jsonl")
        rows = [{"type": "user", "message": {"content": user}}]
        for t in tools:
            rows.append({"type": "assistant", "message": {"content": [{"type": "tool_use", "name": t, "input": {}}]}})
            rows.append({"type": "user", "message": {"content": [{"type": "tool_result", "content": "ok"}]}})
        rows.append({"type": "assistant", "message": {"content": [{"type": "text", "text": "done"}]}})
        open(p, "w").write("\n".join(json.dumps(r) for r in rows) + "\n")
        return p

    def hook(self, event, inp):
        env = dict(os.environ, HARNESS_HOME=self.home)
        r = subprocess.run([sys.executable, "-B", os.path.join(SCRIPTS, "harness.py"), "hook", event],
                           input=json.dumps(inp), capture_output=True, text=True, env=env)
        return r.stdout.strip()

    def test_no_inbox_call_leaves_one_reminder(self):
        tp = self.transcript("please do x", ["mcp__p__harness_claim"])
        self.hook("stop", {"session_id": "s-1", "transcript_path": tp})
        out = self.hook("prompt", {"session_id": "s-1", "prompt": "next", "cwd": "/x/orchestration"})
        self.assertIn("harness_inbox did not run", json.loads(out)["hookSpecificOutput"]["additionalContext"])
        self.assertEqual(self.hook("prompt", {"session_id": "s-1", "prompt": "again", "cwd": "/x/orchestration"}), "")   # once

    def test_inbox_call_in_turn_no_reminder(self):
        tp = self.transcript("please do x", ["mcp__p__harness_inbox", "mcp__p__harness_claim"])
        self.hook("stop", {"session_id": "s-1", "transcript_path": tp})
        self.assertEqual(self.hook("prompt", {"session_id": "s-1", "prompt": "next", "cwd": "/x/orchestration"}), "")

    def test_scheduled_run_skipped(self):                    # (c)
        tp = self.transcript("[scheduled] corpus-steward pass", [])
        self.hook("stop", {"session_id": "s-1", "transcript_path": tp})
        self.assertEqual(self.hook("prompt", {"session_id": "s-1", "prompt": "next", "cwd": "/x/orchestration"}), "")

    def test_older_turn_inbox_does_not_count(self):
        p = self.transcript("first", ["mcp__p__harness_inbox"])
        rows = open(p).read()
        rows += json.dumps({"type": "user", "message": {"content": "second prompt"}}) + "\n"
        rows += json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "hi"}]}}) + "\n"
        open(p, "w").write(rows)
        self.assertEqual(L.turn_summary(p), (False, "second prompt"))

    def test_never_blocks(self):
        out = self.hook("stop", {"session_id": "s-1", "transcript_path": self.transcript("x", [])})
        self.assertEqual(out, "")      # no decision/block JSON from the Stop hook


class Skills(unittest.TestCase):
    def test_skill_lines(self):
        for n in ("protocol", "refresh"):
            t = open(os.path.join(HERE, "..", "skills", n, "SKILL.md"), encoding="utf-8").read()
            self.assertLessEqual(len(t.splitlines()), 60)
            self.assertIn("harness_inbox", t)
        t = open(os.path.join(HERE, "..", "skills", "protocol", "SKILL.md"), encoding="utf-8").read()
        for s in ("ladder", "inbox-ladder", "wait=45", "D-9cc1f", "[scheduled]"):
            self.assertIn(s, t)


if __name__ == "__main__":
    unittest.main()
