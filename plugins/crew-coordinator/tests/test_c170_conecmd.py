"""cc 0.17.0 C-onecmd: harness_admin op=operator_script writes a generated, idempotent bulk-action script (dry run by
default, full paths, validated and quoted values) and returns the one command. Run: python3 -B tests/test_c170_conecmd.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _env  # noqa: F401  isolate HOME and HARNESS_* first
import json, os, subprocess, sys, tempfile, unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
import harness as H
import mcp_server as M
import operator_script as OS

MODEL = "claude-opus-5-5"


class OpScript(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.home = os.path.join(self.tmp, "Exchange")
        os.makedirs(os.path.join(self.home, "_harness"))
        e = mock.patch.dict(os.environ, {"HARNESS_STATE_CACHE": "0"})
        e.start()
        self.addCleanup(e.stop)
        self.h = H.Harness(self.home)
        self.a = self.h.register(project="harness-ops", model=MODEL)["id"]
        self.b = self.h.register(project="harness-ops", model=MODEL)["id"]
        self.c = self.h.register(project="harness-ops", model=MODEL)["id"]

    def run_script(self, path, *mode):
        return subprocess.run(["bash", path, *mode], capture_output=True, text=True, timeout=120,
                              env=dict(os.environ, HARNESS_STATE_CACHE="0"))

    def status(self, aid):
        return H.Harness(self.home).state().agents[aid]["status"]

    def test_dry_run_changes_nothing_apply_runs_rerun_skips(self):
        r = self.h.operator_script(self.a, "retire", [self.b[:8], {"target": self.c[:8], "reason": "done"}], "bulk")
        self.assertEqual(r["steps"], 2)
        self.assertTrue(r["command_dry"].startswith("bash /") and r["command_apply"].endswith(" apply"))
        self.assertEqual(oct(os.stat(r["path"]).st_mode & 0o777), "0o700")
        p = self.run_script(r["path"])
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("would run:", p.stdout)
        self.assertEqual((self.status(self.b), self.status(self.c)), ("active", "active"))
        self.assertFalse(os.path.exists(r["path"] + ".done"))
        p = self.run_script(r["path"], "apply")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual((self.status(self.b), self.status(self.c)), ("retired", "retired"))
        p = self.run_script(r["path"], "apply")
        self.assertIn("ok=0 skip=2 fail=0", p.stdout)
        self.assertEqual(self.run_script(r["path"], "bogus").returncode, 2)

    def test_values_are_validated_and_quoted(self):
        for action, items in (("retire", ["x; rm -rf ~"]), ("set_project", [{"target": self.b[:8], "project": "a b"}]),
                              ("retag", [{"entry": "N-12345", "project": "ok", "ref": "$(id)"}]),
                              ("approve", ["A-1234; ls"]), ("nuke", ["x"]), ("retire", []),
                              ("retire", ["0" * 8] * (OS.MAX_ITEMS + 1)), ("launchers", ["x"])):
            with self.assertRaises(H.HarnessError, msg=(action, items)):
                self.h.operator_script(self.a, action, items)
        evil = "it's \"x\" $(touch /tmp/cc-onecmd-pwned) `id`; echo hi"
        r = self.h.operator_script(self.a, "retire", [self.b[:8]], evil)
        self.assertEqual(self.run_script(r["path"], "apply").returncode, 0)
        self.assertFalse(os.path.exists("/tmp/cc-onecmd-pwned"))
        ev = [e for e in H.Harness(self.home).store.read_all() if e["type"] == "agent.retired"]
        self.assertIn(evil, [e["data"].get("reason") for e in ev])      # recorded literally, never run

    def test_same_request_same_file_and_foreign_file_kept(self):
        r1 = self.h.operator_script(self.a, "set_project", [{"target": self.b[:8], "project": "orchestration"}])
        r2 = self.h.operator_script(self.a, "set_project", [{"target": self.b[:8], "project": "orchestration"}])
        self.assertEqual((r1["path"], r2["reused"]), (r2["path"], True))
        with open(r1["path"], "w") as f:
            f.write("#!/bin/bash\necho mine\n")
        with self.assertRaises(H.HarnessError):
            self.h.operator_script(self.a, "set_project", [{"target": self.b[:8], "project": "orchestration"}])
        with open(r1["path"]) as f:
            self.assertEqual(f.read(), "#!/bin/bash\necho mine\n")

    def test_retag_and_launchers_dry_runs_are_read_only_previews(self):
        r = self.h.operator_script(self.a, "launchers", None)
        with open(r["path"]) as f:
            t = f.read()
        self.assertIn("launchers --apply", t)
        self.assertIn("|| true", t)                       # the dry branch runs `launchers` without --apply
        n = self.h.record(self.a, "note", "Move me", "b", project="harness-ops")["id"]
        r = self.h.operator_script(self.a, "retag", [{"entry": n, "project": "orchestration"}])
        p = self.run_script(r["path"])
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(H.Harness(self.home).corpus.entry_meta(n)["project"], "harness-ops")

    def test_event_and_admin_op(self):
        r = M.admin(self.h, {"op": "operator_script", "agent": self.a, "args": {"action": "approve", "items": ["A-abcde"]}})
        self.assertEqual(r["steps"], 1)
        ev = [e for e in self.h.store.read_all() if e["type"] == "operator_script.written"]
        self.assertEqual((len(ev), ev[-1]["data"]["action"], ev[-1]["actor"]), (1, "approve", self.a))
        self.assertFalse(os.path.isabs(ev[-1]["data"]["path"]))
        with self.assertRaises(H.HarnessError):
            M.admin(self.h, {"op": "operator_script", "agent": self.a, "args": {"action": "approve", "cmd": "x"}})


if __name__ == "__main__":
    unittest.main()
