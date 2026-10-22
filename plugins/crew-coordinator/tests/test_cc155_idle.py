"""cc 0.15.5 WP2f: a skipped idle-wake fire re-arms itself; an idle fire hands off and does not. Run: python3 -B tests/test_cc155_idle.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _env  # noqa: F401  isolate HOME and HARNESS_* first
import os, re, sys, tempfile, unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import ctx_hook as C

SID = "s-idle"


class IdleRearm(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._env = mock.patch.dict(os.environ, {"HARNESS_STATE_DIR": self.tmp})
        self._env.start()
        self.addCleanup(self._env.stop)
        self.inp = {"session_id": SID, "cwd": "/x/proj"}

    def arm(self, nonce="aaa111", arm_ts=1000, last=None, **kw):
        s = {"on": True, "trig_id": "trig_1", "nonce": nonce, "arm_ts": arm_ts, "project": "proj"}
        if last is not None:
            s["last_prompt_ts"] = last
        s.update(kw)
        C.save_note(C.idle_path(self.inp), s)

    def fire(self, nonce, t):
        return C.idle_prompt(dict(self.inp, prompt=f"{C.WAKE} {nonce}"), t, False)

    def state(self):
        return C.load_note(C.idle_path(self.inp))

    def test_fire_with_operator_active_rearms(self):
        self.arm(last=2000)
        out = self.fire("aaa111", 4000)
        self.assertIn("Re-armed", out)
        m = re.search(r'send_later\(delay_minutes=(\d+), name="idle-handoff proj (\w+)"', out)
        self.assertTrue(m)
        self.assertNotEqual(m.group(2), "aaa111")           # fresh id
        self.assertEqual(self.state()["nonce"], m.group(2))

    def test_repeated_skips_keep_rearming(self):
        self.arm(last=2000)
        first = self.fire("aaa111", 4000)
        n1 = self.state()["nonce"]
        C.save_note(C.idle_path(self.inp), dict(self.state(), trig_id="trig_2", last_prompt_ts=5000))   # operator spoke, timer captured
        second = self.fire(n1, 8000)
        self.assertIn("Re-armed", second)                   # the old "once" limit is gone
        self.assertNotIn("Do not re-arm", second)

    def test_fire_when_idle_hands_off_without_rearm(self):
        self.arm(last=500)
        out = self.fire("aaa111", 4000)
        self.assertEqual(out, "Idle wake. Run /handoff and stop.")
        self.assertNotIn("send_later", out)

    def test_two_fires_do_not_stack(self):
        self.arm(last=2000)
        self.fire("aaa111", 4000)                           # re-arms; nonce replaced
        again = self.fire("aaa111", 4001)                   # the same (now stale) fire again
        self.assertIn("Stale idle wake", again)
        self.assertNotIn("send_later", again)

    def test_handed_off_chat_never_rearms(self):
        self.arm(last=2000, handed_off=True)
        out = self.fire("aaa111", 4000)
        self.assertIn("Stale idle wake", out)
        self.assertNotIn("send_later", out)

    def test_wrapper_text_names_the_rule(self):
        self.arm(last=2000)
        out = C.idle_prompt(dict(self.inp, prompt="<task-notification>\n1 unread notification"), 4000, False)
        self.assertIn("Re-arm only when the wake is skipped because the operator was active", out)
        self.assertNotIn("Never re-arm", out)


class NoDeletes(IdleRearm):
    """WP2i (D-314f2): plugin text never asks for delete_trigger or list_triggers."""
    BAD = ("delete_trigger", "list_triggers")

    def test_emitted_text_is_clean(self):
        self.arm(last=2000, arm_ts=0, fires_at=10**9)
        arm_msg = C.idle_prompt(dict(self.inp, prompt="hello"), 100000, False)       # re-arm over an armed id
        self.assertIn("update_trigger(trigger_id=\"trig_1\", enabled=false)", arm_msg)
        self.arm(last=2000)
        texts = [arm_msg, self.fire("aaa111", 4000),
                 C.idle_prompt(dict(self.inp, prompt="<task-notification>\n1 unread notification"), 4000, False)]
        self.arm(last=500)
        for resp in ("handoff-ok m-0123456789ab\nsent", ):
            r = C.idle_tool({"session_id": SID, "tool_name": "mcp__x__harness_handoff", "tool_input": {}, "tool_response": resp}, 5000)
            texts.append(r or "")
        self.assertIn("update_trigger", texts[-1])
        for t in [x for x in texts if x]:
            for b in self.BAD:
                self.assertNotIn(b, t)

    def test_skills_and_docs_are_clean(self):
        root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
        for rel in ("skills/idle-wake/SKILL.md", "skills/handoff/SKILL.md"):
            t = open(os.path.join(root, rel), encoding="utf-8").read()
            for b in self.BAD:
                self.assertNotIn(b, t, rel)
        self.assertIn("cleanup runner", open(os.path.join(root, "skills/idle-wake/SKILL.md"), encoding="utf-8").read())
        self.assertIn("cleanup runner", open(os.path.join(root, "docs/BACKEND.md"), encoding="utf-8").read())


if __name__ == "__main__":
    unittest.main()
