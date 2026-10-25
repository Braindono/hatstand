"""cc 0.17.0 R-087 (operator idea fzj12n): ~/Claude/scripts launchers (no moves) and the delete-site changes
(USER-DATA deletes become archive moves). Run: python3 -B tests/test_c170_r087.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _env  # noqa: F401  isolate HOME and HARNESS_* first
import contextlib, io, json, os, subprocess, sys, tempfile, unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
import harness as H
import launchers as LN


class Launchers(unittest.TestCase):
    def setUp(self):
        self.home_dir = os.environ["HOME"]
        self.ex = os.path.join(self.home_dir, "Claude", "Projects", "Exchange")
        self.ops = os.path.join(self.home_dir, "Claude", "Code", "harness-ops")
        e = mock.patch.dict(os.environ, {"HARNESS_OPS_ROOT": self.ops})
        e.start()
        self.addCleanup(e.stop)
        self.dest = tempfile.mkdtemp(prefix="scripts-", dir=self.home_dir)
        os.rmdir(self.dest)
        self.made = []
        for name, (raw, _p) in LN.DEFAULTS.items():
            t = raw.replace("$EXCHANGE", self.ex).replace("$OPS", self.ops).replace("$PROJECTS", os.path.join(self.home_dir, "Claude", "Projects"))
            os.makedirs(os.path.dirname(t), exist_ok=True)
            if not os.path.exists(t):
                with open(t, "w") as f:
                    f.write("import sys; print('ARGS', sys.argv[1:])\n" if t.endswith(".py") else "echo ARGS \"$@\"\n")
                self.made.append(t)
        self.addCleanup(lambda: [os.remove(t) for t in self.made if os.path.exists(t)])

    def test_dry_run_writes_nothing_and_lists_all(self):
        res = LN.plan(self.ex, self.dest)
        self.assertEqual(sorted(res["write"]), sorted(list(LN.DEFAULTS) + ["README.md"]))
        self.assertFalse(os.path.exists(self.dest))

    def test_apply_writes_executable_launchers_that_run_in_place(self):
        res = LN.plan(self.ex, self.dest)
        LN.apply(res)
        p = os.path.join(self.dest, "harness")
        self.assertTrue(LN.mode_ok(p))
        self.assertEqual(os.stat(self.dest).st_mode & 0o777, 0o700)
        out = subprocess.run([p, "approve", "A-123 x"], capture_output=True, text=True).stdout
        self.assertIn("ARGS ['approve', 'A-123 x']", out)       # arguments pass through, spaces kept
        with open(os.path.join(self.dest, "README.md")) as f:
            self.assertIn("| `harness` |", f.read())
        again = LN.plan(self.ex, self.dest)
        self.assertEqual(again["write"], [])                    # idempotent
        self.assertEqual(len(again["same"]), len(LN.DEFAULTS) + 1)

    def test_never_overwrites_a_file_it_did_not_generate(self):
        os.makedirs(self.dest)
        with open(os.path.join(self.dest, "wake"), "w") as f:
            f.write("#!/bin/sh\necho mine\n")
        res = LN.plan(self.ex, self.dest)
        self.assertIn("wake", res["conflict"])
        LN.apply(res)
        with open(os.path.join(self.dest, "wake")) as f:
            self.assertEqual(f.read(), "#!/bin/sh\necho mine\n")

    def test_missing_and_outside_targets_skipped(self):
        os.remove(self.made[0]) if self.made else None
        res = LN.plan(self.ex, self.dest, {"operator_launchers": {"evil": "/tmp/evil.py", "mine": "~/Claude/Code/x/y.py"}})
        self.assertTrue(any(s.startswith("evil: outside") for s in res["skipped"]))
        self.assertTrue(any(s.startswith("mine: target missing") for s in res["skipped"]))
        self.assertNotIn("evil", res["write"])

    def test_operator_file_adds_launchers_shared_config_does_not(self):
        t = os.path.join(self.home_dir, "Claude", "Code", "x", "tool.py")
        os.makedirs(os.path.dirname(t), exist_ok=True)
        with open(t, "w") as f:
            f.write("print(1)\n")
        self.assertIn("tool", LN.plan(self.ex, self.dest, {"operator_launchers": {"tool": t}})["write"])
        os.makedirs(os.path.join(self.ex, "_harness"), exist_ok=True)
        with open(os.path.join(self.ex, "_harness", "config.json"), "w") as f:
            json.dump({"operator_launchers": {"tool": t}}, f)
        with contextlib.redirect_stdout(io.StringIO()) as o:
            H.main(["--home", self.ex, "launchers", "--dir", self.dest])
        self.assertNotIn('"tool"', o.getvalue())                # the CLI reads operator.json only
        self.assertIn('"dry_run": true', o.getvalue())


class TranscriptPurgeTombstone(unittest.TestCase):
    """The audit's one USER-DATA finding in this plugin: the operator-only transcript purge removed files without the
    tombstone and manifest line the 10-22 ruling (D-8b925) asks for."""

    def test_purge_leaves_tombstone_and_manifest_without_content(self):
        import transcript_indexer as TI
        tmp = tempfile.mkdtemp()
        root = os.path.join(tmp, "ix")
        ix = TI.Indexer(root=root, cache=os.path.join(tmp, "cache"), source=os.path.join(tmp, "src"), ledger=False)
        with open(os.path.join(root, "2026-10-25-p-abcdef12.md"), "w") as f:
            f.write("### operator 2026-10-25 10:00:00\n> leaked sk-secret-value\n")
        with open(os.path.join(root, "2026-10-25-p-99999999.md"), "w") as f:
            f.write("other\n")
        self.assertEqual(ix.purge("abcdef12-0000"), ["2026-10-25-p-abcdef12.md"])
        self.assertFalse(os.path.exists(os.path.join(root, "2026-10-25-p-abcdef12.md")))
        self.assertTrue(os.path.exists(os.path.join(root, "2026-10-25-p-99999999.md")))
        with open(os.path.join(root, "2026-10-25-p-abcdef12.md.purged")) as f:
            tomb = f.read()
        with open(os.path.join(root, ".purged.jsonl")) as f:
            man = json.loads(f.readline())
        self.assertEqual((man["purged"], man["session"]), ("2026-10-25-p-abcdef12.md", "abcdef12-0000"))
        self.assertNotIn("sk-secret", tomb + json.dumps(man))
        self.assertEqual(ix.status()["vault_files"], 1)            # tombstones are not counted as transcripts


if __name__ == "__main__":
    unittest.main()
