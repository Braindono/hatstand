"""cc 0.26.0 items 6 to 10: the owed list. Role-based clearing, reply_to or ref to the sender or its role, co-recipient debts, ages and the cap,
the per-role no-reply-needed close. Run: python3 -B tests/test_c260_item610.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _env  # noqa: F401  isolate HOME and HARNESS_* first
import os
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
_sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
import harness as H
import doorbell as D
import mcp_server as M

MODEL = "claude-sonnet-5-5"


class Owed(unittest.TestCase):
    def setUp(self):
        self.home = os.path.join(tempfile.mkdtemp(), "h")
        os.makedirs(self.home)
        self.h = H.Harness(self.home)
        for r in ("lead", "coder", "other"):
            self.h.role_define("operator", r, "orch")
        self.lead = self.reg("lead")
        self.c1 = self.reg("coder")
        self.third = self.reg("other")

    def reg(self, role):
        a = self.h.register(project="orch", model=MODEL, session_id="s-" + role + str(time.time()))["id"]
        self.h.role_assign("operator", role, a) if hasattr(self.h, "role_assign") else None
        return a

    def owed(self, a):
        return D.owed_replies(self.h.state(), a)

    def task(self, to, kind="task"):
        return self.h.send(self.lead, to, "do x", kind=kind)["id"]

    # item 6
    def test_a_no_carry_successor_does_not_inherit_an_item_a_predecessor_answered(self):
        mid = self.task("role:coder")
        self.assertEqual(self.owed(self.c1), [mid])
        self.h.send(self.c1, self.lead, "done", kind="notice", reply_to=mid)
        self.assertEqual(self.owed(self.c1), [])
        c2 = self.h.register(project="orch", model=MODEL, session_id="s-c2")["id"]
        self.h.role_assign("operator", "coder", c2)
        self.assertEqual(self.owed(c2), [])                                   # answered by an earlier holder of the role

    def test_any_holder_of_the_role_clears_it_for_the_role(self):
        mid = self.task("role:coder")
        c2 = self.h.register(project="orch", model=MODEL, session_id="s-c3")["id"]
        self.h.role_assign("operator", "coder", c2)
        self.assertEqual(self.owed(c2), [mid])                                # unanswered: the successor still owes it
        self.h.send(c2, self.lead, "done", kind="notice", reply_to=mid)
        self.assertEqual(self.owed(c2), [])

    # item 7
    def test_reply_to_clears_and_a_ref_in_a_result_notice_or_message_to_the_sender_clears(self):
        for kind in ("result", "notice", "message"):
            mid = self.task(self.c1)
            self.assertIn(mid, self.owed(self.c1))
            self.h.send(self.c1, self.lead, "see " + mid, kind=kind, refs=[mid])
            self.assertNotIn(mid, self.owed(self.c1), kind)
        mid = self.task(self.c1)
        self.h.send(self.c1, self.lead, "answer", kind="notice", reply_to=mid)
        self.assertNotIn(mid, self.owed(self.c1))

    def test_a_bare_ref_in_a_message_to_a_third_party_does_not_clear(self):
        mid = self.task(self.c1)
        self.h.send(self.c1, self.third, "fyi " + mid, kind="message", refs=[mid])
        self.assertIn(mid, self.owed(self.c1))
        self.h.send(self.c1, self.lead, "later message, no ref", kind="notice", thread=self.h.state().messages[mid]["thread"])
        self.assertNotIn(mid, self.owed(self.c1))                             # as in 0.25.0: a later message of the agent on the thread still clears it

    # item 8
    def test_a_co_recipients_debt_clears_only_when_the_other_recipients_result_completes_it(self):
        mid = self.h.send(self.lead, [self.c1, self.third], "both do x", kind="task")["id"]
        self.assertIn(mid, self.owed(self.third))
        self.h.send(self.c1, self.lead, "progress", kind="notice", thread=self.h.state().messages[mid]["thread"])
        self.h.send(self.c1, self.lead, "partial", kind="message", reply_to=mid)
        self.assertIn(mid, self.owed(self.third))                             # a later message alone never clears the co-recipient
        self.h.send(self.c1, self.lead, "done", kind="result", reply_to=mid)
        self.assertNotIn(mid, self.owed(self.third))                          # the other recipient's result completes it
        self.assertNotIn(mid, self.owed(self.c1))

    # item 9
    def test_the_footer_shows_age_oldest_first_and_one_count_line_past_the_cap(self):
        ids = [self.task(self.c1) for _ in range(8)]
        t = D.owed_footer(self.h.state(), self.owed(self.c1)).strip("\n").splitlines()
        self.assertEqual([x.split()[0] for x in t[1:6]], ids[:5])
        self.assertEqual(t[6], "  +3 more (harness_admin op=owed lists every id)")
        self.assertEqual(D.owed_footer(self.h.state(), []), "")
        old = self.h.state().messages[ids[0]]
        self.assertEqual(D.owed_age(self.h.state(), ids[0], now=old["t"] + 3 * 3600), "3h")
        self.assertEqual(D.owed_age(self.h.state(), ids[0], now=old["t"] + 2 * 86400), "2d")
        self.assertEqual(D.owed_age(self.h.state(), ids[0], now=old["t"] + 90), "1m")

    # item 10
    def test_a_role_dismisses_an_item_task_state_is_untouched_and_the_wakes_stop_counting_it(self):
        mid = self.task("role:coder", kind="question")
        n_before = D.open_task(self.h.state(), self.c1)[0]
        self.assertEqual(n_before, 1)
        r = M.admin(self.h, {"op": "owed_close", "agent": self.c1, "args": {"ids": [mid], "reason": "no reply needed"}})
        self.assertEqual(r["closed"], [mid])
        st = self.h.state()
        self.assertEqual(self.owed(self.c1), [])
        self.assertEqual(D.open_task(st, self.c1)[0], 0)                       # wakes and the open-task count stop counting it
        c2 = self.h.register(project="orch", model=MODEL, session_id="s-c4")["id"]
        self.h.role_assign("operator", "coder", c2)
        self.assertEqual(self.owed(c2), [])                                   # per role: the successor holder shares the dismissal
        self.assertEqual(D._answered(self.h.state(), mid, self.c1, "coder"), "closed")
        ev = [e for e in self.h.store.read_all() if e["type"] == "owed.closed"]
        self.assertEqual([e["data"]["msg_id"] for e in ev], [mid])
        self.assertEqual(M.admin(self.h, {"op": "owed_close", "agent": self.c1, "args": {"ids": [mid]}})["closed"], [])   # once

    def test_task_state_is_untouched_by_a_dismissal(self):
        tid = self.task(self.c1)
        M.admin(self.h, {"op": "owed_close", "agent": self.c1, "args": {"ids": [tid]}})
        self.assertEqual(self.h.state().tasks[tid]["state"], "submitted")
        self.assertEqual(self.owed(self.c1), [])

    def test_an_item_not_addressed_to_the_caller_is_refused(self):
        mid = self.task(self.c1)
        r = M.admin(self.h, {"op": "owed_close", "agent": self.third, "args": {"ids": [mid]}})
        self.assertEqual((r["closed"], r["not_addressed_to_you"]), ([], [mid]))
        self.assertEqual(self.owed(self.c1), [mid])

    def test_owed_close_is_a_plain_admin_op_with_no_approval(self):
        self.assertIn("owed_close", M.ADMIN_OPS)
        mid = self.task(self.c1)
        r = M.admin(self.h, {"op": "owed_close", "agent": self.c1, "args": {"ids": [mid]}})
        self.assertEqual(r["closed"], [mid])                                  # done at once: no approval pending came back
        self.assertNotIn("approval", str(r))

if __name__ == "__main__":
    unittest.main()
