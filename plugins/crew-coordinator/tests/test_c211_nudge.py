"""cc 0.21.1 (A-58ff8 items 1, 2, 4; spec v4): title prompt on every sync; nudge addressed by the app session id first (action kinds only,
cold-recipient cap) with the ROLE rule as the fallback (allowed sobriquets, B1 bare tier, B2 compaction vs handoff); visible outcomes.
Run: python3 -B tests/test_c211_nudge.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _env  # noqa: F401  isolate HOME and HARNESS_* first
import os, sys, tempfile, time, unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
import harness as H
import mcp_server as M
import doorbell as D

MODEL = "claude-sonnet-5-5"


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.home = os.path.join(self.tmp, "Exchange")
        os.makedirs(os.path.join(self.home, "_harness"))
        e = mock.patch.dict(os.environ, {"HARNESS_STATE_CACHE": "0"})
        e.start()
        self.addCleanup(e.stop)
        self.h = H.Harness(self.home)
        for r in ("envoy", "critic", "harness-critic", "curator", "design-coder", "design-system"):
            self.h.role_define("operator", r, "harness-ops", carry="none")
        self.plain = self.reg(host="local_plain")

    def reg(self, role=None, host=None, **kw):
        return self.h.register(project="harness-ops", model=MODEL, task="t", role=role, host_session_id=host, **kw)["id"]

    def call(self, name, **a):
        M.BOUND.update(home=None, id=None)
        return M.call(self.h, name, a)

    def events(self, t):
        return [e for e in self.h.store.read_all() if e["type"] == t]

    def st(self):
        return self.h.state()

    def nudge(self, frm, to, kind="task"):
        self.n = getattr(self, "n", 0) + 1
        return self.call("harness_send", agent=frm, to=to, body="b%d" % self.n, subject="s%d" % self.n, kind=kind).get("nudge")


class Titles(Base):
    def prompted(self, aid):
        r = self.call("harness_sync", agent=aid, do_only=True)
        return "session_titled" in str(r)

    def test_sync_prompts_until_done_or_not_titled_and_returns_for_a_new_name(self):
        a = self.reg("curator", "local_a")
        self.assertTrue(self.prompted(a))
        self.assertTrue(self.prompted(a))                                                # still, on every sync
        self.call("harness_admin", op="session_titled", agent=a, args={"title": self.st().expected_title(a), "status": "done"})
        self.assertFalse(self.prompted(a))
        b = self.reg("envoy", "local_b")
        self.assertTrue(self.prompted(b))
        self.call("harness_admin", op="session_titled", agent=b, args={"title": "x", "status": "not_titled"})
        self.assertFalse(self.prompted(b))
        c = self.reg("envoy", "local_b", predecessor=b, spawn_reason="compaction")        # new name: the old report is stale
        self.assertTrue(self.prompted(c))


# 0.22.0 (item 6, D-3e5e7): the RoleRule class (fallback rows "ROLE - <name>", allowed sobriquets, the bare-ROLE tier) is gone with the
# rule itself; tests/test_c220_nudge.py covers role-only addressing.


class IdRoute(Base):
    def test_action_kind_with_a_recorded_id_is_addressed_by_id_with_the_role_fallback(self):
        r = self.reg("curator", "local_cur1")
        n = self.nudge(self.plain, r[:8], "task")
        self.assertTrue(n["do"].startswith("Do: SendMessage to local_cur1:"))
        self.assertIn("stale_id", n["do"])
        self.assertNotIn("CURATOR", n["do"])                                              # 0.22.0: no role-name row check, no fallback
        self.assertNotIn("subject", n["do"].split("(fixed fields only")[0].lower().replace("subject or body", ""))
        self.assertEqual(self.events("nudge.offered")[-1]["data"]["by_id"], [True])

    def test_a_result_to_a_cold_holder_and_an_idless_holder_get_mail_only(self):        # 0.22.0 item 6
        r = self.reg("curator", "local_cur2")
        self.assertEqual(self.nudge(self.plain, r[:8], "result"), "none (result to a cold holder: mail only)")
        with mock.patch.dict(os.environ, {"CLAUDE_CODE_HOST_SESSION_ID": ""}):
            e = self.reg("envoy", None)
            self.assertEqual(self.nudge(self.plain, e[:8], "task"), "none (no app session id: mail only)")

    def test_a_peer_cannot_set_another_agents_id(self):
        r = self.reg("curator", "local_mine")
        self.reg(host="local_mine")                                                        # a peer claiming the same id changes nobody's record
        self.assertEqual(self.st().agents[r]["host_session_id"], "local_mine")
        for op in ("host_session_id", "set_host_session"):
            with self.assertRaises(H.HarnessError):
                self.call("harness_admin", op=op, agent=self.plain, args={"agent": r, "host_session_id": "local_x"})

    def test_restart_in_a_new_chat_records_the_new_id(self):
        a = self.reg("curator", "local_old")
        b = self.reg("curator", "local_new", predecessor=a, spawn_reason="restore")
        self.assertTrue(self.nudge(self.plain, b[:8], "review")["do"].startswith("Do: SendMessage to local_new:"))

    def test_other_machine_or_archived_session_reports_skipped_and_falls_back(self):
        r = self.reg("curator", "local_gone")
        n = self.nudge(self.plain, r[:8], "task")
        self.assertIn("(stale, archived or deleted session)", n["do"])
        self.assertIn("report skipped with reason stale_id", n["do"])
        res = self.call("harness_admin", op="nudge_result", agent=self.plain, args={"msg_id": n["msg_id"], "outcome": "skipped", "reason": "stale_id"})
        self.assertTrue(res["reported"])

    def test_three_senders_give_one_id_wake_to_a_cold_recipient(self):
        r = self.reg("curator", "local_cold")
        senders = [self.reg(host="local_s%d" % i) for i in range(3)]
        outs = [self.nudge(s, r[:8], "task") for s in senders]
        self.assertTrue(outs[0]["do"].startswith("Do: SendMessage to local_cold"))
        self.assertEqual(outs[1:], ["none (id route closed by a stale mark or the cold-wake cap: mail only)"] * 2)
        self.assertEqual(len(self.events("nudge.idwake")), 1)

    def _mark_stale(self, host):
        r = self.reg("curator", host)
        a, b, c = (self.reg(host="local_%s%d" % (host[-2:], i)) for i in range(3))
        n = self.nudge(a, r[:8], "task")
        self.assertTrue(n["do"].startswith("Do: SendMessage to %s:" % host))
        self.call("harness_admin", op="nudge_result", agent=a, args={"msg_id": n["msg_id"], "outcome": "skipped", "reason": "stale_id"})
        self.assertIn("mail only", self.nudge(b, r[:8], "task"))                          # stale holds until the recipient calls
        return r, c

    def test_t1_one_stale_report_clears_on_the_recipients_next_call_from_that_session(self):
        r, c = self._mark_stale("local_t1")                                                 # critic N-8a392 failing input
        with mock.patch.dict(os.environ, {"CLAUDE_CODE_HOST_SESSION_ID": "local_t1"}):
            self.call("harness_inbox", agent=r)
            self.call("harness_inbox", agent=r)                                           # a second call writes no second clear
        self.assertTrue(self.nudge(c, r[:8], "task")["do"].startswith("Do: SendMessage to local_t1:"))
        self.assertEqual([e["data"]["host_session_id"] for e in self.events("nudge.stale_cleared")], ["local_t1"])

    def test_t1_a_call_from_another_session_does_not_clear_the_mark(self):
        r, c = self._mark_stale("local_t2")
        with mock.patch.dict(os.environ, {"CLAUDE_CODE_HOST_SESSION_ID": "local_elsewhere"}):
            self.call("harness_inbox", agent=r)
        self.assertIn("mail only", self.nudge(c, r[:8], "task"))
        self.assertEqual(self.events("nudge.stale_cleared"), [])
        with mock.patch.dict(os.environ, {"CLAUDE_CODE_HOST_SESSION_ID": "local_t2"}):
            self.call("harness_inbox", agent=r)
        self.assertEqual(len(self.events("nudge.stale_cleared")), 1)

    def test_t1_stale_ids_replay_in_ledger_order(self):
        self.h.store.append("nudge.stale_id", "system", {"host_session_id": "local_x"})
        self.h.store.append("nudge.stale_cleared", "system", {"host_session_id": "local_x"})
        self.h.store.append("nudge.stale_id", "system", {"host_session_id": "local_y"})
        self.assertEqual(D._stale_ids(self.h), {"local_y"})

    def test_a_warm_recipient_is_not_capped(self):
        r = self.reg("curator", "local_warm")
        self.call("harness_inbox", agent=r)                                                # a call just now: warm
        senders = [self.reg(host="local_w%d" % i) for i in range(3)]
        outs = [self.nudge(s, r[:8], "task")["do"] for s in senders]
        self.assertTrue(all(o.startswith("Do: SendMessage to local_warm") for o in outs))
        self.assertEqual(self.events("nudge.idwake"), [])


class Outcomes(Base):
    def setUp(self):
        super().setUp()
        self.rcv = self.reg("curator", "local_r")
        self.snd = self.reg("envoy", "local_s")
        D.settle(self.h, self.rcv)                                                          # 0.22.0: a result rings only a warm holder

    def offer(self):
        return self.nudge(self.snd, self.rcv[:8], "result")["msg_id"]

    def test_result_in_the_next_call_counts_and_is_not_unreported(self):
        m = self.offer()
        self.call("harness_inbox", agent=self.snd)                                         # the call right after the send
        self.call("harness_admin", op="nudge_result", agent=self.snd, args={"msg_id": m, "outcome": "delivered"})
        self.call("harness_inbox", agent=self.snd)
        self.assertEqual(self.events("nudge.unreported"), [])
        self.assertEqual(D.outcomes(self.h.store.read_all())["delivered"], 1)

    def test_non_sender_refused_and_second_report_already_reported(self):
        m = self.offer()
        with self.assertRaises(H.HarnessError):
            self.call("harness_admin", op="nudge_result", agent=self.rcv, args={"msg_id": m, "outcome": "delivered"})
        self.call("harness_admin", op="nudge_result", agent=self.snd, args={"msg_id": m, "outcome": "held"})
        self.assertTrue(self.call("harness_admin", op="nudge_result", agent=self.snd, args={"msg_id": m, "outcome": "held"})["already_reported"])

    def test_unreported_only_after_the_senders_previous_call_and_result_wins(self):
        m = self.offer()
        self.call("harness_inbox", agent=self.snd)
        self.assertEqual(D.outcomes(self.h.store.read_all())["pending"], 1)                # no later call yet beyond the inbox call
        self.call("harness_inbox", agent=self.snd)
        self.assertEqual([e["data"]["msg_id"] for e in self.events("nudge.unreported")], [m])
        o = D.outcomes(self.h.store.read_all())
        self.assertEqual((o["pending"], o["unreported"]), (0, 1))
        self.call("harness_admin", op="nudge_result", agent=self.snd, args={"msg_id": m, "outcome": "delivered"})
        o = D.outcomes(self.h.store.read_all())
        self.assertEqual((o["unreported"], o["delivered"]), (0, 1))

    def test_legacy_nudge_sent_counts_as_an_offer(self):
        ev = [{"type": "nudge.sent", "data": {"msg": "m-old"}}, {"type": "nudge.offered", "data": {"msg_id": "m-new", "msg": "m-new"}}]
        self.assertEqual(D.outcomes(ev)["offered"], 2)


if __name__ == "__main__":
    unittest.main()
