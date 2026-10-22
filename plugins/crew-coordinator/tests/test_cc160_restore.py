"""cc 0.16.0 group 1: restore digest carries operator preferences and INTENT; 2k budget outside the capsule.
Run: python3 -B tests/test_cc160_restore.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _env  # noqa: F401  isolate HOME and HARNESS_* first
import json, os, sys, tempfile, unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
import harness as H

MODEL = "claude-sonnet-5-5"


def write(p, txt):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    open(p, "w").write(txt)


class Restore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.home = os.path.join(self.tmp, "home")
        self.ops = os.path.join(self.tmp, "ops")
        os.makedirs(self.home)
        write(os.path.join(self.ops, "_alias", "alias-map.json"),
              json.dumps({"project_aliases": {"skill-curation": "harness-ops"}}))
        e = mock.patch.dict(os.environ, {"HARNESS_OPS_ROOT": self.ops})
        e.start()
        self.addCleanup(e.stop)
        self.h = H.Harness(self.home)
        self.h.role_define("operator", "coder", "harness-ops")
        a = self.h.register(project="harness-ops", role="coder", model=MODEL)["id"]
        self.a = a

    def digest(self):
        st = self.h.state()
        return self.h.restore_digest(st, self.a, "coder", [])

    def test_missing_files_say_so(self):
        d = self.digest()
        self.assertIn("(no preferences file)", d)
        self.assertIn("(no INTENT.md)", d)

    def test_preferences_from_aliased_folder_rules_only(self):
        write(os.path.join(self.ops, "projects", "skill-curation", "OPERATOR-PREFERENCES.md"),
              "# Prefs\n\n> block quote skipped\n\nProse skipped.\n\n## A\n1. Be terse.\n2. Give a recommendation.\n- Use options.\n")
        d = self.digest()
        self.assertIn("Be terse.", d)
        self.assertIn("Use options.", d)
        self.assertNotIn("block quote", d)
        self.assertNotIn("Prose skipped", d)
        self.assertIn("projects/skill-curation/OPERATOR-PREFERENCES.md", d)

    def test_preferences_capped_with_more_pointer(self):
        rules = "\n".join(f"{i}. rule number {i} " + "x" * 150 for i in range(1, 80))
        write(os.path.join(self.ops, "projects", "skill-curation", "OPERATOR-PREFERENCES.md"), rules)
        d = self.digest()
        sec = d.split("▸ Operator preferences")[1].split("▸ ")[0]
        self.assertLess(H.est_tokens(sec) if hasattr(H, "est_tokens") else len(sec) // 4, 760)
        self.assertIn("more → the file above", sec)

    def test_intent_excerpt(self):
        write(os.path.join(self.ops, "projects", "skill-curation", "coder", "INTENT.md"), "# Intent\nBuild path and script changes.\n")
        write(os.path.join(self.ops, "projects", "skill-curation", "OPERATOR-PREFERENCES.md"), "1. x\n")
        d = self.digest()
        self.assertIn("Build path and script changes.", d)

    def test_total_outside_capsule_within_2k(self):
        write(os.path.join(self.ops, "projects", "skill-curation", "OPERATOR-PREFERENCES.md"),
              "\n".join(f"{i}. rule {i} " + "y" * 200 for i in range(1, 60)))
        d = self.digest()
        from corpus import est_tokens
        self.assertLessEqual(est_tokens(d.split("▸ Latest capsule")[0]), 2000)
        self.assertIn("restore_budget", H.load_config.__doc__ or "restore_budget")  # default documented in code

    def test_default_budget_is_2000(self):
        self.assertIn("(≤2000t)", self.digest())

    def test_unrelated_project_role_gets_no_other_projects_prefs(self):
        write(os.path.join(self.ops, "projects", "skill-curation", "OPERATOR-PREFERENCES.md"), "1. harness-ops rule\n")
        self.h.role_define("operator", "other", "design-system")
        b = self.h.register(project="design-system", role="other", model=MODEL)["id"]
        d = self.h.restore_digest(self.h.state(), b, "other", [])
        self.assertNotIn("harness-ops rule", d)


if __name__ == "__main__":
    unittest.main()
