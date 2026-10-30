"""cc 0.21.0, critic C1 and D2 (N-5f654 thread): (C1) the SessionStart hook registers compaction successors and spawned chats, so it must
carry the chat-title Do-line too; (D2) notify_undelivered is the reader for the cloud fallback (read-only, each notify id once).
Run: python3 -B tests/test_c210_hook_undelivered.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _env  # noqa: F401  isolate HOME and HARNESS_* first
import json, os, subprocess, sys, tempfile, time, unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(HERE, "..", "scripts")
sys.path.insert(0, SCRIPTS)
import harness as H
import mcp_server as M
import notify as N

MODEL = "claude-sonnet-5-5"


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.home = os.path.join(self.tmp, "Exchange")
        os.makedirs(os.path.join(self.home, "_harness"))
        e = mock.patch.dict(os.environ, {"HARNESS_STATE_CACHE": "0", "HARNESS_HOME": self.home})
        e.start()
        self.addCleanup(e.stop)
        self.h = H.Harness(self.home)
        for r in ("envoy", "critic"):
            self.h.role_define("operator", r, "harness-ops", carry="none")

    def hook(self, **inp):
        env = dict(os.environ)
        for k in ("HARNESS_MODEL", "ANTHROPIC_MODEL"):
            env.pop(k, None)
        r = subprocess.run([sys.executable, "-B", os.path.join(SCRIPTS, "harness.py"), "hook", "session-start"],
                           input=json.dumps(dict({"cwd": self.tmp}, **inp)), capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        return out["hookSpecificOutput"]["additionalContext"], out

    def newest(self):
        return [e for e in self.h.store.read_all() if e["type"] == "agent.registered"][-1]["data"]


class HookTitle(Base):
    def test_c1_a_compaction_successor_gets_the_title_line_for_its_own_new_name(self):
        pred = self.h.register(project="harness-ops", model=MODEL, task="old", role="envoy", session_id="sess-1")["id"]
        self.h.store.append("session.bound", pred, {"session_id": "sess-1", "agent": pred})
        old_name = self.h.state().agents[pred]["sobriquet"]
        ctx, _ = self.hook(session_id="sess-1", source="compact", model={"id": MODEL})
        new = self.newest()
        self.assertEqual(new["predecessor"], pred)                                    # it really was registered by the hook, as a successor
        want = "ENVOY - %s" % new["sobriquet"]
        self.assertIn("Do: set this chat's title", ctx)
        self.assertIn('title "%s"' % want, ctx)
        self.assertIn("ToolSearch select:mcp__ccd_session_mgmt__set_session_title", ctx)
        self.assertNotIn('title "ENVOY - %s"' % old_name, ctx)                         # never the predecessor's name

    def test_a_spawned_chat_with_no_role_gets_no_title_line(self):
        ctx, _ = self.hook(session_id="sess-2", source="startup", model={"id": MODEL})
        self.assertNotIn("set this chat's title", ctx)

    def test_a_plain_resume_does_not_repeat_the_title_line(self):
        a = self.h.register(project="harness-ops", model=MODEL, task="x", role="critic", session_id="sess-3")["id"]
        self.h.store.append("session.bound", a, {"session_id": "sess-3", "agent": a})
        ctx, _ = self.hook(session_id="sess-3", source="resume")
        self.assertNotIn("set this chat's title", ctx)


class Undelivered(Base):
    def setUp(self):
        super().setUp()
        self.a = self.h.register(project="harness-ops", model=MODEL, task="a")["id"]
        cp = os.path.join(self.home, "_harness", "config.json")
        c = json.load(open(cp))
        c["notify"] = {"quiet": "off", "dedupe_minutes": 0}
        json.dump(c, open(cp, "w"))

    def call(self, **a):
        M.BOUND.update(home=None, id=None)
        return M.call(self.h, "harness_admin", dict(a, op="notify_undelivered", agent=self.a))

    def test_d2_an_unsent_push_reaches_the_reader_after_60_minutes_once(self):
        r = M.call(self.h, "harness_send", {"agent": self.a, "to": "operator", "body": "need you", "kind": "question", "subject": "s"})
        nid = r["notify"]["id"]
        self.assertEqual(self.call()["count"], 0)                                      # not yet
        with mock.patch("time.time", return_value=time.time() + 61 * 60):
            out = self.call()
            self.assertEqual([x["id"] for x in out["undelivered"]], [nid])
            self.assertIn(nid, out["text"])
            self.assertEqual(self.call()["count"], 1)                                  # asking again does not duplicate it
        M.call(self.h, "harness_admin", {"op": "notify_sent", "agent": self.a, "args": {"id": nid}})
        with mock.patch("time.time", return_value=time.time() + 61 * 60):
            self.assertEqual(self.call()["count"], 0)                                  # reported: no longer undelivered

    def test_it_writes_nothing(self):
        M.call(self.h, "harness_send", {"agent": self.a, "to": "operator", "body": "need you", "kind": "question", "subject": "s"})
        before = len(self.h.store.read_all())
        with mock.patch("time.time", return_value=time.time() + 4000):
            self.call()
        self.assertEqual(len(self.h.store.read_all()), before)

    def test_it_takes_no_arguments(self):
        with self.assertRaises(H.HarnessError):
            M.BOUND.update(home=None, id=None)
            M.call(self.h, "harness_admin", {"op": "notify_undelivered", "agent": self.a, "args": {"all": True}})

    def test_cli_twin_prints_json_for_the_secretary_script(self):
        M.call(self.h, "harness_send", {"agent": self.a, "to": "operator", "body": "need you", "kind": "question", "subject": "s"})
        r = subprocess.run([sys.executable, "-B", os.path.join(SCRIPTS, "harness.py"), "notify-undelivered", "--json"],
                           capture_output=True, text=True, env=dict(os.environ))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout), [])                                     # nothing is 60 minutes old yet; valid JSON list


if __name__ == "__main__":
    unittest.main()
