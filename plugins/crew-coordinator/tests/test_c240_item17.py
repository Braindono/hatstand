"""cc 0.24.0 item 17 (scope A-b2950; guard spec v3; D-945c6, D-7e1dd): the Hatstand commit and push guard.

Tests G1 to G13 of the spec, in scratch repos only. Every git call reads a scratch global config (GIT_CONFIG_GLOBAL, with
GIT_CONFIG_NOSYSTEM=1) whose four includeIf lines match the test's local bare repo, so the real ~/.gitconfig is never read.
Identity values are synthetic and built at run time, so this file passes the rules it tests.
Run: python3 -B tests/test_c240_item17.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _env  # noqa: F401  isolate HOME and HARNESS_* first
import hashlib, json, os, re, shutil, subprocess, sys, tempfile, unittest, uuid
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SCRIPTS = os.path.join(ROOT, "scripts")
sys.path.insert(0, SCRIPTS)
import hatstand_guard as G
import hatstand_check as C

MODEL = "claude-opus-5-5"
GIT = shutil.which("git")
# the synthetic identity that _env.guard_home writes, built in pieces
USER = "zzsynth" + "user"
HOST = "zzsynth" + "host"
PERSONAL = "a.person" + "@" + "somewhere-mail.com"
GH = "git" + "@github.com"          # the git@ remote form, in pieces (the item 15 tree check reads it as an email)


def run(cmd, cwd=None, env=None, data=None):
    return subprocess.run(cmd, cwd=cwd, env=env, input=data, capture_output=True, text=True)


@unittest.skipUnless(GIT, "git needed")
class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.home = os.path.join(self.tmp, "home")
        os.makedirs(self.home)
        _env.guard_home(self.home)
        self.gitconfig = os.path.join(self.tmp, "gitconfig")
        self.hooks = _env.hatstand_hooks(self.tmp, self.home, self.gitconfig)
        self.env = {k: v for k, v in os.environ.items() if not k.startswith("HARNESS_")}
        self.env.update(GIT_CONFIG_GLOBAL=self.gitconfig, GIT_CONFIG_NOSYSTEM="1")
        self.bare = os.path.join(self.tmp, "hatstand.git")
        self.git(self.tmp, "init", "-q", "--bare", "-b", "main", self.bare)
        self.work = self.clone("work")
        self.commit(self.work, "README.md", "a clean start\n", "seed")
        self.ok(self.git(self.work, "push", "-q", "origin", "main"))

    def git(self, cwd, *a, env=None):
        return run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid"] + list(a), cwd=cwd, env=env or self.env)

    def ok(self, r):
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return r

    def refused(self, r, *words):
        self.assertNotEqual(r.returncode, 0, r.stdout + r.stderr)
        for w in words:
            self.assertIn(w, r.stderr)
        return r

    def clone(self, name):
        d = os.path.join(self.tmp, name)
        self.ok(self.git(self.tmp, "clone", "-q", "file://" + self.bare, d))
        return d

    def write(self, repo, name, text):
        p = os.path.join(repo, name)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write(text)

    def commit(self, repo, name, text, msg, *extra):
        self.write(repo, name, text)
        self.ok(self.git(repo, "add", name))
        return self.git(repo, "commit", "-q", "-m", msg, *extra)

    def sha(self, repo, rev="HEAD"):
        return self.git(repo, "rev-parse", rev).stdout.strip()

    def remote_main(self):
        return self.git(self.tmp, "--git-dir", self.bare, "rev-parse", "main").stdout.strip()


class G1Staged(Base):
    def test_g1_the_staged_blob_is_checked_not_the_working_tree(self):
        self.write(self.work, "notes.md", "see /Users/%s/x\n" % USER)
        self.ok(self.git(self.work, "add", "notes.md"))
        self.write(self.work, "notes.md", "nothing private here\n")          # the tree is clean; the index is not
        r = self.refused(self.git(self.work, "commit", "-q", "-m", "notes"), "rule 5a home/user", "(staged): notes.md:1")
        self.assertNotIn(USER, r.stderr)                                     # the value is never printed

    def test_a_clean_staged_commit_passes(self):
        self.ok(self.commit(self.work, "ok.md", "plain words\n", "ok"))


class G2Range(Base):
    def test_g2_a_middle_commit_with_a_host_name_stops_the_push(self):
        self.ok(self.commit(self.work, "a.md", "one\n", "one"))
        self.ok(self.commit(self.work, "b.md", "built on %s\n" % HOST, "two", "--no-verify"))
        bad = self.sha(self.work)
        self.ok(self.commit(self.work, "b.md", "clean again\n", "three"))
        h0 = self.remote_main()
        self.refused(self.git(self.work, "push", "-q", "origin", "main"), "rule 5b host name", "commit " + bad[:12])
        self.assertEqual(self.remote_main(), h0)


class G3TagsAndRefs(Base):
    def test_g3_an_annotated_tag_with_a_personal_email_is_refused(self):
        self.ok(self.git(self.work, "tag", "-a", "demo-v1.0.0", "-m", "release, ask " + PERSONAL))
        self.refused(self.git(self.work, "push", "-q", "origin", "refs/tags/demo-v1.0.0"), "rule 5c email", "tag ")

    def test_g3_a_ref_named_after_a_host_is_refused(self):
        self.ok(self.git(self.work, "push", "-q", "origin", "main"))
        self.refused(self.git(self.work, "push", "-q", "origin", "main:refs/heads/%s-work" % HOST), "rule 5b host name", "ref")

    def test_a_clean_annotated_tag_passes(self):
        self.ok(self.git(self.work, "tag", "-a", "demo-v1.0.0", "-m", "demo 1.0.0"))
        self.ok(self.git(self.work, "push", "-q", "origin", "refs/tags/demo-v1.0.0"))


class G4Pins(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.home, True)
        _env.guard_home(self.home)
        self.rules = G.Rules(self.home)

    def test_g4_a_pinned_credential_fixture_with_a_changed_sha_loses_its_exemption(self):
        self.assertTrue(G.CRED_PINNED)
        for name in G.CRED_PINNED:
            with open(os.path.join(ROOT, name[len(G._CC):]), "rb") as f:
                data = f.read()
            with self.subTest(name=name):
                self.assertFalse([h for h in G.check_blobs([(name, data)], self.rules) if h.rule == G.RULE["d"]])
                hits = G.check_blobs([(name, data + b"\n# one more line\n")], self.rules)
                self.assertTrue(any(h.rule == G.RULE["d"] and "CRED_PINNED" in h.reason for h in hits), hits)
                other = G._CC + "tests/copied_elsewhere.py"                 # the same bytes under another path: no pin
                self.assertTrue(any(h.rule == G.RULE["d"] for h in G.check_blobs([(other, data)], self.rules)))

    def test_g4_a_changed_fixture_manifest_is_refused(self):
        name = G.FIXTURE + "home/x.md"
        hits = G.check_blobs([(name, b"x\n")], self.rules, lambda n: b'{"files": {"x.md": "%s"}}' % hashlib.sha256(b"x\n").hexdigest().encode())
        self.assertTrue(any("manifest.json differs" in h.reason for h in hits), hits)

    def test_the_credential_rules_each_catch_their_shape(self):
        samples = ["gh" + "p_" + "a" * 36, "github" + "_pat_" + "b" * 30, "sk" + "-ant-" + "c" * 30, "sk" + "-proj-" + "d" * 30,
                   "AK" + "IA" + "E" * 16, "xo" + "xb-" + "1" * 12, "AI" + "za" + "f" * 35, "-----BEGIN RSA PRIV" + "ATE KEY-----",
                   "ey" + "Jabcdefghij.ey" + "Jklmnopqrst.signaturexx", "Authorization: Bear" + "er " + "g" * 30,
                   "https://user:" + "s3cretvalue" + "@host.example.com/x", "pass" + 'word = "' + "hunter22" + '"',
                   "someone@" + "private" + "relay.appleid.com"]
        for s in samples:
            with self.subTest(s=s[:8]):
                self.assertTrue(any(r == G.RULE["d"] for r, _l, _w in G.text_hits("x " + s + "\n", self.rules)), s[:8])

    def test_allowed_emails_and_remote_forms_pass(self):
        for s in ("Braindono@users.noreply.github.com", "noreply" + "@anthropic.com", GH + ":Braindono/x.git",
                  "t@example.invalid", "a@example.com", "b@x.test", "icon@2x"):
            with self.subTest(s=s):
                self.assertFalse([r for r, _l, _w in G.text_hits(s + "\n", self.rules) if r == G.RULE["c"]])
        self.assertTrue([r for r, _l, _w in G.text_hits("zz" + "@identity.example.invalid\n", self.rules) if r == G.RULE["c"]])

    def test_rule_5e_refuses_the_workspace_layout_and_allows_placeholders(self):
        for s in ("~/" + "Claude/Code", "$HOME/" + "Claude/x", "${HOME}/" + "Claude", "Library/Application Support/" + "Claude/x",
                  "local-agent-mode" + "-sessions/abc"):
            with self.subTest(s=s):
                self.assertTrue([r for r, _l, _w in G.text_hits(s + "\n", self.rules) if r == G.RULE["e"]])
        for s in ("<home>/Code", "<workspace>/Code", "~/ClaudeX", "the Claude app"):
            with self.subTest(s=s):
                self.assertFalse([r for r, _l, _w in G.text_hits(s + "\n", self.rules) if r == G.RULE["e"]])


class G5FailClosed(Base):
    def test_g5_a_missing_identity_list_stops(self):
        os.remove(os.path.join(self.home, "_harness", "data", G.IDENTITY_FILE))
        self.refused(self.commit(self.work, "a.md", "fine\n", "a"), "identity list")

    def test_g5_an_identity_line_that_is_not_understood_stops(self):
        with open(os.path.join(self.home, "_harness", "data", G.IDENTITY_FILE), "a") as f:
            f.write("nickname someone\n")
        self.refused(self.commit(self.work, "a.md", "fine\n", "a"), "is not 'user|host|email")

    def test_g5_a_missing_manifest_stops(self):
        os.remove(os.path.join(self.hooks, C.MANIFEST))
        self.refused(self.commit(self.work, "a.md", "fine\n", "a"), C.MANIFEST, "re-run the installer")

    def test_g5_a_changed_installed_file_stops(self):
        with open(os.path.join(self.hooks, "hatstand_guard.py"), "a") as f:
            f.write("\n# edited\n")
        self.refused(self.commit(self.work, "a.md", "fine\n", "a"), "hatstand_guard.py differs from its sha256")

    def test_g5_a_plain_shell_without_harness_variables_works(self):
        env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": self.tmp, "GIT_CONFIG_GLOBAL": self.gitconfig,
               "GIT_CONFIG_NOSYSTEM": "1"}
        self.ok(self.git(self.work, "add", "-A", env=env))
        self.write(self.work, "a.md", "fine\n")
        self.ok(self.git(self.work, "add", "a.md", env=env))
        self.ok(self.git(self.work, "commit", "-q", "-m", "a", env=env))
        self.ok(self.git(self.work, "push", "-q", "origin", "main", env=env))

    def test_no_environment_variable_turns_a_rule_off(self):
        env = dict(self.env, HATSTAND_GUARD_OFF="1", HATSTAND_SKIP="1", HARNESS_HOME=os.path.join(self.tmp, "nowhere"))
        self.write(self.work, "a.md", "on %s\n" % HOST)
        self.ok(self.git(self.work, "add", "a.md", env=env))
        self.refused(self.git(self.work, "commit", "-q", "-m", "a", env=env), "rule 5b host name")


class G6IncludeIf(Base):
    def hooks_path(self, url, env):
        d = tempfile.mkdtemp(dir=self.tmp)
        self.ok(self.git(d, "init", "-q", env=env))
        self.ok(self.git(d, "remote", "add", "origin", url, env=env))
        return self.git(d, "config", "--get", "core.hooksPath", env=env).stdout.strip()

    def test_g6_the_global_include_switches_the_hooks_on_for_every_spelling(self):
        tok = "x-access-token:" + "t" * 8 + "@"
        on = [GH + ":Braindono/hatstand.git", GH + ":Braindono/hatstand", "https://github.com/Braindono/hatstand.git",
              "https://github.com/Braindono/hatstand", "https://github.com/Braindono/hatstand.git/", "ssh://" + GH + "/Braindono/hatstand.git",
              "https://github.com/braindono/Hatstand.git", "https://%sgithub.com/Braindono/hatstand.git" % tok, "https://github.com/Braindono/hatstand/"]
        for url in on:
            with self.subTest(url=url):
                self.assertEqual(self.hooks_path(url, self.env), self.hooks)
        for url in (GH + ":Braindono/hatstand-private.git", "https://github.com/Braindono/hatstand-private"):
            with self.subTest(url=url):
                self.assertEqual(self.hooks_path(url, self.env), "")
        self.assertEqual(self.git(self.work, "config", "--get", "core.hooksPath").stdout.strip(), self.hooks)   # a fresh clone

    def test_g6_without_the_global_config_the_hooks_are_off(self):
        empty = os.path.join(self.tmp, "emptyhome")
        os.makedirs(empty)
        env = {k: v for k, v in self.env.items() if k != "GIT_CONFIG_GLOBAL"}
        env["HOME"] = empty
        self.assertEqual(self.hooks_path(GH + ":Braindono/hatstand.git", env), "")

    def test_the_patterns_match_the_daily_job_remote_test(self):
        self.assertEqual(C.INCLUDE_PATTERNS, _env.HATSTAND_INCLUDE_PATTERNS)
        self.assertTrue(C.is_hatstand_remote(GH + ":Braindono/hatstand.git"))
        self.assertFalse(C.is_hatstand_remote(GH + ":Braindono/hatstand-private.git"))


class G7Tree(unittest.TestCase):
    """Today's crew-coordinator tree, as it would be pushed (plugins/crew-coordinator/...), with this machine's names and a
    random identity value. The CHANGELOG is scanned too, now that the curator's scrub is in."""

    def scan(self):
        home = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, home, True)
        _env.guard_home(home)
        with open(os.path.join(home, "_harness", "data", G.IDENTITY_FILE), "w") as f:
            f.write("user u%s\n" % uuid.uuid4().hex[:12])
        rules = G.Rules(home)
        items = []
        for d, dirs, files in os.walk(ROOT):
            dirs[:] = [x for x in dirs if x not in ("__pycache__", ".git", ".claude")]
            for fn in files:
                rel = os.path.relpath(os.path.join(d, fn), ROOT)
                if fn == ".DS_Store":
                    continue
                with open(os.path.join(d, fn), "rb") as f:
                    items.append((G._CC + rel, f.read()))

        def get_blob(n):
            p = os.path.join(ROOT, n[len(G._CC):])
            if not n.startswith(G._CC) or not os.path.isfile(p):
                return None
            with open(p, "rb") as f:
                return f.read()
        return G.check_blobs(items, rules, get_blob)

    def test_g7_the_tree_passes_rules_5a_to_5d(self):
        hits = [h for h in self.scan() if h.rule != G.RULE["e"]]
        self.assertEqual(hits, [], "\n".join(h.stop_line() for h in hits[:20]))

    def test_g7_the_tree_passes_rule_5e(self):
        # the item 15 extension removed the workspace paths (envoy m-9c759018dee2): 5e STOPs in 0.24
        hits = [h for h in self.scan() if h.rule == G.RULE["e"]]
        self.assertEqual(hits, [], "\n".join(h.stop_line() for h in hits[:20]))

    def test_the_checker_files_pass_their_own_rules(self):
        names = [n for n in self.scan() if n.name.endswith(("hatstand_guard.py", "hatstand_check.py", "pre-commit", "pre-push",
                                                             "test_c240_item17.py", "_env.py"))]
        self.assertEqual(names, [])


class G8RepoContentDoesNotDecide(Base):
    def test_g8_planted_hooks_and_a_planted_guard_change_nothing(self):
        self.write(self.work, ".githooks/pre-commit", "#!/bin/sh\nexit 0\n")
        self.write(self.work, ".githooks/pre-push", "#!/bin/sh\nexit 0\n")
        os.chmod(os.path.join(self.work, ".githooks", "pre-commit"), 0o755)
        os.chmod(os.path.join(self.work, ".githooks", "pre-push"), 0o755)
        self.write(self.work, "plugins/crew-coordinator/scripts/hatstand_guard.py", "def check(*a):\n    return []\n")
        self.write(self.work, "scripts/hatstand_guard.py", "def check(*a):\n    return []\n")
        self.write(self.work, "a.md", "on %s\n" % HOST)
        self.ok(self.git(self.work, "add", "-A"))
        self.refused(self.git(self.work, "commit", "-q", "-m", "a"), "rule 5b host name")


class Mirror(Base):
    """A harness home with an envoy and a curator, a mirror of the remote, and the daily job."""

    def setUp(self):
        super().setUp()
        import harness as H
        self.H = H
        e = mock.patch.dict(os.environ, {"HARNESS_STATE_CACHE": "0"})
        e.start()
        self.addCleanup(e.stop)
        h = H.Harness(self.home)
        for r in ("envoy", "curator"):
            h.role_define("operator", r, "harness-ops")
            h.role_assign("operator", r, h.register(project="harness-ops", model=MODEL)["id"])
        self.mirror = os.path.join(self.tmp, "mirror.git")
        self.ok(self.git(self.tmp, "clone", "-q", "--mirror", "file://" + self.bare, self.mirror))
        self.baseline = os.path.join(self.home, "_harness", "data", C.BASELINE)

    def checker(self, *a, env=None):
        return run([sys.executable, "-I", "-B", os.path.join(self.hooks, "hatstand_check.py")] + list(a), env=env or self.env)

    def daily(self, *extra):
        env = {"PATH": "/usr/bin:/bin:" + os.path.dirname(sys.executable), "HOME": self.tmp, "GIT_CONFIG_GLOBAL": self.gitconfig,
               "GIT_CONFIG_NOSYSTEM": "1", "HARNESS_STATE_CACHE": "0", "HARNESS_STATE_DIR": os.path.join(self.tmp, "state")}
        return self.checker("daily", "--mirror", self.mirror, "--harness-scripts", SCRIPTS, *extra, env=env)

    def tasks(self):
        n = 0
        with open(os.path.join(self.home, "_harness", "events.jsonl"), encoding="utf-8") as f:
            for line in f:
                if '"message.sent"' in line and "Hatstand daily check" in line:
                    d = json.loads(line).get("data") or {}
                    self.assertEqual(d.get("kind"), "task")
                    n += 1
        return n

    def bad_push(self, name="leak.md"):
        self.ok(self.commit(self.work, name, "%s was built on %s\n" % (name, HOST), "bad", "--no-verify"))
        self.ok(self.git(self.work, "push", "-q", "--no-verify", "origin", "main"))


class G9Daily(Mirror):
    def test_g9_a_no_verify_push_is_reported_by_the_next_daily_run_as_one_task(self):
        self.ok(self.checker("scan-history", self.mirror, "--write-baseline"))
        r = self.daily()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertRegex(r.stdout, r"hatstand: daily: identity list sha256 [0-9a-f]{12}")
        self.assertEqual(self.tasks(), 0)
        self.bad_push()
        r = self.daily()
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("hatstand: daily: done, 1 problem(s)", r.stdout)
        self.assertIn("new hit on the remote: rule 5b host name", r.stderr)
        self.assertNotIn(HOST, r.stderr)
        self.assertEqual(self.tasks(), 1)

    def test_a_ref_tip_the_sync_did_not_push_is_reported(self):
        self.ok(self.checker("scan-history", self.mirror, "--write-baseline"))
        with open(os.path.join(self.home, "_harness", "events.jsonl"), "a") as f:
            f.write(json.dumps({"type": "hatstand.synced", "data": {"pushed": {"refs/heads/main": self.remote_main()}}}) + "\n")
        self.ok(self.daily())
        self.ok(self.commit(self.work, "c.md", "clean\n", "clean"))
        self.ok(self.git(self.work, "push", "-q", "origin", "main"))           # a clean push from outside the sync
        r = self.daily()
        self.assertIn("refs/heads/main on the remote is not the sha the sync pushed", r.stderr)
        self.assertEqual(self.tasks(), 1)


class G10NoTracking(Base):
    def test_g10_a_clone_that_knows_nothing_of_the_remote_scans_the_whole_history(self):
        d = os.path.join(self.tmp, "fresh")
        self.ok(self.git(self.tmp, "init", "-q", "-b", "main", d))
        self.ok(self.git(d, "remote", "add", "origin", "file://" + self.bare))
        self.ok(self.commit(d, "old.md", "on %s\n" % HOST, "old", "--no-verify"))
        self.ok(self.commit(d, "old.md", "clean now\n", "clean"))
        self.refused(self.git(d, "push", "-q", "origin", "main:refs/heads/side"), "rule 5b host name")


class G11NewTagOnly(Base):
    def test_g11_a_new_tag_scans_only_its_new_commits_and_the_tag_object(self):
        self.ok(self.commit(self.work, "old.md", "on %s\n" % HOST, "old", "--no-verify"))
        self.ok(self.git(self.work, "push", "-q", "--no-verify", "origin", "main"))     # an old hit, already on the remote
        self.ok(self.commit(self.work, "old.md", "scrubbed\n", "scrub"))
        self.ok(self.git(self.work, "tag", "-a", "crew-coordinator-v0.24.0", "-m", "crew-coordinator 0.24.0"))
        self.ok(self.git(self.work, "push", "-q", "origin", "main", "refs/tags/crew-coordinator-v0.24.0"))
        r = run([sys.executable, "-I", "-B", os.path.join(self.hooks, "hatstand_check.py"), "scan-history", self.work], env=self.env)
        self.assertEqual(r.returncode, 1, r.stderr)                                     # the full history still has it
        self.assertIn("rule 5b host name", r.stderr)


class G12SelfCheck(Mirror):
    def sync_env(self):
        mk = os.path.join(self.home, "_harness", "marketplace")
        os.makedirs(os.path.join(mk, "plugins", "demo", ".claude-plugin"), exist_ok=True)
        os.makedirs(os.path.join(mk, ".claude-plugin"), exist_ok=True)
        with open(os.path.join(mk, "plugins", "demo", ".claude-plugin", "plugin.json"), "w") as f:
            f.write('{"name": "demo", "version": "1.0.0"}\n')
        with open(os.path.join(mk, ".claude-plugin", "marketplace.json"), "w") as f:
            f.write('{"plugins": []}\n')
        with open(os.path.join(self.home, "_harness", "wake.py"), "w") as f:
            f.write("print('wake')\n")
        for d in ("plugins", "bin", ".claude-plugin"):
            self.write(self.work, d + "/.keep", "")
        self.ok(self.git(self.work, "add", "-A"))
        self.ok(self.git(self.work, "commit", "-q", "-m", "layout"))
        self.ok(self.git(self.work, "push", "-q", "origin", "main"))
        return dict(self.env, HARNESS_HOME=self.home, HATSTAND_REPO="file://" + self.bare)

    def sync(self, env):
        return run(["/bin/sh", os.path.join(SCRIPTS, "hatstand-sync.sh"), "--push"], env=env)

    def test_the_sync_pushes_with_the_hooks_on_and_reports_each_ref(self):
        r = self.sync(self.sync_env())
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("hatstand: pushed_ref refs/heads/main %s" % self.remote_main(), r.stdout)
        self.assertRegex(r.stdout, r"hatstand: identity list sha256 [0-9a-f]{12}")             # critic r1: a list change shows
        self.assertRegex(r.stdout, r"hatstand: pushed_ref refs/tags/demo-v1\.0\.0 [0-9a-f]{40}")

    def test_g12_a_hook_that_is_not_executable_stops_the_sync(self):
        env = self.sync_env()
        h0 = self.remote_main()
        os.chmod(os.path.join(self.hooks, "pre-push"), 0o644)
        r = self.sync(env)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("pre-push is not executable", r.stderr)
        self.assertEqual(self.remote_main(), h0)

    def test_g12_a_missing_hooks_folder_stops_the_sync(self):
        env = self.sync_env()
        h0 = self.remote_main()
        os.rename(self.hooks, self.hooks + ".moved")
        r = self.sync(env)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("is missing", r.stderr)
        self.assertEqual(self.remote_main(), h0)

    def test_g12_a_local_hooks_path_is_found_and_the_daily_job_sends_one_task(self):
        self.ok(self.checker("scan-history", self.mirror, "--write-baseline"))
        self.ok(self.git(self.work, "config", "--local", "core.hooksPath", ".githooks"))
        r = self.checker("self-check", self.work)
        self.assertEqual(r.returncode, 1)
        self.assertIn("local core.hooksPath", r.stderr)
        self.assertIn(os.path.join(os.path.realpath(self.work), ".githooks"), r.stderr)      # resolved from the clone, as git does
        r = self.daily("--git-root", self.tmp)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("hooks off in work", r.stderr)
        self.assertEqual(self.tasks(), 1)

    def test_g12_the_sync_never_passes_no_verify(self):
        with open(os.path.join(SCRIPTS, "hatstand-sync.sh"), encoding="utf-8") as f:
            code = "\n".join(l for l in f.read().splitlines() if not l.lstrip().startswith("#"))
        self.assertNotIn("--no-verify", code)
        self.assertNotIn("core.hooksPath", code)


class G13Baseline(Mirror):
    def test_g13_known_hits_are_quiet_and_a_new_hit_is_reported(self):
        self.bad_push("old.md")
        self.ok(self.git(self.mirror, "fetch", "-q", "--prune"))
        r = self.checker("scan-history", self.mirror)
        self.assertEqual(r.returncode, 1)                                             # no baseline yet: the old hit shows
        self.ok(self.checker("scan-history", self.mirror, "--write-baseline"))
        with open(self.baseline, encoding="utf-8") as f:
            self.assertNotIn(HOST, f.read())                                          # object, rule and line; no text
        self.ok(self.checker("scan-history", self.mirror))                            # 0 hits against the baseline
        self.bad_push("new.md")
        self.ok(self.git(self.mirror, "fetch", "-q", "--prune"))
        r = self.checker("scan-history", self.mirror)
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertIn("new.md", r.stderr)
        self.assertNotIn("old.md", r.stderr)


class FixRound1(unittest.TestCase):
    """Item 17 fix round 1 (envoy D-4ba2f points 2-3, m-9c759018dee2; critic r1 non-blocking)."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def plugin(self, files):
        root = os.path.join(self.tmp, "demo")
        for rel, text in dict(files, **{".claude-plugin/plugin.json": json.dumps({"name": "demo", "version": "1.0.0", "description": "d"})}).items():
            p = os.path.join(root, rel)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w", encoding="utf-8") as f:
                f.write(text)
        return root

    def publisher(self):
        import harness as H
        H_inv = H.plugin_inventory
        H.plugin_inventory = lambda home, own_code=None: {}
        self.addCleanup(setattr, H, "plugin_inventory", H_inv)
        home = os.path.join(self.tmp, "home")
        os.makedirs(home)
        h = H.Harness(home)
        h.role_define("operator", "envoy", "harness-ops")
        envoy = h.register(project="harness-ops", model=MODEL)["id"]
        h.role_assign("operator", "envoy", envoy)
        return H, h, envoy

    def test_a_publish_build_refuses_a_workspace_path_in_the_package(self):
        H, h, envoy = self.publisher()
        root = self.plugin({"docs/notes.md": "see ~/" + "Claude/Code/x\n"})
        acc = h.send(envoy, "operator", "ACCEPT sha=%s" % H.bytes_sha(H.build_package(root))[:12])["id"]
        with self.assertRaises(H.HarnessError) as cm:
            h.publish_release(root, accept=acc, build=True, dry_run=True)
        self.assertIn("rule 5e", str(cm.exception))
        self.assertIn("docs/notes.md:1", str(cm.exception))

    def test_the_package_check_covers_the_changelog_and_honours_the_fixture(self):
        line = ("~/" + "Claude/x\n").encode()
        self.assertEqual(G.PACKAGE_5E_LATER, ())                                     # the scrubbed CHANGELOG is in
        self.assertTrue(G.workspace_hits([("plugins/demo/CHANGELOG.md", line)]))
        self.assertTrue(G.workspace_hits([("plugins/demo/docs/CHANGELOG.md", line)]))
        self.assertTrue(G.workspace_hits([("plugins/demo/README.md", line)]))
        self.assertTrue(G.workspace_hits([(G.FIXTURE + "home/x.md", line)]))          # no pinned manifest: not exempt

    def test_the_sync_comment_calls_hatstand_the_public_mirror(self):
        head = open(os.path.join(SCRIPTS, "hatstand-sync.sh"), encoding="utf-8").read(400)
        self.assertIn("public mirror github.com/Braindono/hatstand", head)
        self.assertNotIn("private repo github.com/Braindono/hatstand.", head)


class ReleaseTree(unittest.TestCase):
    def test_the_changelog_exemption_is_gone_once_the_tree_is_0_24_0(self):
        """Critic r2 (m-34c132549c91): PACKAGE_5E_LATER only waits for the curator's CHANGELOG scrub; a release tree at 0.24.0 or
        later must not keep it."""
        v = json.load(open(os.path.join(ROOT, ".claude-plugin", "plugin.json"), encoding="utf-8"))["version"]
        if tuple(int(x) for x in re.findall(r"\d+", v)[:3]) >= (0, 24, 0):
            self.assertEqual(G.PACKAGE_5E_LATER, (), "remove CHANGELOG.md from PACKAGE_5E_LATER once the scrubbed CHANGELOG is in")


class SyncRecord(unittest.TestCase):
    def test_hatstand_synced_records_the_pushed_refs(self):
        src = open(os.path.join(SCRIPTS, "harness.py"), encoding="utf-8").read()
        rx = re.search(r're\.finditer\(r"(hatstand: pushed_ref [^"]+)"', src).group(1)
        out = "hatstand: pushed abc1234\nhatstand: pushed_ref refs/heads/main %s\nhatstand: pushed_ref refs/tags/x-v1 %s\n" % ("a" * 40, "b" * 40)
        self.assertEqual({m.group(1): m.group(2) for m in re.finditer(rx, out)}, {"refs/heads/main": "a" * 40, "refs/tags/x-v1": "b" * 40})
        self.assertIn('"pushed": pushed', src)


if __name__ == "__main__":
    unittest.main()
