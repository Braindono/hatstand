"""cc 0.26.0 fix round 2 (raw read F1 to F7): result and handoff replies keep a safety net after the ladder removal in the three probe cases; the virtue hook
skips "by virtue of" and chats with no role; /listen's open_task reuses the owed list; the owed list puts the operator's asks first; small text fixes.
Run: python3 -B tests/test_c260_round2.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _env  # noqa: F401  isolate HOME and HARNESS_* first
import os
import tempfile
import time
import unittest

import test_c250_relay_fixes as F
from test_c250_relay_fixes import D, H

HERE = os.path.dirname(os.path.abspath(__file__))
KINDS = ("result", "handoff")


class F3(F.Fixes):
    """Raw read F3: the scope item 3 condition (a reply whose nudge is skipped or unreported still gets a relay or rewake) for result AND handoff."""

    def probe_a(self, kind):
        self.ready()
        t0 = time.time()
        n = self.send(kind=kind)["nudge"]
        self.assertIsInstance(n, dict, (kind, n))
        out = D.wake_scan(self.h, now=t0 + 20 * 60, force=True)
        self.assertTrue(any(k in ("relay", "miss") and m == n["msg_id"] for k, m in out), (kind, out))

    def probe_b(self, kind, cap, label):
        self.ready()
        self.op["doorbell"] = dict({"nudge_per_agent_hour": 60, "nudge_per_pair_hour": 30}, **{cap: 1})
        self.send(kind="task")                                                          # uses the one slot
        r = self.send(kind=kind)
        skipped = r.get("nudge_skipped") or []
        self.assertTrue(skipped and label in skipped[0]["reason"], (kind, r))
        self.assertTrue(str(skipped[0].get("relay") or "").startswith(("relay requested", "miss")), (kind, skipped))

    def probe_c(self, kind):
        if "curator" not in self.h.state().roles:
            self.h.role_define("operator", "curator", "harness-ops", carry="none")
        c = self.reg("curator", "local_cold_" + kind)                                   # registered, never warmed: a cold holder
        ask = self.call("harness_send", agent=c, to=self.plain, body="please do x", subject="ask", kind="question")["id"]
        D._save(D._sp(self.h, c), {"last_call": time.time() - 4000})                    # its last harness call was over an hour ago: cold
        r = self.call("harness_send", agent=self.plain, to="role:curator", body="done", subject="re", kind=kind, reply_to=ask)
        self.assertIsInstance(r.get("nudge"), dict, (kind, r.get("nudge")))             # was "result to a cold holder: mail only"

    def test_probe_a_result_replier_never_reports(self):
        self.probe_a("result")

    def test_probe_a_handoff_replier_never_reports(self):
        self.probe_a("handoff")

    def test_probe_b_result_pair_cap(self):
        self.probe_b("result", "nudge_per_pair_hour", "pair cap")

    def test_probe_b_handoff_pair_cap(self):
        self.probe_b("handoff", "nudge_per_pair_hour", "pair cap")

    def test_probe_b_result_sender_cap(self):
        self.probe_b("result", "nudge_per_agent_hour", "sender cap")

    def test_probe_b_handoff_sender_cap(self):
        self.probe_b("handoff", "nudge_per_agent_hour", "sender cap")

    def test_probe_c_result_cold_holder_waiting_on_the_thread(self):
        self.probe_c("result")

    def test_probe_c_handoff_cold_holder_waiting_on_the_thread(self):
        self.probe_c("handoff")

    def test_a_reply_to_a_cold_holder_who_asked_nothing_stays_mail_only_and_a_notice_rings_nobody(self):
        self.h.role_define("operator", "curator", "harness-ops", carry="none") if "curator" not in self.h.state().roles else None
        c = self.reg("curator", "local_cold_none")
        D._save(D._sp(self.h, c), {"last_call": time.time() - 4000})
        r = self.call("harness_send", agent=self.plain, to="role:curator", body="done", subject="re", kind="result")
        self.assertFalse(isinstance(r.get("nudge"), dict), r.get("nudge"))
        r = self.call("harness_send", agent=self.plain, to="role:curator", body="fyi", subject="fyi", kind="notice")
        self.assertFalse(isinstance(r.get("nudge"), dict), r.get("nudge"))


for _n in [n for n in dir(F.Fixes) if n.startswith("test_")]:
    setattr(F3, _n, None)


class Small(unittest.TestCase):
    def setUp(self):
        import test_c260_item20 as V
        self.V = V

    def test_the_virtue_idiom_and_a_roleless_chat_send_nothing(self):                 # F4
        import ctx_hook as C
        V = self.V
        t = V.Virtue("test_the_operator_saying_virtue_mails_the_secretary_and_logs")
        t.setUp()
        try:
            for p in ("By virtue of the lease, proceed.", "in virtue of that rule", "BY  VIRTUE\nOF it"):
                self.assertFalse(t.check(p), p)
            self.assertTrue(t.check("patience is a virtue"))
            self.assertTrue(t.check("By virtue of x, and also a real virtue"))           # an idiom does not hide a real use
            self.assertFalse(t.check("a virtue", sid="s-nobody"))                         # a session with no agent
            b = t.h.register(project="orch", model="claude-sonnet-5-5", session_id="s-norole")["id"]
            t.h.store.append("session.bound", b, {"session_id": "s-norole", "agent": b})
            self.assertFalse(t.check("another virtue", sid="s-norole"))                   # an agent with no role
            body = [m for m in t.h.state().messages.values() if "role:secretary" in m["to"]][-1]["body"]
            self.assertNotIn("patience", body)
        finally:
            t.doCleanups()


class Rest(unittest.TestCase):
    def setUp(self):
        self.home = os.path.join(tempfile.mkdtemp(), "h")
        os.makedirs(self.home)
        self.h = H.Harness(self.home)
        for r in ("lead", "coder"):
            self.h.role_define("operator", r, "orch")
        self.lead = self.reg("lead", "s-lead")
        self.c1 = self.reg("coder", "s-c1")

    def reg(self, role, sid):
        a = self.h.register(project="orch", model="claude-sonnet-5-5", session_id=sid)["id"]
        self.h.role_assign("operator", role, a)
        return a

    def test_f5_open_task_reuses_the_owed_list_so_a_successor_does_not_arm_on_an_answered_item(self):
        q = self.h.send(self.lead, "role:coder", "question?", kind="question")["id"]
        self.assertEqual(D.open_task(self.h.state(), self.c1)[0], 1)
        self.h.send(self.c1, self.lead, "answer", kind="notice", reply_to=q)
        c2 = self.reg("coder", "s-c2")                                                    # a no-carry successor takes the role
        self.assertEqual(D.open_task(self.h.state(), c2), (0, []))
        q2 = self.h.send(self.lead, "role:coder", "second?", kind="question")["id"]
        self.assertEqual(D.open_task(self.h.state(), c2), (1, [q2]))
        D_ = D.owed_replies(self.h.state(), c2)
        self.assertEqual(D_, [q2])                                                         # the two agree

    def test_f6_the_operators_asks_come_first_in_the_footer_the_digest_and_the_structured_field(self):
        old = [self.h.send(self.lead, self.c1, "agent ask %d" % i, kind="task")["id"] for i in range(7)]
        op = self.h.send("operator", self.c1, "fresh operator ask", kind="task")["id"]
        st = self.h.state()
        ordered = D.owed_order(st, D.owed_replies(st, self.c1))
        self.assertEqual(ordered[0], op)
        self.assertEqual(ordered[1:], old)                                                  # then oldest first
        foot = D.owed_footer(st, D.owed_replies(st, self.c1))
        self.assertIn(op, foot.strip("\n").splitlines()[1])
        r = self.h.inbox(self.c1, mark_read=False)
        self.assertEqual(r["owed"], ordered[:D.OWED_LINES])                                 # the structured field and the text agree
        self.assertEqual(r["owed"][0], op)
        dig = self.h.restore_digest(self.h.state(), self.c1, "coder", [])
        sec = dig.split("▸ Owes reply")[1].split("▸ ")[0]
        self.assertIn(op, sec.splitlines()[2])                                              # first line after the fence header

    def test_f7_the_inbox_tool_no_longer_invites_a_long_poll(self):
        import mcp_server as M
        desc = [d for n, d, *_ in M.TOOLS if n == "harness_inbox"][0] if hasattr(M, "TOOLS") else open(os.path.join(HERE, "..", "scripts", "mcp_server.py")).read()
        self.assertNotIn("wait=secs", desc)

    def test_f7_a_present_inbox_ladder_preference_gets_a_warning_line(self):
        pf = os.path.join(self.home, "projects", "orch", "OPERATOR-PREFERENCES.md")
        os.makedirs(os.path.dirname(pf))
        open(pf, "w").write("- inbox-ladder: 10,50\n- be terse\n")
        lines = self.h._prefs_lines("orch")
        self.assertTrue(any(x.startswith("WARN the inbox-ladder preference is ignored since 0.26.0") for x in lines), lines)
        open(pf, "w").write("- be terse\n")
        self.assertFalse(any("inbox-ladder" in x for x in self.h._prefs_lines("orch")))

    def test_f7_hotfix_with_an_operator_override_prints_a_warning_and_is_cli_only(self):
        import mcp_server as M
        self.assertNotIn("hotfix", M.ADMIN_ARGS["publish_release"])                         # CLI only
        src = open(os.path.join(HERE, "..", "scripts", "harness.py"), encoding="utf-8").read()
        self.assertIn("ignored: --operator-override skips the cadence check itself", src)
        self.assertIn("CLI only (no MCP argument)", src)


if __name__ == "__main__":
    unittest.main()
