"""cc 0.15.5 WP2h: publish's verify checks the package given by --pkg wherever it lives. Run: python3 -B tests/test_cc155_publish.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _env  # noqa: F401  isolate HOME and HARNESS_* first
import os, shutil, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
import harness as H
from test_release_gates import _mk


class PkgElsewhere(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.h, self.envoy, self.lead, self.plug, self.pkg, self.sha = _mk(self.tmp)
        self.away = os.path.join(self.tmp, "elsewhere")
        os.makedirs(self.away)
        self.moved = os.path.join(self.away, os.path.basename(self.pkg))
        shutil.move(self.pkg, self.moved)    # no package beside the source any more
        m = self.h.send(self.envoy, "operator", f"ACCEPT sha={self.sha[:12]} ok")["id"]
        self.accept = m

    def test_verify_finds_the_pkg_file(self):
        out = self.h.publish_release(self.plug, pkg=self.moved, accept=self.accept)
        self.assertTrue(out["verify"]["ok"], out["verify"])

    def test_plain_verify_still_wants_a_package_beside_the_source(self):
        self.h.publish_release(self.plug, pkg=self.moved, accept=self.accept)
        v = self.h.verify_plugins(only="dummy")
        self.assertFalse(v["ok"])
        self.assertTrue(any("no .plugin package beside the source" in x for x in v["problems"]))
        self.assertTrue(self.h.verify_plugins(only="dummy", pkg=self.moved)["ok"])


if __name__ == "__main__":
    unittest.main()
