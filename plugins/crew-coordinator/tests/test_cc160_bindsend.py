"""cc 0.16.0: bind/send visibility (envoy ACCEPT m-3303ec74d343): call.failed, unread marker + hook line, record kind error,
mismatch event. Run: python3 -B tests/test_cc160_bindsend.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _env  # noqa: F401  isolate HOME and HARNESS_* first
import copy, io, json, os, subprocess, sys, tempfile, time, unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
import harness as H
import mcp_server as M
import ctx_hook as C

MODEL = "claude-sonnet-5-5"


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.home = os.path.join(self.tmp, "home")
        os.makedirs(self.home)
        self.h = H.Harness(self.home)
        M.BOUND.update(home=None, id=None)
        M._FAILED_SEEN.clear()
        self.a = self.h.register(project="p", model=MODEL)["id"]
        self.b = self.h.register(project="p", model=MODEL)["id"]

    def failed(self):
        return [e for e in self.h.store.read_all() if e["type"] == "call.failed"]


class CallFailed(Base):
    def test_failed_send_is_logged_without_body(self):
        with self.assertRaises(H.HarnessError):
            M.call(self.h, "harness_send", {"agent": self.a, "to": "nobody-here", "body": "SECRET BODY TEXT", "subject": "SECRET SUBJECT"})
        ev = self.failed()
        self.assertEqual(len(ev), 1)
        d = ev[0]["data"]
        self.assertEqual(set(d), {"agent", "tool", "error", "to"})
        self.assertNotIn("SECRET", json.dumps(ev[0]))
        self.assertEqual(d["tool"], "harness_send")
        self.assertLessEqual(len(d["error"]), 200)

    def test_record_without_kind_clear_error_and_logged(self):
        with self.assertRaisesRegex(H.HarnessError, r"harness_record: kind required \(decision\|context\|capsule\|note\)"):
            M.call(self.h, "harness_record", {"agent": self.a, "title": "t"})
        self.assertEqual(self.failed()[0]["data"]["tool"], "harness_record")

    def test_rate_cap_three_per_minute(self):
        for _ in range(6):
            with self.assertRaises(H.HarnessError):
                M.call(self.h, "harness_record", {"agent": self.a, "title": "t"})
        self.assertEqual(len(self.failed()), 3)

    def test_read_tools_and_success_not_logged(self):
        with self.assertRaises(H.HarnessError):
            M.call(self.h, "harness_inbox", {"agent": "ffffffff"})
        M.call(self.h, "harness_send", {"agent": self.a, "to": self.b, "body": "ok", "subject": "s"})
        self.assertEqual(self.failed(), [])

    def test_logging_never_masks_the_original_error(self):
        with mock.patch.object(self.h.store, "append", side_effect=OSError("disk full")):
            with self.assertRaises(H.HarnessError):
                M.call(self.h, "harness_record", {"agent": self.a, "title": "t"})

    def test_replay_skips_unknown_type_and_hash_chain_holds(self):
        with self.assertRaises(H.HarnessError):
            M.call(self.h, "harness_record", {"agent": self.a, "title": "t"})
        self.assertTrue(self.h.verify()["ok"])
        st = H.State(copy.deepcopy(self.h.store.read_all()))        # an unaware fold ignores call.failed
        self.assertIn(self.a, st.agents)


class Unread(Base):
    def marker(self, aid):
        p = os.path.join(os.environ["HARNESS_STATE_DIR"], "harness-unread-%s.json" % aid[:8])
        return json.load(open(p)) if os.path.exists(p) else None

    def test_marker_written_on_send_cleared_on_read_counts_only(self):
        self.h.send(self.a, self.b, "SECRET", subject="SECRET SUBJ")
        mk = self.marker(self.b)
        self.assertEqual(mk["n"], 1)
        self.assertEqual(set(mk), {"n", "oldest"})
        self.h.inbox(self.b)
        self.assertIsNone(self.marker(self.b))

    def hook(self, tool="Read", agent_banner=True):
        inp = {"session_id": "s-unread", "tool_name": tool, "tool_input": {}, "tool_response": "x", "hook_event_name": "PostToolUse"}
        if agent_banner:
            p = C.note_path(inp)
            C.save_note(p, dict(C.load_note(p), agent=self.b[:8]))
        return C.on_tool(inp)

    def test_line_only_after_two_minutes_then_quiet_ten(self):
        self.h.send(self.a, self.b, "x", subject="y")
        self.assertIsNone(self.hook())                         # too fresh
        mk = os.path.join(os.environ["HARNESS_STATE_DIR"], "harness-unread-%s.json" % self.b[:8])
        json.dump({"n": 1, "oldest": time.time() - 300}, open(mk, "w"))
        line = self.hook()
        self.assertIn("1 unread", line)
        self.assertNotIn("SECRET", line)
        self.assertIsNone(self.hook())                         # quiet for ten minutes

    def test_no_line_without_known_agent_or_mail(self):
        self.assertIsNone(self.hook(agent_banner=False))
        self.assertIsNone(self.hook())


class Mismatch(Base):
    def test_event_states_mode_and_executed(self):
        M._BIND_SEEN.clear()
        M.BOUND.update(home=self.h.home, id=self.a)
        M.bind_check(self.h, {"agent": self.b}, "harness_sync")
        ev = [e for e in self.h.store.read_all() if e["type"] == "bind.mismatch"][-1]["data"]
        self.assertEqual(ev["mode"], "warn")
        self.assertTrue(ev["executed"])
        self.assertIn("not an authority", ev["bound_is"])


if __name__ == "__main__":
    unittest.main()
