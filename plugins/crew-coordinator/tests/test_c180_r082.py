"""cc 0.18.0 R-082: the Exchange home moves to ~/Claude/Exchange (D-58543); the old ~/Claude/Projects/Exchange is a
fallback for one release (after the move: a compatibility symlink). Envoy conditions (m-9490a7305fa7): one key per
file whatever the spelling (a claim on one spelling blocks the other), real-path containment (a capsule given by the
old spelling restores after the move), and the suite under /usr/bin/python3 3.9 too.
Run: python3 -B tests/test_c180_r082.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _env  # noqa: F401  isolate HOME and HARNESS_* first
import json, os, shutil, subprocess, sys, tempfile, unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
import harness as H
import ctx_hook as C
import launchers as L
import transcript_indexer as T

MODEL = "claude-opus-5-5"


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.new = os.path.join(self.tmp, "Claude", "Exchange")
        self.old = os.path.join(self.tmp, "Claude", "Projects", "Exchange")
        os.makedirs(os.path.join(self.tmp, "Claude", "Projects"))
        e = mock.patch.dict(os.environ, {"HOME": self.tmp, "HARNESS_STATE_CACHE": "0"})
        e.start()
        self.addCleanup(e.stop)
        os.environ.pop("HARNESS_HOME", None)
        os.environ.pop("INDEXER_LEDGER", None)

    def moved(self):
        """The move evening: the folder lives at the new path, the old path is a symlink to it."""
        os.makedirs(os.path.join(self.new, "_harness"))
        os.symlink(self.new, self.old)


class DefaultHome(Base):
    def test_only_old_exists(self):
        os.makedirs(self.old)
        self.assertEqual(H.resolve_home(), self.old)
        self.assertEqual(C.default_home(), self.old)

    def test_new_first_when_both_exist(self):
        os.makedirs(self.old)
        os.makedirs(self.new)
        self.assertEqual(H.resolve_home(), self.new)
        self.assertEqual(C.default_home(), self.new)

    def test_after_the_move_symlink(self):
        self.moved()
        self.assertEqual(H.resolve_home(), self.new)
        self.assertEqual(C.default_home(), self.new)

    def test_neither_names_all_three(self):
        with self.assertRaises(H.HarnessError) as cm:
            H.resolve_home()
        for c in ("~/Claude/Exchange", "~/Claude/Projects/Exchange", "~/mnt/Exchange"):
            self.assertIn(c, str(cm.exception))

    def test_indexer_ledger(self):
        os.makedirs(os.path.join(self.old, "_harness"))
        open(os.path.join(self.old, "_harness", "events.jsonl"), "w").close()
        self.assertEqual(T.exchange_log(), os.path.join(self.old, "_harness", "events.jsonl"))
        self.assertEqual(T.vault_dir() if not os.environ.get("INDEXER_VAULT") else None, os.path.join(self.old, "vault"))
        os.makedirs(os.path.join(self.new, "_harness"))
        open(os.path.join(self.new, "_harness", "events.jsonl"), "w").close()
        self.assertEqual(T.exchange_log(), os.path.join(self.new, "_harness", "events.jsonl"))
        self.assertEqual(T.vault_dir(), os.path.join(self.new, "vault"))

    def test_indexer_ledger_neither_names_new(self):
        self.assertEqual(T.exchange_log(), os.path.join(self.new, "_harness", "events.jsonl"))


class AfterTheMove(Base):
    def setUp(self):
        super().setUp()
        self.moved()
        self.h_new = H.Harness(self.new)          # a chat that resolved the new path
        self.h_old = H.Harness(self.old)          # a chat still started with HARNESS_HOME=<old spelling>
        self.a = self.h_new.register(project="harness-ops", model=MODEL)["id"]
        self.b = self.h_old.register(project="harness-ops", model=MODEL)["id"]
        os.makedirs(os.path.join(self.new, "projects", "harness-ops", "handoffs"))
        self.f_new = os.path.join(self.new, "projects", "harness-ops", "notes.md")
        self.f_old = os.path.join(self.old, "projects", "harness-ops", "notes.md")
        with open(self.f_new, "w") as f:
            f.write("x\n")

    def test_one_ledger(self):
        self.assertEqual(os.path.realpath(self.h_new.store.log), os.path.realpath(self.h_old.store.log))
        self.assertEqual(len(self.h_new.state().agents), len(self.h_old.state().agents))

    def test_both_spellings_one_key(self):
        keys = {H.canonical_path(p, h.home) for p in (self.f_new, self.f_old) for h in (self.h_new, self.h_old)}
        self.assertEqual(len(keys), 1, keys)

    def test_claim_on_one_spelling_blocks_the_other(self):
        self.assertTrue(self.h_old.claim(self.b, self.f_old)["granted"])
        r = self.h_new.claim(self.a, self.f_new)
        self.assertFalse(r["granted"], r)
        self.h_old.release(self.b, self.f_old)
        self.assertTrue(self.h_new.claim(self.a, self.f_new)["granted"])
        self.assertFalse(self.h_old.claim(self.b, self.f_old)["granted"])

    def test_capsule_by_old_spelling_resolves(self):
        cap = os.path.join(self.new, "projects", "harness-ops", "handoffs", "2026-11-01-test.md")
        with open(cap, "w") as f:
            f.write("---\nstatus: open\n---\n# x\n")
        old_cap = os.path.join(self.old, "projects", "harness-ops", "handoffs", "2026-11-01-test.md")
        for h in (self.h_new, self.h_old):
            for p in (cap, old_cap, "Exchange/projects/harness-ops/handoffs/2026-11-01-test.md"):
                self.assertEqual(h._resolve_in_home(p, must_exist=True), "projects/harness-ops/handoffs/2026-11-01-test.md", (h.home, p))

    def test_outside_still_refused(self):
        outside = os.path.join(self.tmp, "elsewhere.md")
        open(outside, "w").close()
        for h in (self.h_new, self.h_old):
            with self.assertRaises(H.HarnessError):
                h._resolve_in_home(outside, must_exist=True)

    def test_symlinked_events_file_still_refused(self):
        other = os.path.join(self.tmp, "other")
        os.makedirs(os.path.join(other, "_harness"))
        os.symlink(self.h_new.store.log, os.path.join(other, "_harness", "events.jsonl"))
        with self.assertRaises(Exception):
            H.Harness(other).state()

    def test_launcher_home_must_hold_a_ledger(self):
        stray = os.path.join(self.tmp, "stray")
        os.makedirs(os.path.join(stray, "_harness", "bin"))
        open(os.path.join(stray, "_harness", "bin", "harness.py"), "w").close()
        row = next(r for r in L.targets(stray) if r["name"] == "harness")
        self.assertFalse(row["ok"], row)
        self.assertIn("harness home", row["why"])
        open(os.path.join(stray, "_harness", "events.jsonl"), "w").close()
        self.assertTrue(next(r for r in L.targets(stray) if r["name"] == "harness")["ok"])

    def test_launcher_targets_under_the_new_home(self):
        os.makedirs(os.path.join(self.new, "_harness", "bin"))
        open(os.path.join(self.new, "_harness", "bin", "harness.py"), "w").close()
        row = next(r for r in L.targets(self.new) if r["name"] == "harness")
        self.assertTrue(row["ok"], row)


@unittest.skipUnless(shutil.which("git") and shutil.which("rsync"), "git and rsync needed")
class SyncDefaultHome(Base):
    def test_sync_finds_the_new_home_without_harness_home(self):
        self.moved()
        mk = os.path.join(self.new, "_harness", "marketplace")
        os.makedirs(os.path.join(mk, "plugins", "demo", ".claude-plugin"))
        os.makedirs(os.path.join(mk, ".claude-plugin"))
        with open(os.path.join(mk, "plugins", "demo", ".claude-plugin", "plugin.json"), "w") as f:
            f.write('{"name": "demo", "version": "2.0.0"}\n')
        with open(os.path.join(mk, ".claude-plugin", "marketplace.json"), "w") as f:
            f.write('{"plugins": []}\n')
        with open(os.path.join(self.new, "_harness", "wake.py"), "w") as f:
            f.write("print('wake')\n")
        _env.guard_home(self.new)
        bare = os.path.join(self.tmp, "hs.git")
        g = lambda *a, cwd=None: subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *a],
                                                cwd=cwd, capture_output=True, text=True, check=True)
        g("init", "-q", "--bare", "-b", "main", bare)
        seed = os.path.join(self.tmp, "seed")
        g("init", "-q", "-b", "main", seed)
        for d in ("plugins", "bin", ".claude-plugin"):
            os.makedirs(os.path.join(seed, d))
            open(os.path.join(seed, d, ".keep"), "w").close()
        g("add", "-A", cwd=seed)
        g("commit", "-q", "-m", "seed", cwd=seed)
        g("push", "-q", bare, "main", cwd=seed)
        env = {k: v for k, v in os.environ.items() if k != "HARNESS_HOME"}
        env.update(HATSTAND_REPO="file://" + bare, GIT_CONFIG_GLOBAL=os.path.join(self.tmp, "gitconfig"))
        r = subprocess.run(["/bin/sh", os.path.join(HERE, "..", "scripts", "hatstand-sync.sh")], capture_output=True,
                           text=True, env=env)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("demo 2.0.0", r.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=1)
