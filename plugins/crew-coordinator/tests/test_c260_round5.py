"""cc 0.26.0 fix round 5: _waiting's thread branch applies _ask_open too, so an earlier ask on the thread that was already answered does not make a
cold holder 'waiting'. Run: python3 -B tests/test_c260_round5.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _env  # noqa: F401  isolate HOME and HARNESS_* first
import time
import unittest

import test_c250_relay_fixes as F
from test_c250_relay_fixes import D


class Thread(F.Fixes):
    def cold_curator(self, host):
        self.ready()
        if "curator" not in self.h.state().roles:
            self.h.role_define("operator", "curator", "harness-ops", carry="none")
        return self.reg("curator", host)

    def test_an_answered_ask_on_the_thread_does_not_ring_a_cold_holder_for_a_later_result(self):     # the critic's probe
        c = self.cold_curator("local_r5a")
        q = self.call("harness_send", agent=c, to=self.plain, body="q?", subject="q", kind="question")["id"]
        self.call("harness_send", agent=self.plain, to="role:curator", body="answer", subject="a", kind="result", reply_to=q)
        D._save(D._sp(self.h, c), {"last_call": time.time() - 4000})                          # the curator's chat is cold
        r = self.call("harness_send", agent=self.plain, to="role:curator", body="later news", subject="re", kind="result", reply_to=q)
        self.assertFalse(isinstance(r.get("nudge"), dict), r.get("nudge"))

    def test_waiting_is_false_for_the_answered_ask_and_true_for_an_open_one_on_the_thread(self):
        c = self.cold_curator("local_r5b")
        q = self.h.send(c, self.plain, "q?", kind="question")["id"]
        self.h.send(self.plain, c, "answer", kind="result", reply_to=q)
        late = self.h.send(self.plain, c, "late", kind="result", reply_to=q)["id"]
        st = self.h.state()
        self.assertFalse(D._waiting(st, st.messages[late], c))
        q2 = self.h.send(c, self.plain, "second?", kind="question", reply_to=late)["id"]        # an open ask on the same thread
        # (the later result answers q2 by reply_to; q2 is unanswered, so the curator is waiting)
        res = self.h.send(self.plain, c, "result", kind="result", reply_to=q2)["id"]
        st = self.h.state()
        self.assertEqual(st.messages[res]["thread"], st.messages[q2]["thread"])
        self.assertTrue(D._waiting(st, st.messages[res], c))

    def test_an_open_ask_on_the_thread_still_rings_a_cold_holder(self):
        c = self.cold_curator("local_r5c")
        q = self.call("harness_send", agent=c, to=self.plain, body="q?", subject="q", kind="question")["id"]
        D._save(D._sp(self.h, c), {"last_call": time.time() - 4000})
        r = self.call("harness_send", agent=self.plain, to="role:curator", body="the answer", subject="re", kind="result", reply_to=q)
        self.assertIsInstance(r.get("nudge"), dict, r.get("nudge"))

    def test_a_finished_task_on_the_thread_is_not_waiting(self):
        c = self.cold_curator("local_r5d")
        t = self.h.send(c, self.plain, "do x", kind="task")["id"]
        self.h.task_update(self.plain, t, "completed", note="done: proof")
        late = self.h.send(self.plain, c, "late", kind="result", reply_to=t)["id"]
        st = self.h.state()
        self.assertFalse(D._waiting(st, st.messages[late], c))


for _n in [n for n in dir(F.Fixes) if n.startswith("test_")]:
    setattr(Thread, _n, None)


if __name__ == "__main__":
    unittest.main()
