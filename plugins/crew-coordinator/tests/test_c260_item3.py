"""cc 0.26.0 item 3: the listening ladder is gone. harness_send carries no ladder, the hooks carry no wait= text, the reminder still fires, the
protocol says end the turn after a send, and a reply whose nudge was skipped still gets a rewake or a relay. Run: python3 -B tests/test_c260_item3.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _env  # noqa: F401  isolate HOME and HARNESS_* first
import os
import time
import unittest
from unittest import mock

import test_c250_relay_fixes as F
from test_c250_relay_fixes import D

HERE = os.path.dirname(os.path.abspath(__file__))


class Item3(F.Fixes):
    def test_send_result_has_no_ladder_for_any_kind(self):
        self.ready()
        for k in ("task", "question", "review", "notice", "result", "message"):
            r = self.send(kind=k)
            self.assertNotIn("ladder", r, k)
            self.assertNotIn("wait=", str(r), k)

    def test_the_inbox_ladder_module_and_pref_are_gone(self):
        self.assertFalse(os.path.exists(os.path.join(HERE, "..", "scripts", "inbox_ladder.py")))
        self.assertTrue(os.path.exists(os.path.join(HERE, "..", "scripts", "inbox_reminder.py")))
        open(os.path.join(self.h.home, "OPERATOR-PREFERENCES.md"), "w").write("- inbox-ladder: 10,50\n")     # the key is ignored
        self.ready()
        self.assertNotIn("ladder", self.send(kind="task"))

    def test_no_hook_or_skill_text_tells_the_agent_to_wait(self):
        for rel in ("hooks/hooks.json", "skills/protocol/SKILL.md", "skills/refresh/SKILL.md", "scripts/inbox_reminder.py"):
            t = open(os.path.join(HERE, "..", rel), encoding="utf-8").read()
            self.assertNotIn("wait=", t, rel)
            self.assertFalse("ladder" in t.lower(), rel)
        t = open(os.path.join(HERE, "..", "skills", "protocol", "SKILL.md"), encoding="utf-8").read()
        self.assertIn("end the turn", t)
        self.assertLessEqual(len(t.splitlines()), 60)

    def test_the_prompt_hook_entry_stays_and_runs_the_reminder(self):
        import json
        j = json.load(open(os.path.join(HERE, "..", "hooks", "hooks.json")))
        self.assertIn("UserPromptSubmit", j["hooks"])
        self.assertIn("inbox_reminder", open(os.path.join(HERE, "..", "scripts", "harness.py"), encoding="utf-8").read())

    def test_a_reply_whose_nudge_was_skipped_still_gets_a_relay_within_the_first_step(self):
        """The required test of D-2750d: the replier reports the nudge skipped (app cap); the reply is a task/question/review, so a relay is
        requested at once, long before the 15-minute step. (An owed line shows only on the role's next turn, so it does not count.)"""
        self.ready()
        n = self.send(kind="question")["nudge"]                    # the reply: a question back to the secretary role
        r = D.record_result(self.h, self.plain, n["msg_id"], "skipped", "app_cap")
        self.assertTrue(r.get("relay_requested"), r)
        self.assertEqual([e["data"]["reason"] for e in self.events("nudge.relay_offer") if e["data"].get("msg_id") == n["msg_id"]], ["app_cap"])

    def test_a_reply_whose_sender_never_reports_gets_a_relay_or_miss_by_the_scan_and_a_woken_one_gets_the_rewake(self):
        self.ready()
        t0 = time.time()
        n = self.send(kind="question")["nudge"]                    # no report at all: the sender went silent
        out = D.wake_scan(self.h, now=t0 + 20 * 60, force=True)
        self.assertTrue(any(k in ("relay", "miss") and m == n["msg_id"] for k, m in out), out)    # R1b: never silent
        mid = self.offer()                                         # woken-but-unread: rewake 1 at 15 minutes
        self.h.store.append("nudge.result", self.plain, {"msg": mid, "msg_id": mid, "by": self.plain, "for": self.plain, "outcome": "woke",
                                                         "reason": "HTTP 200", "status": 200})
        self.assertIn(("rewake1", mid), D.wake_scan(self.h, now=time.time() + 16 * 60, force=True))

    def skipped_case(self, kind, reason):
        """Critic B1 (fix round 1): the reply kind is usually result. app_cap and no_remotetrigger ask for a relay for every nudge kind."""
        self.ready()
        n = self.send(kind=kind)["nudge"]
        self.assertIsInstance(n, dict, (kind, n))
        r = D.record_result(self.h, self.plain, n["msg_id"], "skipped", reason)
        self.assertTrue(r.get("relay_requested"), r)
        self.assertEqual([e["data"]["reason"] for e in self.events("nudge.relay_offer") if e["data"].get("msg_id") == n["msg_id"]], [reason])
        line = D.claim_relay(self.h, self.env)              # a live holder's next harness call carries it
        self.assertTrue(line and n["msg_id"] in line, line)

    def test_result_skipped_app_cap_gets_a_relay_and_a_holder_rings_it(self):
        self.skipped_case("result", "app_cap")

    def test_result_skipped_no_remotetrigger_gets_a_relay(self):
        self.skipped_case("result", "no_remotetrigger")

    def test_handoff_skipped_app_cap_gets_a_relay(self):
        self.skipped_case("handoff", "app_cap")

    def test_handoff_skipped_no_remotetrigger_gets_a_relay(self):
        self.skipped_case("handoff", "no_remotetrigger")

    def test_a_notice_still_starts_no_wake_and_no_relay(self):
        self.ready()
        r = self.send(kind="notice")
        self.assertNotIsInstance(r.get("nudge"), dict)


for _n in [n for n in dir(F.Fixes) if n.startswith("test_")]:
    setattr(Item3, _n, None)


if __name__ == "__main__":
    unittest.main()
