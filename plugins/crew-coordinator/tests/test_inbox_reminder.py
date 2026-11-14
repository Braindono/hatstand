"""0.26.0 item 2: inbox_reminder (moved from inbox_ladder, behaviour unchanged): Stop/prompt reminder, scheduled and Haiku exemption, flag safety.
Run: python3 -B tests/test_inbox_reminder.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _env  # noqa: F401  isolate HOME and HARNESS_* first
import json, os, subprocess, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(HERE, "..", "scripts")
sys.path.insert(0, SCRIPTS)
import harness as H
import inbox_reminder as L

MODEL = "claude-sonnet-5-5"


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


class Unattended(unittest.TestCase):
    def test_scheduled_haiku_and_env_are_unattended(self):
        self.assertTrue(L.is_unattended("[scheduled] steward pass"))
        self.assertTrue(L.is_unattended("x", "claude-haiku-4-5"))
        self.assertTrue(L.is_unattended("x", None, {"HARNESS_UNATTENDED": "1"}))
        self.assertFalse(L.is_unattended("hello", "claude-sonnet-5-5", {}))


if __name__ == "__main__":
    unittest.main()
