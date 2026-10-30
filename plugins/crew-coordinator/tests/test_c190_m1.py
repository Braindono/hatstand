"""cc 0.19.0 M1 (R-121 + R-119): registration records the model (hook input or "unverified", then every change the
transcript shows; the observed model wins over a declared one) and the project (resolver; a role claim wins; an
unknown folder is "unassigned"; never a bare folder name). Critic N-3ee68 failing inputs included.
Run: python3 -B tests/test_c190_m1.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _env  # noqa: F401  isolate HOME and HARNESS_* first
import json, os, shutil, subprocess, sys, tempfile, unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(HERE, "..", "scripts")
sys.path.insert(0, SCRIPTS)
import harness as H
import ctx_hook as C


def assistant(model, sidechain=False):
    return json.dumps({"type": "assistant", "isSidechain": sidechain,
                       "message": {"model": model, "usage": {"input_tokens": 10, "output_tokens": 5}}}) + "\n"


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.home = os.path.join(self.tmp, "Exchange")
        self.ops = os.path.join(self.tmp, "ops")
        for d in (os.path.join(self.home, "projects", "cv-management"), os.path.join(self.ops, "projects", "harness-ops"),
                  os.path.join(self.ops, "projects", "orchestration", "scripts"), os.path.join(self.tmp, "random", "register")):
            os.makedirs(d)
        os.makedirs(os.path.join(self.ops, "_alias"))
        with open(os.path.join(self.ops, "_alias", "alias-map.json"), "w") as f:
            json.dump({"project_aliases": {"orchestration": "harness-ops", "skill-curation": "harness-ops"}}, f)
        e = mock.patch.dict(os.environ, {"HARNESS_STATE_CACHE": "0", "HARNESS_OPS_ROOT": self.ops, "HARNESS_HOME": self.home,
                                         "HARNESS_STATE_DIR": os.path.join(self.tmp, "state")})   # per-test spool and notes
        e.start()
        self.addCleanup(e.stop)
        self.h = H.Harness(self.home)
        self.h.role_define("operator", "envoy", "harness-ops")
        self.h.store.append("role.defined", "operator", {"role": "envoy", "project": "harness-ops", "carry": "none"}) \
            if "envoy" not in self.h.state().roles else None

    def events(self, typ):
        return [e for e in self.h.store.read_all() if e.get("type") == typ]


class Project(Base):
    def test_resolver(self):
        f = lambda p: H.project_from_cwd(self.home, p)
        self.assertEqual(f(os.path.join(self.ops, "projects", "orchestration", "scripts")), ("harness-ops", "resolver"))
        self.assertEqual(f(os.path.join(self.ops, "projects", "harness-ops"))[0], "harness-ops")
        self.assertEqual(f(self.ops), ("harness-ops", "ops-root"))
        self.assertEqual(f(os.path.join(self.home, "projects", "cv-management")), ("cv-management", "resolver"))
        self.assertEqual(f(os.path.join(self.tmp, "random", "register")), ("unassigned", "folder"))   # no basename seed

    def test_ops_cwd_with_and_without_workspaces(self):
        cwd = os.path.join(self.ops, "projects", "orchestration")
        a = H.project_from_cwd(self.home, cwd)
        op = os.path.join(os.environ["HOME"], ".config", "crew-coordinator", "operator.json")
        with open(op) as f:
            orig = f.read()
        try:
            d = json.loads(orig)
            d["workspaces"] = [self.ops]
            with open(op, "w") as f:
                json.dump(d, f)
            os.chmod(op, 0o600)
            self.assertEqual(H.project_from_cwd(self.home, cwd), a)
        finally:
            with open(op, "w") as f:
                f.write(orig)
            os.chmod(op, 0o600)
        self.assertEqual(a[0], "harness-ops")

    def test_role_claim_wins_and_mismatch_shown(self):
        card = self.h.register(project="unassigned", model="claude-opus-5-5", role="envoy")
        a = self.h.state().agents[card["id"]]
        self.assertEqual((a["project"], a["project_source"]), ("harness-ops", "role"))
        self.assertIn("project from role envoy: harness-ops; chat started in 'unassigned'", card["banner"])

    def test_unassigned_banner_and_do_line(self):
        card = self.h.register(project="unassigned", model="claude-opus-5-5")
        self.assertIn("project unassigned", card["banner"])
        r = self.h.sync(card["id"], do_only=True)
        self.assertIn("project unassigned", r if isinstance(r, str) else json.dumps(r))


class Hook(Base):
    def session_start(self, cwd, sid="sess-1", model=None, host="local_abc"):
        inp = {"session_id": sid, "source": "startup", "cwd": cwd}
        if model:
            inp["model"] = model
        env = dict(os.environ, CLAUDE_CODE_HOST_SESSION_ID=host)
        env.pop("HARNESS_MODEL", None)
        env.pop("ANTHROPIC_MODEL", None)
        r = subprocess.run([sys.executable, "-B", os.path.join(SCRIPTS, "harness.py"), "hook", "session-start"],
                           input=json.dumps(inp), capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        return self.events("agent.registered")[-1]["data"]

    def test_unverified_model_project_and_host_session(self):
        d = self.session_start(os.path.join(self.ops, "projects", "orchestration"))
        self.assertEqual((d["model"], d["project"], d["project_source"], d["host_session_id"]),
                         ("unverified", "harness-ops", "resolver", "local_abc"))

    def test_model_from_hook_input(self):
        d = self.session_start(os.path.join(self.tmp, "random", "register"), model={"id": "claude-sonnet-5-5"})
        self.assertEqual((d["model"], d["project"]), ("claude-sonnet-5-5", "unassigned"))


class Model(Base):
    def transcript(self, *models, sidechain=None):
        p = os.path.join(self.tmp, "t.jsonl")
        with open(p, "w") as f:
            for m in models:
                f.write(assistant(m))
            if sidechain:
                f.write(assistant(sidechain, sidechain=True))
        return p

    def test_transcript_model_ignores_subagents(self):
        p = self.transcript("claude-sonnet-5-5", sidechain="claude-haiku-5-5")
        self.assertEqual(C.transcript_model(p), "claude-sonnet-5-5")
        sub = os.path.join(self.tmp, "x", "subagents", "a.jsonl")
        os.makedirs(os.path.dirname(sub))
        shutil.copy(p, sub)
        self.assertIsNone(C.transcript_model(sub))

    def test_observed_wins_over_declared_and_every_change_recorded(self):
        """Critic N-3ee68 failing input: a Sonnet transcript registering model=claude-opus-5-5."""
        card = self.h.register(project="harness-ops", model="claude-opus-5-5", session_id="s-1")
        aid = card["id"]
        self.h.store.append("session.bound", aid, {"session_id": "s-1", "agent": aid})
        p = self.transcript("claude-sonnet-5-5")
        inp = {"session_id": "s-1", "transcript_path": p}
        self.assertEqual(C.record_model(inp), "claude-sonnet-5-5")
        self.assertIsNone(C.record_model(inp))                       # unchanged: nothing spooled
        self.h.ingest_model_spool()
        a = self.h.state().agents[aid]
        self.assertEqual((a["model"], a["declared_model"]), ("claude-sonnet-5-5", "claude-opus-5-5"))
        r = self.h.sync(aid, do_only=True)
        self.assertIn("declared claude-opus-5-5, transcript shows claude-sonnet-5-5", r if isinstance(r, str) else json.dumps(r))
        with open(p, "a") as f:                                     # /model to Opus, then fast mode back to Sonnet
            f.write(assistant("claude-opus-5-5"))
        C.record_model(inp)
        with open(p, "a") as f:
            f.write(assistant("claude-sonnet-5-5"))
        C.record_model(inp)
        self.h.ingest_model_spool()
        sets = [e["data"]["model"] for e in self.events("agent.model_set")]
        self.assertEqual(sets, ["claude-sonnet-5-5", "claude-opus-5-5", "claude-sonnet-5-5"])
        self.assertEqual(len(self.h.state().agents[aid]["model_history"]), 3)
        self.assertIsNone(self.h.ingest_model_spool())              # already ingested: no repeat

    def test_unverified_gets_the_reverify_do_line(self):
        card = self.h.register(project="harness-ops", model="unverified")
        r = self.h.sync(card["id"], do_only=True)
        self.assertIn("model unverified", r if isinstance(r, str) else json.dumps(r))

    def test_unknown_session_lines_ignored(self):
        sp = C.state_path("harness-model-spool.jsonl")
        with open(sp, "a") as f:
            f.write(json.dumps({"session_id": "nobody", "model": "claude-opus-5-5"}) + "\n")
            f.write("not json\n")
            f.write(json.dumps({"session_id": "s-x", "model": "bad model; rm"}) + "\n")
        self.assertIsNone(self.h.ingest_model_spool())
        self.assertEqual(self.events("agent.model_set"), [])


class Rework(Base):
    transcript = Model.transcript
    """Critic N-fe413: blockers 1 and 2 and the spool fixes; the critic's probe (m1probe/probe_m1.py) is the first test."""
    def test_critic_probe_role_claim_after_spool(self):
        a = self.h.register(project="harness-ops", model="unverified", session_id="s-1")["id"]   # SessionStart agent
        self.h.store.append("session.bound", a, {"session_id": "s-1", "agent": a})
        inp = {"session_id": "s-1", "transcript_path": self.transcript("claude-sonnet-5-5")}
        C.record_model(inp)
        self.h.ingest_model_spool()
        b = self.h.register(project="harness-ops", role="envoy", model="claude-opus-5-5")["id"]  # role claim, wrong model
        self.h.store.append("session.bound", b, {"session_id": "s-1", "agent": b})
        C.record_model(inp)
        self.h.ingest_model_spool()                                                           # more turns, same model
        sb = self.h.state().agents[b]
        r = self.h.sync(b, do_only=True)
        r = r if isinstance(r, str) else json.dumps(r)
        self.assertEqual(sb.get("model"), "claude-sonnet-5-5", "role claim kept the declared model")
        self.assertEqual(sb.get("declared_model"), "claude-opus-5-5")
        self.assertIn("transcript shows claude-sonnet-5-5", r)

    def test_role_claim_carries_the_sessions_host_id(self):
        a = self.h.register(project="harness-ops", model="unverified", session_id="s-1", host_session_id="local_abc")["id"]
        with mock.patch.dict(os.environ, {"CLAUDE_CODE_HOST_SESSION_ID": "local_OTHER_shared_server"}):
            b = self.h.register(project="harness-ops", role="envoy", model="claude-opus-5-5")["id"]
        self.h.store.append("session.bound", b, {"session_id": "s-1", "agent": b})
        self.assertEqual(self.h.state().agents[b]["host_session_id"], "local_abc")   # the session's record wins on bind

    def test_out_of_order_ingest_keeps_the_newest(self):
        a = self.h.register(project="harness-ops", model="unverified", session_id="s-1")["id"]
        self.h.store.append("agent.model_set", a, {"agent": a, "model": "claude-opus-5-5", "session_id": "s-1", "t_obs": 200.0})
        self.h.store.append("agent.model_set", a, {"agent": a, "model": "claude-sonnet-5-5", "session_id": "s-1", "t_obs": 100.0})
        self.assertEqual(self.h.state().agents[a]["model"], "claude-opus-5-5")
        sp = C.state_path("harness-model-spool.jsonl")
        with open(sp, "a") as f:
            f.write(json.dumps({"session_id": "s-1", "model": "claude-haiku-5-5", "t": 150.0}) + "\n")
        self.h.ingest_model_spool()
        self.assertEqual(self.h.state().agents[a]["model"], "claude-opus-5-5")      # 150 < 200: not applied

    def test_spool_written_before_seen(self):
        inp = {"session_id": "s-9", "transcript_path": self.transcript("claude-sonnet-5-5")}
        real = open

        def failing(path, *a, **k):
            if str(path).endswith("harness-model-spool.jsonl"):
                raise OSError("disk full")
            return real(path, *a, **k)
        with mock.patch("builtins.open", failing):
            with self.assertRaises(OSError):
                C.record_model(inp)
        self.assertEqual(C.record_model(inp), "claude-sonnet-5-5")                  # not marked seen: spooled now

    def test_unbound_session_lines_retried(self):
        inp = {"session_id": "s-late", "transcript_path": self.transcript("claude-sonnet-5-5")}
        C.record_model(inp)
        self.assertIsNone(self.h.ingest_model_spool())                              # no agent yet: kept for retry
        a = self.h.register(project="harness-ops", model="unverified", session_id="s-late")["id"]
        self.h.ingest_model_spool()
        self.assertEqual(self.h.state().agents[a]["model"], "claude-sonnet-5-5")

    def test_display_path_goes_through_the_resolver(self):
        f = os.path.join(self.ops, "projects", "orchestration", "scripts", "x.py")
        with open(f, "w") as fh:
            fh.write("x\n")
        key = H.canonical_path(f, self.home)
        shown = H.display_key(key, self.home)
        self.assertTrue(shown.endswith(os.path.join("ops", "projects", "orchestration", "scripts", "x.py")), shown)
        self.assertNotIn("Exchange/projects", shown)


if __name__ == "__main__":
    unittest.main(verbosity=1)
