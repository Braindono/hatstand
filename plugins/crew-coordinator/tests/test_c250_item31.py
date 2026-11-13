"""cc 0.25.0 item 31: the SessionStart hook reuses the chat's live agent with a role (the item 25 function); registering a role agent retires the
chat's idle hook id; two chats keep two ids. Run: python3 -B tests/test_c250_item31.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _env  # noqa: F401  isolate HOME and HARNESS_* first
import json, os, subprocess, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(HERE, "..", "scripts")
sys.path.insert(0, SCRIPTS)
import harness as H

MODEL = "claude-sonnet-5-5"


class Item31(unittest.TestCase):
    def setUp(self):
        self.home = os.path.join(tempfile.mkdtemp(), "h")
        os.makedirs(os.path.join(self.home, "_harness"))
        self.st = tempfile.mkdtemp()
        self.h = H.Harness(self.home)
        self.h.role_define("operator", "ops-coder", "harness-ops", carry="none")

    def start(self, sid, host, source="startup"):
        env = dict(os.environ, HARNESS_HOME=self.home, HARNESS_STATE_DIR=self.st, CLAUDE_CODE_HOST_SESSION_ID=host)
        r = subprocess.run([sys.executable, "-B", os.path.join(SCRIPTS, "harness.py"), "hook", "session-start"],
                           input=json.dumps({"session_id": sid, "source": source, "cwd": "/x/harness-ops"}), capture_output=True, text=True, env=env)
        return r.stdout

    def live(self, host):
        st = H.Harness(self.home).state()
        return [a["id"] for a in st.agents.values() if a.get("host_session_id") == host and a["status"] in ("active", "idle")]

    def test_restore_then_hook_leaves_one_live_agent_in_the_chat(self):
        self.start("s-A1", "local_A")
        self.assertEqual(len(self.live("local_A")), 1)                           # the hook id
        hook_id = self.live("local_A")[0]
        role_agent = self.h.register(project="harness-ops", model=MODEL, task="t", role="ops-coder", host_session_id="local_A")["id"]
        self.assertEqual(self.live("local_A"), [role_agent])                     # registering marked the hook id superseded
        self.assertEqual(H.Harness(self.home).state().agents[hook_id]["status"], "superseded")
        out = self.start("s-A2", "local_A")                                      # a later SessionStart in the same chat
        self.assertEqual(self.live("local_A"), [role_agent])                     # reused: no second id
        self.assertIn("reused", out)

    def test_two_chats_keep_two_ids(self):
        self.start("s-A1", "local_A")
        self.start("s-B1", "local_B")
        a, b = self.live("local_A"), self.live("local_B")
        self.assertEqual((len(a), len(b)), (1, 1))
        self.assertNotEqual(a, b)
        self.h.register(project="harness-ops", model=MODEL, task="t", role="ops-coder", host_session_id="local_A")
        self.assertEqual(self.live("local_B"), b)                                # chat B's id is untouched
        self.assertEqual(len(self.live("local_A")), 1)

    def test_one_function_serves_item_25_and_the_hook(self):
        self.assertEqual(H.live_role_agents_for_host(H.Harness(self.home).state(), None), [])
        a = self.h.register(project="harness-ops", model=MODEL, task="t", role="ops-coder", host_session_id="local_Z")["id"]
        self.assertEqual(H.live_role_agents_for_host(self.h.state(), "local_Z"), [a])
        src = open(os.path.join(SCRIPTS, "mcp_server.py"), encoding="utf-8").read()
        self.assertIn("live_role_agents_for_host", src)


if __name__ == "__main__":
    unittest.main()
