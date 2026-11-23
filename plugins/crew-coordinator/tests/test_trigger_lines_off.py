"""0.27.1: no RemoteTrigger Do-line goes to any agent (the shipped default). Run: python3 -B tests/test_trigger_lines_off.py"""
import os as _os, sys as _sys
_os.environ["CC_TEST_TRIGGERS_OFF"] = "1"
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _env  # noqa: F401
import os, sys, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
import doorbell as D


class Off(unittest.TestCase):
    """The runner turns the flag on for the older suites (tests/_env.py), and in one process that stays on; these tests read the shipped default
    from the source and switch the flag off for their own calls."""
    def setUp(self):
        self._old = D.TRIGGER_DO_LINES
        D.TRIGGER_DO_LINES = False

    def tearDown(self):
        D.TRIGGER_DO_LINES = self._old

    def test_default_is_off(self):
        import re
        src = open(os.path.join(HERE, "..", "scripts", "doorbell.py"), encoding="utf-8").read()
        self.assertRegex(src, r"(?m)^TRIGGER_DO_LINES = False\b")

    def test_no_trigger_picked_and_no_wake_line(self):
        self.assertIsNone(D._wake_trigger(None, "envoy", None))      # returns before it reads any state
        self.assertIsNone(D.wake_do(None, "x"))

    def test_stored_offers_with_a_trigger_print_no_trigger_line(self):
        offer = {"trigger": "trig_abc", "msg_id": "m-aaaaaaaaaaaa", "role": "guru", "thread": "t-1", "rewake": 1}
        self.assertIsNone(D.rewake_relay_line(offer))
        self.assertIsNone(D.rewake_relay_line(dict(offer, rewake="extra")))
        self.assertIsNone(D.relay_line(offer))                                   # no session to fall back to: no line
        line = D.relay_line(dict(offer, to_session="local_x"))
        self.assertIn("SendMessage to local_x", line); self.assertNotIn("RemoteTrigger", line)
        self.assertNotIn("RemoteTrigger", D.rewake_relay_line(dict(offer, to_session="local_x")))


if __name__ == "__main__":
    unittest.main()
