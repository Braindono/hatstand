"""cc 0.24.0 item 8 (scope A-b2950; curator spec 2026-11-10_cc024-gaps-checks-build-spec.md v2.1): notify wording and expiry.
8.1 "+N more notifications"; 8.2 a queued row expires only when the secretary's digest listed it (notify.listed) AND it is over a day old;
8.3 the dropped line names kind and thread, shown once. Each test but the guards fails on 0.23.0.
Run: python3 -B tests/test_c240_item8.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _env  # noqa: F401  isolate HOME and HARNESS_* first
import calendar, unittest

import test_c210_notify as T
from test_c210_notify import H, M, N, NOON, MIN

HOUR, DAY = 60 * MIN, 24 * 60 * MIN
FRI_EVENING = calendar.timegm((2026, 11, 6, 19, 0, 0))     # a Friday


class Item8(T.Base):
    def setUp(self):
        super().setUp()
        self.h.role_define("operator", "secretary", "harness-ops", carry="none")
        self.sec = self.h.register(project="harness-ops", model=T.MODEL, task="s", role="secretary")["id"]
        self.cfg(quiet="off", dedupe_minutes=0)

    def ids(self, now):
        return [x["id"] for x in N.undelivered(self.h, now)]

    def listed(self, who, ids):
        return M.call(self.h, "harness_admin", {"op": "notify_listed", "agent": who, "args": {"ids": ids}})

    def digest(self):
        return M.call(self.h, "harness_admin", {"op": "notify_undelivered", "agent": self.sec, "args": {}})

    # 8.1
    def test_extra_count_reads_more_notifications(self):
        self.assertTrue(N.build_text("ENVOY", "operator", {"ref": "m-1"}, extra=3).endswith("+3 more notifications"))
        self.assertNotIn("more", N.build_text("ENVOY", "operator", {"ref": "m-1"}))

    # 8.2: never listed: still offered, however old (Friday-evening case)
    def test_a_row_never_listed_is_offered_after_25_hours_and_after_a_sync_line(self):
        d = N.decide(self.h, self.trig(thread="t-fri"), FRI_EVENING)
        M.call(self.h, "harness_sync", {"agent": self.b})                             # a sync line shown to another agent on Saturday
        M.call(self.h, "harness_sync", {"agent": self.sec})
        self.assertEqual(self.events("notify.listed"), [])
        self.assertIn(d["id"], self.ids(FRI_EVENING + 25 * HOUR))
        self.assertIn(d["id"], self.ids(FRI_EVENING + 62 * HOUR))                     # the Monday digest still carries it

    def test_a_row_listed_and_over_a_day_old_is_dropped_on_the_next_call(self):
        d = N.decide(self.h, self.trig(thread="t-1"), NOON)
        self.assertIn(d["id"], self.ids(NOON + 2 * HOUR))
        r = self.listed(self.sec, [d["id"]])
        self.assertEqual(r["listed"], [d["id"]])
        self.assertIn(d["id"], self.ids(NOON + 23 * HOUR))                            # listed, 23 hours old: still offered
        self.assertNotIn(d["id"], self.ids(NOON + 25 * HOUR))                         # listed, over a day old: dropped
        self.assertEqual(len(self.events("notify.queued")), 1)                        # nothing deleted

    def test_a_listed_expired_row_is_not_batched_into_a_new_count(self):
        self.cfg(quiet="22:00-07:00")
        held = N.decide(self.h, self.trig(thread="t-1"), calendar.timegm((2026, 11, 2, 23, 0, 0)))
        self.assertEqual(held["state"], "hold")
        self.listed(self.sec, [held["id"]])
        nxt = N.decide(self.h, self.trig(thread="t-2"), calendar.timegm((2026, 11, 4, 9, 0, 0)))   # 34 hours later
        self.assertEqual(nxt["batch"], [])
        self.assertNotIn("more", nxt["text"])

    def test_guard_an_unlisted_held_row_still_rides_the_next_push(self):
        self.cfg(quiet="22:00-07:00")
        held = N.decide(self.h, self.trig(thread="t-1"), calendar.timegm((2026, 11, 2, 23, 0, 0)))
        nxt = N.decide(self.h, self.trig(thread="t-2"), calendar.timegm((2026, 11, 4, 9, 0, 0)))
        self.assertEqual(nxt["batch"], [held["id"]])
        self.assertIn("+1 more notifications", nxt["text"])

    def test_only_the_secretary_may_list_and_each_row_is_written_once(self):
        d = N.decide(self.h, self.trig(thread="t-9"), NOON)
        with self.assertRaisesRegex(H.HarnessError, "only the role secretary"):
            self.listed(self.a, [d["id"]])
        self.assertEqual(self.events("notify.listed"), [])
        self.assertIn(d["id"], self.ids(NOON + 25 * HOUR))                            # refused: not listed, still offered
        with T.mock.patch.object(N.time, "time", return_value=NOON + HOUR):          # before the row could expire
            self.listed(self.sec, [d["id"]])
            again = self.listed(self.sec, [d["id"], "n-zzzzz"])
        self.assertEqual(again["listed"], [])
        self.assertEqual(again["unknown"], ["n-zzzzz"])
        self.assertEqual(len(self.events("notify.listed")), 1)
        self.assertEqual(self.events("notify.listed")[0]["data"]["by"], self.sec)

    def test_approval_rows_keep_their_own_expiry(self):
        ap = N.decide(self.h, self.trig(kind="approval", thread=None, ref="A-x1",
                                        approval={"id": "A-x1", "action": "case_close", "expires": None}), NOON)
        timed = N.decide(self.h, self.trig(kind="approval", thread=None, ref="A-x2",
                                           approval={"id": "A-x2", "action": "export", "expires": NOON + 2 * HOUR}), NOON)
        self.listed(self.sec, [ap["id"], timed["id"]])
        later = self.ids(NOON + 26 * HOUR)
        self.assertIn(ap["id"], later)                                                 # listed and old, but an approval: not dropped
        self.assertNotIn(timed["id"], later)                                           # its own expiry, as before

    # 8.3
    def test_the_dropped_line_names_kind_and_thread_and_is_shown_once(self):
        d1 = N.decide(self.h, self.trig(thread="t-aaa"), NOON)
        d2 = N.decide(self.h, self.trig(kind="result", thread="t-bbb", ref="m-2"), NOON)
        self.listed(self.sec, [d1["id"], d2["id"]])
        line, ids = N.dropped(self.h, NOON + 25 * HOUR)
        self.assertEqual(line, "dropped (listed, over a day old): operator t-aaa, result t-bbb")
        self.assertEqual(ids, [d1["id"], d2["id"]])
        r = self.listed(self.sec, [])                                                  # the next digest records that it carried the line
        self.assertEqual(r["dropped"], [d1["id"], d2["id"]])
        self.assertEqual(N.dropped(self.h, NOON + 26 * HOUR), (None, []))               # shown once

    def test_the_digest_reader_carries_the_dropped_line_and_writes_nothing(self):
        d = N.decide(self.h, self.trig(thread="t-ccc"), calendar.timegm((2026, 11, 9, 8, 0, 0)))
        self.listed(self.sec, [d["id"]])
        n = len(self.h.store.read_all())
        with T.mock.patch.object(N.time, "time", return_value=calendar.timegm((2026, 11, 10, 9, 0, 0))):
            out = self.digest()
        self.assertIn("dropped (listed, over a day old): operator t-ccc", out["text"])
        self.assertEqual(out["dropped"], [d["id"]])
        self.assertEqual(len(self.h.store.read_all()), n)                              # read-only (critic D2)


if __name__ == "__main__":
    unittest.main()
