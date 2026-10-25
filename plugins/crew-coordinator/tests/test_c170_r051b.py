"""cc 0.17.0 R-051b handoff gate (config handoff_gate warn|block, override logged, failure path warn-and-proceed) and
R-080 (handoff.gate_warn event with its count). Spec: skill-curation/specs/2026-10-24-stage2-context-loss.md section 3.
Run: python3 -B tests/test_c170_r051b.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _env  # noqa: F401  isolate HOME and HARNESS_* first
import json, os, sys, tempfile, time, unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
import harness as H
import mcp_server as M
import vault as V

MODEL = "claude-opus-5-5"


def ts(t):
    return time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(t))


class Gate(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.home = os.path.join(self.tmp, "Exchange")
        os.makedirs(os.path.join(self.home, "_harness"))
        self.ixroot = os.path.join(self.tmp, "ix")
        os.makedirs(self.ixroot)
        e = mock.patch.dict(os.environ, {"INDEXER_ROOT": self.ixroot, "HARNESS_STATE_CACHE": "0"})
        e.start()
        self.addCleanup(e.stop)
        self.h = H.Harness(self.home)
        self.h.role_define("operator", "ops-coder", "harness-ops")
        self.aid = self.h.register(project="harness-ops", model=MODEL)["id"]
        self.h.role_assign("operator", "ops-coder", self.aid)
        self.t0 = time.time() + 2
        self.sid = "abcdef12-3456"
        self.h.store.append("session.bound", self.aid, {"session_id": self.sid, "agent": self.aid})
        with open(os.path.join(self.ixroot, "2026-10-25-proj-%s.md" % self.sid[:8]), "w") as f:
            f.write("# Transcript\n\n" + "".join("### operator %s\n> %s\n\n" % (ts(self.t0 + i), t) for i, t in
                                                 enumerate(["rename the vault folder please", "add a dashboard tile for gates"])))
        self.reply = '{"tags":[{"n":1,"tag":"done","reason":"renamed"}]}'     # ask 2 is left untagged by the model
        real = V.prepare
        p = mock.patch.object(V, "prepare", side_effect=lambda *a, **k: real(*a, **dict(k, now=self.t0 + 600)))
        p.start()
        self.addCleanup(p.stop)
        m = mock.patch.object(V, "claude_cli", side_effect=lambda prompt, model: self.reply)
        m.start()
        self.addCleanup(m.stop)

    def cfg(self, **d):
        with open(os.path.join(self.home, "_harness", "config.json"), "w") as f:
            json.dump(d, f)

    def capsule(self, *lines):
        return "---\nhandoff: x\n---\n# Handoff\n" + "".join("- %s\n" % x for x in lines)

    def events(self, typ):
        return [e for e in self.h.store.read_all() if e["type"] == typ]

    def vault_files(self):
        root = V.vault_root(self.home)
        return [f for _d, _s, fs in os.walk(root) for f in fs if f.endswith(".md")] if os.path.isdir(root) else []

    # --- warn (default)
    def test_warn_default_logs_count_and_proceeds(self):
        self.cfg(vault="on")
        out = self.h.handoff(self.aid, self.capsule("[done] rename the vault folder"))
        self.assertIn("message", out)
        self.assertEqual(out["gate"], {"mode": "warn", "untagged": 1, "source": "vault", "action": "warn"})
        self.assertIn("1 operator ask(s) untagged", out["warn"])
        ev = self.events("handoff.gate_warn")
        self.assertEqual([(e["data"]["count"], e["data"]["source"]) for e in ev], [(1, "vault")])
        self.assertEqual(len(self.vault_files()), 1)
        self.assertIn("latency_ms", out["vault"])

    def test_unknown_mode_reads_as_warn(self):
        self.cfg(vault="on", handoff_gate="strict")
        out = self.h.handoff(self.aid, self.capsule())
        self.assertEqual(out["gate"]["mode"], "warn")

    def test_capsule_line_covers_an_untagged_ask(self):
        self.cfg(vault="on", handoff_gate="block")
        out = self.h.handoff(self.aid, self.capsule("[open] Add a dashboard tile for gates (next release)"))
        self.assertEqual(out["gate"]["action"], "pass")
        self.assertEqual(self.events("handoff.gate_warn"), [])

    def test_all_tagged_passes_and_logs_nothing(self):
        self.reply = '{"tags":[{"n":1,"tag":"done","reason":"r"},{"n":2,"tag":"open"}]}'
        self.cfg(vault="on", handoff_gate="block")
        out = self.h.handoff(self.aid, self.capsule())
        self.assertEqual(out["gate"]["action"], "pass")
        self.assertEqual(self.events("handoff.gate_warn") + self.events("handoff.gate_blocked"), [])

    # --- block
    def test_block_refuses_lists_asks_and_writes_nothing(self):
        self.cfg(vault="on", handoff_gate="block")
        handoffs_dir = os.path.join(self.home, "projects", "harness-ops", "handoffs")
        with self.assertRaises(H.HarnessError) as cm:
            self.h.handoff(self.aid, self.capsule("[done] rename the vault folder"), state_note="note")
        msg = str(cm.exception)
        self.assertIn("handoff refused (handoff_gate: block): 1 operator ask(s)", msg)
        self.assertIn("add a dashboard tile for gates", msg)
        self.assertIn("gate_override", msg)
        self.assertEqual(self.vault_files(), [])
        self.assertFalse(os.path.isdir(handoffs_dir) and os.listdir(handoffs_dir))
        self.assertEqual(self.events("agent.handed_off"), [])
        self.assertEqual(self.events("vault.written"), [])
        self.assertEqual([e["data"]["count"] for e in self.events("handoff.gate_blocked")], [1])
        self.assertFalse(self.h.state().agents[self.aid].get("handed_off"))

    def test_refused_then_tagged_retry_keeps_the_ask_in_the_vault(self):
        self.cfg(vault="on", handoff_gate="block")
        with self.assertRaises(H.HarnessError):
            self.h.handoff(self.aid, self.capsule())
        out = self.h.handoff(self.aid, self.capsule("[open] add a dashboard tile for gates"))
        self.assertEqual(out["gate"]["action"], "pass")
        self.assertEqual(out["vault"]["asks"], 2)            # the refusal did not shift the window
        with open(os.path.join(self.home, out["vault"]["path"])) as f:
            self.assertIn("add a dashboard tile for gates", f.read())

    def test_block_override_is_logged_and_proceeds(self):
        self.cfg(vault="on", handoff_gate="block")
        out = self.h.handoff(self.aid, self.capsule(), gate_override="operator said leave it")
        self.assertIn("message", out)
        self.assertEqual(out["gate"]["action"], "override")
        ev = self.events("handoff.gate_override")
        self.assertEqual([(e["data"]["count"], e["data"]["reason"]) for e in ev], [(1, "operator said leave it")])
        self.assertIn("gate override logged", out["text"])
        self.assertEqual(len(self.vault_files()), 1)

    def test_blank_override_does_not_count(self):
        self.cfg(vault="on", handoff_gate="block")
        with self.assertRaises(H.HarnessError):
            self.h.handoff(self.aid, self.capsule(), gate_override="   ")

    def test_override_through_mcp_tool(self):
        self.cfg(vault="on", handoff_gate="block")
        r = M._call(self.h, "harness_handoff", {"agent": self.aid, "capsule_md": self.capsule(), "gate_override": "ok by operator"})
        self.assertEqual(r["gate"]["action"], "override")
        schema = [t for t in M.TOOLS if t[0] == "harness_handoff"][0][2] if hasattr(M, "TOOLS") else None
        if schema is not None:
            self.assertIn("gate_override", schema)

    # --- failure path (critic 5): never blocks
    def test_block_model_unavailable_warns_and_proceeds(self):
        self.cfg(vault="on", handoff_gate="block")
        with mock.patch.object(V, "claude_cli", side_effect=V.ModelUnavailable("no login")):
            out = self.h.handoff(self.aid, self.capsule())
        self.assertIn("message", out)
        self.assertEqual(out["gate"]["action"], "warn")
        ev = self.events("handoff.gate_warn")
        self.assertEqual(ev[-1]["data"]["source"], "failure")
        self.assertIn("model unavailable", out["text"])
        self.assertEqual(len(self.vault_files()), 1)          # asks kept, untagged

    def test_block_writer_crash_warns_and_proceeds(self):
        self.cfg(vault="on", handoff_gate="block")
        with mock.patch.object(V, "prepare", side_effect=OSError("disk")):
            out = self.h.handoff(self.aid, self.capsule())
        self.assertIn("message", out)
        self.assertEqual(self.events("handoff.gate_warn")[-1]["data"]["source"], "failure")
        self.assertIn("vault writer failed", out["text"])

    # --- vault off: the 0.16.2 capsule count drives the gate
    def test_vault_off_warn_keeps_old_text_and_logs(self):
        self.cfg(handoff_gate="warn")
        out = self.h.handoff(self.aid, self.capsule("[done] one"))
        self.assertIn("1 of 2 operator asks", out["warn"])
        self.assertEqual([e["data"]["source"] for e in self.events("handoff.gate_warn")], ["capsule"])
        self.assertNotIn("vault", out)

    def test_vault_off_block_and_override(self):
        self.cfg(handoff_gate="block")
        with self.assertRaises(H.HarnessError):
            self.h.handoff(self.aid, self.capsule("[done] one"))
        out = self.h.handoff(self.aid, self.capsule("[done] one"), gate_override="fine")
        self.assertEqual(out["gate"], {"mode": "block", "untagged": 1, "source": "capsule", "action": "override"})

    def test_no_capsule_no_vault_no_gate(self):
        self.cfg(handoff_gate="block")
        out = self.h.handoff(self.aid)
        self.assertNotIn("gate", out)

    # --- checkpoints (envoy m-06bd7290c02e): pre-compact hook and /save; deterministic, warn-only, window unchanged
    def test_checkpoint_writes_untagged_without_model_and_keeps_the_window(self):
        self.cfg(vault="on", handoff_gate="block")
        with mock.patch.object(V, "claude_cli", side_effect=AssertionError("no model at a checkpoint")):
            r = self.h.vault_checkpoint(self.aid, "pre-compact")
        self.assertEqual((r["status"], r["asks"], r["untagged"]), ("written", 2, 2))
        ev = self.events("vault.written")[-1]["data"]
        self.assertEqual(ev["trigger"], "pre-compact")
        out = self.h.handoff(self.aid, self.capsule("[open] add a dashboard tile"))
        self.assertEqual(out["vault"]["asks"], 2)            # the handoff still covers and tags the same asks
        self.assertEqual(out["gate"]["action"], "pass")
        self.assertEqual(len(self.vault_files()), 2)

    def test_save_capsule_writes_a_checkpoint(self):
        self.cfg(vault="on")
        r = self.h.record(self.aid, "capsule", "save: ops-coder 2026-10-25", "body", ["save", "role:ops-coder"], offload=True)
        self.assertEqual(r["vault"]["status"], "written")
        self.assertEqual(self.events("vault.written")[-1]["data"]["trigger"], "save")
        r2 = self.h.record(self.aid, "capsule", "other capsule", "body2", ["handoff"])
        self.assertNotIn("vault", r2)

    def test_checkpoint_off_and_failure_never_raise(self):
        self.cfg(vault="off")
        self.assertIsNone(self.h.vault_checkpoint(self.aid, "pre-compact"))
        self.cfg(vault="on")
        with mock.patch.object(V, "write", side_effect=OSError("disk")):
            self.assertEqual(self.h.vault_checkpoint(self.aid, "save")["status"], "skipped")

    def test_pre_compact_hook_runs_the_checkpoint(self):
        self.cfg(vault="on")
        import io
        with mock.patch.dict(os.environ, {"HARNESS_HOME": self.home}), \
                mock.patch("sys.stdin", io.StringIO(json.dumps({"session_id": self.sid, "trigger": "auto"}))):
            H.hook("pre-compact")
        ev = [e["data"] for e in self.events("vault.written")]
        self.assertEqual([e["trigger"] for e in ev], ["pre-compact"])


if __name__ == "__main__":
    unittest.main()
