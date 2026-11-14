"""cc 0.26.0 item 21: bare-path hook. The Stop hook logs hook.barepath when a final reply names a local .md, .pdf or .docx path and no SendUserFile or
artifact publish ran that turn; never blocks, prints nothing, counts only. Run: python3 -B tests/test_c260_item21.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _env  # noqa: F401  isolate HOME and HARNESS_* first
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(HERE, "..", "scripts")
sys.path.insert(0, SCRIPTS)
import barepath as B
import harness as H

MODEL = "claude-sonnet-5-5"


def tu(name, **inp):
    return {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": name, "input": inp}]}}


def result():
    return {"type": "user", "message": {"content": [{"type": "tool_result", "content": "ok"}]}}


def final(text):
    return {"type": "assistant", "message": {"content": [{"type": "text", "text": text}]}}


def lines(*rows):
    return [json.dumps(r) for r in ({"type": "user", "message": {"content": "go"}},) + rows]


class Pure(unittest.TestCase):
    def test_what_counts_as_a_local_path(self):
        for t in ("see /Users/x/notes/report.md", "open ~/docs/plan.pdf", "in docs/spec.docx", "[plan](projects/p/plan.MD)",
                  "computer:///Users/x/a.pdf"):
            self.assertTrue(B.paths(t), t)
        for t in ("README.md", "https://example.com/a/b/c.md", "file:///Users/x/a.md", "a/b.txt", "no path here", ""):
            self.assertEqual(B.paths(t), [], t)

    def test_sent_or_published_in_the_turn_means_no_hit(self):
        reply = final("The report is at /Users/x/r.md")
        self.assertIsNotNone(B.check("The report is at /Users/x/r.md", lines(reply)))
        self.assertIsNone(B.check("x /Users/x/r.md", lines(tu("SendUserFile", files=["/Users/x/r.md"]), result(), reply)))
        self.assertIsNone(B.check("x /Users/x/r.md", lines(tu("mcp__a__SendUserFile", files=["r"]), result(), reply)))
        self.assertIsNone(B.check("x /Users/x/r.md", lines(tu("Artifact", file_path="/x/p.html"), result(), reply)))      # default action is publish
        self.assertIsNone(B.check("x /Users/x/r.md", lines(tu("Artifact", action="publish", file_path="/x/p.html"), result(), reply)))
        self.assertIsNotNone(B.check("x /Users/x/r.md", lines(tu("Artifact", action="list"), result(), reply)))             # a list is not a publish
        self.assertIsNotNone(B.check("x /Users/x/r.md", lines(tu("Bash", command="ls"), result(), reply)))

    def test_an_earlier_turn_does_not_count(self):
        rows = lines(tu("SendUserFile", files=["a"]), result(), final("sent")) + \
            [json.dumps({"type": "user", "message": {"content": "next"}}), json.dumps(final("now at /Users/x/r.md"))]
        self.assertIsNotNone(B.check("now at /Users/x/r.md", rows))

    def test_the_hit_is_counts_and_a_hash_only(self):
        n, exts, sha = B.check("a /Users/x/a.md and ~/b/c.pdf", lines(final("x")))
        self.assertEqual((n, exts), (2, ["md", "pdf"]))
        self.assertEqual(len(sha), 12)


class Hook(unittest.TestCase):
    def setUp(self):
        self.home = os.path.join(tempfile.mkdtemp(), "h")
        os.makedirs(os.path.join(self.home, "_harness"))
        self.h = H.Harness(self.home)
        self.st = tempfile.mkdtemp()
        self.tmp = tempfile.mkdtemp()
        for r in ("envoy", "curator"):
            self.h.role_define("operator", r, "harness-ops", carry="none")
        self.a = self.h.register(project="harness-ops", model=MODEL, session_id="s-1", role="envoy")["id"]
        self.h.store.append("session.bound", self.a, {"session_id": "s-1", "agent": self.a})

    def stop(self, *rows, sid="s-1"):
        p = os.path.join(self.tmp, "t.jsonl")
        open(p, "w").write("\n".join(lines(*rows)) + "\n")
        env = dict(os.environ, HARNESS_HOME=self.home, HARNESS_STATE_DIR=self.st)
        r = subprocess.run([sys.executable, "-B", os.path.join(SCRIPTS, "harness.py"), "hook", "stop"],
                           input=json.dumps({"session_id": sid, "transcript_path": p}), capture_output=True, text=True, env=env)
        return r.stdout.strip()

    def events(self):
        return [e for e in H.Harness(self.home).store.read_all() if e["type"] == "hook.barepath"]

    def test_a_bare_path_is_logged_once_with_counts_only_and_nothing_is_printed(self):
        out = self.stop(final("Done: /Users/x/out/report.md is ready"))
        self.assertEqual(out, "")                                              # never blocks, no output
        self.stop(final("Done: /Users/x/out/report.md is ready"))              # the same message: once
        ev = self.events()
        self.assertEqual(len(ev), 1)
        self.assertEqual((ev[0]["actor"], ev[0]["data"]["role"], ev[0]["data"]["paths"], ev[0]["data"]["exts"]), (self.a, "envoy", 1, ["md"]))
        self.assertNotIn("report.md", json.dumps(ev[0]))
        self.assertNotIn("/Users", json.dumps(ev[0]))

    def test_a_sent_file_or_an_artifact_in_the_turn_logs_nothing(self):
        self.stop(tu("SendUserFile", files=["/Users/x/report.md"]), result(), final("Sent. Source: /Users/x/report.md"))
        self.stop(tu("Artifact", file_path="/x/p.html"), result(), final("Published; file /Users/x/report.md"))
        self.assertEqual(self.events(), [])

    def test_no_path_no_event_and_a_roleless_chat_is_skipped(self):
        self.stop(final("nothing to see"))
        self.assertEqual(self.events(), [])
        b = self.h.register(project="harness-ops", model=MODEL, session_id="s-2")["id"]
        self.h.store.append("session.bound", b, {"session_id": "s-2", "agent": b})
        self.stop(final("/Users/x/r.md"), sid="s-2")
        self.assertEqual(self.events(), [])

    def test_one_event_per_session_per_day_not_per_message(self):                  # round 6 (item 7)
        self.stop(final("/Users/x/a.md"))
        self.stop(final("/Users/x/b.md"))
        self.assertEqual(len(self.events()), 1)
        for f in os.listdir(self.st):                                                 # the next day: yesterday's date in the state file
            if f.startswith("harness-barepath-"):
                open(os.path.join(self.st, f), "w").write("2000-01-01")
        self.stop(final("/Users/x/c.md"))
        self.assertEqual(len(self.events()), 2)


if __name__ == "__main__":
    unittest.main()
