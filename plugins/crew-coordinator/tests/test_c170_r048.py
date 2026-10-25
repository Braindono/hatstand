"""cc 0.17.0 R-048 hatstand sync op: the plugin's own hatstand-sync.sh against a local bare repo (no network). Dry run
first, push only after a clean dry run of the same marketplace, envoy direct else an approval request, refusal on
secret patterns. Run: python3 -B tests/test_c170_r048.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _env  # noqa: F401  isolate HOME and HARNESS_* first
import os, shutil, subprocess, sys, tempfile, unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
import harness as H
import mcp_server as M

MODEL = "claude-opus-5-5"
GIT = shutil.which("git")


def git(*a, cwd=None):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *a], cwd=cwd,
                          capture_output=True, text=True, check=True).stdout


@unittest.skipUnless(GIT and shutil.which("rsync"), "git and rsync needed")
class Hatstand(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.home = os.path.join(self.tmp, "Exchange")
        mk = os.path.join(self.home, "_harness", "marketplace")
        os.makedirs(os.path.join(mk, "plugins", "demo", ".claude-plugin"))
        os.makedirs(os.path.join(mk, ".claude-plugin"))
        with open(os.path.join(mk, "plugins", "demo", ".claude-plugin", "plugin.json"), "w") as f:
            f.write('{"name": "demo", "version": "1.0.0"}\n')
        with open(os.path.join(mk, ".claude-plugin", "marketplace.json"), "w") as f:
            f.write('{"plugins": []}\n')
        with open(os.path.join(self.home, "_harness", "wake.py"), "w") as f:
            f.write("print('wake')\n")
        self.bare = os.path.join(self.tmp, "hatstand.git")
        git("init", "-q", "--bare", "-b", "main", self.bare)
        seed = os.path.join(self.tmp, "seed")
        git("init", "-q", "-b", "main", seed)
        for d in ("plugins", "bin", ".claude-plugin"):
            os.makedirs(os.path.join(seed, d))
            open(os.path.join(seed, d, ".keep"), "w").close()
        git("add", "-A", cwd=seed)
        git("commit", "-q", "-m", "seed", cwd=seed)
        git("push", "-q", self.bare, "main", cwd=seed)
        e = mock.patch.dict(os.environ, {"HARNESS_STATE_CACHE": "0", "HATSTAND_REPO": "file://" + self.bare,
                                         "GIT_CONFIG_GLOBAL": os.path.join(self.tmp, "gitconfig")})
        e.start()
        self.addCleanup(e.stop)
        self.h = H.Harness(self.home)
        for r in ("envoy", "curator", "secretary"):
            self.h.role_define("operator", r, "harness-ops")
        self.envoy = self.h.register(project="harness-ops", model=MODEL)["id"]
        self.h.role_assign("operator", "envoy", self.envoy)
        self.cur = self.h.register(project="harness-ops", model=MODEL)["id"]
        self.h.role_assign("operator", "curator", self.cur)
        self.sec = self.h.register(project="harness-ops", model=MODEL)["id"]
        self.h.role_assign("operator", "secretary", self.sec)

    def head(self):
        return git("--git-dir", self.bare, "rev-parse", "main").strip()

    def test_dry_run_then_envoy_push(self):
        h0 = self.head()
        with self.assertRaises(H.HarnessError):              # no dry run yet
            self.h.hatstand_sync(self.envoy, push=True)
        r = self.h.hatstand_sync(self.envoy)
        self.assertEqual((r["exit"], r["state"]), (0, "dry-run"), r)
        self.assertEqual(self.head(), h0)                      # a dry run pushes nothing
        r = self.h.hatstand_sync(self.envoy, push=True)
        self.assertEqual(r["state"], "pushed", r)
        self.assertNotEqual(self.head(), h0)
        self.assertTrue(r["commit"] and self.head().startswith(r["commit"]))
        self.assertIn("demo 1.0.0", git("--git-dir", self.bare, "log", "-1", "--format=%s"))
        r = self.h.hatstand_sync(self.envoy)
        self.assertEqual(r["state"], "no-change")

    def test_a_changed_marketplace_needs_a_new_dry_run(self):
        self.h.hatstand_sync(self.envoy)
        with open(os.path.join(self.home, "_harness", "wake.py"), "a") as f:
            f.write("# changed\n")
        with self.assertRaises(H.HarnessError):
            self.h.hatstand_sync(self.envoy, push=True)

    def test_secret_pattern_refuses(self):
        p = os.path.join(self.home, "_harness", "marketplace", "plugins", "demo", "leak.txt")
        with open(p, "w") as f:
            f.write("token " + "gh" + "p_" + "x" * 36 + "\n")       # split so this file itself never trips the scan
        r = self.h.hatstand_sync(self.envoy)
        self.assertEqual((r["state"], r["exit"]), ("refused", 1), r)
        with self.assertRaises(H.HarnessError):                 # no clean dry run: no push
            self.h.hatstand_sync(self.envoy, push=True)

    def test_runtime_data_refuses_outside_the_steward_fixture(self):
        base = os.path.join(self.home, "_harness", "marketplace", "plugins")
        fx = os.path.join(base, "crew-coordinator", "tests", "fixtures", "steward-r045", "home", "_harness")
        os.makedirs(fx)
        with open(os.path.join(fx, "events.jsonl"), "w") as f:
            f.write("{}\n")
        self.assertEqual(self.h.hatstand_sync(self.envoy)["state"], "dry-run")      # the synthetic fixture is allowed
        with open(os.path.join(base, "demo", "events.jsonl"), "w") as f:
            f.write("{}\n")
        r = self.h.hatstand_sync(self.envoy)
        self.assertEqual((r["state"], r["exit"]), ("refused", 1), r)               # anywhere else: runtime data, stop

    def test_roles_curator_push_is_an_approval_others_refused(self):
        self.h.hatstand_sync(self.cur)
        r = self.h.hatstand_sync(self.cur, push=True)
        self.assertEqual(r["action"], "hatstand_push")
        self.assertTrue(r["pending"].startswith("A-"))
        with self.assertRaises(H.HarnessError):
            self.h.hatstand_sync(self.sec)
        h0 = self.head()
        out = self.h._run_approved("hatstand_push", {}, self.cur)   # what `harness.py approve` runs for the operator
        self.assertEqual(out["state"], "pushed")
        self.assertNotEqual(self.head(), h0)

    def test_admin_op_and_events(self):
        r = M.admin(self.h, {"op": "hatstand_sync", "agent": self.envoy, "args": {}})
        self.assertEqual(r["state"], "dry-run")
        ev = [e for e in self.h.store.read_all() if e["type"] == "hatstand.synced"]
        self.assertEqual((ev[-1]["data"]["mode"], ev[-1]["data"]["exit"]), ("dry", 0))
        with self.assertRaises(H.HarnessError):
            M.admin(self.h, {"op": "hatstand_sync", "agent": self.envoy, "args": {"repo": "x"}})


if __name__ == "__main__":
    unittest.main()
