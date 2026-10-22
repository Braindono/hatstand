"""cc 0.15.5: restore and handoff accept capsule paths in project folders the resolver placed outside home.
Run: python3 -B tests/test_cc155_capsule_alias.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _env  # noqa: F401  isolate HOME and HARNESS_* first
import json, os, sys, tempfile, unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
import harness as H


def mkdir(*p):
    d = os.path.join(*p)
    os.makedirs(d, exist_ok=True)
    return d


class CapsuleAlias(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.home = mkdir(self.tmp, "home")
        self.ops = mkdir(self.tmp, "ops")
        mkdir(self.ops, "_alias")
        with open(os.path.join(self.ops, "_alias", "alias-map.json"), "w") as f:
            json.dump({"project_aliases": {"skill-curation": "harness-ops"}}, f)
        e = mock.patch.dict(os.environ, {"HARNESS_OPS_ROOT": self.ops, "HOME": self.tmp})
        e.start()
        self.addCleanup(e.stop)
        self.h = H.Harness(self.home)
        self.cap = os.path.join(mkdir(self.ops, "projects", "skill-curation", "handoffs"), "x.md")
        open(self.cap, "w").write("---\nstatus: open\n---\n# c\n")
        self.want = "projects/skill-curation/handoffs/x.md"

    def test_relative_exchange_path(self):
        self.assertEqual(self.h._resolve_in_home("Exchange/" + self.want, must_exist=True), self.want)

    def test_absolute_ops_path(self):
        self.assertEqual(self.h._resolve_in_home(self.cap, must_exist=True), self.want)

    def test_missing_file_still_not_found(self):
        with self.assertRaisesRegex(H.HarnessError, "capsule file not found"):
            self.h._resolve_in_home("Exchange/projects/skill-curation/handoffs/nope.md", must_exist=True)

    def test_unrelated_absolute_rejected(self):
        other = os.path.join(mkdir(self.tmp, "elsewhere"), "x.md")
        open(other, "w").write("x")
        with self.assertRaisesRegex(H.HarnessError, "outside the Exchange home"):
            self.h._resolve_in_home(other, must_exist=True)

    def test_dotdot_escape_rejected(self):
        with self.assertRaises(H.HarnessError):
            self.h._resolve_in_home("Exchange/projects/skill-curation/../../../elsewhere/x.md", must_exist=True)

    def test_symlink_rejected(self):
        os.symlink(self.cap, os.path.join(os.path.dirname(self.cap), "ln.md"))
        with self.assertRaises(H.HarnessError):
            self.h._resolve_in_home("Exchange/projects/skill-curation/handoffs/ln.md", must_exist=True)

    def test_legacy_home_folder_unchanged(self):
        os.environ.pop("HARNESS_OPS_ROOT", None)   # explicit env wins over legacy by design; no env, no ops tree here
        d = mkdir(self.home, "projects", "skill-curation", "handoffs")
        open(os.path.join(d, "y.md"), "w").write("---\nstatus: open\n---\n")
        self.assertEqual(self.h._resolve_in_home("Exchange/projects/skill-curation/handoffs/y.md", must_exist=True),
                         "projects/skill-curation/handoffs/y.md")


if __name__ == "__main__":
    unittest.main()
