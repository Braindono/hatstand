"""cc 0.15.2: bind_mode and per-call approval caller. Run: python3 -B tests/test_cc152_bind.py"""
import json, os, sys, unittest
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
import harness as H
import mcp_server as M
from test_cc151_w1 import Base


class BindMode(Base):
    def setUp(self):
        super().setUp()
        M._BIND_SEEN.clear()

    def mode(self, m):
        os.makedirs(os.path.join(self.home, "_harness"), exist_ok=True)
        json.dump({"bind_mode": m}, open(os.path.join(self.home, "_harness", "config.json"), "w"))

    def who(self, a):
        return M.call(self.h, "harness_admin", {"op": "whoami", "agent": a})["short"]

    def test_alternating_agents_default_warn(self):
        a, b = self.agent(), self.agent()
        for _ in range(3):
            self.assertEqual(self.who(a), a[:8])
            self.assertEqual(self.who(b), b[:8])

    def test_alternating_agents_off(self):
        self.mode("off")
        a, b = self.agent(), self.agent()
        self.assertEqual(self.who(a), a[:8])
        self.assertEqual(self.who(b), b[:8])

    def test_warn_logs_once(self):
        a, b = self.agent(), self.agent()
        self.who(a)
        self.who(b)
        self.who(b)
        self.assertEqual(len(M._BIND_SEEN), 1)

    def test_enforce_refuses(self):
        self.mode("enforce")
        a, b = self.agent(), self.agent()
        self.who(a)
        with self.assertRaisesRegex(H.HarnessError, "is bound to .* refused"):
            self.who(b)

    def test_operator_still_refused_in_warn(self):
        a = self.agent()
        self.who(a)
        with self.assertRaisesRegex(H.HarnessError, "approval requests"):
            M.call(self.h, "harness_admin", {"op": "whoami", "agent": "operator"})

    def test_approval_caller_is_call_agent(self):
        a, b = self.agent(), self.agent()
        self.who(a)   # process bound to a
        r = M.call(self.h, "harness_admin", {"op": "flag_release", "agent": b, "args": {"name": "x", "retired": True}})
        pend = r["pending"]
        row = [x for x in self.h.approvals(True) if x["id"] == pend][0]
        self.assertEqual(str(row["caller"])[:8], b[:8])


if __name__ == "__main__":
    unittest.main()
