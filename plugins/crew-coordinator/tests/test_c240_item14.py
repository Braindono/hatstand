"""cc 0.24.0 item 14 (scope A-b2950; curator build spec v1.3, 2026-11-10_cc024-item14-hatstand-postpublish-build-spec.md): the
Hatstand sync is on the post-publish list, and a push is checked against the remote before any tag. Changes 1, 2, 3a and 4;
the mirror-behind line (3b) is commit 14b with its own tests (test_c240_item14b.py). Local bare repos only, no network.
Run: python3 -B tests/test_c240_item14.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _env  # noqa: F401  isolate HOME and HARNESS_* first
import json, os, shutil, subprocess, sys, tempfile, time, unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(HERE, "..", "scripts")
sys.path.insert(0, SCRIPTS)
import harness as H
import test_c220_gate as G220
from test_c220_gate import RG, RS

MODEL = "claude-opus-5-5"
GIT = shutil.which("git")
PUBLISH = {"tool_name": "Bash", "tool_input": {"command": "python3 harness.py publish --build"}}


def git(*a, cwd=None, check=True):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *a], cwd=cwd,
                          capture_output=True, text=True, check=check)


class P1PostPublishLine(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.home, self.h = G220.make_home(self.tmp)

    def check(self, change=lambda: None):
        pre = {"t": time.time() - 1, "code": "c" * 64, "hashes": RS.hash_tree(self.home), "carried": []}
        with open(os.path.join(self.home, "_harness", "release_prehash.json"), "w") as f:
            json.dump(pre, f)
        self.h.store.append("release.published", "human", {"name": "crew-coordinator", "version": "0.24.0", "code": "c" * 64})
        change()
        return RG.post_check(PUBLISH, self.home)

    def test_p1_an_ok_postcheck_names_the_sync_with_plugin_and_version(self):
        out = self.check()
        self.assertTrue(out.startswith("release.postcheck: ok"), out)
        self.assertIn("Do: role:envoy runs harness_admin op=hatstand_sync (dry run), then push=true, and reports the pushed commit "
                      "(D-3660f): crew-coordinator 0.24.0.", out)

    def test_p1_a_failed_postcheck_has_no_sync_line(self):
        def change():
            with open(os.path.join(self.home, G220.LOCAL), "w") as f:
                f.write("changed")
        out = self.check(change)
        self.assertIn("release.postcheck FAILED", out)
        self.assertNotIn("hatstand_sync", out)


@unittest.skipUnless(GIT and shutil.which("rsync"), "git and rsync needed")
class Sync(unittest.TestCase):
    """A scratch home with a one-plugin marketplace, the item 17 hooks switched on in a scratch global config, an envoy, and a
    local bare repo as the remote."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.home = os.path.join(self.tmp, "Exchange")
        self.mk = os.path.join(self.home, "_harness", "marketplace")
        os.makedirs(os.path.join(self.mk, "plugins", "demo", ".claude-plugin"))
        os.makedirs(os.path.join(self.mk, ".claude-plugin"))
        self.version("1.0.0")
        with open(os.path.join(self.mk, ".claude-plugin", "marketplace.json"), "w") as f:
            f.write('{"plugins": []}\n')
        with open(os.path.join(self.home, "_harness", "wake.py"), "w") as f:
            f.write("print('wake')\n")
        _env.guard_home(self.home)
        self.gitconfig = os.path.join(self.tmp, "gitconfig")
        _env.hatstand_hooks(self.tmp, self.home, self.gitconfig)
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
        e = mock.patch.dict(os.environ, {"HARNESS_STATE_CACHE": "0", "HATSTAND_REPO": "file://" + self.bare,
                                         "GIT_CONFIG_GLOBAL": self.gitconfig})
        e.start()
        self.addCleanup(e.stop)
        self.h = H.Harness(self.home)
        self.h.role_define("operator", "envoy", "harness-ops")
        self.envoy = self.h.register(project="harness-ops", model=MODEL)["id"]
        self.h.role_assign("operator", "envoy", self.envoy)

    def version(self, v):
        with open(os.path.join(self.mk, "plugins", "demo", ".claude-plugin", "plugin.json"), "w") as f:
            f.write('{"name": "demo", "version": "%s"}\n' % v)

    def push(self):
        self.h.hatstand_sync(self.envoy)
        return self.h.hatstand_sync(self.envoy, push=True)

    def event(self):
        return [e for e in self.h.store.read_all() if e["type"] == "hatstand.synced"][-1]["data"]

    def tags(self):
        return git("--git-dir", self.bare, "tag", "-l").stdout.split()

    def post_receive(self, body):
        p = os.path.join(self.bare, "hooks", "post-receive")
        with open(p, "w") as f:
            f.write("#!/bin/sh\n" + body)
        os.chmod(p, 0o755)

    def test_p2_a_push_is_verified_and_the_event_says_so(self):
        r = self.push()
        self.assertEqual((r["exit"], r["state"], r["verified"]), (0, "pushed", True), r)
        self.assertTrue(any(l.startswith("hatstand: verified ") and l.endswith("= release tree") for l in r["output"]), r["output"])
        ev = self.event()
        self.assertTrue(ev["verified"])
        self.assertEqual(ev["plugins"], {"demo": "1.0.0"})
        self.assertEqual(self.tags(), ["demo-v1.0.0"])

    def test_p3_a_remote_that_moves_main_after_the_push_stops_the_run_and_no_tag_is_pushed(self):
        # the remote adds a commit with another tree on main right after our push; its echo also carries the verified words (P3c)
        self.post_receive('unset GIT_QUARANTINE_PATH\n'
                          'export GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@example.invalid GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@example.invalid\n'
                          'echo "hatstand: verified 0000000 = release tree"\n'
                          'b=$(echo extra | git hash-object -w --stdin)\n'
                          'export GIT_INDEX_FILE="$PWD/tmp-index"\n'
                          'git read-tree main && git update-index --add --cacheinfo 100644,$b,extra.txt\n'
                          'c=$(git commit-tree -p main -m extra $(git write-tree)) && git update-ref refs/heads/main $c\n'
                          'rm -f "$GIT_INDEX_FILE"\n')
        r = self.push()
        out = "\n".join(r["output"])
        self.assertEqual((r["exit"], r["state"], r["verified"]), (1, "refused", False), out)
        self.assertIn("remote main differs from the pushed tree", out)
        self.assertIn("remote: hatstand: verified", out)               # P3c: the remote's echo is there, and does not count
        self.assertFalse(self.event()["verified"])
        self.assertEqual(self.tags(), [])

    def stub_fetch(self):
        """A git on PATH whose `fetch origin main` first writes a FETCH_HEAD equal to HEAD (a stale one that would match), then fails."""
        d = os.path.join(self.tmp, "stubbin")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "git"), "w") as f:
            f.write('#!/bin/sh\n'
                    'case " $* " in *" fetch -q origin main "*) "%s" rev-parse HEAD > .git/FETCH_HEAD; exit 1;; esac\n'
                    'exec "%s" "$@"\n' % (GIT, GIT))
        os.chmod(os.path.join(d, "git"), 0o755)
        e = mock.patch.dict(os.environ, {"PATH": d + os.pathsep + os.environ.get("PATH", "")})
        e.start()
        self.addCleanup(e.stop)

    def test_p3b_a_failed_fetch_after_the_push_stops_and_never_verifies(self):
        self.stub_fetch()
        r = self.push()
        out = "\n".join(r["output"])
        self.assertEqual((r["exit"], r["verified"]), (1, False), out)
        self.assertIn("vs fetch failed", out)
        self.assertNotIn("hatstand: verified", out)
        self.assertEqual(self.tags(), [])

    def test_p3b_a_failed_fetch_on_the_no_change_path_stops_too(self):
        self.push()
        self.stub_fetch()
        r = self.h.hatstand_sync(self.envoy, push=True)
        out = "\n".join(r["output"])
        self.assertEqual((r["exit"], r["verified"]), (1, False), out)
        self.assertIn("no changes", out)
        self.assertNotIn("hatstand: verified", out)

    def test_p4_a_no_change_push_prints_the_verified_line(self):
        self.push()
        r = self.push()
        self.assertEqual((r["exit"], r["state"], r["verified"]), (0, "no-change", True), r)
        self.assertTrue(any(l.startswith("hatstand: verified ") and l.endswith("= release tree (no changes)") for l in r["output"]),
                        r["output"])

    def test_a_dry_run_is_never_verified(self):
        r = self.h.hatstand_sync(self.envoy)
        self.assertFalse(r["verified"])
        self.assertFalse(self.event()["verified"])


class Docs(unittest.TestCase):
    def test_events_doc_names_the_fields_and_the_pin_matches(self):
        import hashlib
        import hatstand_guard as GD
        p = os.path.join(HERE, "..", "docs", "EVENTS.md")
        doc = open(p, encoding="utf-8").read()
        row = next(l for l in doc.splitlines() if l.startswith("| `hatstand.synced`"))
        for k in ("verified", "plugins", "pushed"):
            self.assertIn(k, row)
        self.assertEqual(GD.SHAPE_PINNED[GD._CC + "docs/EVENTS.md"], hashlib.sha256(open(p, "rb").read()).hexdigest())

    def test_the_update_skill_names_the_hatstand_step(self):
        s = open(os.path.join(HERE, "..", "skills", "update", "SKILL.md"), encoding="utf-8").read()
        self.assertIn("op=hatstand_sync", s)

    def test_hooks_json_is_unchanged_by_item_14(self):
        hj = json.load(open(os.path.join(HERE, "..", "hooks", "hooks.json"), encoding="utf-8"))
        self.assertNotIn("hatstand", json.dumps(hj))


if __name__ == "__main__":
    unittest.main()
