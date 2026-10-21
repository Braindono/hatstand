"""cc 0.14.1 tests: code-vs-package publish check, refused-claim exit code. Run: python3 -B tests/test_pkg_check_claim_exit.py"""
import contextlib, io, json, os, shutil, sys, tempfile, unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import harness as H
from test_release_gates import _mk, mkzip


class PkgCheckTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.h, self.envoy, self.lead, self.plug, self.pkg, self.sha = _mk(self.tmp)

    def _bump(self, ver):
        with open(os.path.join(self.plug, ".claude-plugin", "plugin.json"), "w") as f:
            json.dump({"name": "dummy", "version": ver}, f)

    def test_matching_pkg_publishes(self):
        a = self.h.send(self.envoy, "operator", f"ACCEPT sha={self.sha[:12]}")["id"]
        out = self.h.publish_release(self.plug, pkg=self.pkg, accept=a)
        self.assertEqual(out["version"], "1.0.0")

    def test_stale_pkg_refused_writes_nothing(self):
        # the real case: tree already moved on (new content), --pkg is the older package
        self._bump("1.0.1")
        a = self.h.send(self.envoy, "operator", f"ACCEPT sha={self.sha[:12]}")["id"]
        n = len(self.h.store.read_all())
        with self.assertRaises(H.HarnessError) as c:
            self.h.publish_release(self.plug, pkg=self.pkg, accept=a)
        self.assertIn("does not match", str(c.exception))
        self.assertEqual(len(self.h.store.read_all()), n)

    def test_stale_pkg_refused_even_with_override(self):
        self._bump("1.0.1")
        n = len(self.h.store.read_all())
        with self.assertRaises(H.HarnessError):
            self.h.publish_release(self.plug, pkg=self.pkg, override="ship it")
        self.assertEqual(len(self.h.store.read_all()), n, "no gate_override event on a refused publish")

    def test_non_zip_pkg_refused(self):
        bad = os.path.join(self.tmp, "bad.plugin")
        open(bad, "wb").write(b"not a zip")
        with self.assertRaises(H.HarnessError):
            self.h.publish_release(self.plug, pkg=bad, override="x")


class ClaimExitTests(unittest.TestCase):
    def test_second_claim_exits_nonzero_with_json(self):
        tmp = tempfile.mkdtemp()
        home = os.path.join(tmp, "home"); os.makedirs(home)
        h = H.Harness(home)
        a = h.register(project="p", model="claude-opus-5-5")["id"]
        b = h.register(project="p", model="claude-opus-5-5")["id"]

        def cli(agent):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = H.main(["--home", home, "claim", "--agent", agent, "shared.md"])
            return rc, buf.getvalue()

        rc, out = cli(a)
        self.assertFalse(rc)
        self.assertTrue(json.loads(out)["granted"])
        rc, out = cli(b)
        self.assertEqual(rc, 3)
        body = json.loads(out)
        self.assertIs(body["granted"], False)
        self.assertIn("held_by", body)


if __name__ == "__main__":
    unittest.main(verbosity=2)
