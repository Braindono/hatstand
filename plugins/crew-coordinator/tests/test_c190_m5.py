"""cc 0.19.0 M5: the stale reload Do-line, R-120 approval visibility, R-116 Hatstand version tags, the lesson cue wiring
(hooks.json + the lesson.cued ingest). Run: python3 -B tests/test_c190_m5.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _env  # noqa: F401  isolate HOME and HARNESS_* first
import json, os, shutil, subprocess, sys, tempfile, time, types, unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(HERE, "..", "scripts")
sys.path.insert(0, SCRIPTS)
import harness as H
from test_c190_m3 import Base, MODEL


class ReloadLine(unittest.TestCase):
    def st(self):
        reg = {H.SELF_NAME: {"name": H.SELF_NAME, "version": "9.9.9", "code": "cafe" * 5, "kind": "plugin", "t": time.time()}}
        me = {"id": "me", "status": "active", "inventory": {H.SELF_NAME: {"v": "9.0.0", "code": "0ld0" * 3}}, "last_mcp_via": {}}
        return types.SimpleNamespace(registry=reg, agents={"me": me}, now=time.time())

    def test_reload_line_is_gone_once_the_live_server_runs_the_published_code(self):
        st = self.st()
        stale = H.drift_lines(st, "me", {H.SELF_NAME: "9.9.9"})
        self.assertTrue(any(f.startswith("reload: ") for f in stale["flags"]), stale)            # the recorded inventory is old
        live = H.drift_lines(st, "me", {H.SELF_NAME: "9.9.9"}, live=("9.9.9", "cafe" * 3))
        self.assertEqual([f for f in live["flags"] if f.startswith("reload: ")], [])             # the server answering runs it
        behind = H.drift_lines(st, "me", {H.SELF_NAME: "9.9.9"}, live=("9.0.0", "0ld0" * 3))
        self.assertTrue(any(f.startswith("reload: ") for f in behind["flags"]), behind)         # a really stale server still says so

    def test_other_plugins_still_use_the_recorded_code(self):
        st = self.st()
        st.registry["other"] = {"name": "other", "version": "2.0.0", "code": "bbbb", "kind": "plugin"}
        st.agents["me"]["inventory"]["other"] = {"v": "1.0.0", "code": "aaaa"}
        L = H.drift_lines(st, "me", {"other": "2.0.0", H.SELF_NAME: "9.9.9"}, live=("9.9.9", "cafe" * 3))
        self.assertEqual([f.split()[1] for f in L["flags"] if f.startswith("reload: ")], ["other"])

    def test_sync_passes_the_live_code_only_over_mcp(self):
        src = open(os.path.join(SCRIPTS, "harness.py"), encoding="utf-8").read()
        self.assertIn('live=(VERSION, (RUNNING_CODE_SHA or "")[:12]) if TRANSPORT == "mcp"', src)


class Approvals(Base):
    def req(self, who="curator", action="export", **args):
        return self.h.request_approval(self.ids[who], action, args or {"out": "x"})["pending"]

    def test_ttl_from_config(self):
        a = self.req()
        rec = self.h._approval_records()[a]
        self.assertAlmostEqual(rec["expires"] - rec["requested"], 600, delta=2)
        with open(os.path.join(self.home, "_harness", "config.json"), "w") as f:
            json.dump({"approval_ttl_seconds": 3600}, f)
        b = self.req(out="y")
        rec = self.h._approval_records()[b]
        self.assertAlmostEqual(rec["expires"] - rec["requested"], 3600, delta=2)
        with open(os.path.join(self.home, "_harness", "config.json"), "w") as f:
            json.dump({"approval_ttl_seconds": 30}, f)               # below the floor: the default
        c = self.req(out="z")
        rec = self.h._approval_records()[c]
        self.assertAlmostEqual(rec["expires"] - rec["requested"], 600, delta=2)

    def test_sync_lists_each_pending_approval_with_requester_action_and_minutes(self):
        a, b = self.req("curator", "export", out="x"), self.req("envoy", "export", out="y")
        t = self.h.sync(self.ids["ops-coder"])["text"]
        self.assertRegex(t, rf"▲ approval {a} from \S+ \S+: export, \d+ min left \(harness.py approve {a}\)")
        self.assertIn(f"▲ approval {b} from", t)
        self.assertNotIn("approval request(s)", t)
        for i in range(5):
            self.req("steward", "export", out=f"m{i}")
        t = self.h.sync(self.ids["ops-coder"])["text"]
        self.assertIn("more approval requests: harness.py pending", t)
        self.assertEqual(t.count("▲ approval A-"), 5)

    def test_a_lesson_curation_approval_says_no_expiry(self):
        les = self.lesson("curator", "x", "Check twice")
        r = self.h.lesson_curate_propose(self.ids["curator"], [les["id"]])
        self.assertIn(f"{r['pending']} from", self.h.sync(self.ids["ops-coder"])["text"])
        self.assertIn("lesson_curate, no expiry", self.h.sync(self.ids["ops-coder"])["text"])

    def lesson(self, by, what, rule):
        return self.h.record(self.ids[by], "note", "Lesson: " + what, f"What happened: {what}\nCause: c\nRule: {rule}", ["lesson", "role:all"])

    def test_approvals_all_shows_every_state_with_its_outcome(self):
        import mcp_server as M
        ok, no, old = self.req(out="a"), self.req(out="b"), self.req(out="c")
        self.grant(ok)
        self.h.deny(no)
        bad = self.h.request_approval(self.ids["curator"], "role_assign", {"role": "nope-role", "target": self.ids["curator"]})["pending"]
        self.grant(bad)
        pend = M.call(self.h, "harness_admin", {"op": "approvals", "agent": self.ids["curator"][:8]})["text"]
        self.assertIn(old, pend)
        self.assertNotIn(ok, pend)
        allx = M.call(self.h, "harness_admin", {"op": "approvals", "agent": self.ids["curator"][:8], "args": {"all": True}})["text"]
        for i, state in ((ok, "granted"), (no, "denied"), (old, "pending"), (bad, "failed")):
            self.assertRegex(allx, rf"{i} {state}")
        self.assertRegex(allx, rf"{bad} failed role_assign .* result: .*")

    def test_recall_of_an_approval_id_returns_its_event_chain(self):
        a = self.req(out="chain")
        self.grant(a)
        self.h.consume_approval(self.ids["curator"], "export", {"out": "chain"})
        t = self.h.recall(None, [a], None, None, None, 5, 2000)["text"]
        self.assertIn(f"{a} approval · export · state granted (used)", t)
        self.assertRegex(t, r"events: requested \S+ → granted \S+ \(cli-tty\) → consumed")
        self.assertIn("untrusted from the requester", t)
        self.assertIn("no such approval", self.h.recall(None, ["A-00000"], None, None, None, 5, 2000)["text"])

    def grant(self, pid):
        return self.h.approve(pid, "cli-tty", self.h._approval_records()[pid]["args_digest"][:4], True)

    def test_a_failed_approval_reaches_the_requester_once(self):
        bad = self.h.request_approval(self.ids["curator"], "role_assign", {"role": "nope-role", "target": self.ids["curator"]})["pending"]
        self.assertEqual(self.grant(bad)["state"], "failed")
        t1 = self.h.sync(self.ids["curator"])["text"]
        self.assertRegex(t1, rf"✕ approval {bad} \(role_assign\) failed: ")
        self.assertNotIn(f"✕ approval {bad}", self.h.sync(self.ids["curator"])["text"])          # once
        self.assertNotIn(f"✕ approval {bad}", self.h.sync(self.ids["envoy"])["text"])            # only the requester


class Cue(Base):
    def spool(self, *lines, raw=None):
        p = os.path.join(self.home, "_harness", "cue_spool.jsonl")
        with open(p, "a", encoding="utf-8") as f:
            for d in lines:
                f.write(json.dumps(d) + "\n")
            if raw:
                f.write(raw)
        return p

    def line(self, lesson="N-aaaaa", sid="sess-1", **kw):
        return dict({"ts": "2026-10-29T00:00:00Z", "session_id": sid, "host_session_id": "local_x", "tool": "Bash", "lesson": lesson,
                     "mode": "note", "matched": "input", "input_sha": "abc123abc123"}, **kw)

    def cued(self):
        return [e for e in self.h.store.read_all() if e["type"] == "lesson.cued"]

    def test_hooks_json_wires_the_cue_for_tools_and_prompts(self):
        hj = json.load(open(os.path.join(HERE, "..", "hooks", "hooks.json")))
        pre = [h for g in hj["hooks"]["PreToolUse"] for h in g["hooks"] if "lesson_cue.py" in h["command"]]
        ups = [h for g in hj["hooks"]["UserPromptSubmit"] for h in g["hooks"] if "lesson_cue.py" in h["command"]]
        self.assertEqual((len(pre), len(ups)), (1, 1))
        g = [g for g in hj["hooks"]["PreToolUse"] if any("lesson_cue.py" in h["command"] for h in g["hooks"])][0]
        self.assertNotEqual(g["matcher"], "*")                   # narrow: Bash, edit tools and MCP tools

    def test_ingest_makes_one_event_per_line_once(self):
        self.spool(self.line("N-aaaaa"), self.line("N-bbbbb", tool="Edit"))
        self.assertEqual(self.h.ingest_cue_spool(), 2)
        self.assertEqual([e["data"]["lesson"] for e in self.cued()], ["N-aaaaa", "N-bbbbb"])
        self.assertEqual(self.h.ingest_cue_spool(), 0)
        self.assertEqual(len(self.cued()), 2)
        self.spool(self.line("N-ccccc"))
        self.assertEqual(self.h.ingest_cue_spool(), 1)
        self.assertEqual(set(self.cued()[0]["data"]), {"ts", "session_id", "host_session_id", "tool", "lesson", "mode", "matched", "input_sha"})

    def test_a_half_written_line_waits_and_a_bad_line_is_skipped(self):
        self.spool(self.line("N-aaaaa"), raw="not json\n" + json.dumps(self.line("N-bbbbb"))[:30])
        self.assertEqual(self.h.ingest_cue_spool(), 1)                           # the bad line is skipped, the half line waits
        p = os.path.join(self.home, "_harness", "cue_spool.jsonl")
        with open(p, "a") as f:
            f.write(json.dumps(self.line("N-bbbbb"))[30:] + "\n")
        self.assertEqual(self.h.ingest_cue_spool(), 1)
        self.assertEqual([e["data"]["lesson"] for e in self.cued()], ["N-aaaaa", "N-bbbbb"])

    def test_truncated_file_starts_again_and_the_session_gives_the_actor(self):
        a = self.ids["ops-coder"]
        self.h.store.append("session.bound", a, {"session_id": "sess-9", "agent": a})
        self.spool(self.line("N-aaaaa", sid="sess-9"), self.line("N-bbbbb", sid="unknown"))
        self.h.ingest_cue_spool()
        self.assertEqual([e["actor"] for e in self.cued()], [a, "system"])
        p = os.path.join(self.home, "_harness", "cue_spool.jsonl")
        open(p, "w").write(json.dumps(self.line("N-ccccc")) + "\n")             # rotated: shorter than the offset
        self.assertEqual(self.h.ingest_cue_spool(), 1)

    def test_the_cap_per_sync_and_the_rest_next_time(self):
        self.spool(*[self.line(f"N-{i:05x}") for i in range(7)])
        with mock.patch.object(H.Harness, "CUE_SPOOL_MAX", 3):
            self.assertEqual(self.h.ingest_cue_spool(), 3)
            self.assertEqual(self.h.ingest_cue_spool(), 3)
            self.assertEqual(self.h.ingest_cue_spool(), 1)
        self.assertEqual(len(self.cued()), 7)

    def test_sync_ingests_and_the_real_hook_script_feeds_it(self):
        les = self.h.record(self.ids["curator"], "note", "Lesson: push", "What happened: x\nCause: y\nRule: Check the branch first", ["lesson", "role:all"])["id"]
        self.curate("curator", les)                                       # M6: a cue can only repeat an approved lesson's Rule
        self.assertTrue(os.path.isfile(os.path.join(self.home, "_harness", "data", "lesson_cues.json")))
        trig = {"v": 1, "max_per_session": 3, "entries": [{"id": les, "tool": "^Bash$", "input": "(?i)git push", "cue": "free text is ignored", "mode": "note", "on": "tool"}]}
        os.makedirs(os.path.join(self.home, "_harness", "data"), exist_ok=True)
        json.dump(trig, open(os.path.join(self.home, "_harness", "data", "lesson_triggers.json"), "w"))
        env = dict(os.environ, HARNESS_LESSON_CUE="on", HARNESS_HOME=self.home)
        r = subprocess.run([sys.executable, "-B", os.path.join(SCRIPTS, "lesson_cue.py")], capture_output=True, text=True, env=env,
                           input=json.dumps({"hook_event_name": "PreToolUse", "session_id": "s7", "tool_name": "Bash", "tool_input": {"command": "git push origin main"}}))
        self.assertIn(f"Lesson {les}: Check the branch first", r.stdout)
        self.assertNotIn("free text is ignored", r.stdout)
        self.h.sync(self.ids["ops-coder"])
        self.assertEqual([e["data"]["lesson"] for e in self.cued()], [les])
        self.h.sync(self.ids["ops-coder"])
        self.assertEqual(len(self.cued()), 1)

    def test_off_by_default_prints_nothing(self):
        env = {k: v for k, v in os.environ.items() if k != "HARNESS_LESSON_CUE"}
        env["HARNESS_HOME"] = self.home
        r = subprocess.run([sys.executable, "-B", os.path.join(SCRIPTS, "lesson_cue.py")], capture_output=True, text=True, env=env,
                           input=json.dumps({"hook_event_name": "PreToolUse", "session_id": "s8", "tool_name": "Bash", "tool_input": {"command": "git push"}}))
        self.assertEqual((r.returncode, r.stdout), (0, ""))
        self.assertFalse(os.path.exists(os.path.join(self.home, "_harness", "cue_spool.jsonl")))


def git(*a, cwd=None):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *a], cwd=cwd, capture_output=True, text=True, check=True).stdout


@unittest.skipUnless(shutil.which("git") and shutil.which("rsync"), "git and rsync needed")
class Tags(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.home = os.path.join(self.tmp, "Exchange")
        self.mk = os.path.join(self.home, "_harness", "marketplace")
        for pl in ("demo", "other"):
            os.makedirs(os.path.join(self.mk, "plugins", pl, ".claude-plugin"))
        os.makedirs(os.path.join(self.mk, ".claude-plugin"))
        self.version("demo", "1.0.0")
        self.version("other", "0.5.0")
        open(os.path.join(self.mk, ".claude-plugin", "marketplace.json"), "w").write('{"plugins": []}\n')
        open(os.path.join(self.home, "_harness", "wake.py"), "w").write("print('wake')\n")
        _env.guard_home(self.home)
        open(os.path.join(self.home, "_harness", "events.jsonl"), "w").write("")
        self.bare = os.path.join(self.tmp, "hatstand.git")
        git("init", "-q", "--bare", "-b", "main", self.bare)
        seed = os.path.join(self.tmp, "seed")
        git("init", "-q", "-b", "main", seed)
        for d in ("plugins", "bin", ".claude-plugin"):
            os.makedirs(os.path.join(seed, d))
            open(os.path.join(seed, d, ".keep"), "w").close()
        git("add", "-A", cwd=seed)
        git("commit", "-q", "-m", "seed", cwd=seed)
        git("push", "-q", self.bare, "main", cwd=seed)
        self.env = dict(os.environ, HARNESS_HOME=self.home, HATSTAND_REPO="file://" + self.bare, GIT_CONFIG_GLOBAL=os.path.join(self.tmp, "gitconfig"))

    def version(self, pl, v):
        open(os.path.join(self.mk, "plugins", pl, ".claude-plugin", "plugin.json"), "w").write('{"name": "%s", "version": "%s"}\n' % (pl, v))

    def sync(self, push=True):
        r = subprocess.run(["/bin/sh", os.path.join(SCRIPTS, "hatstand-sync.sh")] + (["--push"] if push else []), capture_output=True, text=True, env=self.env)
        return r.returncode, r.stdout + r.stderr

    def tags(self):
        return sorted(git("--git-dir", self.bare, "tag", "-l").split())

    def test_a_new_version_gets_one_annotated_tag_and_a_resync_none(self):
        code, out = self.sync()
        self.assertEqual(code, 0, out)
        self.assertEqual(self.tags(), ["demo-v1.0.0", "other-v0.5.0"])
        self.assertEqual(git("--git-dir", self.bare, "cat-file", "-t", "refs/tags/demo-v1.0.0").strip(), "tag")      # annotated
        code, out = self.sync()
        self.assertIn("no changes", out)
        self.assertNotIn("tagged", out)
        self.assertEqual(self.tags(), ["demo-v1.0.0", "other-v0.5.0"])
        first = git("--git-dir", self.bare, "rev-list", "-n1", "demo-v1.0.0").strip()
        self.version("demo", "1.1.0")
        code, out = self.sync()
        self.assertEqual(out.count("hatstand: tagged"), 1, out)
        self.assertEqual(self.tags(), ["demo-v1.0.0", "demo-v1.1.0", "other-v0.5.0"])
        self.assertEqual(git("--git-dir", self.bare, "rev-list", "-n1", "demo-v1.0.0").strip(), first)               # the old tag did not move
        self.assertNotEqual(git("--git-dir", self.bare, "rev-list", "-n1", "demo-v1.1.0").strip(), first)
        self.assertEqual(git("--git-dir", self.bare, "for-each-ref", "--format=%(refname)", "refs/heads").split(), ["refs/heads/main"])                          # no branches

    def test_a_dry_run_creates_no_tag(self):
        code, out = self.sync(push=False)
        self.assertEqual(code, 0, out)
        self.assertEqual(self.tags(), [])
        self.assertNotIn("tagged", out)

    def test_an_untagged_version_with_no_file_change_is_tagged_on_a_push(self):
        self.sync()
        git("--git-dir", self.bare, "tag", "-d", "other-v0.5.0")
        code, out = self.sync()
        self.assertIn("hatstand: tagged other-v0.5.0", out)
        self.assertEqual(self.tags(), ["demo-v1.0.0", "other-v0.5.0"])

    def test_a_bad_version_string_is_skipped(self):
        self.version("other", "0.5.0;touch x")
        code, out = self.sync()
        self.assertEqual(code, 0, out)
        self.assertEqual(self.tags(), ["demo-v1.0.0"])


if __name__ == "__main__":
    unittest.main(verbosity=1)
