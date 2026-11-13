"""cc 0.25.0 item 27(a): one command per message, observed by the Stop hook for envoy, curator, ops-coder and steward. Two or more fenced shell
blocks in the final message print one short line and log hook.onecmd; one block, a non-shell fence or another role stay silent; never blocks.
Run: python3 -B tests/test_c250_onecmd.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _env  # noqa: F401  isolate HOME and HARNESS_* first
import json, os, subprocess, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(HERE, "..", "scripts")
sys.path.insert(0, SCRIPTS)
import harness as H
import onecmd as O

MODEL = "claude-sonnet-5-5"
F = "```"
TWO = "Dry run:\n%sbash\nrun.sh --dry\n%s\nThen apply:\n%sbash\nrun.sh --apply\n%s\n" % (F, F, F, F)
ONE = "Run:\n%sbash\nrun.sh\n%s\nExpected: ok\n" % (F, F)
PY = "Sample:\n%spython\nprint(1)\n%s\nand\n%sjson\n{}\n%s\n" % (F, F, F, F)


class Pure(unittest.TestCase):
    def test_counts(self):
        self.assertEqual(O.shell_blocks(TWO), 2)
        self.assertEqual(O.shell_blocks(ONE), 1)
        self.assertEqual(O.shell_blocks(PY), 0)
        self.assertEqual(O.shell_blocks("%sbash\nx\n%s\n~~~sh\ny\n~~~\n" % (F, F)), 2)
        self.assertEqual(O.shell_blocks("%smarkdown\n%sbash\nnot a block\n%s\n" % ("````", F, F) + "````\n"), 0)   # a fence inside a longer fence is text

    def test_crlf_fences_count(self):
        crlf = TWO.replace("\n", "\r\n")
        self.assertEqual(O.shell_blocks(crlf), 2)
        self.assertIsNotNone(O.check("curator", crlf))
        self.assertEqual(O.shell_blocks(ONE.replace("\n", "\r\n")), 1)

    def test_line_under_40_tokens_and_roles(self):
        line, n, tok = O.check("envoy", TWO)
        self.assertEqual((line, n), (O.LINE, 2))
        self.assertLess(tok, 40)
        for r in ("curator", "ops-coder", "steward"):
            self.assertIsNotNone(O.check(r, TWO))
        self.assertIsNone(O.check("harness-critic", TWO))
        self.assertIsNone(O.check("envoy", ONE))
        self.assertIsNone(O.check("envoy", PY))


class Hook(unittest.TestCase):
    def setUp(self):
        self.home = os.path.join(tempfile.mkdtemp(), "h")
        os.makedirs(os.path.join(self.home, "_harness"))
        self.h = H.Harness(self.home)
        self.st = tempfile.mkdtemp()
        self.tmp = tempfile.mkdtemp()
        for r in ("envoy", "curator", "ops-coder", "steward", "harness-critic"):
            self.h.role_define("operator", r, "harness-ops", carry="none")

    def agent(self, role, sid):
        a = self.h.register(project="harness-ops", model=MODEL, session_id=sid, role=role)["id"]
        self.h.store.append("session.bound", a, {"session_id": sid, "agent": a})
        return a

    def transcript(self, text):
        p = os.path.join(self.tmp, "t.jsonl")
        rows = [{"type": "user", "message": {"content": "go"}}, {"type": "assistant", "message": {"content": [{"type": "text", "text": text}]}}]
        open(p, "w").write("\n".join(json.dumps(r) for r in rows) + "\n")
        return p

    def stop(self, sid, text):
        env = dict(os.environ, HARNESS_HOME=self.home, HARNESS_STATE_DIR=self.st)
        r = subprocess.run([sys.executable, "-B", os.path.join(SCRIPTS, "harness.py"), "hook", "stop"],
                           input=json.dumps({"session_id": sid, "transcript_path": self.transcript(text)}),
                           capture_output=True, text=True, env=env)
        return r.stdout.strip()

    def events(self):
        return [e for e in H.Harness(self.home).store.read_all() if e["type"] == "hook.onecmd"]

    def test_two_bash_fences_warn_once_and_log(self):
        a = self.agent("ops-coder", "s-1")
        out = json.loads(self.stop("s-1", TWO))
        self.assertEqual(out, {"systemMessage": O.LINE})                      # one line, no decision: it never blocks
        self.assertEqual(self.stop("s-1", TWO), "")                           # the same message again: once
        ev = self.events()
        self.assertEqual(len(ev), 1)
        self.assertEqual((ev[0]["data"]["blocks"], ev[0]["data"]["role"], ev[0]["actor"]), (2, "ops-coder", a))
        self.assertLess(ev[0]["data"]["tokens"], 40)
        self.assertNotIn("run.sh", json.dumps(ev[0]))                          # counts only, no message text

    def test_one_fence_and_a_code_sample_are_silent(self):
        self.agent("envoy", "s-2")
        self.assertEqual(self.stop("s-2", ONE), "")
        self.assertEqual(self.stop("s-2", PY), "")
        self.assertEqual(self.events(), [])

    def test_a_role_outside_the_four_is_silent(self):
        self.agent("harness-critic", "s-3")
        self.assertEqual(self.stop("s-3", TWO), "")
        self.assertEqual(self.events(), [])

    def test_a_new_message_warns_again(self):
        self.agent("curator", "s-4")
        self.assertNotEqual(self.stop("s-4", TWO), "")
        self.assertNotEqual(self.stop("s-4", TWO + "more\n"), "")
        self.assertEqual(len(self.events()), 2)

    def test_replay_is_unaffected(self):
        self.agent("steward", "s-5")
        self.stop("s-5", TWO)
        evs = self.h.store.read_all()
        n = len(evs)
        H.State(evs)
        self.assertEqual(len(self.h.store.read_all()), n)


if __name__ == "__main__":
    unittest.main()
