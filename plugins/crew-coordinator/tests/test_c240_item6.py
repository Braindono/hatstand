"""cc 0.24.0 item 6 (scope A-b2950; curator spec 2026-11-10_cc024-gaps-checks-build-spec.md v2.1): the post-publish check ignores
files the harness rewrites at runtime (_harness/nudge_state/, recall_stats.jsonl, retired_sessions.json). Each runtime test fails on 0.23.0.
Run: python3 -B tests/test_c240_item6.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _env  # noqa: F401  isolate HOME and HARNESS_* first
import json, os, shutil, tempfile, time, unittest

import test_c220_gate as G
from test_c220_gate import RG, RS

PUBLISH = {"tool_name": "Bash", "tool_input": {"command": "python3 harness.py publish --build"}}


class Item6(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.home, self.h = G.make_home(self.tmp)
        for rel in ("_harness/nudge_state/x.json", "_harness/recall_stats.jsonl", "_harness/retired_sessions.json", "_harness/wake.json",
                    "_harness/data/nudge_state/x"):
            self.put(rel, "before")

    def put(self, rel, text):
        p = os.path.join(self.home, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as f:
            f.write(text)

    def check(self, change):
        pre = {"t": time.time() - 1, "code": "c" * 64, "hashes": RS.hash_tree(self.home), "carried": []}
        with open(os.path.join(self.home, "_harness", "release_prehash.json"), "w") as f:
            json.dump(pre, f)
        self.h.store.append("release.published", "human", {"name": "crew-coordinator", "version": "9", "code": "c" * 64})
        change()
        out = RG.post_check(PUBLISH, self.home)
        ev = [e for e in self.h.store.read_all() if e["type"] == "release.postcheck"][-1]["data"]
        return out, ev

    def test_changed_runtime_files_give_postcheck_ok(self):
        for rel in ("_harness/nudge_state/x.json", "_harness/recall_stats.jsonl", "_harness/retired_sessions.json"):
            with self.subTest(rel=rel):
                self.setUp()
                out, ev = self.check(lambda: self.put(rel, "after"))
                self.assertIn("release.postcheck: ok", out)
                self.assertTrue(ev["ok"], ev)

    def test_a_new_or_deleted_nudge_state_file_does_not_fail(self):
        out, ev = self.check(lambda: (os.remove(os.path.join(self.home, "_harness/nudge_state/x.json")),
                                      self.put("_harness/nudge_state/new.json", "n")))
        self.assertTrue(ev["ok"], ev)

    def test_guard_local_data_and_wake_json_still_fail(self):
        for rel in (G.LOCAL, "_harness/wake.json"):
            with self.subTest(rel=rel):
                self.setUp()
                out, ev = self.check(lambda: self.put(rel, "after"))
                self.assertIn("release.postcheck FAILED", out)
                self.assertIn("I1 local file changed: " + rel, ev["failures"])

    def test_the_filter_is_anchored(self):
        out, ev = self.check(lambda: self.put("_harness/data/nudge_state/x", "after"))
        self.assertFalse(ev["ok"])
        self.assertIn("I1 local file changed: _harness/data/nudge_state/x", ev["failures"])

    def test_guard_release_sim_is_unchanged(self):
        self.assertFalse(hasattr(RS, "RUNTIME_PREFIXES"))
        self.assertFalse(hasattr(RS, "_drop_runtime"))


if __name__ == "__main__":
    unittest.main()
