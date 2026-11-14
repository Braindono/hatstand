"""cc 0.26.0 item 13: the sync Changed list shows at most 12 lines plus '+N more (full=true)'; joins, role moves and thread lines are counted,
not listed, unless full=true. Run: python3 -B tests/test_c260_item13.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _env  # noqa: F401  isolate HOME and HARNESS_* first
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
import harness as H

MODEL = "claude-sonnet-5-5"


class Changed(unittest.TestCase):
    def setUp(self):
        from unittest import mock
        p = mock.patch.object(H, "health_rows", return_value=([], 0))        # no real plugin inventory in the Changed list
        p.start()
        self.addCleanup(p.stop)
        self.home = os.path.join(tempfile.mkdtemp(), "h")
        os.makedirs(self.home)
        self.h = H.Harness(self.home)
        self.me = self.h.register(project="orch", model=MODEL, session_id="s-me")["id"]
        self.h.sync(self.me)                                                  # the baseline: everything after this is new

    def others(self, n):
        return [self.h.register(project="orch", model=MODEL, session_id="s-o%d" % i)["id"] for i in range(n)]

    def changed(self, **kw):
        t = self.h.sync(self.me, **kw)["text"]
        return t, (t.split("Changed:\n")[1].split("\nPredecessor")[0].splitlines() if "Changed:\n" in t else [])

    def test_joins_are_counted_not_listed_unless_full(self):
        self.others(6)
        t, lines = self.changed()
        self.assertNotIn("joined:", t)
        self.assertTrue(any("6 joined" in x and "full=true" in x for x in lines), lines)

    def test_full_true_lists_the_joins(self):
        self.others(6)
        t, lines = self.changed(full=True)
        self.assertEqual(t.count("joined: "), 6)

    def test_the_list_is_capped_at_12_lines_with_a_count_line(self):
        ids = self.others(20)
        self.h.sync(self.me)                                                  # consume the joins
        for a in ids:
            self.h.retire(a, "done", by=a)                                    # 20 'retired:' lines: listed lines, not counted ones
        t, lines = self.changed()
        self.assertLessEqual(len(lines), H.CHANGED_CAP + 1, lines)       # 12 lines plus the count line
        self.assertTrue(any(x.startswith("+") and "more (harness_sync full=true)" in x for x in lines), lines)

    def test_full_true_shows_everything(self):
        ids = self.others(20)
        self.h.sync(self.me)
        for a in ids:
            self.h.retire(a, "done", by=a)
        t, lines = self.changed(full=True)
        self.assertEqual(t.count("retired: "), 20)
        self.assertFalse(any("more (harness_sync full=true)" in x for x in lines))

    def test_health_lines_share_the_cap(self):
        from unittest import mock
        rows = [(0, 0, "plugin%d row" % i) for i in range(20)]
        with mock.patch.object(H, "health_rows", return_value=(rows, 0)):
            self.others(1)
            t, lines = self.changed()
        self.assertLessEqual(len(lines), H.CHANGED_CAP + 1, lines)       # 12 lines plus the count line

    def test_few_lines_are_shown_in_full_without_a_count_line(self):
        ids = self.others(2)
        self.h.sync(self.me)
        self.h.retire(ids[0], "done", by=ids[0])
        t, lines = self.changed()
        self.assertIn("retired: ", t)
        self.assertFalse(any("more (harness_sync" in x for x in lines))


if __name__ == "__main__":
    unittest.main()
