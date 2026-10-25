"""cc 0.17.0 R-059: the sync line names the role window; models and surfaces never change it; Haiku silent.
Run: python3 -B tests/test_c170_r059.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _env  # noqa: F401  isolate HOME and HARNESS_* first
import os, sys, unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
import harness as H
import ctx_hook as C


class Line(unittest.TestCase):
    def setUp(self):
        C.CURRENT_ROLE = None

    def test_role_in_the_list(self):
        self.assertEqual(H.ctx_surface_line(None, "claude-opus-5-5", "ops-coder"),
                         "ctx window: 1000k (role ops-coder), plan 600k, handoff 800k")

    def test_old_role_name_resolves(self):
        self.assertIn("1000k (role corpus-envoy)", H.ctx_surface_line(None, "claude-sonnet-5-5", "corpus-envoy"))

    def test_role_outside_the_list_and_no_role(self):
        self.assertEqual(H.ctx_surface_line(None, "claude-sonnet-5-5", "secretary"),
                         "ctx window: 500k (default; role secretary not in the 1M list), plan 300k, handoff 400k")
        self.assertIn("default; no role yet", H.ctx_surface_line(None, "claude-fable-5-1", None))

    def test_surface_env_changes_nothing(self):
        for surf in ("code", "chat", "cowork", ""):
            with mock.patch.dict(os.environ, {"HARNESS_SURFACE": surf}):
                self.assertIn("500k (default", H.ctx_surface_line(None, "claude-sonnet-5-5", "secretary"), surf)

    def test_haiku_has_no_line(self):
        self.assertIsNone(H.ctx_surface_line(None, "claude-haiku-5-5", "ops-coder"))

    def test_ctx_band_matches_hook_for_a_role(self):
        self.assertEqual(H.ctx_band(600000, None, None, "claude-opus-5-5", "envoy"), "plan")
        self.assertEqual(H.ctx_band(300000, None, None, "claude-opus-5-5", "secretary"), "plan")
        self.assertEqual(H.ctx_band(299999, None, None, "claude-opus-5-5", "secretary"), "ok")


if __name__ == "__main__":
    unittest.main()
