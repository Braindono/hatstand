"""Context windows (0.16.2 item 11, replaced by 0.17.0 R-059): neither model nor surface changes a window.
Run: python3 -B tests/test_cc162_ctx_windows.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _env  # noqa: F401  isolate HOME and HARNESS_* first
import os, sys, unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
import ctx_hook as C


def lim(model, surf):
    env = {"HARNESS_SURFACE": surf} if surf else {}
    with mock.patch.dict(os.environ, env, clear=False):
        if not surf:
            os.environ.pop("HARNESS_SURFACE", None)
        C.CURRENT_ROLE = None
        return C.limits(model, None, {})


class Windows(unittest.TestCase):
    def test_code_surface_no_longer_raises_the_window(self):     # 0.17.0 R-059: no role -> 500k for every model
        for m in ("claude-sonnet-5-5", "claude-opus-5-5"):
            l = lim(m, "code")
            self.assertEqual((l["window"], l["plan_tok"], l["handoff_tok"]), (500000, 350000, 425000), m)

    def test_chat_and_cowork_keep_the_smaller_window(self):
        for surf in ("chat", "cowork"):
            for m in ("claude-opus-5-5", "claude-sonnet-5-5"):
                self.assertEqual(lim(m, surf)["window"], 500000, (m, surf))

    def test_unknown_surface_uses_the_smallest_window(self):
        self.assertEqual(lim("claude-opus-5-5", None)["window"], 500000)

    def test_haiku_unchanged_and_silent(self):
        l = lim("claude-haiku-5-5", "code")
        self.assertEqual(l["window"], 200000)
        self.assertTrue(l["silent"])


if __name__ == "__main__":
    unittest.main()
