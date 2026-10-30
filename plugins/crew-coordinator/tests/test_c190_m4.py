"""cc 0.19.0 M4 (R-106 + E14): one context gauge. ctx_hook.limits() is the only source of the window and the plan/handoff
shares (defaults 0.70 / 0.85); harness.ctx_band and ctx_surface_line call it, with no second 0.6/0.8 table; harness-critic gets
the 1M window; config overrides the defaults. Run: python3 -B tests/test_c190_m4.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _env  # noqa: F401  isolate HOME and HARNESS_* first
import json, os, re, shutil, sys, tempfile, unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(HERE, "..", "scripts")
sys.path.insert(0, SCRIPTS)
import harness as H
import ctx_hook as C

OPUS = "claude-opus-5-5"
ROLES = ("envoy", "curator", "ops-coder", "reviewer-coder", "harness-critic", "steward", "secretary", "dreamer", None)


class Gauge(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.home = os.path.join(self.tmp, "Exchange")
        os.makedirs(os.path.join(self.home, "_harness"))
        e = mock.patch.dict(os.environ, {"HARNESS_HOME": self.home, "HARNESS_STATE_DIR": os.path.join(self.tmp, "state")})
        e.start()
        self.addCleanup(e.stop)

    def config(self, d):
        with open(os.path.join(self.home, "_harness", "config.json"), "w") as f:
            json.dump(d, f)

    def test_defaults_are_70_85_with_the_role_windows(self):
        want = {"envoy": 1000000, "curator": 1000000, "ops-coder": 1000000, "reviewer-coder": 1000000, "harness-critic": 1000000,
                "steward": 500000, "secretary": 500000, "dreamer": 500000, None: 500000}
        for role in ROLES:
            L = C.limits(OPUS, None, {}, role)
            w = want[role]
            self.assertEqual((L["window"], L["plan_tok"], L["handoff_tok"]), (w, int(w * 0.7), int(w * 0.85)), role)

    def test_harness_critic_window_and_the_old_name_alias(self):
        self.assertEqual(C.limits(OPUS, None, {}, "harness-critic")["window"], 1000000)
        self.assertEqual(C.role_window("harness-critic", {}), 1000000)

    def test_ctx_band_and_limits_agree_for_every_role_with_and_without_config(self):
        for cfg in ({}, {"ctx_plan": 0.5, "ctx_handoff": 0.75}, {"ctx_plan_tokens": 100000, "ctx_handoff_tokens": 200000},
                    {"ctx_window": 400000}, {"ctx_role_windows": {"steward": 800000}}):
            self.config(cfg)
            for role in ROLES:
                L = C.limits(OPUS, None, H.load_config(self.home), role)
                for ctx in (L["plan_tok"] - 1, L["plan_tok"], L["handoff_tok"] - 1, L["handoff_tok"]):
                    want = "now" if ctx >= L["handoff_tok"] else "plan" if ctx >= L["plan_tok"] else "ok"
                    self.assertEqual(H.ctx_band(ctx, 0, self.home, OPUS, role), want, (cfg, role, ctx))

    def test_config_overrides_the_defaults(self):
        self.config({"ctx_plan": 0.6, "ctx_handoff": 0.8})
        L = C.limits(OPUS, None, H.load_config(self.home), "envoy")
        self.assertEqual((L["plan_tok"], L["handoff_tok"]), (600000, 800000))
        self.config({"ctx_role_windows": {"envoy": 600000}})
        self.assertEqual(C.limits(OPUS, None, H.load_config(self.home), "envoy")["window"], 600000)
        self.assertEqual(C.limits(OPUS, None, H.load_config(self.home), "harness-critic")["window"], 500000)   # a config map replaces the default map

    def test_the_sync_window_line_uses_the_same_numbers(self):
        self.assertEqual(H.ctx_surface_line(self.home, OPUS, "harness-critic"), "ctx window: 1000k (role harness-critic), plan 700k, handoff 850k")
        self.assertEqual(H.ctx_surface_line(self.home, OPUS, "steward"),
                         "ctx window: 500k (default; role steward not in the 1M list), plan 350k, handoff 425k")

    def test_no_second_gauge_in_harness_py(self):
        src = open(os.path.join(SCRIPTS, "harness.py"), encoding="utf-8").read()
        body = src[src.index("def ctx_band("):src.index("def path_link(")]
        self.assertNotRegex(body, r"\*\s*0\.[0-9]")                    # no literal share in ctx_band
        self.assertIn("band_for", body)
        self.assertEqual(re.findall(r"\bctx_plan\b[^\n]*0\.[0-9]+", src), [])   # harness.py holds no default share either


if __name__ == "__main__":
    unittest.main(verbosity=1)
