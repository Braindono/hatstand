"""cc 0.14.4: ctx hook table, model x surface (D-5d771, amended D-8ee87). Run: python3 -B tests/test_ctx_table.py"""
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

    def lim(self, model, path=None):
        L = H.limits(model, path)
        return L["window"], L["plan_tok"], L["handoff_tok"]


class Table(Base):
    def test_sonnet_code_1m(self):
        self.assertEqual(self.lim(SONNET, CODE_PATH), (1000000, 600000, 800000))

    def test_sonnet_chat_and_cowork_500k(self):
        os.environ["HARNESS_SURFACE"] = "chat"
        self.assertEqual(self.lim(SONNET), (500000, 300000, 400000))
        os.environ.pop("HARNESS_SURFACE")
        self.assertEqual(self.lim(SONNET, COWORK_PATH), (500000, 300000, 400000))

    def test_surface_unknown_is_conservative(self):
        self.assertEqual(self.lim(SONNET), (500000, 300000, 400000))
        self.assertEqual(self.lim(SONNET, "/somewhere/else.jsonl"), (500000, 300000, 400000))

    def test_env_surface_code_is_positive(self):
        os.environ["HARNESS_SURFACE"] = "code"
        self.assertEqual(self.lim(SONNET), (1000000, 600000, 800000))

    def test_opus_code_500k(self):
        self.assertEqual(self.lim(OPUS, CODE_PATH), (500000, 300000, 400000))

    def test_unlisted_200k_60_80(self):
        self.assertEqual(self.lim("claude-other-1", CODE_PATH), (200000, 120000, 160000))

    def test_no_config_file(self):
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "_harness")))
        self.assertEqual(self.lim(SONNET, CODE_PATH), (1000000, 600000, 800000))


class Overrides(Base):
    def test_window_by_model_wins_any_surface(self):
        self.config({"ctx_window_by_model": {SONNET: 250000}})
        self.assertEqual(self.lim(SONNET, CODE_PATH), (250000, 150000, 200000))

    def test_ctx_table_merges(self):
        self.config({"ctx_table": {SONNET: {"window": {"code": 800000}, "plan": 0.5}}})
        self.assertEqual(self.lim(SONNET, CODE_PATH), (800000, 400000, 640000))
        self.assertEqual(self.lim(SONNET, COWORK_PATH), (500000, 250000, 400000))

    def test_absolute_token_override(self):
        self.config({"ctx_plan_tokens": 100000, "ctx_handoff_tokens": 150000})
        self.assertEqual(self.lim(SONNET, CODE_PATH), (1000000, 100000, 150000))

    def test_zero_tokens_do_not_turn_off(self):
        self.config({"ctx_plan_tokens": 0, "ctx_handoff_tokens": 0})
        self.assertEqual(self.lim(SONNET, CODE_PATH), (1000000, 600000, 800000))

    def test_legacy_pct_only_for_unlisted(self):
        self.config({"ctx_plan": 0.7, "ctx_handoff": 0.85})
        self.assertEqual(self.lim(SONNET, CODE_PATH), (1000000, 600000, 800000))
        self.assertEqual(self.lim("claude-other-1"), (200000, 140000, 170000))


class Bands(Base):
    def test_band_for_uses_table(self):
        self.assertEqual(H.band_for(599999, model=SONNET, path=CODE_PATH)[0], "ok")
        self.assertEqual(H.band_for(600000, model=SONNET, path=CODE_PATH)[0], "plan")
        self.assertEqual(H.band_for(800000, model=SONNET, path=CODE_PATH)[0], "now")
        self.assertEqual(H.band_for(300000, model=SONNET)[0], "plan")    # unknown surface

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
        g = self._gauge(SONNET, 650000)
        self.assertIn("plan 600k", g)
        self.assertIn("handoff 800k", g)
        self.assertIn("1000k window", g)

    def test_haiku_prints_nothing(self):
        os.environ["HARNESS_SURFACE"] = "code"
        for n in (50000, 100000, 130000, 180000):
            self.assertIsNone(self._gauge(HAIKU, n))

    def test_haiku_cold_silent(self):
        p = self._transcript(HAIKU, 150000)
        self.assertIsNone(H.cold({"transcript_path": p}, 1.9e9))


if __name__ == "__main__":
    unittest.main()
