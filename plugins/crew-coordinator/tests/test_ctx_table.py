"""ctx hook windows. cc 0.17.0 (R-059, D-2b929): window by role only, model and surface never matter; Haiku silent.
Run: python3 -B tests/test_ctx_table.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _env  # noqa: F401  isolate HOME and HARNESS_* first
import json, os, sys, tempfile, unittest, uuid

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import ctx_hook as H

SONNET, OPUS, HAIKU = "claude-sonnet-5-5", "claude-opus-5-5", "claude-haiku-5-5"
CODE_PATH = "/Users/x/.claude/projects/-p/abc.jsonl"
COWORK_PATH = "/Users/x/Library/Application Support/Claude/local-agent-mode-sessions/a/b/.claude/projects/-p/abc.jsonl"


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.saved = {k: os.environ.get(k) for k in ("HARNESS_HOME", "HARNESS_SURFACE", "HARNESS_CTX_WINDOW")}
        os.environ["HARNESS_HOME"] = self.tmp    # empty: no _harness/config.json
        os.environ.pop("HARNESS_SURFACE", None)
        os.environ.pop("HARNESS_CTX_WINDOW", None)

    def tearDown(self):
        for k, v in self.saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def config(self, d):
        os.makedirs(os.path.join(self.tmp, "_harness"), exist_ok=True)
        json.dump(d, open(os.path.join(self.tmp, "_harness", "config.json"), "w"))

    def lim(self, model, path=None, role=None):
        H.CURRENT_ROLE = None
        L = H.limits(model, path, None, role)
        return L["window"], L["plan_tok"], L["handoff_tok"]


class Table(Base):
    def test_role_in_the_1m_list_any_model_any_surface(self):
        for m in (SONNET, OPUS, "claude-fable-5-1"):
            for path in (CODE_PATH, COWORK_PATH, None, "/somewhere/else.jsonl"):
                self.assertEqual(self.lim(m, path, "ops-coder"), (1000000, 700000, 850000), (m, path))

    def test_other_role_or_no_role_gets_500k_any_model_any_surface(self):
        for role in ("secretary", "letters-manager", None):
            for m in (SONNET, OPUS, "claude-other-1"):
                for path in (CODE_PATH, COWORK_PATH, None):
                    self.assertEqual(self.lim(m, path, role), (500000, 350000, 425000), (role, m, path))

    def test_surface_env_no_longer_changes_the_window(self):
        for surf in ("code", "chat", "cowork"):
            os.environ["HARNESS_SURFACE"] = surf
            self.assertEqual(self.lim(SONNET, None, "secretary"), (500000, 350000, 425000), surf)
            self.assertEqual(self.lim(OPUS, None, "envoy"), (1000000, 700000, 850000), surf)

    def test_no_config_file(self):
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "_harness")))
        self.assertEqual(self.lim(SONNET, CODE_PATH, "curator"), (1000000, 700000, 850000))

    def test_no_per_model_table_left(self):
        self.assertFalse(hasattr(H, "CTX_TABLE"))


class Overrides(Base):
    def test_legacy_model_keys_are_ignored(self):
        self.config({"ctx_window_by_model": {SONNET: 250000}, "ctx_table": {SONNET: {"window": {"code": 800000}}}})
        self.assertEqual(self.lim(SONNET, CODE_PATH, "secretary"), (500000, 350000, 425000))
        self.assertEqual(self.lim(SONNET, CODE_PATH, "envoy"), (1000000, 700000, 850000))

    def test_default_window_from_config(self):
        self.config({"ctx_window": 400000})
        self.assertEqual(self.lim(SONNET, None, "secretary"), (400000, 280000, 340000))
        self.assertEqual(self.lim(SONNET, None, "envoy")[0], 1000000)   # the role window is not the default

    def test_absolute_token_override(self):
        self.config({"ctx_plan_tokens": 100000, "ctx_handoff_tokens": 150000})
        self.assertEqual(self.lim(SONNET, CODE_PATH, "envoy"), (1000000, 100000, 150000))

    def test_zero_tokens_do_not_turn_off(self):
        self.config({"ctx_plan_tokens": 0, "ctx_handoff_tokens": 0})
        self.assertEqual(self.lim(SONNET, CODE_PATH, "envoy"), (1000000, 700000, 850000))

    def test_shares_from_config_apply_to_every_role(self):
        self.config({"ctx_plan": 0.7, "ctx_handoff": 0.85})
        self.assertEqual(self.lim(SONNET, CODE_PATH, "envoy"), (1000000, 700000, 850000))
        self.assertEqual(self.lim(SONNET, None, "secretary"), (500000, 350000, 425000))


class Bands(Base):
    def test_band_for_uses_the_role_window(self):
        H.CURRENT_ROLE = None
        self.assertEqual(H.band_for(699999, model=SONNET, path=CODE_PATH, role="envoy")[0], "ok")
        self.assertEqual(H.band_for(700000, model=SONNET, path=CODE_PATH, role="envoy")[0], "plan")
        self.assertEqual(H.band_for(850000, model=SONNET, path=CODE_PATH, role="envoy")[0], "now")
        self.assertEqual(H.band_for(350000, model=SONNET, path=CODE_PATH)[0], "plan")    # no role: the 500k window

    def test_haiku_silent_at_any_size(self):
        for n in (1000, 90000, 120000, 190000, 400000):
            self.assertEqual(H.band_for(n, model=HAIKU, path=CODE_PATH)[0], "ok")

    def test_ctx_band_matches_hook(self):
        import harness
        os.environ["HARNESS_SURFACE"] = "code"
        for model, n in ((SONNET, 600000), (SONNET, 800000), (OPUS, 300000), (OPUS, 100000), (HAIKU, 190000)):
            self.assertEqual(harness.ctx_band(n, None, self.tmp, model),
                             H.band_for(n, model=model, c={})[0], (model, n))


class Printed(Base):
    def _transcript(self, model, n, ts="2026-10-13T12:00:00Z"):
        p = os.path.join(self.tmp, "t.jsonl")
        rec = {"timestamp": ts, "message": {"model": model, "usage": {"input_tokens": n}}}
        open(p, "w").write(json.dumps(rec) + "\n")
        return p

    def _gauge(self, model, n, sid="g1"):
        p = self._transcript(model, n)
        return H.gauge({"session_id": f"{sid}-{uuid.uuid4().hex}", "transcript_path": p}, p)

    def test_text_has_computed_k(self):
        os.environ["HARNESS_SURFACE"] = "code"
        H.CURRENT_ROLE = None
        g = self._gauge(SONNET, 350000)          # no role known: the one 500k window, whatever the surface says
        self.assertIn("plan 350k", g)
        self.assertIn("handoff 425k", g)
        self.assertIn("500k window", g)

    def test_haiku_prints_nothing(self):
        os.environ["HARNESS_SURFACE"] = "code"
        for n in (50000, 100000, 130000, 180000):
            self.assertIsNone(self._gauge(HAIKU, n))

    def test_haiku_cold_silent(self):
        p = self._transcript(HAIKU, 150000)
        self.assertIsNone(H.cold({"transcript_path": p}, 1.9e9))


if __name__ == "__main__":
    unittest.main()
