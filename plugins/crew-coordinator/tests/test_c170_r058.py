"""cc 0.17.0 R-058 (R-030): set-project's 'role stays' note uses the current role name and treats aliased projects
(orchestration = harness-ops) as the same project. Run: python3 -B tests/test_c170_r058.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _env  # noqa: F401  isolate HOME and HARNESS_* first
import json, os, sys, tempfile, unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
import harness as H

MODEL = "claude-opus-5-5"


class RoleStaysNote(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        ops = os.path.join(self.tmp, "ops")
        os.makedirs(os.path.join(ops, "_alias"))
        json.dump({"project_aliases": {"orchestration": "harness-ops", "skill-curation": "harness-ops"}},
                  open(os.path.join(ops, "_alias", "alias-map.json"), "w"))
        e = mock.patch.dict(os.environ, {"HARNESS_OPS_ROOT": ops})
        e.start()
        self.addCleanup(e.stop)
        self.home = os.path.join(self.tmp, "Exchange")
        os.makedirs(self.home)
        self.h = H.Harness(self.home)

    def holder(self, role, project):
        self.h.role_define("operator", role, project)
        a = self.h.register(project=project, model=MODEL)["id"]
        self.h.role_assign("operator", role, a)
        return a

    def test_aliased_project_gives_no_note(self):
        a = self.holder("steward", "orchestration")
        r = self.h.set_project(a, "harness-ops", "operator")
        self.assertNotIn("warn", r)

    def test_old_role_name_is_printed_as_the_current_one(self):
        a = self.holder("corpus-steward", "orchestration")     # defined under the old name
        r = self.h.set_project(a, "cv-management", "operator")
        self.assertIn("role steward stays in project orchestration", r.get("warn", ""))
        self.assertNotIn("corpus-steward", r.get("warn", ""))

    def test_real_move_still_warns(self):
        a = self.holder("letters-manager", "cv-management")
        r = self.h.set_project(a, "design-system", "operator")
        self.assertIn("role letters-manager stays in project cv-management", r.get("warn", ""))


if __name__ == "__main__":
    unittest.main()
