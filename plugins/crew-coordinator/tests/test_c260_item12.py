"""cc 0.26.0 item 12: the nudge part of a send result lists each recipient once with its session; the Do-line text is given once, not repeated
per recipient. Run: python3 -B tests/test_c260_item12.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _env  # noqa: F401  isolate HOME and HARNESS_* first
import unittest

import test_c250_relay_fixes as F


class Item12(F.Fixes):
    def two(self):
        self.h.role_define("operator", "ops-coder", "harness-ops", carry="none")
        a = self.reg("curator", "local_t12a")
        b = self.reg("ops-coder", "local_t12b")
        self.warm(a)
        self.warm(b)
        return a, b

    def test_two_recipients_are_listed_once_each_with_a_session_and_the_text_comes_once(self):
        a, b = self.two()
        r = self.call("harness_send", agent=self.plain, to=["role:curator", "role:ops-coder"], body="b", subject="s", kind="task")
        n = r["nudge"]
        self.assertEqual(len(n["to"]), 2)
        self.assertTrue(any("local_t12a" in x for x in n["to"]) and any("local_t12b" in x for x in n["to"]), n["to"])
        self.assertEqual(n["do"].count("Do: SendMessage"), 1)                       # the instruction text, once
        self.assertEqual(n["do"].count("fixed fields only"), 1)
        self.assertEqual(n["do"].count("report skipped with reason stale_id"), 1)
        self.assertIn("local_t12a", n["do"])
        self.assertIn("local_t12b", n["do"])
        self.assertEqual(n["do"].count(n["line"]), 1)

    def test_one_recipient_is_unchanged(self):
        a, b = self.two()
        n = self.call("harness_send", agent=self.plain, to="role:curator", body="b", subject="s", kind="task")["nudge"]
        self.assertEqual(len(n["to"]), 1)
        self.assertEqual(n["do"].count("Do: SendMessage to local_t12a:"), 1)

    def test_a_recipient_named_twice_is_listed_once(self):
        a, b = self.two()
        n = self.call("harness_send", agent=self.plain, to=["role:curator", a], body="b", subject="s", kind="task")["nudge"]
        self.assertEqual(len(n["to"]), 1)


for _n in [n for n in dir(F.Fixes) if n.startswith("test_")]:
    setattr(Item12, _n, None)


if __name__ == "__main__":
    unittest.main()
