"""cc 0.16.3: role-keyed 1M context window and the Opus code window revert. Run: python3 -B tests/test_cc163_role_window.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _env  # noqa: F401  isolate HOME and HARNESS_* first
import json, os, sys, unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
import ctx_hook as C

OPUS, SONNET, HAIKU = "claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5"


def lim(model, role=None, c=None, surf=None):
    env = {"HARNESS_SURFACE": surf} if surf else {}
    with mock.patch.dict(os.environ, env):
        if not surf:
            os.environ.pop("HARNESS_SURFACE", None)
        C.CURRENT_ROLE = None
        return C.limits(model, None, c if c is not None else {}, role)


class RoleWindow(unittest.TestCase):
    def test_coder_envoy_curator_get_1m_on_unknown_surface_any_model(self):
        for role in ("ops-coder", "design-coder", "envoy", "curator"):
            for m in (SONNET, OPUS):
                l = lim(m, role)
                self.assertEqual((l["window"], l["plan_tok"], l["handoff_tok"]), (1000000, 700000, 850000), (role, m))

    def test_other_roles_keep_the_table(self):
        for role in ("secretary", "letters-manager", "design-system", None):
            self.assertEqual(lim(SONNET, role)["window"], 500000, role)
            self.assertEqual(lim(OPUS, role)["window"], 500000, role)

    def test_no_role_gets_500k_on_code_for_every_model(self):     # 0.17.0 R-059 (was: Sonnet 1M by model on code)
        self.assertEqual(lim(OPUS, None, surf="code")["window"], 500000)
        self.assertEqual(lim(SONNET, None, surf="code")["window"], 500000)

    def test_old_role_names_resolve_through_the_alias_layer(self):
        for old in ("corpus-envoy", "skill-curation-lead", "claude-code"):
            self.assertEqual(lim(SONNET, old)["window"], 1000000, old)
        self.assertEqual(lim(SONNET, "corpus-steward")["window"], 500000)       # steward is not in the list

    def test_config_extends_or_empties_the_list(self):
        self.assertEqual(lim(SONNET, "secretary", {"ctx_role_windows": {"secretary": 800000}})["window"], 800000)
        self.assertEqual(lim(SONNET, "envoy", {"ctx_role_windows": {}})["window"], 500000)

    def test_token_overrides_win_model_keys_do_not(self):
        self.assertEqual(lim(SONNET, "envoy", {"ctx_window_by_model": {SONNET: 300000}})["window"], 1000000)   # 0.17.0: model keys ignored
        l = lim(SONNET, "envoy", {"ctx_plan_tokens": 111000, "ctx_handoff_tokens": 222000})
        self.assertEqual((l["plan_tok"], l["handoff_tok"]), (111000, 222000))

    def test_haiku_stays_silent_and_small(self):
        l = lim(HAIKU, "ops-coder")
        self.assertTrue(l["silent"])
        self.assertEqual(l["plan_tok"], 0)

    def test_no_banner_no_role_unchanged(self):
        self.assertEqual(lim(SONNET, None)["window"], 500000)

    def test_current_role_global_is_used_when_no_role_argument(self):
        C.CURRENT_ROLE = "envoy"
        try:
            self.assertEqual(C.limits(SONNET, None, {})["window"], 1000000)
        finally:
            C.CURRENT_ROLE = None


class BannerRole(unittest.TestCase):
    def inp(self, banner_role, sid="s-role"):
        body = (f"╭─ CREW COORDINATOR ───\n│ ◆ Misty Rasp #2ecb35dd · {banner_role} · harness-ops\n"
                f"│ id: {'a' * 64}\n╰───\n")
        return {"session_id": sid, "tool_name": "mcp__x__harness_register", "tool_input": {}, "tool_response": body,
                "hook_event_name": "PostToolUse"}

    def test_role_parsed_from_banner_kept_and_reset(self):
        i = self.inp("ops-coder")
        C.on_tool(i)
        self.assertEqual(C.load_note(C.note_path(i)).get("role"), "ops-coder")
        j = self.inp("role unset")
        C.on_tool(j)
        self.assertIsNone(C.load_note(C.note_path(j)).get("role"))

    def test_successor_with_a_different_role_resets(self):
        C.on_tool(self.inp("envoy", "s-r2"))
        C.on_tool(self.inp("secretary", "s-r2"))
        self.assertEqual(C.load_note(C.note_path(self.inp("x", "s-r2"))).get("role"), "secretary")


if __name__ == "__main__":
    unittest.main()
