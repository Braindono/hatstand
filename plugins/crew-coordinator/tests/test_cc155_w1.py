"""cc 0.15.5 WP1+WP2: surface, ctx status lines, PreCompact stub, approval how/attribution, note topics, intent line,
computer:// links. Run: python3 -B tests/test_cc155_w1.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _env  # noqa: F401  isolate HOME and HARNESS_* first
import json, os, re, sys, tempfile, unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
import ctx_hook as C
import harness as H
import mcp_server as M
from test_cc151_w1 import Base, MODEL

SONNET, HAIKU = "claude-sonnet-5-5", "claude-haiku-5-5"


class Surface(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._env = mock.patch.dict(os.environ, {"HARNESS_HOME": self.tmp})
        self._env.start()
        self.addCleanup(self._env.stop)
        os.environ.pop("HARNESS_SURFACE", None)

    def test_cloud_paths_are_unknown_with_smallest_window(self):
        for p in ("/root/.claude/projects/-home-claude/abc.jsonl", "/sessions/s1/.claude/projects/-p/abc.jsonl",
                  "/home/claude/.claude/projects/-p/abc.jsonl", "/opt/.claude/projects/x.jsonl", ""):
            self.assertEqual(C.surface_src(p), ("unknown", "unknown"), p)
            self.assertEqual(C.limits(SONNET, p)["window"], 500000, p)

    def test_desktop_home_paths_are_code(self):
        for p in ("/Users/x/.claude/projects/-p/abc.jsonl", "/home/bob/.claude/projects/-p/abc.jsonl"):
            self.assertEqual(C.surface_src(p), ("code", "path"), p)
        C.CURRENT_ROLE = None
        self.assertEqual(C.limits(SONNET, "/Users/x/.claude/projects/-p/a.jsonl")["window"], 500000)   # 0.17.0: surface ignored

    def test_cowork_path(self):
        p = "/Users/x/Library/Application Support/Claude/local-agent-mode-sessions/a/b/.claude/projects/-p/abc.jsonl"
        self.assertEqual(C.surface_src(p), ("cowork", "path"))

    def test_explicit_wins_both_ways(self):
        with mock.patch.dict(os.environ, {"HARNESS_SURFACE": "code"}):
            self.assertEqual(C.surface_src("/root/.claude/projects/x/a.jsonl"), ("code", "explicit"))
        with mock.patch.dict(os.environ, {"HARNESS_SURFACE": "cowork"}):
            self.assertEqual(C.surface_src("/Users/x/.claude/projects/x/a.jsonl"), ("cowork", "explicit"))


class SyncLines(Base):
    def setUp(self):
        super().setUp()
        self._e2 = mock.patch.dict(os.environ, {"HARNESS_HOME": self.home}, clear=False)
        self._e2.start()
        self.addCleanup(self._e2.stop)
        os.environ.pop("HARNESS_SURFACE", None)

    def test_window_line_once_per_session_surface_irrelevant(self):     # 0.17.0 R-059
        a = self.h.register(project="orch", model=MODEL)["id"]
        t1 = self.h.sync(a, ctx=10000)["text"]
        t2 = self.h.sync(a, ctx=10000)["text"]
        self.assertRegex(t1, r"ctx window: 500k \(default; no role yet\), plan 300k, handoff 400k")
        self.assertNotIn("ctx window", t2)                 # once per session
        self.assertNotIn("HARNESS_SURFACE", t1)            # no surface hint any more
        with mock.patch.dict(os.environ, {"HARNESS_SURFACE": "code"}):
            b = self.h.register(project="orch", model=MODEL)["id"]
            u1 = self.h.sync(b, ctx=10000)["text"]
        self.assertIn("ctx window: 500k (default; no role yet), plan 300k, handoff 400k", u1)

    def test_unmeasured_and_haiku_silent(self):
        a = self.h.register(project="orch", model=MODEL)["id"]
        self.assertIn("ctx unmeasured", self.h.sync(a)["text"])
        self.assertNotIn("ctx unmeasured", self.h.sync(a, ctx=5000)["text"])
        hk = self.h.register(project="orch", model=HAIKU)["id"]
        t = self.h.sync(hk)["text"]
        self.assertNotIn("ctx window", t)
        self.assertNotIn("ctx unmeasured", t)


class PreCompact(Base):
    def setUp(self):
        super().setUp()
        self.sd = os.path.join(self.tmp, "state")
        self._e2 = mock.patch.dict(os.environ, {"HARNESS_STATE_DIR": self.sd, "HARNESS_HOME": self.home})
        self._e2.start()
        self.addCleanup(self._e2.stop)

    def stubs(self):
        return [n for n in (os.listdir(self.sd) if os.path.isdir(self.sd) else []) if n.startswith("harness-precompact-") and n.endswith(".json")]

    def test_stub_unique_never_overwritten_no_temp_left(self):
        p1 = C.precompact_stub("s-1", "aid1", "lead", "auto", now=1000)
        p2 = C.precompact_stub("s-1", "aid1", "lead", "auto", now=1000)
        self.assertTrue(p1 and p2 and p1 != p2)
        self.assertEqual(sorted(os.listdir(self.sd)), sorted(os.path.basename(x) for x in (p1, p2)))
        rec = json.load(open(p1))
        self.assertEqual((rec["agent"], rec["role"]), ("aid1", "lead"))
        self.assertNotIn("\n", rec["stub"])
        self.assertEqual(os.stat(p1).st_mode & 0o777, 0o600)

    def test_session_id_cannot_escape_dir(self):
        p = C.precompact_stub("../../etc/x", "a", "r", "auto")
        self.assertEqual(os.path.dirname(p), self.sd)

    def test_fails_open(self):
        bad = os.path.join(self.tmp, "afile")
        open(bad, "w").write("x")
        with mock.patch.dict(os.environ, {"HARNESS_STATE_DIR": bad}):
            self.assertIsNone(C.precompact_stub("s", "a", "r", "auto"))
            self.assertEqual(C.take_precompact("a"), [])

    def test_hook_writes_stub_only_for_roled_agent_and_sync_records_it(self):
        self.h.role_define("operator", "lead", "orch")
        a = self.h.register(project="orch", model=MODEL, session_id="s-9")["id"]
        self.h.role_assign("operator", "lead", a)
        nrole = self.h.register(project="orch", model=MODEL, session_id="s-10")["id"]
        for sid in ("s-9", "s-10"):
            with mock.patch.object(H, "_hook_input", return_value={"session_id": sid, "trigger": "auto"}):
                H.hook("pre-compact")
        self.assertEqual(len(self.stubs()), 1)             # the role-less agent got none
        before = len(self.h.store.read_all())
        txt = M.call(self.h, "harness_sync", {"agent": a})["text"]
        self.assertIn("compaction happened", txt)
        self.assertEqual(self.stubs(), [])
        rows = self.h.corpus.search(None, kind="context", tags=["role-state:lead:precompact"])
        self.assertEqual(len(rows), 1)
        main = self.h.corpus.search(None, kind="context", tags=["role-state:lead"])
        self.assertEqual(main, [])                         # the stub never becomes the main note

    def test_no_handoffs_write(self):
        self.h.role_define("operator", "lead", "orch")
        a = self.h.register(project="orch", model=MODEL, session_id="s-1")["id"]
        self.h.role_assign("operator", "lead", a)
        with mock.patch.object(H, "_hook_input", return_value={"session_id": "s-1"}):
            H.hook("pre-compact")
        self.assertFalse(os.path.exists(os.path.join(self.home, "projects", "orch", "handoffs")))


class Approval(Base):
    def test_how_is_runnable_one_line(self):
        a = self.agent("lead")
        r = self.adm("export", a)
        how = r["how"]
        self.assertTrue(how.startswith("python3 "))
        self.assertIn(r["pending"], how)
        self.assertNotIn("\n", how)
        self.assertNotIn("<", how)
        path = re.match(r"python3 (?:'([^']+)'|(\S+)) approve ", how)
        self.assertTrue(os.path.isfile(path.group(1) or path.group(2)))

    def test_no_bound_fallback(self):
        a, b = self.agent("lead"), self.agent("other")
        self.as_(b)
        with self.assertRaisesRegex(H.HarnessError, "agent="):
            M.call(self.h, "harness_admin", {"op": "export", "args": {}})
        with self.assertRaisesRegex(H.HarnessError, "agent="):
            M.call(self.h, "harness_admin", {"op": "export", "agent": "zzzzzzzz", "args": {}})
        self.assertEqual(self.types("approval.requested"), [])
        r = self.adm("export", a)         # the named agent is the caller, not the bound one
        rec = self.types("approval.requested")[-1]["data"]
        self.assertEqual(rec["caller"], a)


class Topics(Base):
    def setUp(self):
        super().setUp()
        self.a = self.agent("lead")

    def tags(self, tag):
        return self.h.corpus.search(None, kind="context", tags=[tag])

    def test_default_main_back_compat(self):
        self.h.state_note(self.a, "one")
        self.h.state_note(self.a, "two", "main")
        self.h.state_note(self.a, "three", None)
        rows = self.tags("role-state:lead")
        self.assertEqual(len(rows), 1)
        self.assertIn("role-state", rows[0]["tags"])

    def test_topic_supersedes_per_topic_only(self):
        self.h.state_note(self.a, "main one")
        self.h.state_note(self.a, "t1 one", "wp3")
        self.h.state_note(self.a, "t1 two", "wp3")
        self.h.state_note(self.a, "t2 one", "wp4")
        self.assertEqual(len(self.tags("role-state:lead:wp3")), 1)
        self.assertEqual(len(self.tags("role-state:lead:wp4")), 1)
        self.assertEqual(len(self.tags("role-state:lead")), 1)
        self.assertIn("main one", self.h.corpus.get([self.tags("role-state:lead")[0]["id"]], budget=400)[0])

    def test_bad_topic_and_mcp_param(self):
        for bad in ("Has Space", "x" * 25, "a/b"):
            with self.assertRaisesRegex(H.HarnessError, "topic"):
                self.h.state_note(self.a, "n", bad)
        r = M.call(self.h, "harness_sync", {"agent": self.a, "state_note": "via mcp", "topic": "wp9"})
        self.assertIn("state_note:", r["text"])
        self.assertEqual(len(self.tags("role-state:lead:wp9")), 1)

    def test_digest_main_full_topics_one_line(self):
        self.h.state_note(self.a, "MAIN-NOTE-BODY")
        self.h.state_note(self.a, "TOPIC-NOTE-BODY " * 20, "wp3")
        new = self.h.register(project="orch", model=MODEL)["id"]
        d = self.h.restore("lead", model=MODEL, confirmed=True)
        txt = d["text"] if isinstance(d, dict) and "text" in d else json.dumps(d)
        self.assertIn("MAIN-NOTE-BODY", txt)
        self.assertRegex(txt, r"topic wp3 · \S+ · recall [A-Z]-[0-9a-f]+")
        self.assertNotIn("TOPIC-NOTE-BODY", txt)


class Intent(Base):
    def setUp(self):
        super().setUp()
        self.h.role_define("operator", "lead", "orch")
        self.a = self.agent("lead")

    def role_section(self):
        st = self.h.state()
        d = self.h.restore_digest(st, self.a, "lead", [])
        return d.split("Role")[1].split("State note")[0]

    def test_absent_then_present(self):
        self.assertNotIn("intent:", self.role_section())
        d = os.path.join(self.home, "projects", "orch", "lead")
        os.makedirs(d)
        open(os.path.join(d, "INTENT.md"), "w").write("intent")
        for n in "abcdefg":
            open(os.path.join(d, f"{n}.md"), "w").write("x")
        sec = self.role_section()
        self.assertIn(os.path.join(d, "INTENT.md"), sec)
        self.assertIn("files: a.md, b.md, c.md, d.md, e.md +2", sec)
        self.assertNotIn("intent\n", sec)                  # path only, never the content

    def test_lint_warns_for_no_carry_role_without_intent(self):
        r = self.h.role_define("operator", "steward", "orch", carry="none", name="Steward")
        self.assertIn("INTENT.md", r["warn"])
        d = os.path.join(self.home, "projects", "orch", "steward")
        os.makedirs(d)
        open(os.path.join(d, "INTENT.md"), "w").write("x")
        self.assertNotIn("warn", self.h.role_define("operator", "steward", "orch", carry="none", name="Steward"))
        r2 = self.h.role_define("operator", "full-r", "orch")
        self.assertNotIn("warn", r2)
        # the approval request path warns too
        q = self.adm("role_define", self.a, role="steward2", project="orch", carry="none", name="S2")
        self.assertIn("INTENT.md", q["warn"])


class Links(Base):
    def test_path_link_forms(self):
        home = os.path.expanduser("~")
        self.assertEqual(H.path_link(home + "/Claude/a b.md"), f"[a b.md](computer://{home.replace(' ', '%20')}/Claude/a%20b.md)")
        self.assertEqual(H.path_link("/tmp/x.md"), "/tmp/x.md")
        self.assertEqual(H.path_link(home), home)

    def test_handoff_claim_status_links(self):
        a = self.agent("lead")
        # the temp tree is not under the real home: patch expanduser so the link form applies
        with mock.patch("os.path.expanduser", lambda p: self.tmp if p == "~" else p):
            r = self.h.handoff(a, "---\nproject: orch\nstatus: open\n---\n# H\nbody\n", None, False, None)
            first = r["text"].splitlines()[0]
            self.assertRegex(first, r"handoff-ok m-\w+ · capsule \[.+\.md\]\(computer://")
            self.assertIn("```\nrestore as lead from Exchange/", r["text"])   # the bootstrap line is untouched
            key = "notes/x.md"
            c = self.h.claim(a, key)
            self.assertRegex(c["link"], r"^\[x\.md\]\(computer://")
            self.assertRegex(self.h.status(key)["artifacts"][0]["link"], r"^\[x\.md\]\(computer://")
            self.assertRegex(self.h.ledger()["text"], r"leases: \[x\.md\]\(computer://")


class HowRuns(Base):
    """Envoy item (wave 1): the approval `how` command is runnable from a harness-ops path, an Exchange path and a
    path with spaces, not only 'the file exists'."""
    def copy_scripts(self, *parts):
        import importlib.util, shutil, subprocess
        dst = os.path.join(self.tmp, *parts, "scripts")
        shutil.copytree(os.path.join(HERE, "..", "scripts"), dst, ignore=shutil.ignore_patterns("__pycache__"))
        spec = importlib.util.spec_from_file_location("harness_copy_" + str(len(parts)) + str(abs(hash(dst))), os.path.join(dst, "harness.py"))
        return dst, spec

    def check(self, *parts):
        import importlib.util, shlex, subprocess
        dst, spec = self.copy_scripts(*parts)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = mod
        sys.path.insert(0, dst)
        try:
            spec.loader.exec_module(mod)
        finally:
            sys.path.remove(dst)
        h = mod.Harness(self.home)
        a = h.register(project="orch", model=MODEL)["id"]
        r = h.request_approval(a, "export", {"out": None})
        argv = shlex.split(r["how"])
        self.assertEqual(argv[:2], ["python3", os.path.join(dst, "harness.py")])
        env = dict(os.environ, HARNESS_HOME=self.home, PYTHONDONTWRITEBYTECODE="1")
        pend = subprocess.run(argv[:2] + ["pending"], capture_output=True, text=True, env=env, stdin=subprocess.DEVNULL)
        self.assertEqual(pend.returncode, 0, pend.stderr)
        self.assertIn(r["pending"], pend.stdout)                  # this harness.py sees the request
        run = subprocess.run(argv, capture_output=True, text=True, env=env, stdin=subprocess.DEVNULL)
        self.assertEqual(run.returncode, 2, run.stderr)           # the exact command starts and stops at the tty gate
        self.assertIn("interactive terminal", run.stdout)

    def test_harness_ops_path(self):
        self.check("harness-ops", "projects", "skill-curation", "specs", "cc-x")

    def test_exchange_path(self):
        self.check("Exchange", "projects", "skill-curation", "specs", "cc-x")

    def test_path_with_spaces(self):
        self.check("Application Support", "plugin cache", "cc-x")


if __name__ == "__main__":
    unittest.main()
