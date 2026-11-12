"""cc 0.24.0 item 16 (scope A-b2950; relay-wake spec 2026-11-10_cc024-relay-wake-spec.md v3.2, section 5, tests M1-M2): wake.measure on the
first read of a rung or woken mail, and the weekly report's wake section (per-direction read times and unread counts, misses, relay pairs,
ctx coverage, roles handed off over 24 h). Each M test fails on 0.23.0.
Run: python3 -B tests/test_c240_item16.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _env  # noqa: F401  isolate HOME and HARNESS_* first
import contextlib, os, time, unittest
from unittest import mock

import test_c220_nudge as C
from test_c220_nudge import D, H, TRIG
import weekly_report as WR

CAPSULE = "---\nhandoff: x\n---\n# H\nRoutine handoff.\n"


class Item16(C.Base):
    def setUp(self):
        super().setUp()
        self.op["doorbell"] = {"nudge_per_agent_hour": 60, "nudge_per_pair_hour": 30}
        self.h.role_define("operator", "design-system", "harness-ops", carry="none")
        self.t0 = time.time()

    @contextlib.contextmanager
    def at(self, sec):
        with mock.patch.object(D.time, "time", return_value=self.t0 + sec):
            yield

    def cowork_secretary(self):
        with mock.patch.dict(os.environ, {"CLAUDE_CODE_HOST_SESSION_ID": ""}):
            a = self.reg("secretary", None)
        C.legacy_pin(self.h, {"secretary": C.WP("secretary")})
        return a

    def send_at(self, sec, to="role:secretary", frm=None, kind="task"):
        with self.at(sec):
            return self.send(frm or self.plain, to, kind=kind)

    def read_at(self, sec, aid):
        with self.at(sec):
            self.call("harness_inbox", agent=aid)

    def sync_at(self, sec, aid, ctx):
        with self.at(sec):
            self.call("harness_sync", agent=aid, ctx=ctx)

    def stats(self, until_sec):
        return WR.wake_stats(WR.all_events(self.home), self.t0 - 60, self.t0 + until_sec)

    # M1
    def test_m1_a_woken_cowork_task_read_14_s_after_the_fire_and_20_s_after_the_send(self):
        sec = self.cowork_secretary()
        n = self.send_at(0)["nudge"]
        with self.at(6):
            D.record_result(self.h, self.plain, n["msg_id"], "woke", "HTTP 200")
        self.read_at(20, sec)
        m = [e["data"] for e in self.events("wake.measure")]
        self.assertEqual(len(m), 1)
        self.assertEqual((m[0]["msg_id"], m[0]["direction"], m[0]["carrier"]), (n["msg_id"], "Code to Cowork", "remotetrigger"))
        self.assertEqual((m[0]["seconds_from_fire"], m[0]["seconds_from_sent"]), (14, 20))
        self.read_at(40, sec)                                                           # first read only
        self.assertEqual(len(self.events("wake.measure")), 1)

    def test_m1_inverse_mail_that_was_not_rung_or_was_skipped_is_not_measured(self):
        cur = self.reg("curator", "local_cur")
        self.warm(cur)
        n = self.send_at(0, to="role:curator")["nudge"]
        D.record_result(self.h, self.plain, n["msg_id"], "skipped", "stale_id")
        self.send_at(100, to="role:curator", kind="notice")
        self.read_at(200, cur)
        self.assertEqual(self.events("wake.measure"), [])

    def test_m1_a_relayed_ring_names_the_relay_carrier_and_a_code_direction(self):
        cur = self.reg("curator", "local_cur")
        self.warm(cur)
        n = self.send_at(0, to="role:curator")["nudge"]
        with self.at(3):
            D.record_result(self.h, self.plain, n["msg_id"], "delivered", "row")
        self.read_at(13, cur)
        m = self.events("wake.measure")[-1]["data"]
        self.assertEqual((m["direction"], m["carrier"], m["seconds_from_sent"]), ("Code to Code", "sendmessage", 13))

    def test_m1_the_ctx_delta_of_the_woken_turn_reaches_the_report(self):
        sec = self.cowork_secretary()
        self.sync_at(-30, sec, 40000)
        n = self.send_at(0)["nudge"]
        with self.at(6):
            D.record_result(self.h, self.plain, n["msg_id"], "woke", "HTTP 200")
        self.read_at(20, sec)
        self.assertEqual(self.events("wake.measure")[-1]["data"]["ctx_before"], 40000)
        self.sync_at(90, sec, 52000)
        w = self.stats(3600)["measures"]["Code to Cowork"]
        self.assertEqual((w["reads"], w["ctx_coverage"], w["median_ctx_delta"], w["median_s_from_fire"]), (1, 1.0, 12000, 14))

    # nb (critic m-a5eed50a7177): a later report or a compaction is not this turn's tokens
    def test_ctx_pairs_over_10_min_or_negative_are_dropped_and_counted(self):
        sec = self.cowork_secretary()
        for k, (after, ctx) in enumerate(((700, 90000), (60, 1000))):                # 11 min later; a compaction
            self.sync_at(k * 4000 - 30, sec, 40000)
            n = self.send_at(k * 4000)["nudge"]
            with self.at(k * 4000 + 6):
                D.record_result(self.h, self.plain, n["msg_id"], "woke", "HTTP 200")
            self.read_at(k * 4000 + 20, sec)
            self.sync_at(k * 4000 + 20 + after, sec, ctx)
        w = self.stats(3 * 3600)["measures"]["Code to Cowork"]
        self.assertEqual((w["reads"], w["ctx_coverage"], w["ctx_dropped"], w["median_ctx_delta"]), (2, 0.0, 2, None))
        self.assertIn("| Code to Cowork | 2 |", "\n".join(WR.render_wake(self.stats(3 * 3600))))

    # M2
    def test_m2_the_weekly_report_counts_unread_after_30_s_15_min_and_1_h_per_direction(self):
        cur = self.reg("curator", "local_cur")
        self.warm(cur)
        mids = [self.send_at(k * 120, to="role:curator", frm=self.reg(host="local_s%d" % k))["id"] for k in range(3)]
        with self.at(10):
            self.h.store.append("message.read", cur, {"ids": [mids[0]]})               # read 10 s after its send
        with self.at(240 + 20 * 60):
            self.h.store.append("message.read", cur, {"ids": [mids[2]]})               # read 20 min after its send
        u = self.stats(2 * 3600)["unread"]["Code to Code"]                             # mids[1] never read
        self.assertEqual(u, {"offered": 3, "30s": 2, "15min": 2, "1h": 1})
        u_early = self.stats(10 * 60)["unread"]["Code to Code"]                       # only 30 s has passed for counting
        self.assertEqual((u_early["30s"], u_early["15min"], u_early["1h"]), (2, 0, 0))

    def test_m2_misses_relay_pairs_and_the_rendered_section(self):
        cur = self.reg("curator", "local_cur")
        with self.at(5):
            self.h.store.append("nudge.miss", "system", {"msg_id": "m-000000000001", "to": cur, "from": self.plain, "reason": "capped:pair; relay cap full"})
        for k in range(16):
            with self.at(10 + k * 60):
                self.h.store.append("nudge.relay_offer", "system", {"msg_id": "m-%012d" % (k + 2), "to": cur, "to_session": "local_cur",
                                                                     "from": self.plain, "role": "agent", "reason": "sender_silent"})
        w = self.stats(3600)
        self.assertEqual(w["misses"], {"Code to Code": 1})
        pair = "%s>%s" % (self.plain[:8], cur[:8])
        self.assertEqual((w["relay_pairs"][pair], w["relay_pairs_flagged"]), (16, [pair]))
        for start in (3600 - 300, 3600 * 5 + 1800):                                   # across the hour mark, or not: the same flag
            with self.subTest(start=start):
                t0 = (int(self.t0 // 3600) * 3600) + start
                ev = [{"type": "nudge.relay_offer", "t": t0 + k * 30, "data": {"from": "a" * 8, "to": "b" * 8}} for k in range(16)]
                self.assertEqual(WR.wake_stats(ev, t0 - 10, t0 + 3600)["relay_pairs_flagged"], ["aaaaaaaa>bbbbbbbb"])
        ev = [{"type": "nudge.relay_offer", "t": self.t0 + k * 240, "data": {"from": "a" * 8, "to": "b" * 8}} for k in range(16)]
        self.assertEqual(WR.wake_stats(ev, self.t0 - 10, self.t0 + 7200)["relay_pairs_flagged"], [])    # 16 over 64 min: not flagged
        md = "\n".join(WR.render_wake(w))
        self.assertIn("## 8. Wake measures", md)
        self.assertIn("| Code to Code | 0 | 0 | 0 | 0 | 1 |", md)
        self.assertIn("- relays per sender>recipient: %s 16; over 15 in one hour: %s" % (pair, pair), md)
        self.assertIn("- handed_off over 24 h: none", md)

    # critic m-a8198b08d081, envoy m-c50eb489657a: a role that stays handed off over 24 h is listed
    def test_handed_off_over_24_h_is_listed(self):
        ds = self.reg("design-system", "local_ds")
        with self.at(0):
            self.h.handoff(ds, CAPSULE)
        self.assertEqual(self.stats(23 * 3600)["handed_off_over_24h"], [])
        g = self.stats(25 * 3600)["handed_off_over_24h"]
        self.assertEqual([x["role"] for x in g], ["design-system"])
        self.reg("design-system", "local_ds2", predecessor=ds)                         # a successor: no longer listed
        self.assertEqual(self.stats(26 * 3600)["handed_off_over_24h"], [])


if __name__ == "__main__":
    unittest.main()
