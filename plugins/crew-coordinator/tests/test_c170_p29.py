"""cc 0.17.0 P-2.9: restore digest ceiling (config digest_ceiling_tokens) and C-live failing a stage on a breach.
Spec: skill-curation/specs/2026-10-24-stage2-context-loss.md section 5; plan v2 stage 2 (critic 7).
Run: python3 -B tests/test_c170_p29.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _env  # noqa: F401  isolate HOME and HARNESS_* first
import contextlib, io, json, os, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
sys.path.insert(0, HERE)
import harness as H
import c_live as C

LM = C.LM
MODEL = "claude-opus-5-5"


class CeilingRules(unittest.TestCase):
    def test_override_int_dict_star_and_budget_cap(self):
        self.assertEqual(LM.ceiling_for({"digest_ceiling_tokens": 900}, "envoy"), 900)
        cfg = {"digest_ceiling_tokens": {"envoy": 1700, "*": 1100}, "restore_budget": 2000}
        self.assertEqual(LM.ceiling_for(cfg, "envoy", old_tokens=100), 1700)      # the operator override wins over growth
        self.assertEqual(LM.ceiling_for(cfg, "new-role"), 1100)
        self.assertEqual(LM.ceiling_for({"digest_ceiling_tokens": {"envoy": 2061}, "restore_budget": 2000}, "envoy"), 2000)
        for bad in (None, "1500", True, -1, 0, {"x": 5}):
            self.assertEqual(LM.ceiling_for({"digest_ceiling_tokens": bad}, "envoy"), 2000, bad)   # budget only

    def test_rule_a_growth_on_the_same_snapshot_with_caps(self):
        cfg = dict(H.DEFAULT_CONFIG)
        self.assertEqual(LM.ceiling_for(cfg, "ops-coder", old_tokens=1154), 1385)   # ceil(1154 x 1.2)
        self.assertEqual(LM.ceiling_for(cfg, "envoy", old_tokens=1552), 1794)       # cap below 1863
        self.assertEqual(LM.ceiling_for(cfg, "dreamer", old_tokens=1900), 2000)     # restore_budget
        self.assertEqual(LM.ceiling_for(dict(cfg, digest_growth_max=1.1), "dreamer", old_tokens=1000), 1100)

    def test_default_config_is_rule_a(self):
        d = H.DEFAULT_CONFIG
        self.assertEqual(d["digest_growth_max"], 1.2)
        self.assertEqual(d["digest_caps"], {"envoy": 1794, "curator": 1794})
        self.assertIsNone(d["digest_ceiling_tokens"])

    def test_check_flags_over_and_cut(self):
        new = {"roles": {"a": {"digest_head_tokens": 1200}, "b": {"digest_head_tokens": 1201},
                         "c": {"digest_head_tokens": 500, "digest_cut": True}, "d": {"holder": None}}}
        old = {"roles": {"a": {"digest_head_tokens": 1000}, "b": {"digest_head_tokens": 1000}, "c": {"digest_head_tokens": 500}}}
        cc = LM.ceiling_check(new, dict(H.DEFAULT_CONFIG), old=old)
        self.assertEqual(cc["breaches"], ["b", "c"])
        self.assertEqual(cc["roles"]["a"], {"tokens": 1200, "old": 1000, "ceiling": 1200, "cut": False})
        self.assertNotIn("d", cc["roles"])
        self.assertEqual(LM.ceiling_check(new, {})["breaches"], ["c"])      # no old tree, no override: budget and cut only

    def test_report_exit_codes(self):
        with contextlib.redirect_stdout(io.StringIO()) as o:
            self.assertEqual(C._ceiling_report({"roles": {"a": {"tokens": 9, "ceiling": 10, "cut": False}}, "breaches": []}), 0)
        self.assertIn("ceiling: ok (1 roles); least headroom a 9/10", o.getvalue())
        with contextlib.redirect_stdout(io.StringIO()) as o:
            self.assertEqual(C._ceiling_report({"roles": {"a": {"tokens": 11, "ceiling": 10, "cut": False}}, "breaches": ["a"]}), 2)
        self.assertIn("CEILING BREACH (stage fails): a 11 > 10", o.getvalue())


class CLiveExit(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.home = os.path.join(self.tmp, "Exchange")
        os.makedirs(os.path.join(self.home, "_harness"))
        h = H.Harness(self.home)
        h.role_define("operator", "ops-coder", "harness-ops")
        a = h.register(project="harness-ops", model=MODEL)["id"]
        h.role_assign("operator", "ops-coder", a)

    def run_c(self, ceiling):
        with open(os.path.join(self.home, "_harness", "config.json"), "w") as f:
            json.dump({"digest_ceiling_tokens": ceiling}, f)
        with contextlib.redirect_stdout(io.StringIO()) as o:
            rc = C.main(["--home", self.home])
        return rc, o.getvalue()

    def test_breach_fails_with_exit_2(self):
        rc, out = self.run_c(50)
        self.assertEqual(rc, 2)
        self.assertIn("CEILING BREACH (stage fails): ops-coder", out)

    def test_under_ceiling_passes(self):
        rc, out = self.run_c({"ops-coder": 1900, "*": 1900})
        self.assertEqual(rc, 0)
        self.assertIn("ceiling: ok (1 roles)", out)


if __name__ == "__main__":
    unittest.main()
