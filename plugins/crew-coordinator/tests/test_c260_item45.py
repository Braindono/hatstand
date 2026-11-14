"""cc 0.26.0 items 4 and 5: an addressee's reply_to marks the mail read (a bare ref never does), a defaulted inbox says it is a peek, and no rewake
fires for mail that was read or answered. Run: python3 -B tests/test_c260_item45.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _env  # noqa: F401  isolate HOME and HARNESS_* first
import time
import unittest
from unittest import mock

import test_c250_relay_fixes as F
from test_c250_relay_fixes import D


class Item45(F.Fixes):
    def sent(self, to, **kw):
        return self.call("harness_send", agent=self.plain, to=to, body="b", subject="s", **kw)

    def unread_for(self, aid):
        return self.h._inbox_ids(self.h.state(), aid, True)

    def test_an_addressees_reply_to_marks_the_mail_read(self):
        self.ready()
        mid = self.send()["nudge"]["msg_id"]                     # task to role:secretary
        self.assertIn(mid, self.unread_for(self.sec))
        self.call("harness_send", agent=self.sec, to=self.plain, body="done", subject="r", kind="notice", reply_to=mid)
        self.assertNotIn(mid, self.unread_for(self.sec))
        ev = [e for e in self.events("message.read") if mid in e["data"]["ids"]]
        self.assertEqual([e["data"].get("via") for e in ev], ["reply_to"])

    def test_a_bare_ref_does_not_mark_read(self):
        self.ready()
        mid = self.send()["nudge"]["msg_id"]
        self.call("harness_send", agent=self.sec, to=self.plain, body="see", subject="r", kind="notice", refs=[mid])
        self.assertIn(mid, self.unread_for(self.sec))

    def test_a_reply_to_by_a_non_addressee_does_not_mark_anything(self):
        self.ready()
        mid = self.send()["nudge"]["msg_id"]
        other = self.reg("harness-critic", "local_o45")
        self.call("harness_send", agent=other, to=self.plain, body="x", subject="r", kind="notice", reply_to=mid)
        self.assertEqual([e for e in self.events("message.read") if mid in e["data"]["ids"]], [])
        self.assertIn(mid, self.unread_for(self.sec))

    def test_a_reply_to_twice_marks_once(self):
        self.ready()
        mid = self.send()["nudge"]["msg_id"]
        for _ in (1, 2):
            self.call("harness_send", agent=self.sec, to=self.plain, body="d", subject="r", kind="notice", reply_to=mid)
        self.assertEqual(len([e for e in self.events("message.read") if mid in e["data"]["ids"]]), 1)

    # item 5: the replay
    def woken(self, mid):
        self.h.store.append("nudge.result", self.plain, {"msg": mid, "msg_id": mid, "by": self.plain, "for": self.plain, "outcome": "woke",
                                                         "reason": "HTTP 200", "status": 200})

    def test_no_rewake_fires_for_mail_that_was_answered_by_reply_to(self):
        self.ready()
        t0 = time.time()
        mid = self.send()["nudge"]["msg_id"]
        self.woken(mid)
        self.call("harness_send", agent=self.sec, to=self.plain, body="done", subject="r", kind="notice", reply_to=mid)   # answered, never inboxed
        out = D.wake_scan(self.h, now=t0 + 16 * 60 + 4000, force=True)
        self.assertEqual([x for x in out if x[1] == mid], [])
        self.assertEqual([e for e in self.events("nudge.rewake") if e["data"]["msg_id"] == mid], [])

    def test_no_rewake_fires_for_mail_read_with_an_explicit_inbox(self):
        self.ready()
        t0 = time.time()
        mid = self.send()["nudge"]["msg_id"]
        self.woken(mid)
        self.call("harness_inbox", agent=self.sec)
        self.assertEqual([x for x in D.wake_scan(self.h, now=t0 + 16 * 60 + 4000, force=True) if x[1] == mid], [])

    def test_a_rewake_still_fires_for_mail_unread_and_unanswered(self):
        self.ready()
        mid = self.send()["nudge"]["msg_id"]
        self.woken(mid)
        self.assertTrue([x for x in D.wake_scan(self.h, now=time.time() + 16 * 60 + 4000, force=True) if x[0].startswith("rewake") and x[1] == mid])

    def test_owed_clears_when_the_reply_to_marks_it_read_and_answers_it(self):
        self.ready()
        mid = self.send(kind="task")["nudge"]["msg_id"]
        st = self.h.state()
        self.assertIn(mid, D.owed_replies(st, self.sec))
        self.call("harness_send", agent=self.sec, to=self.plain, body="done", subject="r", kind="result", reply_to=mid)
        self.assertNotIn(mid, D.owed_replies(self.h.state(), self.sec))


for _n in [n for n in dir(F.Fixes) if n.startswith("test_")]:
    setattr(Item45, _n, None)


if __name__ == "__main__":
    unittest.main()
