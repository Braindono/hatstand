"""cc 0.14.3: protocol skill states the inbox defaults. Run: python3 -B tests/test_inbox_default.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _env  # noqa: F401  isolate HOME and HARNESS_* first
import os, unittest

P = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "skills", "protocol", "SKILL.md")


class InboxDefault(unittest.TestCase):
    def test_protocol_inbox_default(self):
        t = open(P, encoding="utf-8").read()
        self.assertIn("harness_inbox", t)
        self.assertIn("wait=45", t)
        self.assertLessEqual(len(t.splitlines()), 60)


if __name__ == "__main__":
    unittest.main()
