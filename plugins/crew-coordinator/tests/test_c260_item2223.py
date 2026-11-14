"""cc 0.26.0 items 22 and 23: operator scripts print "approval N of M" at each prompt and list every prompt in the header; the release script (action
release_scope) files and approves its own release scopes through the CLI in one step, so the request's expiry cannot lapse while it waits on a human.
Run: python3 -B tests/test_c260_item2223.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _env  # noqa: F401  isolate HOME and HARNESS_* first
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(HERE, "..", "scripts")
sys.path.insert(0, SCRIPTS)
import harness as H
import operator_script as OS

STUB = "import sys\nprint('STUB ' + ' '.join(sys.argv[3:]))\n"       # stands in for harness.py: argv = [stub, --home, H, command, ...]
ITEM = {"plugin": "crew-coordinator", "version": "0.26.0", "items": ["Prefs lookup (scripts/harness.py): the lookup", "Reminder module: moved"],
        "rationale": "the 0.26.0 scope"}


class Render(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.home = os.path.join(self.tmp, "h")
        os.makedirs(self.home)
        self.stub = os.path.join(self.tmp, "stub.py")
        open(self.stub, "w").write(STUB)

    def script(self, action, items):
        r = OS.write(self.home, self.stub, action, items, None, "tester")
        return r["path"], open(r["path"]).read()

    def run_script(self, path, *mode):
        r = subprocess.run(["bash", path, *mode], capture_output=True, text=True)
        return r.stdout

    def test_the_header_lists_every_prompt_in_order(self):
        _p, txt = self.script("approve", ["A-aaaaa", "A-bbbbb", "A-ccccc"])
        hdr = [ln for ln in txt.splitlines() if ln.startswith("#")]
        self.assertIn("# prompts: 3, in this order (you type a code at each):", hdr)
        i = hdr.index("# prompts: 3, in this order (you type a code at each):")
        self.assertEqual(hdr[i + 1:i + 4], ["#   1. approve A-aaaaa", "#   2. approve A-bbbbb", "#   3. approve A-ccccc"])

    def test_each_prompt_prints_approval_n_of_m_before_it_asks(self):
        p, _txt = self.script("approve", ["A-aaaaa", "A-bbbbb"])
        out = self.run_script(p, "apply").splitlines()
        a = out.index("approval 1 of 2")
        self.assertTrue(out[a + 1].startswith("STUB approve A-aaaaa"))
        b = out.index("approval 2 of 2")
        self.assertTrue(out[b + 1].startswith("STUB approve A-bbbbb"))

    def test_a_dry_run_asks_nothing_and_a_finished_step_is_skipped_without_a_prompt_line(self):
        p, _txt = self.script("approve", ["A-aaaaa", "A-bbbbb"])
        self.assertNotIn("approval 1 of 2", self.run_script(p))
        self.run_script(p, "apply")
        again = self.run_script(p, "apply")
        self.assertNotIn("approval", again)
        self.assertIn("skip approve:A-aaaaa (done)", again)

    def test_the_header_names_the_progress_file(self):                            # critic (non-blocking)
        p, txt = self.script("approve", ["A-aaaaa"])
        self.assertIn("# progress file: " + p + ".done", txt)

    def test_an_action_with_no_prompts_has_no_prompt_lines(self):
        _p, txt = self.script("retire", ["a" * 8])
        self.assertNotIn("# prompts", txt)
        self.assertNotIn("approval 1 of", txt)


class ReleaseScript(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.home = os.path.join(self.tmp, "h")
        os.makedirs(self.home)
        self.stub = os.path.join(self.tmp, "stub.py")
        open(self.stub, "w").write(STUB)

    def test_release_scope_steps_file_the_scope_through_the_cli_with_validated_values(self):
        steps = OS.normalize("release_scope", [ITEM, dict(ITEM, version="0.26.1")])
        self.assertEqual([s[0] for s in steps], ["release_scope:crew-coordinator:0.26.0", "release_scope:crew-coordinator:0.26.1"])
        cmd = steps[0][1]
        self.assertEqual(cmd[:5], ["release-scope", "--plugin", "crew-coordinator", "--version", "0.26.0"])
        self.assertEqual(json.loads(cmd[cmd.index("--items") + 1]), ITEM["items"])

    def test_bad_values_are_refused(self):
        for bad in (dict(ITEM, version="0.26"), dict(ITEM, plugin="Bad Name"), dict(ITEM, items=[]), dict(ITEM, items=["ab"]),
                    dict(ITEM, rationale=""), dict(ITEM, approval_ref="not-an-id"), "text"):
            with self.subTest(bad=str(bad)[:40]), self.assertRaises(OS.ScriptError):
                OS.normalize("release_scope", [bad])

    def test_the_generated_script_prompts_and_numbers_each_scope(self):
        r = OS.write(self.home, self.stub, "release_scope", [ITEM, dict(ITEM, plugin="harness-router", version="1.2.3")], None, "tester")
        txt = open(r["path"]).read()
        self.assertIn("#   1. release_scope crew-coordinator 0.26.0", txt)
        out = subprocess.run(["bash", r["path"], "apply"], capture_output=True, text=True).stdout.splitlines()
        self.assertIn("approval 1 of 2", out)
        self.assertIn("approval 2 of 2", out)
        self.assertTrue(any(x.startswith("STUB release-scope --plugin crew-coordinator") for x in out))

    def test_the_cli_refuses_without_a_terminal(self):
        r = subprocess.run([sys.executable, "-B", os.path.join(SCRIPTS, "harness.py"), "--home", self.home, "release-scope", "--plugin", "p",
                            "--version", "1.0.0", "--items", json.dumps(ITEM["items"]), "--rationale", "r"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 2)
        self.assertIn("interactive terminal", r.stdout + r.stderr)


class Cli(unittest.TestCase):
    """The release-scope command files the request and approves it in one step: the scope is recorded, the request is granted, nothing pends."""

    def setUp(self):
        self.home = os.path.join(tempfile.mkdtemp(), "h")
        os.makedirs(self.home)
        self.h = H.Harness(self.home)

    def run_cli(self, items, answer=None):
        def ask(prompt):
            rec = [r for r in H.Harness(self.home)._approval_records().values() if r["state"] == "pending"][-1]
            return answer if answer is not None else rec["args_digest"][:4]
        tty = mock.Mock()
        tty.isatty.return_value = True
        out = io.StringIO()
        out.isatty = lambda: True
        with mock.patch.object(sys, "stdin", tty), mock.patch.object(sys, "stdout", out), mock.patch("builtins.input", ask), \
                mock.patch.dict(os.environ):          # main() sets HARNESS_HOME from --home: restored on exit
            code = H.main(["--home", self.home, "release-scope", "--plugin", "crew-coordinator", "--version", "0.26.0",
                           "--items", json.dumps(items), "--rationale", "the 0.26.0 scope"])
        return code, out.getvalue()

    def test_the_scope_is_filed_and_approved_in_one_step(self):
        code, out = self.run_cli(ITEM["items"])
        self.assertIn("release_scope requested by", out)
        st = H.Harness(self.home).state()
        self.assertEqual(st.release_scopes[("crew-coordinator", "0.26.0")]["items"], ITEM["items"])
        self.assertEqual([r["state"] for r in H.Harness(self.home)._approval_records().values()], ["granted"])

    def test_a_wrong_code_records_nothing(self):
        try:
            self.run_cli(ITEM["items"], answer="zzzz")
        except (H.HarnessError, SystemExit):
            pass
        self.assertEqual(H.Harness(self.home).state().release_scopes, {})

    def test_the_same_request_run_again_reuses_the_pending_one(self):
        a = self.h.request_approval("operator", "release_scope", {"plugin": "crew-coordinator", "version": "0.26.0", "items": ITEM["items"],
                                                                   "rationale": "the 0.26.0 scope"})
        self.run_cli(ITEM["items"])
        recs = H.Harness(self.home)._approval_records()
        self.assertEqual(list(recs), [a["pending"]])


if __name__ == "__main__":
    unittest.main()
