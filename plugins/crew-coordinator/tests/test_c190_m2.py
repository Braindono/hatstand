"""cc 0.19.0 M2 (D-b751f auto-retire, D-c8590 c3): a role claim retires the superseded chat. Marker file
_harness/retired_sessions.json, a standalone PreToolUse guard (scripts/retire_guard.py), RETIRED replies on harness calls,
a per-session last-hook timestamp that decides whether the holder is still active, retire_session on the successor.
Run: python3 -B tests/test_c190_m2.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _env  # noqa: F401  isolate HOME and HARNESS_* first
import json, os, subprocess, sys, threading, time, unittest

from test_c190_m1 import Base, SCRIPTS
import harness as H
import ctx_hook as C
import mcp_server as M

MODEL = "claude-opus-5-5"
PFX = "mcp__plugin_crew-coordinator_crew-coordinator__"


class Retire(Base):
    def setUp(self):
        super().setUp()
        self.h.store.append("role.defined", "operator", {"role": "envoy", "project": "harness-ops", "carry": "none"})
        self.assertTrue(self.h._no_carry(self.h.state(), "envoy"))
        self.a = self.claim("sA", "local_A")

    def claim(self, sid, host, confirmed=False, role="envoy"):
        card = self.h.register(role=role, model=MODEL, require_model=True, host_session_id=host, confirmed=confirmed)
        if sid:
            self.h.store.append("session.bound", card["id"], {"session_id": sid, "agent": card["id"]})
        return card

    def post_bind(self, card, sid, host):
        """The real post-bind hook, fed the register result's banner (the path that appends session.bound and retires)."""
        inp = {"session_id": sid, "tool_name": "mcp__x__harness_register", "tool_response": {"text": card["banner"]}}
        r = subprocess.run([sys.executable, "-B", os.path.join(SCRIPTS, "harness.py"), "hook", "post-bind"], input=json.dumps(inp),
                           capture_output=True, text=True, env=dict(os.environ, CLAUDE_CODE_HOST_SESSION_ID=host))
        self.assertEqual(r.returncode, 0, r.stderr)

    def guard(self, sid, tool="Edit", tool_input=None, host=""):
        env = dict(os.environ, CLAUDE_CODE_HOST_SESSION_ID=host)
        env.pop("CLAUDE_CODE_HOST_SESSION_ID") if not host else None
        r = subprocess.run([sys.executable, "-B", os.path.join(SCRIPTS, "retire_guard.py")],
                           input=json.dumps({"session_id": sid, "tool_name": tool, "tool_input": tool_input or {}}),
                           capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)["hookSpecificOutput"] if r.stdout.strip() else None

    def retire_a(self):
        b = self.claim(None, "local_B", confirmed=True)
        self.post_bind(b, "sB", "local_B")
        return b

    def test_shared_process_only_the_predecessor_is_blocked(self):
        b = self.retire_a()
        denied = self.guard("sA")
        self.assertEqual(denied["permissionDecision"], "deny")
        self.assertTrue(denied["permissionDecisionReason"].startswith("RETIRED: superseded by"))
        self.assertIsNone(self.guard("sB"))   # B shares the server process; its own Edit is not blocked
        self.assertEqual(self.h.state().agents[self.a["id"]]["status"], "superseded")
        self.assertEqual(self.h.retired_load()["sessions"]["sA"]["successor"], b["id"])

    def test_everything_denied_except_the_read_only_allowlist(self):
        self.retire_a()
        for tool in ("Bash", "Edit", "Write", "MultiEdit", "NotebookEdit", "SendMessage", "Agent", "Task", "WebFetch", "Skill",
                     "WebSearch", PFX + "harness_send", PFX + "harness_claim", PFX + "harness_admin", PFX + "harness_register",
                     "mcp__other__anything", "mcp__evil__harness_inbox", "mcp__evil__harness_record"):
            self.assertEqual((self.guard("sA", tool) or {}).get("permissionDecision"), "deny", tool)
        self.assertEqual((self.guard("sA", PFX + "harness_record", {"kind": "note"}) or {}).get("permissionDecision"), "deny")
        for tool, ti in (("Read", {}), ("Grep", {}), ("Glob", {}), (PFX + "harness_inbox", {}), (PFX + "harness_recall", {}),
                         (PFX + "harness_sync", {}), (PFX + "harness_record", {"kind": "capsule"})):
            self.assertIsNone(self.guard("sA", tool, ti), tool)
        self.assertIsNone(self.guard("sB", "SendMessage"))   # the successor is untouched

    def test_retired_reply_on_harness_calls(self):
        b = self.retire_a()
        r = M.retired_reply(self.h, "harness_send", {"agent": self.a["id"][:8], "to": "operator", "body": "x"})
        self.assertTrue(r["text"].startswith("RETIRED: superseded by"), r)
        self.assertIsNone(M.retired_reply(self.h, "harness_send", {"agent": b["id"][:8]}))   # the successor is untouched
        self.assertIsNone(M.retired_reply(self.h, "harness_record", {"agent": self.a["id"][:8], "kind": "capsule"}))
        self.assertTrue(M.retired_reply(self.h, "harness_record", {"agent": self.a["id"][:8], "kind": "note"}))
        self.assertTrue(M.call(self.h, "harness_send", {"agent": self.a["id"][:8], "to": "operator", "body": "x"})["text"]
                        .startswith("RETIRED"))

    def test_twenty_minute_task_needs_confirm(self):
        # the holder ran one long task: no ledger event for 20 minutes, but its hooks kept firing
        C.touch_activity({"session_id": "sA"}, time.time() - 1200)
        with self.assertRaises(H.HarnessError) as cm:
            self.claim(None, "local_B")
        self.assertIn("confirmed=true", str(cm.exception))
        self.assertEqual(len(self.events("agent.registered")), 1)   # nothing was created, nothing superseded
        self.assertEqual(self.h.state().agents[self.a["id"]]["status"], "active")
        self.assertEqual(self.claim(None, "local_B", confirmed=True)["spawn_reason"], "role-claim")

    def test_quiet_for_an_hour_retires_without_confirm(self):
        C.touch_activity({"session_id": "sA"}, time.time() - 3700)
        b = self.claim(None, "local_B")
        self.assertEqual(self.h.state().agents[self.a["id"]]["status"], "superseded")
        self.assertEqual(b["retire_session"], "local_A")

    def test_restore_asks_when_a_hook_is_recent(self):
        C.touch_activity({"session_id": "sA"}, time.time() - 1200)
        self.h.state().agents[self.a["id"]]["last_seen"] = 0   # ledger says quiet; the hook says active
        r = self.h.restore("envoy", model=MODEL)
        self.assertIn("confirmed=true", r["text"])

    def test_activity_file_is_written_by_the_hook(self):
        inp = {"session_id": "sZ", "hook_event_name": "PostToolUse", "tool_name": "Bash", "tool_input": {}}
        r = subprocess.run([sys.executable, "-B", os.path.join(SCRIPTS, "ctx_hook.py")], input=json.dumps(inp), capture_output=True,
                           text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertLess(time.time() - float(open(C.activity_path("sZ")).read()), 30)

    def test_failed_register_leaves_the_predecessor_untouched(self):
        with self.assertRaises(H.HarnessError):
            self.h.register(role="envoy", model=None, require_model=True, host_session_id="local_B")   # T2: model required
        self.assertEqual(self.h.state().agents[self.a["id"]]["status"], "active")
        self.assertEqual(self.h.retired_load()["sessions"], {})
        self.assertIsNone(self.guard("sA"))
        # registered but never bound (post-bind did not run): the guard still lets A work
        self.claim(None, "local_B", confirmed=True)
        self.assertIsNone(self.guard("sA"))

    def grant(self, pid):
        code = self.h._approval_records()[pid]["args_digest"][:4]
        return self.h.approve(pid, "cli-tty", code, True)

    def test_self_revive_needs_a_server_verified_operator_approval(self):
        b = self.retire_a()
        ra = {"role": "envoy", "model": MODEL, "agent": self.a["id"][:8]}
        # the guard: a bare confirmed=true is denied; only a call that carries an approval id reaches the server
        self.assertEqual(self.guard("sA", PFX + "harness_restore", {"role": "envoy", "confirmed": True})["permissionDecision"], "deny")
        self.assertEqual(self.guard("sA", PFX + "harness_restore", {"role": "envoy"})["permissionDecision"], "deny")
        self.assertIsNone(self.guard("sA", PFX + "harness_restore", {"role": "envoy", "approval": "A-12345"}))
        # the server: no approval -> a pending request, no restore, B still holds the role
        r = M.call(self.h, "harness_restore", dict(ra, confirmed=True))
        self.assertTrue(r.get("pending") and r.get("retired"), r)
        self.assertEqual(self.h.state().role_holder("envoy"), b["id"])
        for bad in ("A-bogus", r["pending"]):   # unknown id; a real but still pending id
            with self.assertRaises(H.HarnessError):
                M.call(self.h, "harness_restore", dict(ra, approval=bad))
        self.assertEqual(self.h.state().role_holder("envoy"), b["id"])
        # a granted approval works once, for that agent only
        self.grant(r["pending"])
        with self.assertRaises(H.HarnessError):   # another agent cannot use it
            M.call(self.h, "harness_restore", {"role": "envoy", "model": MODEL, "agent": b["id"][:8], "approval": r["pending"]})
        with self.assertRaises(H.HarnessError):   # different arguments
            M.call(self.h, "harness_restore", dict(ra, approval=r["pending"], project="other"))
        out = M.call(self.h, "harness_restore", dict(ra, approval=r["pending"]))
        self.assertTrue(out.get("short"), out)
        self.assertNotEqual(self.h.state().role_holder("envoy"), b["id"])
        with self.assertRaises(H.HarnessError):   # single use
            M.call(self.h, "harness_restore", dict(ra, approval=r["pending"]))
        # the retired chat binds the new agent: it is no longer retired, and B (now superseded) is
        self.post_bind({"banner": out["text"]}, "sA", "local_A")
        self.assertIsNone(self.guard("sA", "Edit"))
        self.assertEqual(self.guard("sB", "Edit")["permissionDecision"], "deny")

    def test_successor_session_differs_from_the_predecessors(self):
        # compaction in the same chat: the successor's session is the predecessor's, so nothing is retired
        c = self.h.register(predecessor=self.a["id"], model=MODEL, require_model=True, host_session_id="local_A")
        self.post_bind(c, "sA", "local_A")
        self.assertEqual(self.h.retired_load()["sessions"], {})
        self.assertIsNone(self.guard("sA"))
        # a different chat: its own session id is never listed
        d = self.h.register(role="envoy", model=MODEL, require_model=True, host_session_id="local_D", confirmed=True)
        self.post_bind(d, "sD", "local_D")
        self.assertIn("sA", self.h.retired_load()["sessions"])
        self.assertNotIn("sD", self.h.retired_load()["sessions"])

    def test_new_chat_in_the_same_window_is_not_denied(self):
        # critic N-07440 (3): sess-NEW shares the retired chat's desktop host id; it must be able to register
        self.retire_a()
        self.assertEqual(self.h.retired_load()["sessions"]["sA"]["host_session_id"], "local_A")
        for tool in ("Edit", "Bash", PFX + "harness_register", PFX + "harness_restore", PFX + "harness_send"):
            self.assertIsNone(self.guard("sess-NEW", tool, host="local_A"), tool)

    def test_host_keyed_entry_denies_writes_but_never_register_or_restore(self):
        # a predecessor whose session id was never known is keyed host:<id>
        a2 = self.h.register(role="envoy", model=MODEL, require_model=True, host_session_id="local_H", confirmed=True)
        b2 = self.h.register(role="envoy", model=MODEL, require_model=True, host_session_id="local_I", confirmed=True)
        self.h.store.append("session.bound", b2["id"], {"session_id": "sI", "agent": b2["id"]})
        self.assertEqual(self.h.mark_retired_sessions(b2["id"], "sI"), ["host:local_H"])
        self.assertEqual(self.guard("other", "Edit", host="local_H")["permissionDecision"], "deny")
        self.assertIsNone(self.guard("other", PFX + "harness_register", host="local_H"))
        self.assertIsNone(self.guard("other", PFX + "harness_restore", host="local_H"))
        self.assertIsNone(self.guard("other", "Edit", host="local_Z"))

    def test_marker_updates_do_not_lose_entries_under_overlap(self):
        n = 40
        barrier = threading.Barrier(n)

        def put(i):
            h = H.Harness(self.home)
            barrier.wait()

            def f(d):
                time.sleep(0.001)   # widen the read-modify-write window (the critic's overlap)
                d["sessions"][f"s{i}"] = {"agent": f"a{i}"}
            h._retired_update(f)
        ts = [threading.Thread(target=put, args=(i,)) for i in range(n)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        self.assertEqual(len(self.h.retired_load()["sessions"]), n)
        left = [f for f in os.listdir(os.path.join(self.home, "_harness")) if f.endswith(".tmp")]
        self.assertEqual(left, [])

    def test_unreadable_marker_fails_open_and_is_logged(self):
        with open(os.path.join(self.home, "_harness", "retired_sessions.json"), "w") as f:
            f.write("{broken")
        self.assertIsNone(self.guard("sA"))
        with open(os.path.join(os.environ["HARNESS_STATE_DIR"], "retire-guard.log")) as f:
            self.assertIn("unreadable marker", f.read())

    def test_prompt_hook_tells_the_retired_chat(self):
        self.retire_a()
        env = dict(os.environ, CLAUDE_CODE_HOST_SESSION_ID="local_A")
        r = subprocess.run([sys.executable, "-B", os.path.join(SCRIPTS, "harness.py"), "hook", "prompt"],
                           input=json.dumps({"session_id": "sA", "prompt": "hello"}), capture_output=True, text=True, env=env)
        self.assertIn("RETIRED: superseded by", r.stdout)

    def test_guard_fails_open(self):
        r = subprocess.run([sys.executable, "-B", os.path.join(SCRIPTS, "retire_guard.py")], input="not json", capture_output=True,
                           text=True)
        self.assertEqual((r.returncode, r.stdout.strip()), (0, ""))


class Hooks(unittest.TestCase):
    def test_guard_matcher_is_first_in_hooks_json(self):
        hj = json.load(open(os.path.join(SCRIPTS, "..", "hooks", "hooks.json")))
        first = hj["hooks"]["PreToolUse"][0]
        self.assertEqual(first["matcher"], "*")
        self.assertIn("retire_guard.py", first["hooks"][0]["command"])


if __name__ == "__main__":
    unittest.main(verbosity=1)
