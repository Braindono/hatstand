"""cc 0.18.0: the three P1 security fixes from the audit triage (D-d45fc).
R-096 (G-01) quoted JSON keys redact; R-097 (G-03, D-c92cb) Hatstand sync scan and corpus/ledger guard; R-098 (G-07)
lease race. Run: python3 -B tests/test_c180_fixes.py
Secret-shaped and ledger-shaped test strings are built by concatenation, so this file itself never trips the scan
or the guard when it is synced."""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _env  # noqa: F401  isolate HOME and HARNESS_* first
import gzip, hashlib, json, os, shutil, subprocess, sys, tempfile, threading, unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
import harness as H
import hatstand_guard as G
import transcript_indexer as T

MODEL = "claude-opus-5-5"
GIT = shutil.which("git")
LEDGER_LINE = '{"se' + 'q": 9, "t": 1.0, "type": "x", "pr' + 'ev": "ab", "ha' + 'sh": "cd"}'
LEDGER_EVENT = {"se" + "q": 9, "type": "x", "pr" + "ev": "ab", "ha" + "sh": "cd"}
REAL_FIXTURE = os.path.join(HERE, "fixtures", "steward-r045")


def planted(put, only=None):
    """The critic's planted set (N-b5617); each case must stop a push. put(name, bytes) writes one staged file.
    -> number of cases. `only` = index of one case."""
    rel = "x/events.txt"
    line = (LEDGER_LINE + "\n").encode()

    def manifest(extra_file=False, ledger_note=False):
        with open(os.path.join(REAL_FIXTURE, "manifest.json")) as f:
            man = json.load(f)
        if extra_file:
            man["files"][rel] = hashlib.sha256(line).hexdigest()
        if ledger_note:
            man["note"] = LEDGER_LINE
        return json.dumps(man, indent=1).encode()
    cases = [
        lambda: put("plugins/crew-coordinator/corpus/\u00e9vents.txt", line),                 # B1 quoted name
        lambda: (put(G.FIXTURE + "home/" + rel, line),                                       # B2 self-certified
                 put(G.FIXTURE + "manifest.json", manifest(extra_file=True))),
        lambda: put(G.FIXTURE + "manifest.json", manifest(ledger_note=True)),                 # B2 line in manifest
        lambda: put("plugins/demo/Vault/a.md", b"minutes\n"),                                 # N1 case
        lambda: put("plugins/demo/Corpus/b.md", b"an entry\n"),                               # N1 case
        lambda: put("plugins/demo/data/ledger.gz", gzip.compress(line * 3)),                  # N1 gzip
        lambda: put("plugins/demo/data/u16.txt", (LEDGER_LINE + "\n").encode("utf-16")),     # N1 UTF-16
        lambda: put("plugins/demo/data/pretty.json", json.dumps(LEDGER_EVENT, indent=2).encode()),  # N1 multi-line
        lambda: put("plugins/demo/docs/notes.md", json.dumps(LEDGER_EVENT, indent=2).encode()),     # ledger dump in .md
        lambda: put("plugins/demo/docs/esc.md", LEDGER_LINE.replace('"', '\\"').encode()),            # (a) escaped quotes
        lambda: put("plugins/demo/docs/repr.txt", repr(LEDGER_EVENT).encode()),                     # (b) Python repr
        lambda: put("plugins/demo/data/u32.txt", (LEDGER_LINE + "\n").encode("utf-32")),          # (c) UTF-32
        lambda: put("plugins/demo/assets/logo.png", (LEDGER_LINE + "\n").encode()),               # (d) fake asset
    ]
    for k, c in enumerate(cases):
        if only is None or only == k:
            c()
    return len(cases)


# ---------------------------------------------------------------- R-096
class QuotedKeys(unittest.TestCase):
    def test_envoy_json_cases_redact(self):
        for key in ("password", "api_key", "token", "clientSecret"):
            for sep in (": ", ":"):
                s = '{"%s"%s"%s"}' % (key, sep, "v4lue" + "Q" * 10)
                out, kinds = T.redact(s)
                self.assertNotIn("Q" * 10, out, s)
                self.assertTrue(kinds, s)

    def test_plain_forms_still_redact(self):
        for s in ("password=" + "h" * 12, "token: " + "a" * 12, "api-key = " + "z" * 12, "client_secret='" + "y" * 12 + "'"):
            out, kinds = T.redact(s)
            self.assertIn("redacted", out, s)

    def test_escaped_json_keys_redact(self):
        """critic N3: a JSON document stored inside a JSON string escapes its quotes."""
        for key in ("password", "api_key", "token", "clientSecret"):
            s = '{\\"%s\\": \\"%s\\"}' % (key, "v4lue" + "Q" * 10)
            out, kinds = T.redact(s)
            self.assertNotIn("Q" * 10, out, s)

    def test_long_value_quoted_key(self):
        out, kinds = T.redact('{"access_token": "' + "A1" * 20 + '"}')
        self.assertNotIn("A1" * 20, out)

    def test_long_runs_are_linear(self):
        """envoy m-003c67eeb528: unbounded name classes backtracked quadratically on long hyphen runs (8,000 x 'a-': 6.8 s)."""
        import time
        pats = {n: rx for n, rx in T.SPANS if n in ("secret-assignment", "long-hex-or-b64-value", "url-credentials")}
        self.assertEqual(len(pats), 3)
        for s in ("a-" * 50000, "a_" * 50000, "-" * 100000, "token" + "-a" * 49997):
            for n, rx in pats.items():
                t = time.time()
                rx.sub("", s)
                self.assertLess(time.time() - t, 1.0, (n, s[:6]))
        t = time.time()
        T.redact("a-" * 50000)
        self.assertLess(time.time() - t, 2.0)                 # every pattern together (0.17.0's url-credentials: 8.9 s)
        self.assertIn("redacted:url-credentials", T.redact("https://bob:" + "hunter2@example.com/x")[0])

    def test_lookalikes_untouched(self):
        for s in ('"input_tokens": 123456789', "max_tokens=100000000", "author: Jane Doe here", "the password is short"):
            self.assertEqual(T.redact(s), (s, []), s)


# ---------------------------------------------------------------- R-097 (guard unit)
class Guard(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, True)
        # 0.21.0 (A-5a989 item 9): the guard fails closed without a home, so these unit cases get a prepared one unless they pass their own
        self.ghome = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.ghome, True)
        _env.guard_home(self.ghome)
        orig = G.check
        p = mock.patch.object(G, "check", lambda root, names, home="__default__": orig(root, names, self.ghome if home == "__default__" else home))
        p.start()
        self.addCleanup(p.stop)

    def put(self, name, text):
        p = os.path.join(self.root, name)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as f:
            f.write(text)
        return name

    def putb(self, name, data):
        p = os.path.join(self.root, name)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "wb") as f:
            f.write(data)
        return name

    def test_clean_plugin_file(self):
        n = self.put("plugins/demo/skills/ledger/SKILL.md", "a skill named ledger is fine\n")
        self.assertEqual(G.check(self.root, [n]), [])

    def test_path_denylist(self):
        for n in ("plugins/demo/corpus/x.md", "plugins/demo/docs/vault/y.md", "plugins/demo/handoffs/h.md",
                  "plugins/demo/digests/d.md", "plugins/demo/_archive/a.md", "projects/p/x.md", "plugins/demo/ledger/e.md",
                  "plugins/demo/data/log.jsonl", "plugins/demo/registry.json", "plugins/demo/x.lock"):
            self.put(n, "x\n")
            self.assertTrue(G.check(self.root, [n]), n)

    def test_planted_ledger_line(self):
        n = self.put("plugins/demo/README.md", "hello\n" + LEDGER_LINE + "\n")
        hits = G.check(self.root, [n])
        self.assertEqual(len(hits), 1)
        self.assertIn("ledger event shape", hits[0][1])

    def test_shape_pinned_files_by_path_and_sha(self):
        """curator m-cb0764d65780: the 4 files that describe the event shape pass only with their pinned sha."""
        tree = os.path.join(HERE, "..")
        for name in G.SHAPE_PINNED:
            with open(os.path.join(tree, name[len(G._CC):]), "rb") as f:
                real = f.read()
            n = self.putb(name, real)
            self.assertEqual(G.check(self.root, [n]), [], name)
            n = self.putb(name, real + ("\n" + LEDGER_LINE + "\n").encode())
            hits = G.check(self.root, [n])
            self.assertTrue(hits and "pinned file" in hits[0][1], name)

    def test_markdown_ledger_dump_stops(self):
        n = self.putb("plugins/demo/notes.md", ("# notes\n```json\n" + json.dumps(LEDGER_EVENT, indent=2) + "\n```\n").encode())
        self.assertIn("multi-line", G.check(self.root, [n])[0][1])

    def test_planted_corpus_title(self):
        home = os.path.join(self.root, "home")
        title = "A long live corpus title that must never leave the Exchange"
        os.makedirs(os.path.join(home, "_harness"))
        with open(os.path.join(home, "_harness", "events.jsonl"), "w") as f:
            f.write(json.dumps({"type": "corpus.recorded", "data": {"title": title}}) + "\n")
            f.write(json.dumps({"type": "corpus.recorded", "data": {"title": "short title"}}) + "\n")
        n = self.put("plugins/demo/notes.md", "intro\n" + title + "\n")
        self.assertEqual(G.check(self.root, [n]), [])                      # the default test home holds no such title
        _env.guard_home(home)
        hits = G.check(self.root, [n], home)
        self.assertTrue(hits and "corpus title" in hits[0][1])
        m = self.put("plugins/demo/ok.md", "short title\n")                 # titles under 40 chars are not checked
        self.assertEqual(G.check(self.root, [m], home), [])

    def test_real_fixture_exempt_by_pinned_manifest(self):
        names = []
        for dp, dn, fn in os.walk(REAL_FIXTURE):
            for f in fn:
                src = os.path.join(dp, f)
                rel = os.path.relpath(src, REAL_FIXTURE)
                with open(src, "rb") as fh:
                    names.append(self.putb(G.FIXTURE + rel, fh.read()))
        self.assertEqual(G.check(self.root, names), [])

    def test_case_insensitive_folders(self):
        for n in ("plugins/demo/Vault/a.md", "plugins/demo/CORPUS/b.md", "plugins/demo/Handoffs/c.md", "plugins/demo/x/Events.JSONL"):
            self.put(n, "plain\n")
            self.assertTrue(G.check(self.root, [n]), n)

    def test_unopenable_name_stops(self):
        hits = G.check(self.root, ["plugins/demo/\\303\\251vents.txt"])          # what a quoted git name looks like
        self.assertTrue(hits and "cannot open" in hits[0][1])

    def test_binary_policy(self):
        n = self.putb("plugins/demo/blob.bin", bytes(range(128, 256)) * 4)
        self.assertIn("binary", G.check(self.root, [n])[0][1])
        m = self.putb("plugins/demo/icon.png", b"\x89PNG\r\n\x1a\n" + bytes(range(128, 256)))
        self.assertEqual(G.check(self.root, [m]), [])
        for ext, magic in (("png", b"\x89PNG\r\n\x1a\n"), ("pdf", b"%PDF-1.7"), ("woff2", b"wOF2"), ("gif", b"GIF89a")):
            ok = self.putb("plugins/demo/ok." + ext, magic + b"\x00\x01\x02")
            self.assertEqual(G.check(self.root, [ok]), [], ext)
            bad = self.putb("plugins/demo/bad." + ext, b"plain text pretending\n")
            self.assertIn("magic bytes", G.check(self.root, [bad])[0][1], ext)

    def test_new_shapes_each_stop(self):
        """envoy m-1953412e1e3f (a)-(d)."""
        cases = {"esc.md": LEDGER_LINE.replace('"', '\\"').encode(), "repr.txt": repr(LEDGER_EVENT).encode(),
                 "u32.txt": (LEDGER_LINE + "\n").encode("utf-32"), "u32be.txt": (LEDGER_LINE + "\n").encode("utf-32-be"),
                 "logo.png": (LEDGER_LINE + "\n").encode()}
        for n, b in cases.items():
            name = self.putb("plugins/demo/x/" + n, b)
            self.assertTrue(G.check(self.root, [name]), n)

    def test_critic_planted_set_all_stopped(self):
        names = set()
        planted(lambda n, b: names.add(self.putb(n, b)))         # all cases at once (the critic's 7, pretty.json, notes.md, envoy a-d)
        hits = {n for n, _ in G.check(self.root, sorted(names))}
        self.assertEqual(hits, names, names - hits)

    def test_names_nul_separated(self):
        self.assertEqual(G.read_names("a b.md\0c\nd.md\0"), ["a b.md", "c\nd.md"])
        self.assertEqual(G.read_names("a.md\nb.md\n"), ["a.md", "b.md"])


# ---------------------------------------------------------------- R-097 (whole sync script)
def git(*a, cwd=None):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *a], cwd=cwd,
                          capture_output=True, text=True, check=True).stdout


@unittest.skipUnless(GIT and shutil.which("rsync"), "git and rsync needed")
class SyncScript(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.home = os.path.join(self.tmp, "Exchange")
        self.mk = os.path.join(self.home, "_harness", "marketplace")
        os.makedirs(os.path.join(self.mk, "plugins", "demo", ".claude-plugin"))
        os.makedirs(os.path.join(self.mk, ".claude-plugin"))
        with open(os.path.join(self.mk, "plugins", "demo", ".claude-plugin", "plugin.json"), "w") as f:
            f.write('{"name": "demo", "version": "1.0.0"}\n')
        with open(os.path.join(self.mk, ".claude-plugin", "marketplace.json"), "w") as f:
            f.write('{"plugins": []}\n')
        with open(os.path.join(self.home, "_harness", "wake.py"), "w") as f:
            f.write("print('wake')\n")
        _env.guard_home(self.home)
        self.title = "Operator standing rule about something private and long enough"
        with open(os.path.join(self.home, "_harness", "events.jsonl"), "w") as f:
            f.write(json.dumps({"type": "corpus.recorded", "data": {"title": self.title}}) + "\n")
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
        self.env = dict(os.environ, HARNESS_HOME=self.home, HATSTAND_REPO="file://" + self.bare,
                        GIT_CONFIG_GLOBAL=os.path.join(self.tmp, "gitconfig"))

    def run_sync(self, push=False):
        script = os.path.join(HERE, "..", "scripts", "hatstand-sync.sh")
        r = subprocess.run(["/bin/sh", script] + (["--push"] if push else []), capture_output=True, text=True, env=self.env)
        return r.returncode, r.stdout + r.stderr

    def plant(self, name, text):
        p = os.path.join(self.mk, "plugins", "demo", name)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as f:
            f.write(text)

    def head(self):
        return git("--git-dir", self.bare, "rev-parse", "main").strip()

    def test_clean_push(self):
        code, out = self.run_sync(push=True)
        self.assertEqual(code, 0, out)
        self.assertIn("hatstand: pushed", out)
        msg = git("--git-dir", self.bare, "log", "-1", "--format=%B")             # R-115 (D-b7b3c)
        self.assertNotIn("co-authored-by", msg.lower())
        self.assertTrue(msg.startswith("Sync to "), msg)
        who = git("--git-dir", self.bare, "log", "-1", "--format=%an <%ae>|%cn <%ce>").strip()
        self.assertEqual(who, "Braindono <Braindono@users.noreply.github.com>|Braindono <Braindono@users.noreply.github.com>")

    def test_planted_corpus_line_stops_the_push(self):
        h0 = self.head()
        self.plant("docs/notes.md", "notes\n" + self.title + "\n")
        code, out = self.run_sync(push=True)
        self.assertEqual(code, 1, out)
        self.assertIn("corpus title", out)
        self.assertEqual(self.head(), h0)

    def test_planted_ledger_line_stops_the_push(self):
        h0 = self.head()
        self.plant("data/sample.json", LEDGER_LINE + "\n")
        code, out = self.run_sync(push=True)
        self.assertEqual(code, 1, out)
        self.assertIn("ledger event shape", out)
        self.assertEqual(self.head(), h0)

    def test_critic_planted_files_each_stop_the_push(self):
        h0 = self.head()
        n = planted(lambda *_: None)
        for k in range(n):
            with self.subTest(case=k):
                mk = os.path.join(self.tmp, "mk%d" % k)                    # a fresh marketplace per case
                shutil.copytree(self.mk, mk)

                def put(name, b, mk=mk):
                    p = os.path.join(mk, name)
                    os.makedirs(os.path.dirname(p), exist_ok=True)
                    with open(p, "wb") as f:
                        f.write(b)
                planted(put, only=k)
                home = os.path.join(self.tmp, "home%d" % k)
                os.makedirs(os.path.join(home, "_harness"))
                os.rename(mk, os.path.join(home, "_harness", "marketplace"))
                shutil.copy(os.path.join(self.home, "_harness", "wake.py"), os.path.join(home, "_harness", "wake.py"))
                env = dict(self.env, HARNESS_HOME=home)
                r = subprocess.run(["/bin/sh", os.path.join(HERE, "..", "scripts", "hatstand-sync.sh"), "--push"],
                                   capture_output=True, text=True, env=env)
                self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
                self.assertIn("STOP", r.stderr)
        self.assertEqual(self.head(), h0)

    def test_title_check_runs_without_harness_home(self):
        """critic N2: run directly, the script passes its home to the guard."""
        home = os.path.join(self.tmp, "Claude", "Projects", "Exchange")
        os.makedirs(os.path.dirname(home))
        os.rename(self.home, home)
        self.mk = os.path.join(home, "_harness", "marketplace")
        self.env = {k: v for k, v in self.env.items() if k != "HARNESS_HOME"}
        self.env["HOME"] = self.tmp
        self.plant("docs/notes.md", "notes\n" + self.title + "\n")
        code, out = self.run_sync()
        self.assertEqual(code, 1, out)
        self.assertIn("corpus title", out)

    def stub_git(self, fail):
        """A git on PATH that fails only the named call and passes everything else to the real git."""
        d = os.path.join(self.tmp, "stubbin")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "git"), "w") as f:
            f.write('#!/bin/sh\n'
                    'case " $* " in *" --name-only -z "*) [ "$STUB_FAIL" = names ] && exit 1;; esac\n'
                    'case " $* " in *" -U0 "*) [ "$STUB_FAIL" = diff ] && exit 1;; esac\n'
                    'exec "%s" "$@"\n' % GIT)
        os.chmod(os.path.join(d, "git"), 0o755)
        self.env = dict(self.env, PATH=d + os.pathsep + self.env.get("PATH", ""), STUB_FAIL=fail)

    def test_failing_git_name_list_stops(self):
        """envoy m-5af8e7c4a480: a failing git must not hand the guard an empty list (the sync went on before)."""
        h0 = self.head()
        self.plant("data/sample.json", LEDGER_LINE + "\n")
        self.stub_git("names")
        code, out = self.run_sync(push=True)
        self.assertNotEqual(code, 0, out)
        self.assertIn("could not list the staged files", out)
        self.assertEqual(self.head(), h0)

    def test_failing_git_diff_stops_the_secret_scan(self):
        h0 = self.head()
        self.plant("leak.txt", "value " + "gh" + "p_" + "x" * 36 + "\n")
        self.stub_git("diff")
        code, out = self.run_sync(push=True)
        self.assertNotEqual(code, 0, out)
        self.assertIn("git diff failed", out)
        self.assertEqual(self.head(), h0)

    def test_stub_passes_other_calls(self):
        self.stub_git("none")
        code, out = self.run_sync()
        self.assertEqual(code, 0, out)

    def test_new_secret_patterns(self):
        for leak in ("sk-" + "proj-" + "a" * 20, "AI" + "za" + "b" * 35, "AS" + "IA" + "C" * 16, "gh" + "s_" + "d" * 36):
            with self.subTest(leak=leak[:6]):
                self.plant("leak.txt", "value " + leak + "\n")
                code, out = self.run_sync()
                self.assertEqual(code, 1, out)
                self.assertIn("secret pattern", out)

    def test_task_words_are_not_secrets(self):
        self.plant("notes.md", "see task-notification-handling-rules and ask-for-approval-before-publishing\n")
        code, out = self.run_sync()
        self.assertEqual(code, 0, out)

    def test_header_states_the_rule(self):
        with open(os.path.join(HERE, "..", "scripts", "hatstand-sync.sh")) as f:
            head = f.read(3000)
        self.assertIn("NEVER published to Hatstand", head)


# ---------------------------------------------------------------- R-098
class LeaseRace(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.home = os.path.join(self.tmp, "Exchange")
        os.makedirs(self.home)
        e = mock.patch.dict(os.environ, {"HARNESS_STATE_CACHE": "0"})
        e.start()
        self.addCleanup(e.stop)
        self.h = H.Harness(self.home)
        self.a = self.h.register(project="harness-ops", model=MODEL)["id"]
        self.b = self.h.register(project="harness-ops", model=MODEL)["id"]
        self.path = os.path.join(self.home, "shared.md")
        with open(self.path, "w") as f:
            f.write("x\n")

    def test_stale_snapshot_second_claim_refused(self):
        """B read the state before A's claim was written: the check under the append lock refuses B."""
        stale = self.h.state()
        self.assertTrue(self.h.claim(self.a, self.path)["granted"])
        with mock.patch.object(H.Harness, "state", return_value=stale):
            r = self.h.claim(self.b, self.path)
        self.assertFalse(r["granted"], r)
        self.assertTrue(r.get("race"))
        L = self.h.state().active_lease(H.canonical_path(self.path, self.home))
        self.assertEqual(L["holder"], self.a)

    def test_two_near_simultaneous_claims(self):
        """Two harness instances (two chats) claim at once; exactly one is granted, and replay agrees."""
        h2 = H.Harness(self.home)
        barrier, res = threading.Barrier(2), {}

        def go(h, aid):
            barrier.wait()
            res[aid] = h.claim(aid, self.path)
        ts = [threading.Thread(target=go, args=(self.h, self.a)), threading.Thread(target=go, args=(h2, self.b))]
        [t.start() for t in ts]
        [t.join() for t in ts]
        granted = [k for k, v in res.items() if v.get("granted")]
        self.assertEqual(len(granted), 1, res)
        L = H.Harness(self.home).state().active_lease(H.canonical_path(self.path, self.home))
        self.assertEqual(L["holder"], granted[0])

    def test_replay_keeps_the_earlier_unexpired_lease(self):
        key = H.canonical_path(self.path, self.home)
        self.h.store.append("lease.claimed", self.a, {"path": key, "lease_id": "l-a", "ttl": 600, "intent": None, "base_version": 0})
        self.h.store.append("lease.claimed", self.b, {"path": key, "lease_id": "l-b", "ttl": 600, "intent": None, "base_version": 0})
        L = self.h.state().active_lease(key)
        self.assertEqual((L["holder"], L["lease_id"]), (self.a, "l-a"))

    def test_replay_allows_a_claim_after_release_or_expiry(self):
        key = H.canonical_path(self.path, self.home)
        self.h.store.append("lease.claimed", self.a, {"path": key, "lease_id": "l-a", "ttl": 600, "intent": None, "base_version": 0})
        self.h.store.append("lease.released", self.a, {"path": key, "lease_id": "l-a"})
        self.h.store.append("lease.claimed", self.b, {"path": key, "lease_id": "l-b", "ttl": 600, "intent": None, "base_version": 0})
        self.assertEqual(self.h.state().active_lease(key)["holder"], self.b)

    def test_own_renewal_and_normal_handover_unchanged(self):
        self.assertTrue(self.h.claim(self.a, self.path)["granted"])
        self.assertTrue(self.h.claim(self.a, self.path).get("renewed"))
        self.h.release(self.a, self.path)
        self.assertTrue(self.h.claim(self.b, self.path)["granted"])


if __name__ == "__main__":
    unittest.main(verbosity=1)
