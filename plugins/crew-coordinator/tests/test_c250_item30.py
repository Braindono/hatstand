"""cc 0.25.0 item 30: the digest, the banner and the inbox use one unread function and one owed function. Run: python3 -B tests/test_c250_item30.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _env  # noqa: F401  isolate HOME and HARNESS_* first
import re
import unittest

import test_c220_nudge as C
from test_c220_nudge import D, H, MODEL


class Item30(C.Base):
    def test_after_a_restore_as_a_successor_the_digest_and_the_inbox_agree_on_owed_and_unread(self):
        old = self.reg("curator", "local_old30")
        for i in range(12):                                                       # 12 tasks owed (the old cap would have printed 8)
            self.call("harness_send", agent=self.plain, to="role:curator", body="b%d" % i, subject="s%d" % i, kind="task")
        self.call("harness_send", agent=self.plain, to="role:curator", body="n", subject="n", kind="notice")
        self.call("harness_send", agent=self.plain, to="*", body="bc", subject="bc", kind="notice")
        self.call("harness_inbox", agent=old)                                     # the predecessor reads everything: lineage read-state
        self.call("harness_send", agent=self.plain, to="role:curator", body="late", subject="late", kind="notice")   # one unread for the successor
        before = self.h.unread_count(self.h.state(), old)                        # what the inbox would count for the lineage right now
        self.assertEqual(before, 1)
        dig = self.h.restore("curator", model=MODEL, confirmed=True)
        text = dig["text"] if isinstance(dig, dict) else str(dig)
        succ = self.h.state().role_holder("curator")
        self.assertNotEqual(succ, old)
        self.assertRegex(text, r"12 owed; newest 5 shown")
        inbox = self.call("harness_inbox", agent=succ, peek=True)
        self.assertRegex(inbox["text"], r"owed reply 12:")                       # the footer counts what the digest counts, not 8
        self.assertEqual(inbox["owed_total"], 12)
        self.assertEqual(len(D.owed_replies(self.h.state(), succ)), 12)
        self.assertEqual(len(D.owed_replies(self.h.state(), succ, cap=8)), 8)    # a caller may still ask for a short list
        unread_digest = len(re.findall(r"^\s+m-[0-9a-f]+", text.split("▸ Unread mail")[1].split("▸ ")[0], re.M)) if "▸ Unread mail:" not in text else 0
        self.assertEqual(unread_digest, before)                                  # digest unread == the inbox count at that moment
        self.assertEqual(inbox["count"], 0)                                      # the digest marked what it showed as read, as designed
        self.assertEqual(self.h.unread_count(self.h.state(), succ), inbox["count"])
        self.assertEqual(self.h.unread_ids(self.h.state(), succ), self.h._inbox_ids(self.h.state(), succ, True))

    def test_one_function_each_no_second_copy_in_the_digest(self):
        src = open(_os.path.join(_os.path.dirname(H.__file__), "harness.py"), encoding="utf-8").read()
        i = src.index('secs.append(("Owes reply"')
        self.assertIn("owed_replies(st, aid)", src[i - 900:i])
        self.assertIn("self.unread_ids(st, aid)", src)


if __name__ == "__main__":
    unittest.main()
