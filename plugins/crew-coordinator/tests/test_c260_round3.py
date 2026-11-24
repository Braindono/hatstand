"""cc 0.26.0 fix round 3 (second raw read F1 to F7): owed_close refuses operator mail; replies to an expects_reply ask and answers by ref get the
relay backstop; housekeeping roles are fixed in code and the envoy is held to the steward's tier; the sync cap never cuts decision cards or task
changes; one report per recipient of a multi-recipient send; the virtue notice names the step the secretary can take.
(F2 is in test_c260_item14, F3 and F4 in test_c260_item1.) Run: python3 -B tests/test_c260_round3.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _env  # noqa: F401  isolate HOME and HARNESS_* first
import json
import os
import tempfile
import time
import unittest
from unittest import mock

import test_c250_relay_fixes as F
from test_c250_relay_fixes import D, H

HERE = os.path.dirname(os.path.abspath(__file__))
MODEL = "claude-sonnet-5-5"


class OwedClose(unittest.TestCase):
    def setUp(self):
        self.home = os.path.join(tempfile.mkdtemp(), "h")
        os.makedirs(self.home)
        self.h = H.Harness(self.home)
        for r in ("lead", "coder"):
            self.h.role_define("operator", r, "orch")
        self.lead = self.reg("lead", "s-lead")
        self.c = self.reg("coder", "s-c")

    def reg(self, role, sid):
        a = self.h.register(project="orch", model=MODEL, session_id=sid)["id"]
        self.h.role_assign("operator", role, a)
        return a

    def test_f1_the_operators_task_cannot_be_dismissed_and_stays_owed(self):
        op = self.h.send("operator", "role:coder", "Do not publish until I say so.", kind="task")["id"]
        ag = self.h.send(self.lead, "role:coder", "agent ask", kind="task")["id"]
        r = self.h.owed_close(self.c, [op, ag], "not needed")
        self.assertEqual(r["closed"], [ag])
        self.assertEqual(r["refused_operator_mail"], [op])
        self.assertIn("operator", r["reason"])
        self.assertEqual(self.types("owed.closed"), 1)
        self.assertIn(op, D.owed_replies(self.h.state(), self.c))                        # still owed
        q = self.h.send("operator", "role:coder", "which one?", kind="question")["id"]
        self.assertEqual(self.h.owed_close(self.c, [q])["refused_operator_mail"], [q])
        self.assertEqual(D.open_task(self.h.state(), self.c), (1, [q]))                  # /listen still arms on his question

    def test_f1_operator_mail_of_any_kind_is_refused(self):
        m = self.h.send("operator", "role:coder", "fyi", kind="message")["id"]
        r = self.h.owed_close(self.c, [m])
        self.assertEqual(r["closed"], [])
        self.assertEqual(r["refused_operator_mail"], [m])

    def types(self, t):
        return len([e for e in self.h.store.read_all() if e.get("type") == t])


class Safety(F.Fixes):
    """F5: a reply whose nudge the harness cap skips is relayed when it answers an open ask: an expects_reply mail, or an ask on another thread by ref."""

    def asker_sends(self, **kw):
        c = self.reg("curator", "local_ask_%d" % int(time.time() * 1000 % 100000)) if False else None
        return c

    def probe(self, kind, how):
        self.ready()
        self.op["doorbell"] = dict({"nudge_per_agent_hour": 60, "nudge_per_pair_hour": 30}, nudge_per_pair_hour=1)
        if "curator" not in self.h.state().roles:
            self.h.role_define("operator", "curator", "harness-ops", carry="none")
        c = self.reg("curator", "local_f5_" + how)
        self.warm(c)
        if how == "expects_reply":
            ask = self.call("harness_send", agent=c, to=self.plain, body="please do x", subject="ask", kind="message", expects_reply=True)["id"]
            kw = dict(reply_to=ask)
        elif how == "ref":
            ask = self.call("harness_send", agent=c, to=self.plain, body="please do x", subject="ask", kind="question")["id"]
            kw = dict(refs=[ask])                                  # a new thread that only names the ask
        self.call("harness_send", agent=self.plain, to="role:curator", body="warm up the pair cap", subject="w", kind="task")
        r = self.call("harness_send", agent=self.plain, to="role:curator", body="done", subject="re", kind=kind, **kw)
        skipped = r.get("nudge_skipped") or []
        self.assertTrue(skipped and "pair cap" in skipped[0]["reason"], (how, kind, r))
        self.assertTrue(str(skipped[0].get("relay") or "").startswith(("relay requested", "miss")), (how, kind, skipped))

    def test_f5_a_result_answering_an_expects_reply_mail_is_relayed_when_capped(self):
        self.probe("result", "expects_reply")

    def test_f5_a_handoff_answering_an_expects_reply_mail_is_relayed_when_capped(self):
        self.probe("handoff", "expects_reply")

    def test_f5_a_result_answering_an_ask_by_ref_on_another_thread_is_relayed_when_capped(self):
        self.probe("result", "ref")

    def test_f5_waiting_sees_the_expects_reply_ask_and_the_ref_but_not_a_stranger(self):
        if "curator" not in self.h.state().roles:
            self.h.role_define("operator", "curator", "harness-ops", carry="none")
        c = self.reg("curator", "local_f5_w")
        ask = self.h.send(c, self.plain, "x", kind="message", expects_reply=True)["id"]
        rep = self.h.send(self.plain, c, "y", kind="result", reply_to=ask)["id"]
        st = self.h.state()
        self.assertTrue(D._waiting(st, st.messages[rep], c))
        other = self.h.send(self.plain, c, "z", kind="result")["id"]                    # a result on its own thread: nothing asked
        st = self.h.state()
        self.assertFalse(D._waiting(st, st.messages[other], c))
        q = self.h.send(c, self.plain, "q?", kind="question")["id"]
        byref = self.h.send(self.plain, c, "a", kind="result", refs=[q])["id"]
        st = self.h.state()
        self.assertNotEqual(st.messages[byref]["thread"], st.messages[q]["thread"])
        self.assertTrue(D._waiting(st, st.messages[byref], c))


for _n in [n for n in dir(F.Fixes) if n.startswith("test_")]:
    setattr(Safety, _n, None)


class Housekeeping(unittest.TestCase):
    def setUp(self):
        import test_cc151_w1 as W
        import mcp_server as M
        self.M = M
        self.t = W.Base("setUp") if False else None
        self.W = W

    def base(self, name):
        class T(self.W.Base):
            def runTest(s):
                pass
        t = T()
        t.setUp()
        self.addCleanup(t.doCleanups)
        return t

    def cfg(self, t, **kw):
        p = os.path.join(t.home, "_harness", "config.json")
        os.makedirs(os.path.dirname(p), exist_ok=True)
        json.dump(kw, open(p, "w"))

    def test_f6_the_housekeeping_role_list_in_config_is_ignored(self):
        t = self.base("a")
        self.cfg(t, housekeeping_roles=["writer-role"], curation_roles={"steward": ["archive"]})
        w = t.agent("writer-role")
        n = t.note(w)
        t.as_(w)
        self.assertIn("pending", t.adm("pin", w, ids=[n], reason='"rule line text"'))      # a role named in config gains nothing

    def test_f6_the_envoy_without_a_curation_grant_is_held_to_the_stewards_tier_and_routine_entries(self):
        t = self.base("b")
        self.cfg(t, curation_roles={"steward": ["archive"]})                                # the envoy has no grant: it takes the housekeeping path
        envoy, w, owner = t.agent("envoy"), t.agent(), t.agent("owner-role")
        outside = t.note(w)                                                                 # a note of project "orch": not the steward's tier
        t.as_(envoy)
        self.assertIn("pending", t.adm("archive", envoy, ids=[outside], reason='"rule line text"'))      # S6: the operator decides
        orch = t.h.record(w, "note", "an orchestration note", "rule line text", project="orchestration")["id"]
        self.assertIn("archived", t.adm("archive", envoy, ids=[orch], reason='"rule line text"'))        # inside the tier: no approval
        d = t.h.record(owner, "decision", "owned", "the decision rule")["id"]
        ack = t.h.send(owner, envoy, f"ack archive {d}")["id"]                                      # 0.27.2: a decision without the owner's ack is refused when raised
        self.assertIn("pending", t.adm("archive", envoy, ids=[d], reason='"the decision rule"', ack=ack))   # a decision: never routine
        n = t.note(w, title="another")
        self.assertIn("pinned", t.adm("pin", envoy, ids=[n], reason='"rule line text"'))
        self.assertIn("pending", t.adm("pin", envoy, ids=[n], reason='"rule line text"'))                # already pinned: not routine

    def test_f6_the_steward_keeps_its_tier(self):
        t = self.base("c")
        steward, w = t.agent("steward"), t.agent()
        outside = t.note(w)
        t.as_(steward)
        with self.assertRaisesRegex(H.HarnessError, "S6"):
            t.adm("archive", steward, ids=[outside], reason='"rule line text"')


class Cap(unittest.TestCase):
    def setUp(self):
        p = mock.patch.object(H, "health_rows", return_value=([], 0))
        p.start()
        self.addCleanup(p.stop)
        self.home = os.path.join(tempfile.mkdtemp(), "h")
        os.makedirs(self.home)
        self.h = H.Harness(self.home)
        self.me = self.h.register(project="orch", model=MODEL, session_id="s-me")["id"]
        self.h.sync(self.me)

    def changed(self):
        t = self.h.sync(self.me)["text"]
        return t, (t.split("Changed:\n")[1].split("\nPredecessor")[0].splitlines() if "Changed:\n" in t else [])

    def test_f7_new_decision_cards_and_task_changes_are_never_cut_by_the_cap(self):
        other = self.h.register(project="orch", model=MODEL, session_id="s-o")["id"]
        self.h.sync(self.me)
        ids = [self.h.register(project="orch", model=MODEL, session_id="s-r%d" % i)["id"] for i in range(25)]
        self.h.sync(self.me)
        for a in ids:
            self.h.retire(a, "done", by=a)                                                  # 25 listed lines that fill the cap
        decs = [self.h.record(other, "decision", "operator rule %d" % i, "the rule %d body" % i)["id"] for i in range(3)]
        tasks = [self.h.send(self.me, other, "task %d" % i, kind="task", subject="job %d" % i)["id"] for i in range(3)]
        for t_ in tasks:
            self.h.task_update(other, t_, "working")
        t, lines = self.changed()
        for d in decs:
            self.assertIn(d, t, "decision card cut by the cap: " + d)
        self.assertGreaterEqual(sum(1 for x in lines if x.strip().startswith("task:") or " → working" in x), 3, lines)
        self.assertTrue(any("more (harness_sync full=true)" in x for x in lines), lines)       # the other lines were still counted, not listed


class PerRecipient(F.Fixes):
    """F7: one report per recipient of a multi-recipient send."""

    def two(self):
        self.h.role_define("operator", "ops-coder", "harness-ops", carry="none")
        if "curator" not in self.h.state().roles:
            self.h.role_define("operator", "curator", "harness-ops", carry="none")
        a = self.reg("curator", "local_pr_a")
        b = self.reg("ops-coder", "local_pr_b")
        self.warm(a)
        self.warm(b)
        return a, b

    def send2(self):
        a, b = self.two()
        r = self.call("harness_send", agent=self.plain, to=["role:curator", "role:ops-coder"], body="b", subject="s", kind="task")
        return a, b, r["nudge"]

    def test_the_do_line_asks_for_one_report_per_recipient_with_to(self):
        a, b, n = self.send2()
        self.assertIn('to:"<one of the to values>"', n["do"])
        self.assertIn("local_pr_a, local_pr_b", n["do"])
        self.assertIn("One report per recipient", n["do"])

    def test_one_recipient_is_unchanged_and_has_no_to(self):
        a, b = self.two()
        n = self.call("harness_send", agent=self.plain, to="role:curator", body="b", subject="s", kind="task")["nudge"]
        self.assertNotIn("One report per recipient", n["do"])

    def test_a_refusal_after_a_delivery_still_asks_for_its_relay(self):
        a, b, n = self.send2()
        mid = n["msg_id"]
        r1 = self.admin(self.plain, "nudge_result", msg_id=mid, outcome="delivered", reason="", to="local_pr_a")
        self.assertTrue(r1.get("reported"), r1)
        r2 = self.admin(self.plain, "nudge_result", msg_id=mid, outcome="skipped", reason="app_cap", to="local_pr_b")
        self.assertTrue(r2.get("relay_requested"), r2)                                       # not "already reported"
        off = [e for e in self.h.store.read_all() if e["type"] == "nudge.relay_offer"][-1]["data"]
        self.assertEqual(off["to_session"], "local_pr_b")

    def test_a_second_report_for_the_same_recipient_is_already_reported(self):
        a, b, n = self.send2()
        mid = n["msg_id"]
        self.admin(self.plain, "nudge_result", msg_id=mid, outcome="delivered", reason="", to="local_pr_a")
        r = self.admin(self.plain, "nudge_result", msg_id=mid, outcome="delivered", reason="", to="local_pr_a")
        self.assertTrue(r.get("already_reported"), r)
        r = self.admin(self.plain, "nudge_result", msg_id=mid, outcome="delivered", reason="", to="local_pr_b")
        self.assertTrue(r.get("reported"), r)

    def test_a_to_that_is_not_a_recipient_session_is_refused_and_records_nothing(self):
        a, b, n = self.send2()
        with self.assertRaises(Exception) as cx:
            self.admin(self.plain, "nudge_result", msg_id=n["msg_id"], outcome="delivered", reason="", to="local_nobody")
        self.assertIn("to must be one recipient of this message", str(cx.exception))
        self.assertEqual([e for e in self.h.store.read_all() if e["type"] == "nudge.result"], [])

    def test_a_report_without_to_still_covers_the_whole_message(self):
        a, b, n = self.send2()
        r = self.admin(self.plain, "nudge_result", msg_id=n["msg_id"], outcome="delivered", reason="")
        self.assertTrue(r.get("reported"), r)
        r = self.admin(self.plain, "nudge_result", msg_id=n["msg_id"], outcome="delivered", reason="", to="local_pr_b")
        self.assertTrue(r.get("reported"), r)          # round 6: a recipient's own report after a whole one is still taken (it can be an app_cap skip)


for _n in [n for n in dir(F.Fixes) if n.startswith("test_")]:
    setattr(PerRecipient, _n, None)


class Virtue(unittest.TestCase):
    def test_f7_the_virtue_notice_names_the_step_the_secretary_can_take_and_carries_no_prompt_text(self):
        import test_c260_item20 as V
        t = V.Virtue("test_the_operator_saying_virtue_mails_the_secretary_and_logs")
        t.setUp()
        try:
            self.assertTrue(t.check("patience is a virtue SECRETTEXT"))
            body = [m for m in t.h.state().messages.values() if "role:secretary" in m["to"]][-1]["body"]
            self.assertIn("To act: ask the operator", body)
            self.assertNotIn("SECRETTEXT", body)
        finally:
            t.doCleanups()


if __name__ == "__main__":
    unittest.main()
