"""cc 0.14.5: hooks follow the restored agent (transcript banner) when the session map is stale.
Run: python3 -B tests/test_restore_rebind.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _env  # noqa: F401  isolate HOME and HARNESS_* first
import json, os, subprocess, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(HERE, "..", "scripts")
sys.path.insert(0, SCRIPTS)
import harness as H

MODEL = "claude-sonnet-5-5"


class Rebind(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.home = os.path.join(self.tmp, "home")
        os.makedirs(self.home)
        self.h = H.Harness(self.home)
        self.h.role_define("operator", "claude-code", "orchestration")
        self.old = self.h.register(project="orchestration", model=MODEL)["id"]
        self.h.role_assign("operator", "claude-code", self.old)
        self.sid = "sess-1"
        self.A = self.h.register(project="code", model=MODEL, session_id=self.sid)["id"]
        self.h.store.append("session.bound", self.A, {"session_id": self.sid, "agent": self.A})
        self.h.restore("claude-code", model=MODEL, confirmed=True)   # B: new agent, session map still -> A
        st = self.h.state()
        self.B = st.role_holder("claude-code")
        self.assertNotEqual(self.A, self.B)
        self.f = "specs/f.txt"
        self.h.claim(self.B, self.f)

    def transcript(self, agent_id, banner=True):
        st = self.h.state()
        p = os.path.join(self.tmp, "t.jsonl")
        line = (f"╭─ CREW COORDINATOR ──────\n│ ◆ {st.agents[agent_id]['sobriquet']} #{agent_id[:8]}") if banner else "no banner here"
        open(p, "w").write(json.dumps({"message": {"content": line}}) + "\n")
        return p

    def run_hook(self, event, tpath, tool="Edit", cwd="/Users/x/Code"):
        inp = {"session_id": self.sid, "transcript_path": tpath, "cwd": cwd, "tool_name": tool,
               "tool_input": {"file_path": os.path.join(self.home, self.f)}}
        env = dict(os.environ, HARNESS_HOME=self.home)
        r = subprocess.run([sys.executable, "-B", os.path.join(SCRIPTS, "harness.py"), "hook", event],
                           input=json.dumps(inp), capture_output=True, text=True, env=env)
        return r.stdout.strip()

    def test_restored_holder_allowed(self):
        out = self.run_hook("pre-tool-use", self.transcript(self.B))
        self.assertNotIn("deny", out)

    def test_other_holder_still_denied(self):
        C = self.h.register(project="orchestration", model=MODEL)["id"]
        self.h.release(self.B)
        self.h.claim(C, self.f)
        out = self.run_hook("pre-tool-use", self.transcript(self.B))
        self.assertIn("deny", out)

    def test_no_banner_unchanged(self):
        out = self.run_hook("pre-tool-use", self.transcript(self.B, banner=False))
        self.assertIn("deny", out)    # session-bound A, lease held by B

    def test_post_bind_binds_session_to_restored(self):
        resp = f"\u256d\u2500 CREW COORDINATOR \u2500\u2500\u2500\n\u2502 \u25c6 {self.h.state().agents[self.B]['sobriquet']} #{self.B[:8]}\nexpertise: x"
        inp = {"session_id": self.sid, "tool_name": "mcp__plugin_crew-coordinator_crew-coordinator__harness_restore",
               "tool_response": resp}
        env = dict(os.environ, HARNESS_HOME=self.home)
        subprocess.run([sys.executable, "-B", os.path.join(SCRIPTS, "harness.py"), "hook", "post-bind"],
                       input=json.dumps(inp), capture_output=True, text=True, env=env)
        self.assertEqual(self.h.state().sessions.get(self.sid), self.B)
        # now the guard allows B even with no banner in the transcript
        out = self.run_hook("pre-tool-use", self.transcript(self.B, banner=False))
        self.assertNotIn("deny", out)

    def test_post_bind_ignores_other_tools_and_bound_agents(self):
        resp = f"\u256d\u2500 CREW COORDINATOR \u2500\u2500\u2500\n\u2502 \u25c6 x #{self.B[:8]}"
        env = dict(os.environ, HARNESS_HOME=self.home)
        subprocess.run([sys.executable, "-B", os.path.join(SCRIPTS, "harness.py"), "hook", "post-bind"],
                       input=json.dumps({"session_id": self.sid, "tool_name": "mcp__x__harness_send", "tool_response": resp}),
                       capture_output=True, text=True, env=env)
        self.assertEqual(self.h.state().sessions.get(self.sid), self.A)
        D = self.h.register(project="code", model=MODEL, session_id="sess-other")["id"]
        self.h.store.append("session.bound", D, {"session_id": "sess-other", "agent": D})
        subprocess.run([sys.executable, "-B", os.path.join(SCRIPTS, "harness.py"), "hook", "post-bind"],
                       input=json.dumps({"session_id": self.sid, "tool_name": "harness_restore",
                                         "tool_response": f"\u256d\u2500 CREW COORDINATOR \u2500\u2500\u2500\n\u2502 \u25c6 y #{D[:8]}"}), capture_output=True, text=True, env=env)
        self.assertEqual(self.h.state().sessions.get(self.sid), self.A)

    def test_banner_of_agent_bound_elsewhere_ignored(self):
        D = self.h.register(project="code", model=MODEL, session_id="sess-other")["id"]
        self.h.store.append("session.bound", D, {"session_id": "sess-other", "agent": D})
        self.h.release(self.B)
        self.h.claim(D, self.f)
        out = self.run_hook("pre-tool-use", self.transcript(D))
        self.assertIn("deny", out)

    def test_post_tool_use_commits_as_restored(self):
        open(os.path.join(self.home, self.f), "w").write("x") if os.path.isdir(os.path.join(self.home, "specs")) \
            else (os.makedirs(os.path.join(self.home, "specs")), open(os.path.join(self.home, self.f), "w").write("x"))
        self.run_hook("post-tool-use", self.transcript(self.B))
        evs = [e for e in self.h.store.read_all() if e.get("type") == "artifact.versioned"]
        self.assertTrue(evs, "no commit event")
        self.assertEqual(evs[-1].get("actor"), self.B)


if __name__ == "__main__":
    unittest.main()
