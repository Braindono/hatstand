"""cc 0.26.0 item 1: the preferences file resolves from the canonical-slug folder, then alias folders (round 3: no config override); two files give
a warn line naming both; never newest by mtime. Run: python3 -B tests/test_c260_item1.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _env  # noqa: F401  isolate HOME and HARNESS_* first
import json, os, sys, tempfile, time, unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
import harness as H


def write(p, txt):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w") as f:
        f.write(txt)


class Prefs(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.home = os.path.join(self.tmp, "home")
        self.ops = os.path.join(self.tmp, "ops")
        os.makedirs(os.path.join(self.home, "_harness"))
        write(os.path.join(self.ops, "_alias", "alias-map.json"),
              json.dumps({"project_aliases": {"skill-curation": "harness-ops", "orchestration": "harness-ops"}}))
        e = mock.patch.dict(os.environ, {"HARNESS_OPS_ROOT": self.ops})
        e.start()
        self.addCleanup(e.stop)
        self.h = H.Harness(self.home)
        self.orch = os.path.join(self.ops, "projects", "orchestration", "OPERATOR-PREFERENCES.md")
        self.skill = os.path.join(self.ops, "projects", "skill-curation", "OPERATOR-PREFERENCES.md")
        write(self.orch, "- stale orchestration rule\n")
        write(self.skill, "- current skill-curation rule\n")

    def lines(self):
        return self.h._prefs_lines("harness-ops")

    def test_two_alias_files_warn_and_name_both(self):
        L = self.lines()
        warn = [x for x in L if x.startswith("WARN two preferences files")]
        self.assertEqual(len(warn), 1)
        self.assertIn("projects/orchestration/OPERATOR-PREFERENCES.md", warn[0])
        self.assertIn("projects/skill-curation/OPERATOR-PREFERENCES.md", warn[0])

    def test_mtime_never_decides(self):
        now = time.time()
        os.utime(self.orch, (now + 1000, now + 1000))          # the stale file is the newest
        a = self.lines()
        os.utime(self.skill, (now + 2000, now + 2000))
        b = self.lines()
        self.assertEqual(a[0], b[0])

    def test_config_prefs_file_is_ignored(self):                  # round 3 F3: agent-writable config never picks the preferences
        write(os.path.join(self.home, "_harness", "config.json"), json.dumps({"prefs_file": self.skill}))
        L = self.lines()
        self.assertIn("stale orchestration rule", L)               # the alias order still decides (orchestration < skill-curation)
        self.assertNotIn("current skill-curation rule", L)
        write(os.path.join(self.home, "_harness", "config.json"), json.dumps({"prefs_file": "/etc/hosts"}))
        self.assertFalse(any("hosts" in x for x in self.lines()))

    def test_the_ladder_warning_and_the_two_files_warning_both_show_and_archiving_clears_the_second(self):   # round 3 F4
        write(self.orch, "- inbox-ladder: 10,50\n- rule\n")
        L = self.lines()
        self.assertTrue(any(x.startswith("WARN the inbox-ladder") for x in L), L)
        two = [x for x in L if x.startswith("WARN two preferences files")]
        self.assertEqual(len(two), 1, L)
        self.assertNotIn("prefs_file", two[0])
        os.unlink(self.skill)                                         # the advice: archive the ignored one
        L = self.lines()
        self.assertFalse(any(x.startswith("WARN two") for x in L), L)
        self.assertTrue(any(x.startswith("WARN the inbox-ladder") for x in L), L)

    def test_the_canonical_slug_folder_wins_over_the_stale_alias_file(self):   # round 3 F4: harness-ops's own file is picked first
        write(os.path.join(self.ops, "projects", "harness-ops", "OPERATOR-PREFERENCES.md"), "- harness-ops own rule\n")
        L = self.lines()
        self.assertIn("harness-ops own rule", L)
        self.assertNotIn("stale orchestration rule", L)

    def test_the_canonical_slug_folder_beats_the_aliases(self):
        canon = os.path.join(self.ops, "projects", "harness-ops", "OPERATOR-PREFERENCES.md")
        write(canon, "- canonical rule\n")
        L = self.lines()
        self.assertIn("canonical rule", L)

    def test_one_file_gives_no_warning(self):
        os.unlink(self.orch)
        self.assertFalse(any(x.startswith("WARN") for x in self.lines()))


if __name__ == "__main__":
    unittest.main()
