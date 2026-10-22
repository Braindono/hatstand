"""cc 0.15.5: register/restore resolve project aliases before the role/project check.
Run: python3 -B tests/test_cc155_alias_restore.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _env  # noqa: F401  isolate HOME and HARNESS_* first
import json, os, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
import harness as H

MODEL = "claude-sonnet-5-5"


class AliasRestore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.home = os.path.join(self.tmp, "home")
        os.makedirs(os.path.join(self.home, "_harness"))
        with open(os.path.join(self.home, "_harness", "project-aliases.json"), "w") as f:
            json.dump({"aliases": {"orchestration": "harness-ops"}}, f)
        self.h = H.Harness(self.home)
        self.h.role_define("operator", "ops-coder", "harness-ops")

    def test_alias_project_takes_role(self):
        a = self.h.register(project="orchestration", role="ops-coder", model=MODEL)
        self.assertEqual(self.h.state().role_holder("ops-coder"), a["id"])

    def test_canonical_project_still_works(self):
        a = self.h.register(project="harness-ops", role="ops-coder", model=MODEL)
        self.assertEqual(self.h.state().role_holder("ops-coder"), a["id"])

    def test_unrelated_project_still_rejected(self):
        with self.assertRaises(H.HarnessError):
            self.h.register(project="design-system", role="ops-coder", model=MODEL)


class FileSha(unittest.TestCase):
    def test_unreadable_file_is_none(self):
        d = tempfile.mkdtemp()
        f = os.path.join(d, "x")
        open(f, "w").write("a")
        self.assertEqual(H.file_sha(f), H.hashlib.sha256(b"a").hexdigest())
        orig = open
        def deny(path, *a, **k):
            if path == f:
                raise PermissionError(1, "Operation not permitted")
            return orig(path, *a, **k)
        H.open = deny
        try:
            self.assertIsNone(H.file_sha(f))
        finally:
            del H.open


if __name__ == "__main__":
    unittest.main()
