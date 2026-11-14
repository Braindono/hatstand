"""cc 0.26.0 fix round 6 (raw read 3): F1 an acknowledgement never closes an ask for the wake backstop; F2 a message that replies to an open ask rings like a
result; F3 per-recipient reports keyed for a wake-routine-only recipient; F4 harness_admin op=owed and the newest operator directive always shown; F5 an
inbox listing over the size limit leaves unshown mail unread; F6 no polling advice; F7 a cut result to a waiting asker is read once it answered; bare-path
at most once a day (test_c260_item21). Run: python3 -B tests/test_c260_round6.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _env  # noqa: F401  isolate HOME and HARNESS_* first
import os
import re
import tempfile
import time
import unittest

import test_c250_relay_fixes as F
from test_c250_relay_fixes import D, H
import mcp_server as M

HERE = os.path.dirname(os.path.abspath(__file__))
MODEL = "claude-sonnet-5-5"


class Wake(F.Fixes):
    """F1 and F2: a cold asker (curator) asked the plain agent; the plain agent replies in different ways."""

    def asker(self, host, pair_cap=None):
        if not getattr(self, "_ready_done", False):
            self.ready()
            self._ready_done = True
        if pair_cap:
            self.op["doorbell"] = {"nudge_per_agent_hour": 60, "nudge_per_pair_hour": pair_cap}
        if "curator" not in self.h.state().roles:
            self.h.role_define("operator", "curator", "harness-ops", carry="none")
        c = self.reg("curator", host)
        self.warm(c)
        q = self.call("harness_send", agent=c, to=self.plain, body="please do x", subject="ask", kind="question")["id"]
        return c, q

    def cold(self, c):
        D._save(D._sp(self.h, c), {"last_call": time.time() - 4000})

    def reply(self, kind, q, **kw):
        return self.call("harness_send", agent=self.plain, to="role:curator", body="text " + kind, subject="re", kind=kind, reply_to=q, **kw)

    def test_f1_an_ack_then_the_result_rings_a_cold_asker(self):
        c, q = self.asker("local_f1a")
        self.reply("message", q)                                                            # "on it"
        self.cold(c)
        r = self.reply("result", q)
        self.assertIsInstance(r.get("nudge"), dict, r.get("nudge"))                         # was: mail only, because the ack counted as the answer

    def test_f1_an_ack_then_a_capped_result_gets_a_relay(self):
        c, q = self.asker("local_f1b", pair_cap=1)
        self.call("harness_send", agent=self.plain, to="role:curator", body="warm up the pair cap", subject="w", kind="task")
        self.reply("message", q)
        r = self.reply("result", q)
        skipped = r.get("nudge_skipped") or []
        self.assertTrue(skipped and "pair cap" in skipped[0]["reason"], r)
        self.assertTrue(str(skipped[0].get("relay") or "").startswith(("relay requested", "miss")), skipped)

    def test_f1_only_a_result_or_handoff_closes_the_ask_and_owed_close_does_too(self):
        c, q = self.asker("local_f1c")
        st = lambda: self.h.state()
        for kind in ("message", "notice"):
            qk = self.h.send(c, self.plain, "ask by " + kind, kind="question")["id"]
            self.h.send(self.plain, c, "ack", kind=kind, reply_to=qk)
            m = self.h.send(self.plain, c, "next", kind="result", reply_to=qk)["id"]
            self.assertTrue(D._ask_open(st(), st().messages[qk], st().messages[m]), kind)      # the ack did not close it
        done = self.h.send(self.plain, c, "done", kind="result", reply_to=q)["id"]
        late = self.h.send(self.plain, c, "late", kind="result", reply_to=q)["id"]
        self.assertFalse(D._ask_open(st(), st().messages[q], st().messages[late]))            # a result did
        c2, q2 = self.asker("local_f1d")
        self.h.owed_close(self.plain, [q2])                                                    # the replier's role dismissed it
        m2 = self.h.send(self.plain, c2, "x", kind="result", reply_to=q2)["id"]
        self.assertFalse(D._ask_open(st(), st().messages[q2], st().messages[m2]))

    def test_f2_a_message_replying_to_an_open_ask_rings_a_cold_asker(self):
        c, q = self.asker("local_f2a")
        self.cold(c)
        r = self.reply("message", q)
        self.assertIsInstance(r.get("nudge"), dict, r.get("nudge"))

    def test_f2_a_notice_still_rings_nobody_and_a_message_with_no_open_ask_neither(self):
        c, q = self.asker("local_f2b")
        self.cold(c)
        self.assertFalse(isinstance(self.reply("notice", q).get("nudge"), dict))
        r = self.call("harness_send", agent=self.plain, to="role:curator", body="chat", subject="x", kind="message")
        self.assertFalse(isinstance(r.get("nudge"), dict), r.get("nudge"))

    def test_f2_a_capped_message_reply_gets_a_relay(self):
        c, q = self.asker("local_f2c", pair_cap=1)
        self.call("harness_send", agent=self.plain, to="role:curator", body="warm up the pair cap", subject="w", kind="task")
        r = self.reply("message", q)
        skipped = r.get("nudge_skipped") or []
        self.assertTrue(skipped and "pair cap" in skipped[0]["reason"], r)
        self.assertTrue(str(skipped[0].get("relay") or "").startswith(("relay requested", "miss")), skipped)


for _n in [n for n in dir(F.Fixes) if n.startswith("test_")]:
    setattr(Wake, _n, None)


class Mixed(F.Fixes):
    """F3: two recipients by session id plus the secretary by its wake routine only."""

    def three(self):
        self.ready()
        self.h.role_define("operator", "ops-coder", "harness-ops", carry="none")
        if "curator" not in self.h.state().roles:
            self.h.role_define("operator", "curator", "harness-ops", carry="none")
        a = self.reg("curator", "local_m_a")
        b = self.reg("ops-coder", "local_m_b")
        self.warm(a)
        self.warm(b)
        r = self.call("harness_send", agent=self.plain, to=["role:curator", "role:ops-coder", "role:secretary"], body="b", subject="s", kind="task")
        self.assertIsInstance(r.get("nudge"), dict, r)
        return r["nudge"]["msg_id"], r["nudge"]["do"]

    def events(self, t):
        return [e for e in self.h.store.read_all() if e["type"] == t]

    def test_f3_the_do_line_lists_a_key_for_the_wake_routine_recipient(self):
        mid, do = self.three()
        self.assertIn("local_m_a", do)
        self.assertIn(self.sec[:8], do)
        self.assertIn("One report per recipient", do)

    def test_f3_the_trigger_recipients_skip_after_the_session_recipients_delivered_asks_for_its_relay(self):    # the reviewer's probe
        mid, _ = self.three()
        self.admin(self.plain, "nudge_result", msg_id=mid, outcome="delivered", reason="", to="local_m_a")
        self.admin(self.plain, "nudge_result", msg_id=mid, outcome="delivered", reason="", to="local_m_b")
        self.assertIn(mid, [x["data"]["msg_id"] for x in self.events("nudge.result")])
        r = self.admin(self.plain, "nudge_result", msg_id=mid, outcome="skipped", reason="no_remotetrigger", to=self.sec[:8])
        self.assertTrue(r.get("relay_requested"), r)                                         # was: {'already_reported': True}
        off = [e for e in self.events("nudge.relay_offer") if e["data"]["msg_id"] == mid][-1]["data"]
        self.assertEqual(off["to"], self.sec)
        self.assertTrue(off.get("trigger"))

    def test_f3_the_message_is_not_fully_reported_until_the_trigger_recipient_has_reported(self):
        mid, _ = self.three()
        self.admin(self.plain, "nudge_result", msg_id=mid, outcome="delivered", reason="", to="local_m_a")
        self.admin(self.plain, "nudge_result", msg_id=mid, outcome="delivered", reason="", to="local_m_b")
        self.assertNotIn(mid, D._results(self.h))                                            # the third recipient is still missing
        self.admin(self.plain, "nudge_result", msg_id=mid, outcome="skipped", reason="no_remotetrigger", to=self.sec[:8])
        self.assertNotIn(mid, D._results(self.h))                                            # a relay is pending for it: still open

    def test_f3_a_whole_report_after_partial_ones_never_swallows_the_missing_recipient(self):
        mid, _ = self.three()
        self.admin(self.plain, "nudge_result", msg_id=mid, outcome="delivered", reason="", to="local_m_a")
        self.admin(self.plain, "nudge_result", msg_id=mid, outcome="delivered", reason="", to="local_m_b")
        r = self.admin(self.plain, "nudge_result", msg_id=mid, outcome="skipped", reason="no_remotetrigger")      # no `to`
        self.assertTrue(r.get("relay_requested"), r)
        self.assertNotEqual(r.get("already_reported"), True)

    def test_f3_the_reverse_order_a_whole_delivered_report_first_still_lets_a_recipient_report_app_cap(self):
        mid, _ = self.three()
        r = self.admin(self.plain, "nudge_result", msg_id=mid, outcome="delivered", reason="")
        self.assertTrue(r.get("reported"), r)
        r = self.admin(self.plain, "nudge_result", msg_id=mid, outcome="skipped", reason="app_cap", to="local_m_b")
        self.assertNotEqual(r.get("already_reported"), True, r)                              # a whole report does not block a recipient's own skip

    def test_f3_a_bad_to_is_refused_and_names_the_keys(self):
        mid, _ = self.three()
        with self.assertRaises(Exception) as cx:
            self.admin(self.plain, "nudge_result", msg_id=mid, outcome="delivered", reason="", to="local_nobody")
        self.assertIn(self.sec[:8], str(cx.exception))


for _n in [n for n in dir(F.Fixes) if n.startswith("test_")]:
    setattr(Mixed, _n, None)


class Owed(unittest.TestCase):
    def setUp(self):
        self.home = os.path.join(tempfile.mkdtemp(), "h")
        os.makedirs(self.home)
        self.h = H.Harness(self.home)
        self.a = self.h.register(project="orch", model=MODEL, session_id="s-a")["id"]
        self.b = self.h.register(project="orch", model=MODEL, session_id="s-b")["id"]

    def test_f4_a_real_op_lists_every_owed_id_and_the_footer_points_to_it(self):
        ids = [self.h.send(self.a, self.b, "agent ask %d" % i, kind="task")["id"] for i in range(7)]
        t = self.h.inbox(self.b, mark_read=False)["text"]
        self.assertIn("+2 more (harness_admin op=owed lists every id)", t)
        M.BOUND.update(home=None, id=None)
        r = M.call(self.h, "harness_admin", {"op": "owed", "agent": self.b, "args": {}})
        self.assertEqual(r["total"], 7)
        self.assertEqual([x["id"] for x in r["owed"]], ids)                                   # all seven, the two newest included
        self.assertEqual(set(r["owed"][0]) >= {"id", "from", "kind", "thread", "subject", "age"}, True)

    def test_f4_the_newest_operator_directive_always_shows_first(self):
        old = [self.h.send(self.a, self.b, "agent ask %d" % i, kind="task")["id"] for i in range(6)]
        ops = [self.h.send("operator", self.b, "operator ask %d" % i, kind="task")["id"] for i in range(3)]
        r = self.h.inbox(self.b, mark_read=False)
        self.assertEqual(r["owed"][:3], ops[::-1])                                            # newest operator ask first
        self.assertIn(ops[-1], r["text"].split("owed reply")[1].splitlines()[1])
        M.BOUND.update(home=None, id=None)
        full = M.call(self.h, "harness_admin", {"op": "owed", "agent": self.b, "args": {}})
        self.assertEqual([x["id"] for x in full["owed"]], ops[::-1] + old)

    def test_f4_the_op_is_read_only_and_limits(self):
        for i in range(5):
            self.h.send(self.a, self.b, "t%d" % i, kind="task")
        n = len(self.h.store.read_all())
        M.BOUND.update(home=None, id=None)
        r = M.call(self.h, "harness_admin", {"op": "owed", "agent": self.b, "args": {"limit": 2}})
        self.assertEqual((r["total"], len(r["owed"])), (5, 2))
        self.assertEqual(len(self.h.store.read_all()), n)


class BigInbox(unittest.TestCase):
    def setUp(self):
        self.home = os.path.join(tempfile.mkdtemp(), "h")
        os.makedirs(self.home)
        self.h = H.Harness(self.home)
        self.a = self.h.register(project="orch", model=MODEL, session_id="s-a")["id"]
        self.b = self.h.register(project="orch", model=MODEL, session_id="s-b")["id"]

    def unread(self):
        return self.h.inbox(self.b, mark_read=False, full=True)["ids"]

    def test_f5_mail_past_the_listing_limit_stays_unread_and_the_note_names_a_real_way(self):      # the reviewer's probe: four 4,000-character directives
        sent = [self.h.send(self.a, self.b, ("word " * 800)[:3990] + "END%d" % i, kind=k)["id"]
                for i, k in enumerate(("task", "handoff", "question", "task"))]
        r = self.h.inbox(self.b)
        t = r["text"]
        self.assertLess(len(t), 11000)
        self.assertNotIn("[truncated", t)                                                      # nothing is cut out of the middle
        for mid in r["ids"]:
            self.assertIn("END%d" % sent.index(mid), t)                                        # every shown mail is whole
        self.assertTrue(r["not_shown"])
        self.assertEqual(set(r["ids"]) | set(r["not_shown"]), set(sent))
        self.assertIn("harness_inbox full=true", t)
        self.assertIn("harness_recall ids=[%s" % r["not_shown"][0], t)
        self.assertEqual(set(self.unread()), set(r["not_shown"]))                              # the hidden ones are still unread
        r2 = self.h.inbox(self.b)                                                              # the next call shows the rest
        self.assertEqual(set(r["ids"]) | set(r2["ids"]), set(sent) if not r2.get("not_shown") else set(r["ids"]) | set(r2["ids"]))
        self.assertEqual(self.unread(), r2.get("not_shown", []))

    def test_f5_full_true_shows_more_in_one_listing(self):
        for i in range(4):
            self.h.send(self.a, self.b, ("word " * 800)[:3990] + "END%d" % i, kind="task")
        r = self.h.inbox(self.b, full=True)
        self.assertEqual(len(r["ids"]), 4)
        self.assertFalse(r.get("not_shown"))
        self.assertEqual(self.unread(), [])

    def test_f5_one_mail_longer_than_the_listing_is_shown_cut_and_stays_unread(self):
        mid = self.h.send(self.a, self.b, ("word " * 4000)[:19000] + "TAILEND", kind="task")["id"]
        r = self.h.inbox(self.b)
        self.assertIn("stays unread", r["text"])
        self.assertIn("harness_recall ids=", r["text"])
        self.assertEqual(self.unread(), [mid])
        r = self.h.inbox(self.b, full=True)
        self.assertIn("TAILEND", r["text"])
        self.assertEqual(self.unread(), [])

    def test_f5_a_short_inbox_is_unchanged(self):
        mid = self.h.send(self.a, self.b, "short", kind="task")["id"]
        r = self.h.inbox(self.b)
        self.assertEqual(r["ids"], [mid])
        self.assertFalse(r.get("not_shown"))
        self.assertEqual(self.unread(), [])


class Polling(unittest.TestCase):
    def test_f6_the_protocol_and_the_eval_mock_no_longer_teach_polling(self):
        root = os.path.join(HERE, "..")
        pat = open(os.path.join(root, "skills", "protocol", "references", "patterns.md"), encoding="utf-8").read()
        self.assertEqual(re.findall(r"inbox\(wait", pat), [])
        self.assertNotIn("inbox(wait", pat)
        mock = open(os.path.join(root, "evals", "mocks", "crew-coordinator", "_tools.json"), encoding="utf-8").read()
        self.assertNotIn("long-poll", mock)
        self.assertNotIn("wait=secs", mock)


class CutResult(unittest.TestCase):
    def setUp(self):
        self.home = os.path.join(tempfile.mkdtemp(), "h")
        os.makedirs(self.home)
        self.h = H.Harness(self.home)
        self.a = self.h.register(project="orch", model=MODEL, session_id="s-a")["id"]
        self.b = self.h.register(project="orch", model=MODEL, session_id="s-b")["id"]

    def unread(self):
        return self.h.inbox(self.b, mark_read=False)["ids"]

    def test_f7_a_cut_result_to_a_waiting_asker_is_read_once_the_asker_has_answered(self):
        q = self.h.send(self.b, self.a, "q?", kind="question")["id"]
        r = self.h.send(self.a, self.b, ("word " * 400)[:1497] + "QQQ", kind="result", reply_to=q)["id"]
        self.h.inbox(self.b)
        self.h.inbox(self.b)
        self.assertEqual(self.unread(), [r])                                                   # the asker is waiting and has not answered
        self.h.send(self.b, self.a, "thanks, got it", kind="message", reply_to=q)              # the asker goes on with the thread (not a reply_to the result)
        t = self.h.inbox(self.b)["text"]
        self.assertIn("harness_recall ids=[%s]" % r, t)                                        # the pointer stays
        self.assertEqual(self.unread(), [])

    def test_f7_a_reply_to_the_result_itself_marks_it_read_at_once(self):                       # 0.26.0 item 4
        q = self.h.send(self.b, self.a, "q?", kind="question")["id"]
        r = self.h.send(self.a, self.b, ("word " * 400)[:1497] + "QQQ", kind="result", reply_to=q)["id"]
        self.h.inbox(self.b)
        self.assertEqual(self.unread(), [r])
        self.h.send(self.b, self.a, "thanks", kind="message", reply_to=r)
        self.assertEqual(self.unread(), [])

    def test_f7_recalling_it_whole_is_still_a_read(self):
        q = self.h.send(self.b, self.a, "q?", kind="question")["id"]
        r = self.h.send(self.a, self.b, ("word " * 400)[:1497] + "QQQ", kind="result", reply_to=q)["id"]
        self.h.inbox(self.b)
        M.BOUND.update(home=None, id=None)
        M.call(self.h, "harness_recall", {"ids": [r], "agent": self.b})
        self.assertEqual(self.unread(), [])


if __name__ == "__main__":
    unittest.main()
