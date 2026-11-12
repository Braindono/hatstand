"""cc 0.24.0 item 7 (scope A-b2950; curator spec 2026-11-10_cc024-gaps-checks-build-spec.md v2.1): the pre-freeze check names added and
removed approval actions. One function (Harness.action_diff) used by release_scope with candidate_tree and by scripts/check_actions.py.
Trees are built from this tree's harness.py (0.24.0 item 13 removed wake_pin): "0.22.5" with wake_pin and without the three proctor
actions, "0.23.0" with wake_pin, "0.24-like" as is.
Each test fails on 0.23.0 (no candidate_tree, no script).
Run: python3 -B tests/test_c240_item7.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _env  # noqa: F401  isolate HOME and HARNESS_* first
import json, os, shutil, subprocess, sys, tempfile, unittest
from unittest import mock

import test_c220_nudge as C
from test_c220_nudge import H

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(os.path.dirname(HERE), "scripts", "check_actions.py")
SRC = os.path.join(os.path.dirname(HERE), "scripts", "harness.py")
ADD_WAKE_PIN = ('"release_scope", "hatstand_push", "lesson_curate",', '"release_scope", "hatstand_push", "lesson_curate", "wake_pin",')
DROP_PROCTOR = ('"proctor_shadow", "case_severity", "case_close")   # 0.23.0', ')   # 0.23.0')
ITEMS_023 = ["item 2: proctor events, approval actions proctor_shadow, case_severity and case_close"]


def tree(tmp, name, drop=()):
    with open(SRC, encoding="utf-8") as f:
        s = f.read()
    for old, new in drop:
        assert s.count(old) == 1, old
        s = s.replace(old, new)
    d = os.path.join(tmp, name)
    os.makedirs(os.path.join(d, "scripts"))
    with open(os.path.join(d, "scripts", "harness.py"), "w", encoding="utf-8") as f:
        f.write(s)
    return d


class Trees(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.v0225 = tree(self.tmp, "v0225", [ADD_WAKE_PIN, DROP_PROCTOR])
        self.v0230 = tree(self.tmp, "v0230", [ADD_WAKE_PIN])
        self.v024 = tree(self.tmp, "v024")

    def scope(self, items):
        p = os.path.join(self.tmp, "scope%d.json" % len(os.listdir(self.tmp)))
        with open(p, "w") as f:
            json.dump(items, f)
        return p

    def run_script(self, prev, cand, items):
        r = subprocess.run([sys.executable, "-B", SCRIPT, prev, cand, self.scope(items)], capture_output=True, text=True)
        return r.returncode, r.stdout + r.stderr


class Script(Trees):
    def test_0225_to_0230_lists_the_three_added_and_exits_0_with_the_023_items(self):
        code, out = self.run_script(self.v0225, self.v0230, ITEMS_023)
        self.assertEqual(code, 0, out)
        self.assertIn("added: case_close, case_severity, proctor_shadow", out)
        self.assertIn("removed: none", out)

    def test_empty_scope_exits_1_naming_each(self):
        code, out = self.run_script(self.v0225, self.v0230, [])
        self.assertEqual(code, 1, out)
        for n in ("proctor_shadow", "case_severity", "case_close"):
            self.assertIn(f"NOT NAMED: approval action {n} added", out)

    def test_a_removed_action_is_listed_and_needs_an_item(self):
        code, out = self.run_script(self.v0230, self.v024, ["unrelated item"])
        self.assertEqual(code, 1, out)
        self.assertIn("removed: wake_pin", out)
        self.assertIn("NOT NAMED: approval action wake_pin removed", out)
        code, out = self.run_script(self.v0230, self.v024, ["item 13: wake_pin approval removed (wake registration)"])
        self.assertEqual(code, 0, out)

    def test_names_must_be_whole_words(self):
        code, out = self.run_script(self.v0230, self.v024, ["wake_pinned events stay"])
        self.assertEqual(code, 1, out)

    def test_unreadable_tree_exits_2_and_writes_nothing(self):
        code, out = self.run_script(os.path.join(self.tmp, "nope"), self.v0230, [])
        self.assertEqual(code, 2, out)
        self.assertIn("approval actions unreadable", out)

    def test_the_script_uses_the_harness_function(self):
        with open(SCRIPT, encoding="utf-8") as f:
            s = f.read()
        self.assertIn("H.Harness.action_diff(", s)
        self.assertNotIn("APPROVAL_ACTIONS", s.split('"""', 2)[2])     # no second parser in the script


class Filing(Trees, C.Base):
    def setUp(self):
        Trees.setUp(self)
        C.Base.setUp(self)
        # fix round 1 (critic 5): the previous tree is the last PUBLISHED release tree in the home's marketplace ("0.22.5" here)
        shutil.copytree(self.v0225, os.path.join(self.home, "_harness", "marketplace", "plugins", "crew-coordinator"))

    def file(self, items, plugin="crew-coordinator", **kw):
        a = {"plugin": plugin, "version": "0.23.0", "items": items, "rationale": "r"}
        a.update(kw)
        with mock.patch.object(H, "PLUGIN_ROOT", self.v024):      # the running plugin is NOT the comparison base
            return self.call("harness_admin", agent=self.plain, op="release_scope", args=a)

    def test_fix1_the_base_is_the_published_tree_not_the_running_plugin(self):
        r = self.file(ITEMS_023, candidate_tree=self.v0230)
        w = " | ".join(r.get("warnings") or [])
        self.assertNotIn("wake_pin", w)                                  # running v024 lacks wake_pin; the published base has it
        self.assertNotIn("approval action", w)

    def test_fix1_no_published_tree_skips_with_a_line(self):
        r = self.file(["item 1: something else"], plugin="other-plugin", candidate_tree=self.v0230)
        self.assertIn("pending", r)
        self.assertTrue(any("check skipped: no published release tree of other-plugin" in w for w in r.get("warnings") or []), r)

    def test_candidate_tree_with_no_naming_items_warns_for_each(self):
        r = self.file(["item 1: something else"], candidate_tree=self.v0230)
        w = " | ".join(r.get("warnings") or [])
        for n in ("proctor_shadow", "case_severity", "case_close"):
            self.assertIn(f"approval action {n} is added in the candidate tree but no item names it", w)
        self.assertIn("pending", r)                                                  # never a refusal

    def test_candidate_tree_with_naming_items_gives_no_warning(self):
        r = self.file(ITEMS_023, candidate_tree=self.v0230)
        self.assertFalse([w for w in (r.get("warnings") or []) if "approval action" in w], r)

    def test_without_candidate_tree_no_check_and_no_error(self):
        r = self.file(["item 1: something else"])
        self.assertFalse([w for w in (r.get("warnings") or []) if "approval action" in w], r)
        self.assertIn("pending", r)

    def test_a_missing_candidate_tree_skips_with_a_line_and_files(self):
        r = self.file(["item 1: something else"], candidate_tree=os.path.join(self.tmp, "missing"))
        self.assertIn("pending", r)
        self.assertTrue(any(w.startswith("approval action check skipped: approval actions unreadable") for w in r.get("warnings") or []), r)

    def test_candidate_tree_is_not_part_of_the_approval_args(self):
        r = self.file(ITEMS_023, candidate_tree=self.v0230)
        rec = self.h._approval_records()[r["pending"]]
        self.assertNotIn("candidate_tree", rec["args"])


if __name__ == "__main__":
    unittest.main()
