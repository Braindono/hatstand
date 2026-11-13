"""cc 0.25.0 item 39: one named system sender "system" (alarm scan, handoff_watch): accepted without a roster agent, never nudged, never alarmed,
not owed, not id-checked, and no chat can claim it. Run: python3 -B tests/test_c250_item39.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _env  # noqa: F401  isolate HOME and HARNESS_* first
import time
import unittest

import test_c250_relay_fixes as F
from test_c250_relay_fixes import D, H


class Item39(F.Fixes):
    def sysmail(self, kind="task", to="role:curator", ids_check=False):
        return self.h.send("system", [to], "do something", subject="s", kind=kind, ids_check=ids_check)

    def test_send_accepts_the_named_sender_without_a_roster_agent_and_it_is_not_the_operator(self):
        self.reg("curator", "local_s39")
        r = self.sysmail()
        m = self.h.state().messages[r["id"]]
        self.assertEqual(m["from"], "system")
        self.assertNotIn(m["from"], ("human", "operator"))
        self.assertNotIn("system", self.h.state().agents)
        ev = [e for e in self.h.store.read_all() if e["type"] == "message.sent" and e["data"]["id"] == r["id"]][0]
        self.assertNotEqual(ev["actor"], "human")

    def test_an_unread_system_notice_makes_no_nudge_offer_and_no_alarm(self):
        c = self.reg("curator", "local_s39b")
        self.warm(c)
        r = self.sysmail()
        D._save(D._sp(self.h, c), {"last_call": time.time() - 300})
        out = D._attach(self.h, "system", dict(r))
        self.assertNotIn("nudge", out)
        self.assertNotIn("nudge", D._attach_holder(self.h, dict(r)))
        later = time.time() + 40 * 60
        D.alarm_scan(self.h, now=later, force=True)
        self.assertEqual([e for e in self.events("nudge.alarm") if e["data"].get("msg_id") == r["id"]], [])
        self.assertEqual([e for e in self.events("nudge.offered") if (e["data"].get("msg") or e["data"].get("msg_id")) == r["id"]], [])
        self.assertTrue(D.is_system_sender("system"))
        self.assertFalse(D.is_system_sender("human"))

    def test_a_system_notice_is_not_owed_even_when_it_asks_for_a_reply(self):
        c = self.reg("curator", "local_s39c")
        self.h.send("system", ["role:curator"], "b", subject="s", kind="task")
        self.h.send("system", ["role:curator"], "b", subject="s", kind="notice", expects_reply=True)
        self.assertEqual(D.owed_replies(self.h.state(), c), [])

    def test_the_id_check_ignores_the_named_sender(self):
        self.reg("curator", "local_s39d")
        before = len(self.events("hook.idcheck")) + len(self.events("call.failed"))
        self.h.send("system", ["role:curator"], "cites D-00000 which is unknown", subject="s", kind="notice", ids_check=True)
        self.assertEqual(len(self.events("hook.idcheck")) + len(self.events("call.failed")), before)

    def test_no_chat_can_send_as_system_over_mcp(self):
        self.reg("curator", "local_s39e")
        with self.assertRaises(H.HarnessError):
            self.call("harness_send", agent="system", to="role:curator", body="x", subject="s", kind="notice")


for _n in [n for n in dir(F.Fixes) if n.startswith("test_")]:
    setattr(Item39, _n, None)


if __name__ == "__main__":
    unittest.main()
