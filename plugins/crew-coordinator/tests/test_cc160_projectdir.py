"""cc 0.16.0 group 3: project folders only through the resolver (harness.py side). Run: python3 -B tests/test_cc160_projectdir.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _env  # noqa: F401  isolate HOME and HARNESS_* first
import json, os, re, sys, tempfile, unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
import harness as H


class SecondRoot(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.home = os.path.join(self.tmp, "home")
        self.ops = os.path.join(self.tmp, "ops")
        os.makedirs(self.home)
        os.makedirs(os.path.join(self.ops, "projects", "orchestration", "scripts"))
        e = mock.patch.dict(os.environ, {"HARNESS_OPS_ROOT": self.ops})
        e.start()
        self.addCleanup(e.stop)
        self.h = H.Harness(self.home)

    def test_corpus_index_script_found_in_second_root(self):
        self.assertEqual(self.h._ci_script(), os.path.join(self.ops, "projects", "orchestration", "scripts", "corpus_index.py"))

    def test_missing_folder_falls_back_to_resolver_candidate_not_home_literal(self):
        os.rmdir(os.path.join(self.ops, "projects", "orchestration", "scripts"))
        os.rmdir(os.path.join(self.ops, "projects", "orchestration"))
        self.assertNotEqual(self.h._ci_script(), os.path.join(self.home, "projects", "orchestration", "scripts", "corpus_index.py"))
        self.assertTrue(self.h._ci_script().startswith(self.ops))

    def test_no_home_projects_literal_left_outside_the_resolver(self):
        src = open(os.path.join(HERE, "..", "scripts", "harness.py"), encoding="utf-8").read()
        lits = [m.start() for m in re.finditer(r'os\.path\.join\((?:self\.)?home, "projects"', src)]
        # the resolver's own candidate list, the project_dirs listing and the legacy-equals-resolved check are the only users
        self.assertLessEqual(len(lits), 3)


if __name__ == "__main__":
    unittest.main()
