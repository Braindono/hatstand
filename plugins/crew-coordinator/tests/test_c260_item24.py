"""cc 0.26.0 item 24: after an auto compaction the SessionStart compact branch adds the role's latest state note and its unread and owed counts;
parts already printed are not repeated. Run: python3 -B tests/test_c260_item24.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _env  # noqa: F401  isolate HOME and HARNESS_* first
import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(HERE, "..", "scripts")
sys.path.insert(0, SCRIPTS)
import harness as H

MODEL = "claude-sonnet-5-5"
NOTE = "Next: finish the gates | Open: items 20 to 24 | Verified: items 1 to 19 | Chat: none"


class Compact(unittest.TestCase):
    def setUp(self):
        self.home = os.path.join(tempfile.mkdtemp(), "h")
        os.makedirs(os.path.join(self.home, "_harness"))
        self.st = tempfile.mkdtemp()
        self.h = H.Harness(self.home)
        for r in ("ops-coder", "curator"):
            self.h.role_define("operator", r, "harness-ops", carry="none")
        self.a = self.h.register(project="harness-ops", model=MODEL, session_id="s-1", role="ops-coder")["id"]
        self.h.store.append("session.bound", self.a, {"session_id": "s-1", "agent": self.a})
        self.cur = self.h.register(project="harness-ops", model=MODEL, session_id="s-c", role="curator")["id"]

    def start(self, source):
        env = dict(os.environ, HARNESS_HOME=self.home, HARNESS_STATE_DIR=self.st)
        r = subprocess.run([sys.executable, "-B", os.path.join(SCRIPTS, "harness.py"), "hook", "session-start"],
                           input=json.dumps({"session_id": "s-1", "source": source, "cwd": self.home, "model": MODEL}),
                           capture_output=True, text=True, env=env)
        return json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"]

    def test_a_compaction_successor_gets_the_note_and_the_counts_once(self):
        self.h.state_note(self.a, NOTE)
        self.h.send(self.cur, self.a, "build it", subject="s", kind="task")              # owed and unread
        self.h.send(self.cur, self.a, "fyi", subject="s2", kind="notice")                # unread only
        ctx = self.start("compact")
        self.assertIn("After compaction: 2 unread (harness_inbox), 1 owed (harness_admin op=owed lists them).", ctx)
        self.assertIn("finish the gates", ctx)
        self.assertIn("Your latest state note", ctx)
        self.assertIn("untrusted from your state note", ctx)                              # the note is fenced as data
        self.assertEqual(ctx.count("unread message(s)"), 0)                               # the plain unread line is not repeated
        self.assertEqual(ctx.count("unread (harness_inbox)"), 1)
        self.assertEqual(ctx.count("◆"), 1)                                               # the banner once

    def test_a_long_note_is_cut_with_a_recall_pointer(self):
        self.h.state_note(self.a, "Next: " + "x" * 1000)
        ctx = self.start("compact")
        self.assertIn("… recall ", ctx)
        self.assertLess(len(ctx.split("Your latest state note")[1]), H.Harness.COMPACT_NOTE_CHARS + 400)

    def test_no_note_no_mail_adds_nothing(self):
        ctx = self.start("compact")
        self.assertNotIn("After compaction", ctx)

    def test_only_a_compaction_gets_it(self):
        self.h.state_note(self.a, NOTE)
        self.h.send(self.cur, self.a, "fyi", subject="s2", kind="notice")
        ctx = self.start("startup")
        self.assertNotIn("After compaction", ctx)
        self.assertNotIn("finish the gates", ctx)

    def test_counts_only_for_a_note_less_role(self):
        self.h.send(self.cur, self.a, "do it", subject="s", kind="task")
        ctx = self.start("compact")
        self.assertIn("After compaction: 1 unread (harness_inbox), 1 owed (harness_admin op=owed lists them).", ctx)
        self.assertNotIn("Your latest state note", ctx)

    def test_the_hook_still_answers_with_the_banner(self):
        self.assertIn("CREW COORDINATOR", self.start("compact"))


if __name__ == "__main__":
    unittest.main()
