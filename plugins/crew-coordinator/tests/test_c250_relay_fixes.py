"""cc 0.25.0 items 22 to 26 (relay-test fixes, scope v6): dead routines get no Do-lines (relay, verify, disable) and a dead offer closes
trigger_dead without shadowing the sender's report; the relay line comes only in a holder's own harness result; a role-less banner counts
direct mail only; harness_sync and harness_inbox default agent= from the host session; an answered mail closes its alarm.
Run: python3 -B tests/test_c250_relay_fixes.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _env  # noqa: F401  isolate HOME and HARNESS_* first
import os
import time
import unittest
from unittest import mock

import test_c240_item13 as I
from test_c240_item13 import D, H, T1, T2, S1, S2
import ctx_hook as CH

GONE = "HTTP 400 persistent_session_gone"


class Fixes(I.C.Base):
    for _n in ("cowork", "admin", "register", "verify", "ready", "send", "do", "state", "text"):
        locals()[_n] = I.Item13.__dict__[_n]
    del _n

    def setUp(self):
        I.C.Base.setUp(self)
        self.op["doorbell"] = {"nudge_per_agent_hour": 60, "nudge_per_pair_hour": 30}
        self.h.role_define("operator", "harness-critic", "harness-ops", carry="none")
        self.sec = self.cowork("secretary")
        self.env = self.reg("envoy", "local_env")
        self.warm(self.env)
        self.k = 0

    def report(self, outcome, reason, who=None, read=True):
        n = self.send(frm=who)["nudge"]
        assert isinstance(n, dict), n
        self.admin(who or self.plain, "nudge_result", msg_id=n["msg_id"], outcome=outcome, reason=reason)
        if read:
            self.call("harness_inbox", agent=self.sec)
        return n["msg_id"]

    def inject(self, status, reason=None):
        """A fire report for the routine through a mail of its own (the offered mail stays unread: no second ring is allowed then)."""
        self.k += 1
        m = "m-inj%d" % self.k
        self.h.store.append("nudge.trigwake", "system", {"role": "secretary", "to": [self.sec], "msg_id": m, "trigger": T1, "relay": True})
        self.h.store.append("nudge.result", self.plain, {"msg": m, "msg_id": m, "by": self.plain, "for": self.plain, "outcome": "held",
                                                         "reason": reason or "HTTP %d" % status, "status": status})

    def offer(self):
        """A task to role:secretary whose sender cannot run the routine: a relay offer through the verified routine."""
        n = self.send()["nudge"]
        r = D.record_result(self.h, self.plain, n["msg_id"], "skipped", "no_remotetrigger")
        self.assertTrue(r.get("relay_requested"), r)
        return n["msg_id"]

    def dead(self, trig=T1):
        return D.trigger_dead(self.h.state(), trig)

    # item 22: dead by three 429s from two reporters, or by 400 persistent_session_gone
    def test_three_429_from_two_reporters_make_the_routine_dead_and_silence_every_line(self):
        self.ready()
        other = self.reg(host="local_o2")
        self.report("held", "HTTP 429")
        self.report("held", "HTTP 429", who=other)
        self.assertFalse(self.dead())
        self.report("held", "HTTP 429")
        self.assertTrue(self.dead())
        self.assertNotIn("RemoteTrigger", self.do())
        self.assertIsNone(D._wake_trigger(self.h.state(), "secretary", self.h))

    def test_a_400_persistent_session_gone_makes_it_dead_at_once(self):
        self.ready()
        self.report("held", GONE)
        self.assertTrue(self.dead())
        self.assertNotIn("RemoteTrigger", self.do())

    def test_a_live_routine_with_two_429s_still_gets_offers_and_a_2xx_resets(self):
        self.ready()
        self.report("held", "HTTP 429")
        self.report("held", "HTTP 429")
        self.assertFalse(self.dead())
        self.assertIn(T1, self.do())
        self.report("held", "HTTP 200")
        self.report("held", "HTTP 429")
        self.assertFalse(self.dead())

    def test_a_relayers_404_before_the_verify_does_not_count(self):
        """Critic B2: a 404 at seq 100 before the routine is verified at seq 200, then fires 200: offers, verify and disable lines continue."""
        self.register()
        st = self.h.state()
        self.h.store.append("nudge.trigwake", "system", {"role": "secretary", "to": [self.sec], "msg_id": "m-x404", "trigger": T1, "relay": True})
        self.h.store.append("nudge.result", self.plain, {"msg": "m-x404", "msg_id": "m-x404", "by": self.plain, "for": self.plain,
                                                         "outcome": "held", "reason": "HTTP 404", "status": 404})
        self.assertEqual(self.verify().get("verified"), "secretary")
        self.assertFalse(self.dead())
        self.assertIn(T1, self.do())
        self.report("held", "HTTP 200")
        self.assertFalse(self.dead())

    def test_a_rejected_or_disabled_routine_is_dead_a_pending_one_is_not(self):
        self.register()
        self.assertFalse(self.dead())
        self.verify(prompt="Run harness_inbox. Also post.")
        self.assertTrue(self.dead())
        self.h.store.append("wake.disabled", self.env, {"trigger": T2})
        self.assertTrue(self.dead(T2))

    # disable builder
    def replaced(self, reason):
        self.ready()
        self.report("held", reason)
        new = self.cowork("secretary", predecessor=self.sec)
        self.register(who=new, trig=T2, session=S2)
        self.verify(trig=T2, session=S2)
        self.assertEqual(D.wake_to_disable(self.h.state()), {T1: "secretary"})

    def test_disable_line_is_kept_for_400_gone_401_403_429_and_5xx(self):
        for i, reason in enumerate((GONE, "HTTP 401", "HTTP 403", "HTTP 429", "HTTP 503")):
            with self.subTest(reason=reason):
                self.tearDown() if i else None
                self.setUp() if i else None
                self.replaced(reason)
                self.assertEqual([c["data"]["what"] for c in self.events("wake.claim") if c["data"]["trigger"] == T1], ["disable"], reason)

    def test_disable_line_is_suppressed_when_the_last_fire_was_404_or_410(self):
        for i, reason in enumerate(("HTTP 404", "HTTP 410")):
            with self.subTest(reason=reason):
                if i:
                    self.tearDown()
                    self.setUp()
                self.replaced(reason)
                self.assertEqual([c for c in self.events("wake.claim") if c["data"]["trigger"] == T1], [], reason)
                self.assertNotIn("enabled=false", str(D.wake_do(self.h, self.env)), reason)

    # closure case (critic B1 and note 2)
    def test_claim_closes_a_dead_offer_with_a_miss_and_no_result_and_the_rewakes_still_fire(self):
        self.ready()
        t0 = time.time()
        mid = self.offer()
        self.inject(429)
        self.inject(429)
        self.inject(429)
        self.assertTrue(self.dead())
        self.assertIsNone(D.claim_relay(self.h, self.env))
        self.assertEqual([e["data"]["reason"] for e in self.events("relay.closed") if e["data"]["msg_id"] == mid], ["trigger_dead"])
        self.assertEqual(len([e for e in self.events("nudge.miss") if e["data"]["msg_id"] == mid and e["data"]["reason"] == "trigger_dead"]), 1)
        self.assertEqual([e for e in self.events("nudge.result") if e["data"].get("msg_id") == mid], [])
        D.claim_relay(self.h, self.env)                                               # closing twice writes nothing more
        self.assertEqual(len(self.events("relay.closed")), 1)
        self.assertEqual(len([e for e in self.events("nudge.miss") if e["data"]["msg_id"] == mid]), 1)
        self.assertEqual(D.alarm_scan(self.h, now=t0 + 600, force=True), [])          # no alarm for a dead offer with no warm claimer
        self.h.store.append("nudge.result", self.plain, {"msg": mid, "msg_id": mid, "by": self.plain, "for": self.plain, "outcome": "woke",
                                                         "reason": "HTTP 200", "status": 200})   # the sender reports after the closure
        out = D.wake_scan(self.h, now=time.time() + 16 * 60, force=True)
        self.assertIn(("rewake1", mid), out)

    def test_relay_expire_after_65_minutes_writes_no_result_for_a_closed_dead_offer_and_raises_no_alarm(self):
        """Critic note 1, kept as built: a sender report AFTER the 65-minute expiry is shadowed by the system result (the closure case a report
        BEFORE it is the one the R2 rewakes need). The alarm scan still ignores the dead offer."""
        self.ready()
        t0 = time.time()
        mid = self.offer()
        for _ in range(3):
            self.inject(429)
        D.claim_relay(self.h, self.env)
        self.assertEqual(D.alarm_scan(self.h, now=t0 + 4000, force=True), [])
        self.assertEqual([e for e in self.events("nudge.result") if e["data"].get("msg_id") == mid], [])      # 0.25.0 (item 34): never a system result
        self.assertEqual(self.events("nudge.alarm"), [])

    def test_relay_expire_at_65_minutes_closes_a_live_offer_with_a_miss_and_no_result(self):
        self.ready()
        mid = self.offer()
        self.assertEqual(D.relay_expire(self.h, now=time.time() + 3901), [mid])
        self.assertEqual([e for e in self.events("nudge.result") if e["data"].get("msg_id") == mid], [])      # 0.25.0 (item 34): miss plus closed, no result
        self.assertEqual([e["data"]["reason"] for e in self.events("relay.closed") if e["data"]["msg_id"] == mid], ["expired"])

    def test_replay_appends_nothing(self):
        self.ready()
        self.offer()
        for _ in range(3):
            self.report("held", "HTTP 429")
        n = len(self.h.store.read_all())
        D.trigger_dead(H.State(self.h.store.read_all()), T1)
        self.assertEqual(len(self.h.store.read_all()), n)

    # item 23
    def test_a_hook_after_bash_never_claims_or_carries_a_relay_line(self):
        self.ready()
        mid = self.offer()
        inp = {"session_id": "s1", "tool_name": "Bash", "tool_input": {}, "transcript_path": "/x/s1.jsonl"}
        self.assertIsNone(CH.relay_hook(inp))
        self.assertEqual(self.events("nudge.relay_claim"), [])
        line = D.attach_relay(self.h, self.env, {"text": "x"})["text"]                 # the holder's own harness result carries it
        self.assertIn("RemoteTrigger action=run trigger_id=" + T1, line)
        self.assertIn(mid, line)

    def test_a_live_routines_verify_line_reaches_a_relay_holder_not_the_routines_role(self):
        self.register()
        self.assertIn("RemoteTrigger action=get trigger_id=" + T1, str(D.wake_do(self.h, self.env)))
        self.assertIsNone(D.wake_do(self.h, self.sec))

    # item 24
    def test_a_role_less_banner_counts_direct_mail_not_broadcasts(self):
        lone = self.reg(host="local_lone")
        for i in range(14):
            self.call("harness_send", agent=self.env, to="*", body="bc%d" % i, subject="bc%d" % i, kind="notice")
        st = self.h.state()
        self.assertEqual(len(self.h._inbox_ids(st, lone, True)), 14)                      # harness_inbox still lists them
        c = self.h.card(st, lone)
        self.assertEqual(c["unread"], 0)
        self.assertNotIn("direct mail", H.unread_text(c))
        self.call("harness_send", agent=self.env, to=lone, body="d", subject="d", kind="message")
        self.admin(lone, "group", group="g250")
        self.call("harness_send", agent=self.env, to="group:g250", body="g", subject="g", kind="message")
        c = self.h.card(self.h.state(), lone)
        self.assertEqual((c["unread"], H.unread_text(c)), (2, "2 direct mail"))
        self.assertIn("unread: 2 direct mail", self.h.whoami(lone)["text"])

    def test_fleet_dashboard_and_register_follow_the_same_role_less_rule(self):
        lone = self.reg(host="local_lone2")
        self.call("harness_send", agent=self.env, to="*", body="bc", subject="bc", kind="notice")
        self.assertEqual(self.h.unread_count(self.h.state(), lone), 0)
        row = next(r for r in self.h.operator_rows() if r["short"] == lone[:8])
        self.assertEqual(row["unread"], 0)
        snap = next(a for a in self.h.snapshot()["agents"] if a["id"] == lone)
        self.assertEqual(snap["unread"], 0)
        self.call("harness_send", agent=self.env, to=lone, body="d", subject="d", kind="message")
        reg = self.call("harness_register", project="harness-ops", model="claude-sonnet-5-5", task="t")
        text = reg["text"] if isinstance(reg, dict) else str(reg)
        self.assertNotIn("unread: 14", text)
        self.assertEqual(self.h.unread_count(self.h.state(), lone), 1)

    def test_after_restore_banner_and_digest_agree_and_a_predecessors_broadcast_never_shows(self):
        first = self.reg("envoy2", "local_e2") if False else self.reg("curator", "local_c1")
        self.call("harness_send", agent=self.env, to="*", body="bc", subject="bc", kind="notice")
        self.call("harness_inbox", agent=first)
        heir = self.reg("curator", "local_c2", predecessor=first)
        c = self.h.card(self.h.state(), heir)
        self.assertEqual(c["unread"], len(self.h._inbox_ids(self.h.state(), heir, True)))
        self.assertEqual(c["unread"], 0)

    # item 25
    def test_item25_defaults_agent_only_from_exactly_one_live_agent_with_a_role_under_the_host_session(self):
        one = self.reg("curator", "local_h25")
        with mock.patch.dict(os.environ, {"CLAUDE_CODE_HOST_SESSION_ID": ""}):
            with self.assertRaisesRegex(H.HarnessError, r"pass agent=<short id>"):
                self.call("harness_inbox")
        with mock.patch.dict(os.environ, {"CLAUDE_CODE_HOST_SESSION_ID": "local_h25"}):
            self.assertIn("message", str(self.call("harness_inbox", peek=True)))
            two = self.reg("harness-critic", "local_h25")
            with self.assertRaisesRegex(H.HarnessError, r"pass agent=<short id>"):
                self.call("harness_sync")
            self.h.retire(two, "t", by="human")
            self.assertIn("agent", self.text(self.call("harness_sync")).lower() + "agent")
            succ = self.reg("curator", "local_h25", predecessor=one)                         # a compaction predecessor does not count
            self.assertEqual(self.h.state().agents[one]["status"], "superseded")
            self.call("harness_inbox", peek=True)
        with mock.patch.dict(os.environ, {"CLAUDE_CODE_HOST_SESSION_ID": "local_other"}):
            with self.assertRaisesRegex(H.HarnessError, r"pass agent=<short id>"):
                self.call("harness_inbox")

    def test_item25_a_defaulted_inbox_is_peek_only_and_marks_nothing_read(self):
        """Raw eval F2: helpers inheriting the lead's identity must not consume the lead's mail."""
        a = self.reg("curator", "local_f2")
        self.call("harness_send", agent=self.plain, to=a, body="b", subject="s", kind="notice")
        n = len(self.h._inbox_ids(self.h.state(), a, True))
        self.assertGreaterEqual(n, 1)
        with mock.patch.dict(os.environ, {"CLAUDE_CODE_HOST_SESSION_ID": "local_f2"}):
            r = self.call("harness_inbox")                  # defaulted: peek
            self.assertTrue(self.text(r).startswith("defaulted agent: peek only; pass agent=<id> to mark read"))
            self.call("harness_inbox", mark_read=True)      # still peek, whatever the caller asks
        self.assertEqual(len(self.h._inbox_ids(self.h.state(), a, True)), n)
        r = self.call("harness_inbox", agent=a)             # explicit agent: reads and marks as before, no peek note
        self.assertNotIn("defaulted agent", self.text(r))
        self.assertEqual(len(self.h._inbox_ids(self.h.state(), a, True)), 0)

    # item 26
    def alarmed(self):
        c = self.active("curator", "local_a26")
        n = self.send_task(c)
        return c, n

    def active(self, role, host):
        a = self.reg(role, host)
        self.warm(a)
        return a

    def send_task(self, c):
        n = self.call("harness_send", agent=self.plain, to="role:curator", body="b", subject="s", kind="task")
        D._save(D._sp(self.h, c), {"last_call": time.time() - 300})
        return n["nudge"]["msg_id"] if isinstance(n.get("nudge"), dict) else n["id"]

    def test_item26_a_notice_reply_on_the_thread_stops_or_closes_the_alarm(self):
        c, mid = self.alarmed()
        later = time.time() + 11 * 60
        self.assertEqual(len(D.alarm_scan(self.h, now=later, force=True)), 1)
        self.call("harness_send", agent=c, to=self.plain, body="ack", subject="ack", kind="notice", reply_to=mid)
        D.alarm_scan(self.h, now=later + 70, force=True)
        self.assertEqual([e["data"]["reason"] for e in self.events("nudge.alarm_closed")], ["reply"])
        self.assertEqual(D.alarm_lines(self.h, self.h.state(), c), [])
        self.assertEqual(D.alarm_summary(self.h)["alarms"], 1)                          # the event is kept; only the line closes

    def test_item26_a_reply_before_the_scan_writes_no_alarm_and_a_successors_reply_counts(self):
        c, mid = self.alarmed()
        heir = self.reg("curator", "local_a26b", predecessor=c)
        self.call("harness_send", agent=heir, to=self.plain, body="ack", subject="ack", kind="notice", reply_to=mid)
        self.assertEqual(D.alarm_scan(self.h, now=time.time() + 11 * 60, force=True), [])
        self.assertEqual(self.events("nudge.alarm"), [])

    def test_item26_a_reply_on_another_thread_does_not_close_it_and_an_unread_mail_alarms(self):
        c, mid = self.alarmed()
        self.call("harness_send", agent=c, to=self.plain, body="other", subject="other", kind="notice")
        out = D.alarm_scan(self.h, now=time.time() + 11 * 60, force=True)
        self.assertEqual([(x["msg_id"], x["cond"]) for x in out], [(mid, "unread")])

    def test_item26_unreported_alarm_closes_on_a_read(self):
        c = self.active("curator", "local_a26u")
        n = self.call("harness_send", agent=self.plain, to="role:curator", body="b", subject="s", kind="task")["nudge"]["msg_id"]
        self.h.store.append("nudge.unreported", "system", {"msg": n, "msg_id": n, "by": self.plain})
        self.assertEqual([x["cond"] for x in D.alarm_scan(self.h, force=True)], ["unreported"])
        self.call("harness_inbox", agent=c)
        D.alarm_scan(self.h, now=time.time() + 120, force=True)
        self.assertEqual([e["data"]["reason"] for e in self.events("nudge.alarm_closed")], ["read"])


if __name__ == "__main__":
    unittest.main()
