"""cc 0.26.0 fix round 4: (a) a truncated recall never marks a cut mail read; (b) a ref only counts as waiting while the ask is still open;
addendum: a recipient's own nudge_result (to=) does not hide another recipient's skip from the unreported, expiry, alarm and wake-block readers.
Run: python3 -B tests/test_c260_round4.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _env  # noqa: F401  isolate HOME and HARNESS_* first
import os
import tempfile
import time
import unittest
from unittest import mock

import test_c250_relay_fixes as F
from test_c250_relay_fixes import D, H
import mcp_server as M

MODEL = "claude-sonnet-5-5"


class RecallRead(unittest.TestCase):
    def setUp(self):
        self.home = os.path.join(tempfile.mkdtemp(), "h")
        os.makedirs(self.home)
        self.h = H.Harness(self.home)
        self.a = self.h.register(project="orch", model=MODEL, session_id="s-a")["id"]
        self.b = self.h.register(project="orch", model=MODEL, session_id="s-b")["id"]

    def unread(self):
        return self.h.inbox(self.b, mark_read=False)["ids"]

    def recall(self, mid, **kw):
        M.BOUND.update(home=None, id=None)
        r = M.call(self.h, "harness_recall", dict({"ids": [mid], "agent": self.b}, **kw))
        return r["text"] if isinstance(r, dict) else str(r)

    def long(self):
        body = "\n".join("line %04d of a long report" % i for i in range(650)) + "\nLAST LINE QQQ"      # about 19k characters
        self.assertGreater(len(body), 17000)
        mid = self.h.send(self.a, self.b, body, kind="notice")["id"]
        self.h.inbox(self.b)                                                              # cut: stays unread
        self.assertEqual(self.unread(), [mid])
        return mid

    def test_a_truncated_recall_does_not_mark_the_mail_read_and_the_note_names_budget(self):
        mid = self.long()
        t = self.recall(mid)                                                              # the default budget: head and tail only
        self.assertIn("[truncated", t)
        self.assertIn("raise budget=", t)
        self.assertEqual(self.unread(), [mid])

    def test_a_recall_with_enough_budget_returns_the_whole_text_and_marks_it_read(self):
        mid = self.long()
        t = self.recall(mid, budget=6000)
        self.assertNotIn("[truncated", t)
        self.assertIn("LAST LINE QQQ", t)
        self.assertIn("line 0000 of", t)
        self.assertEqual(self.unread(), [])

    def test_a_short_mail_is_still_read_by_a_default_recall(self):
        mid = self.h.send(self.a, self.b, "word " * 300, kind="notice")["id"]
        self.h.inbox(self.b)
        self.assertEqual(self.unread(), [mid])
        self.recall(mid)
        self.assertEqual(self.unread(), [])


class WaitingByRef(F.Fixes):
    def curator(self, host):
        if "curator" not in self.h.state().roles:
            self.h.role_define("operator", "curator", "harness-ops", carry="none")
        c = self.reg("curator", host)
        return c

    def test_an_open_ask_cited_by_ref_is_waiting(self):
        c = self.curator("local_w1")
        q = self.h.send(c, self.plain, "q?", kind="question")["id"]
        r = self.h.send(self.plain, c, "a", kind="result", refs=[q])["id"]
        st = self.h.state()
        self.assertTrue(D._waiting(st, st.messages[r], c))

    def test_an_old_answered_ask_cited_by_ref_is_not_waiting(self):
        c = self.curator("local_w2")
        q = self.h.send(c, self.plain, "q?", kind="question")["id"]
        self.h.send(self.plain, c, "answer", kind="result", reply_to=q)                  # answered on the thread (a result closes it)
        r = self.h.send(self.plain, c, "weeks later", kind="result", refs=[q])["id"]
        st = self.h.state()
        self.assertFalse(D._waiting(st, st.messages[r], c))

    def test_an_ask_answered_by_a_ref_on_another_thread_is_not_open_either(self):
        c = self.curator("local_w3")
        q = self.h.send(c, self.plain, "q?", kind="question")["id"]
        self.h.send(self.plain, c, "answer", kind="result", refs=[q])                    # the first answer, by ref
        r = self.h.send(self.plain, c, "again", kind="result", refs=[q])["id"]
        st = self.h.state()
        self.assertFalse(D._waiting(st, st.messages[r], c))

    def test_a_finished_task_cited_by_ref_is_not_waiting(self):
        c = self.curator("local_w4")
        t = self.h.send(c, self.plain, "do x", kind="task")["id"]
        self.h.task_update(self.plain, t, "completed", note="done: proof")
        r = self.h.send(self.plain, c, "late", kind="result", refs=[t])["id"]
        st = self.h.state()
        self.assertFalse(D._waiting(st, st.messages[r], c))

    def test_an_answered_reply_to_ask_does_not_ring_a_cold_holder(self):
        self.ready()
        c = self.curator("local_w5")
        q = self.call("harness_send", agent=c, to=self.plain, body="q?", subject="q", kind="question")["id"]
        self.call("harness_send", agent=self.plain, to="role:curator", body="answer", subject="a", kind="result", reply_to=q)
        D._save(D._sp(self.h, c), {"last_call": time.time() - 4000})                      # cold
        r = self.call("harness_send", agent=self.plain, to="role:curator", body="old news", subject="re", kind="result", refs=[q])
        self.assertFalse(isinstance(r.get("nudge"), dict), r.get("nudge"))              # mail only: the ask was answered long ago


for _n in [n for n in dir(F.Fixes) if n.startswith("test_")]:
    setattr(WaitingByRef, _n, None)


class PerRecipientReaders(F.Fixes):
    def two(self):
        self.ready()
        self.h.role_define("operator", "ops-coder", "harness-ops", carry="none")
        if "curator" not in self.h.state().roles:
            self.h.role_define("operator", "curator", "harness-ops", carry="none")
        a = self.reg("curator", "local_rd_a")
        b = self.reg("ops-coder", "local_rd_b")
        self.warm(a)
        self.warm(b)
        r = self.call("harness_send", agent=self.plain, to=["role:curator", "role:ops-coder"], body="b", subject="s", kind="task")
        return a, b, r["nudge"]["msg_id"]

    def events(self, t):
        return [e for e in self.h.store.read_all() if e["type"] == t]

    def test_the_first_recipients_delivery_is_not_a_whole_result_for_the_scans(self):
        a, b, mid = self.two()
        self.admin(self.plain, "nudge_result", msg_id=mid, outcome="delivered", reason="", to="local_rd_a")
        evs = self.h.store.read_all()
        self.assertNotIn(mid, D._first_results(evs))                                       # the wake block does not take it for the whole send
        self.assertNotIn(mid, D._results(self.h))                                          # the expiry, read-close and notice scans keep the message open
        self.admin(self.plain, "nudge_result", msg_id=mid, outcome="delivered", reason="", to="local_rd_b")
        evs = self.h.store.read_all()
        self.assertIn(mid, D._first_results(evs))                                          # every recipient reported: now it is a result
        self.assertIn(mid, D._results(self.h))

    def test_a_whole_report_without_to_is_unchanged(self):
        a, b, mid = self.two()
        self.admin(self.plain, "nudge_result", msg_id=mid, outcome="delivered", reason="")
        self.assertIn(mid, D._first_results(self.h.store.read_all()))
        self.assertIn(mid, D._results(self.h))

    def test_the_unreported_scan_still_flags_a_send_with_only_one_recipient_reported(self):
        a, b, mid = self.two()
        self.admin(self.plain, "nudge_result", msg_id=mid, outcome="delivered", reason="", to="local_rd_a")
        t = time.time()
        D.settle(self.h, self.plain, now=t + 1)
        D.settle(self.h, self.plain, now=t + 2)
        self.assertIn(mid, [(e["data"] or {}).get("msg_id") for e in self.events("nudge.unreported")])

    def test_the_unreported_scan_does_not_flag_a_send_every_recipient_reported(self):
        a, b, mid = self.two()
        self.admin(self.plain, "nudge_result", msg_id=mid, outcome="delivered", reason="", to="local_rd_a")
        self.admin(self.plain, "nudge_result", msg_id=mid, outcome="delivered", reason="", to="local_rd_b")
        t = time.time()
        D.settle(self.h, self.plain, now=t + 1)
        D.settle(self.h, self.plain, now=t + 2)
        self.assertNotIn(mid, [(e["data"] or {}).get("msg_id") for e in self.events("nudge.unreported")])

    def test_the_expiry_scan_closes_the_skipped_recipients_offer_and_writes_its_miss(self):
        a, b, mid = self.two()
        self.admin(self.plain, "nudge_result", msg_id=mid, outcome="delivered", reason="", to="local_rd_a")
        r = self.admin(self.plain, "nudge_result", msg_id=mid, outcome="skipped", reason="app_cap", to="local_rd_b")
        self.assertTrue(r.get("relay_requested"), r)
        D.relay_expire(self.h, now=time.time() + 4000)
        self.assertEqual([e["data"]["reason"] for e in self.events("relay.closed") if e["data"]["msg_id"] == mid], ["expired"])
        miss = [e["data"] for e in self.events("nudge.miss") if e["data"]["msg_id"] == mid]
        self.assertEqual(len(miss), 1)
        self.assertEqual(miss[0]["to"], b)                                                  # B's, not A's

    def test_the_second_recipients_own_report_closes_only_its_own_offer(self):
        a, b, mid = self.two()
        self.admin(self.plain, "nudge_result", msg_id=mid, outcome="skipped", reason="app_cap", to="local_rd_b")
        offer = [e for e in self.events("nudge.relay_offer") if e["data"]["msg_id"] == mid][-1]["data"]
        self.assertEqual(offer["to_session"], "local_rd_b")
        # A's delivery arrives later: it must not claim or close B's relay offer
        self.admin(self.plain, "nudge_result", msg_id=mid, outcome="delivered", reason="", to="local_rd_a")
        self.assertTrue(D._closes({"to_session": "local_rd_a"}, "local_rd_a"))
        self.assertFalse(D._closes({"to_session": "local_rd_a"}, "local_rd_b"))
        self.assertTrue(D._closes({}, "local_rd_b"))                                       # a whole-message result closes any offer
        D.relay_expire(self.h, now=time.time() + 4000)
        self.assertEqual(len([e for e in self.events("nudge.miss") if e["data"]["msg_id"] == mid]), 1)

    def test_the_alarm_scan_still_sees_the_unread_recipient_after_the_first_recipients_report(self):
        a, b, mid = self.two()
        D._save(D._sp(self.h, b), {"last_call": time.time() - 300})
        self.admin(self.plain, "nudge_result", msg_id=mid, outcome="delivered", reason="", to="local_rd_a")
        self.admin(self.plain, "nudge_result", msg_id=mid, outcome="skipped", reason="app_cap", to="local_rd_b")
        later = time.time() + 4000
        D.relay_expire(self.h, now=later)
        with mock.patch.object(D, "_last_activity", lambda h, st, rid: later):
            out = D.alarm_scan(self.h, now=later, force=True)
        self.assertIn(b, [x["to"] for x in out if x["msg_id"] == mid], out)            # round 7 (class A): one alarm per (message, recipient): b's is there


for _n in [n for n in dir(F.Fixes) if n.startswith("test_")]:
    setattr(PerRecipientReaders, _n, None)


if __name__ == "__main__":
    unittest.main()
