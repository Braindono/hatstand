"""0.27.1: one open question per topic across chats. Run: python3 -B tests/test_open_questions.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _env  # noqa: F401
import os, sys, tempfile, unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import open_questions as Q

T = ["checklist", "layout", "runbook", "hub"]
Q1 = "What layout should the Hub checklist use, rows or cards?"
Q2 = "Which checklist layout is right for the Hub: rows or cards?"


class OQ(unittest.TestCase):
    def setUp(self):
        self.h = tempfile.mkdtemp(); os.makedirs(os.path.join(self.h, "_harness"))

    def test_second_chat_on_the_same_topic_is_flagged_first_is_not(self):
        self.assertIsNone(Q.seen(self.h, "a1", "envoy", T, now=1000.0))
        msg = Q.seen(self.h, "b2", "secretary", T + ["extra"], now=1060.0)
        self.assertIn("one open question per topic", msg); self.assertIn("envoy", msg); self.assertIn("1 minutes", msg)

    def test_same_chat_asking_again_other_topic_and_expiry_are_quiet(self):
        Q.seen(self.h, "a1", "envoy", T, now=1000.0)
        self.assertIsNone(Q.seen(self.h, "a1", "envoy", T, now=1010.0))
        self.assertIsNone(Q.seen(self.h, "b2", "x", ["budget", "tokens", "cap"], now=1020.0))
        self.assertIsNone(Q.seen(self.h, "b2", "x", T, now=1000.0 + 2 * Q.WINDOW_S))

    def test_one_term_is_never_a_topic_and_no_text_is_stored(self):
        self.assertIsNone(Q.seen(self.h, "a1", "envoy", ["hub"], now=1.0))
        Q.seen(self.h, "a1", "envoy", T, now=2.0)
        self.assertNotIn("Should", open(os.path.join(self.h, "_harness", "open_questions.jsonl")).read())

    def test_real_row_h_case_and_the_two_approvals(self):
        Q.seen(self.h, "a1", "envoy", Q.topic_terms(Q1), now=10.0)
        self.assertIn("one open question", Q.seen(self.h, "b2", "secretary", Q.topic_terms(Q2), now=20.0))
        Q.seen(self.h, "a1", "envoy", Q.topic_terms("Do you approve 0.27.1 for release?"), now=30.0)
        self.assertIsNone(Q.seen(self.h, "b2", "curator", Q.topic_terms("Do you approve 0.27.1 scope: items 1 to 3?"), now=40.0))

    def test_bad_row_and_parallel_askers(self):
        import json, threading
        p = os.path.join(self.h, "_harness", "open_questions.jsonl")
        open(p, "w").write(json.dumps({"t": "x", "agent": "z", "terms": ["a", "b", "c"]}) + "\n")
        ts = [threading.Thread(target=Q.seen, args=(self.h, "c%d" % i, "r", ["alpha", "beta", "gamma", "delta"], 100.0 + i)) for i in range(8)]
        [t.start() for t in ts]; [t.join() for t in ts]
        rows = [l for l in open(p).read().splitlines() if l.strip()]
        self.assertEqual(len(rows), 8)                       # the bad row is dropped, all 8 askers are kept

    def test_symlinked_file_is_not_followed(self):
        victim = os.path.join(self.h, "victim"); open(victim, "w").write("keep")
        os.symlink(victim, os.path.join(self.h, "_harness", "open_questions.jsonl"))
        Q.seen(self.h, "a1", "envoy", T, now=3.0)
        self.assertEqual(open(victim).read(), "keep")


if __name__ == "__main__":
    unittest.main()
