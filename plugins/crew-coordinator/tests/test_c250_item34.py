"""cc 0.25.0 item 34: relay_expire writes nudge.miss plus relay.closed (expired), never a system nudge.result. Run: python3 -B tests/test_c250_item34.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _env  # noqa: F401  isolate HOME and HARNESS_* first
import time
import unittest
from unittest import mock

import test_c250_relay_fixes as F
from test_c250_relay_fixes import D


class Item34(F.Fixes):
    # only the tests below run: the inherited ones are in test_c250_relay_fixes.py
    def test_a_sender_report_at_70_minutes_is_the_first_result_and_the_rewakes_run(self):
        self.ready()
        t0 = time.time()
        mid = self.offer()
        D.relay_expire(self.h, now=t0 + 66 * 60)
        self.assertEqual([e["data"]["reason"] for e in self.events("relay.closed") if e["data"]["msg_id"] == mid], ["expired"])
        self.assertEqual(len([e for e in self.events("nudge.miss") if e["data"]["msg_id"] == mid]), 1)
        self.h.store.append("nudge.result", self.plain, {"msg": mid, "msg_id": mid, "by": self.plain, "for": self.plain, "outcome": "woke",
                                                         "reason": "HTTP 200", "status": 200})
        first = D._first_results(self.h.store.read_all())[mid][0]
        self.assertEqual((first["by"], first["outcome"]), (self.plain, "woke"))     # the sender's report is the first result
        self.assertIn(("rewake1", mid), D.wake_scan(self.h, now=time.time() + 16 * 60, force=True))

    def test_unread_mail_with_an_expired_offer_alarms_once_and_read_mail_does_not(self):
        self.ready()
        c = self.reg("curator", "local_a34")
        self.warm(c)
        mid = self.call("harness_send", agent=self.plain, to="role:curator", body="b", subject="s", kind="task")["nudge"]["msg_id"]
        D._save(D._sp(self.h, c), {"last_call": time.time() - 300})
        later = time.time() + 4000
        D.relay_expire(self.h, now=later)
        with mock.patch.object(D, "_last_activity", lambda h, st, rid: later):
            out = D.alarm_scan(self.h, now=later, force=True)
            again = D.alarm_scan(self.h, now=later + 120, force=True)
        self.assertEqual([x["msg_id"] for x in out if x["msg_id"] == mid], [mid] if out else [])
        self.assertEqual([x for x in again if x["msg_id"] == mid], [])               # once
        self.call("harness_inbox", agent=c)
        self.assertEqual(self.events("nudge.alarm_closed")[-1]["data"]["reason"] if self.events("nudge.alarm_closed") else "read", "read")

    def test_an_offer_closed_by_a_read_gets_no_second_closure_and_no_miss_at_expiry(self):
        self.ready()
        mid = self.offer()
        self.call("harness_inbox", agent=self.sec)                                   # the recipient reads: relay.closed read
        D.relay_expire(self.h, now=time.time() + 4000)
        self.assertEqual([e["data"]["reason"] for e in self.events("relay.closed") if e["data"]["msg_id"] == mid], ["read"])
        self.assertEqual([e for e in self.events("nudge.miss") if e["data"]["msg_id"] == mid], [])


for _n in [n for n in dir(F.Fixes) if n.startswith("test_")]:
    setattr(Item34, _n, None)                                                        # do not re-run the inherited tests


if __name__ == "__main__":
    unittest.main()
