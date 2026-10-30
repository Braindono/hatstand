"""cc 0.21.0 items 2 and 3 (A-ae352): harness_inbox peek over MCP (marks nothing) and harness_admin op=approvals_pending (read-only; id, action,
requester, expiry; no args, no digest). Run: python3 -B tests/test_c210_m2.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _env  # noqa: F401  isolate HOME and HARNESS_* first
import json, os, sys, tempfile, time, unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
import harness as H
import mcp_server as M

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
        self.a = self.h.register(project="harness-ops", model=MODEL, task="a")["id"]
        self.b = self.h.register(project="harness-ops", model=MODEL, task="b")["id"]

    def call(self, name, **a):
        M.BOUND.update(home=None, id=None)        # one test process plays two chats: a real server binds one agent, so no bind.mismatch noise
        return M.call(self.h, name, a)

    def ledger_len(self):
        return len(self.h.store.read_all())


class Peek(Base):
    def test_p5_peek_lists_unread_mail_and_writes_nothing(self):
        self.call("harness_send", agent=self.a, to=self.b, body="one", subject="s1", kind="message")
        self.call("harness_send", agent=self.a, to=self.b, body="two", subject="s2", kind="task")
        before, unread0 = self.ledger_len(), self.h.state().agents[self.b].get("unread")
        r = self.call("harness_inbox", agent=self.b, peek=True)
        self.assertEqual(r["count"], 2)
        self.assertIn("one", r["text"])
        self.assertEqual(self.ledger_len(), before, "peek wrote an event")                        # 0 message.read events, nothing else either
        self.assertEqual([e for e in self.h.store.read_all()[before - 1:] if e["type"] == "message.read"], [])
        self.assertEqual(self.h.state().agents[self.b].get("unread"), unread0)                    # unread counter unchanged
        self.assertEqual(self.call("harness_inbox", agent=self.b, peek=True)["count"], 2)         # still unread after a second peek
        again = self.call("harness_inbox", agent=self.b)                                          # the normal call still marks them
        self.assertEqual(again["count"], 2)
        self.assertEqual(self.call("harness_inbox", agent=self.b)["count"], 0)

    def test_owed_reply_counts_are_unchanged_by_a_peek(self):
        t = self.call("harness_send", agent=self.a, to=self.b, body="please", subject="s", kind="task", expects_reply=True)
        o1 = self.call("harness_inbox", agent=self.b, peek=True).get("owed")
        o2 = self.call("harness_inbox", agent=self.b, peek=True).get("owed")
        self.assertEqual(o1, o2)
        self.assertEqual(o1, [t["id"]])

    def test_peek_false_and_missing_behave_like_before(self):
        self.call("harness_send", agent=self.a, to=self.b, body="x", subject="s")
        self.assertEqual(self.call("harness_inbox", agent=self.b, peek=False)["count"], 1)
        self.assertEqual(self.call("harness_inbox", agent=self.b)["count"], 0)

    def test_the_tool_schema_offers_peek(self):
        tool = [t for t in M.TOOLS if t["name"] == "harness_inbox"][0] if isinstance(M.TOOLS, list) and isinstance(M.TOOLS[0], dict) else None
        if tool is None:
            self.assertIn("peek", json.dumps(M.tools_list() if hasattr(M, "tools_list") else str(M.TOOLS)))
        else:
            self.assertIn("peek", tool["inputSchema"]["properties"])


class ApprovalsPending(Base):
    def _ask(self, action="set_project", **args):
        return self.h.request_approval(self.a, action, args or {"target": self.b, "project": "secret-project-name-xyz"})

    def test_p6_rows_show_id_action_requester_expiry_and_nothing_else(self):
        ask = self._ask()
        full = [r for r in self.h.approvals(True)][0]
        r = self.call("harness_admin", op="approvals_pending", agent=self.a)
        self.assertEqual(r["count"], 1)
        row = r["approvals"][0]
        self.assertEqual(set(row), {"id", "action", "requested_by", "seconds_to_expiry"})
        self.assertEqual((row["id"], row["action"]), (ask["pending"], "set_project"))
        self.assertTrue(0 < row["seconds_to_expiry"] <= 600)
        self.assertIs(r["digest_shown"], False)
        blob = json.dumps(r)
        digest = full["args_digest"]
        for leak in (digest, digest[:12], digest[:4], "secret-project-name-xyz", self.b, "args", "digest="):
            self.assertNotIn(leak, blob.replace('"digest_shown"', ""), "leaked: " + leak)

    def test_no_expiry_requests_say_so(self):
        self.h.request_approval(self.a, "lesson_curate", {"lessons": []})
        row = self.call("harness_admin", op="approvals_pending", agent=self.a)["approvals"][0]
        self.assertIsNone(row["seconds_to_expiry"])
        self.assertIn("no expiry", self.call("harness_admin", op="approvals_pending", agent=self.a)["text"])

    def test_it_writes_nothing_even_when_a_request_has_lapsed(self):
        self._ask()
        with mock.patch("time.time", return_value=time.time() + 4000):                    # the 600 s TTL is long gone
            before = self.ledger_len()
            r = self.call("harness_admin", op="approvals_pending", agent=self.a)
            self.assertEqual(r["count"], 0)                                                   # lapsed requests are not pending
            self.assertEqual(self.ledger_len(), before, "approvals_pending logged approval.expired or wrote something")

    def test_granted_and_denied_are_not_listed(self):
        a1 = self._ask()
        self.h.store.append("approval.denied", "system", {"id": a1["pending"]})
        self.assertEqual(self.call("harness_admin", op="approvals_pending", agent=self.a)["count"], 0)

    def test_it_takes_no_arguments_and_the_old_digest_view_is_untouched(self):
        with self.assertRaises(H.HarnessError):
            self.call("harness_admin", op="approvals_pending", agent=self.a, args={"all": True})
        self._ask()
        old = self.call("harness_admin", op="approvals", agent=self.a)
        self.assertIn("digest=", old["text"])          # item 3 adds a tool; the existing op=approvals is outside A-ae352 (backlog)


if __name__ == "__main__":
    unittest.main()
