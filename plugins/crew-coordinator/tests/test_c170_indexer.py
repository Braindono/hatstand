"""cc 0.17.0 stage 0: indexer fixes. R-076 (.noindex root, rename migration, Spotlight probe) and the status counters
(distinct denied sessions, unreadable state reported, ledger read once per pass). Run: python3 -B tests/test_c170_indexer.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _env  # noqa: F401  isolate HOME and HARNESS_* first
import json, os, sys, tempfile, unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
import transcript_indexer as T


def user(text, ts="2026-10-24T10:00:00Z"):
    return {"type": "user", "timestamp": ts, "origin": {"kind": "human"}, "message": {"role": "user", "content": text}}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.home = os.path.join(self.tmp, "home")
        os.makedirs(os.path.join(self.home, "Claude"))
        self.env = mock.patch.dict(os.environ, {"HOME": self.home, "INDEXER_SCRIPTS": os.path.join(self.tmp, "scripts"),
                                                "INDEXER_LAUNCHAGENTS": os.path.join(self.tmp, "LA")})
        self.env.start()
        self.addCleanup(self.env.stop)
        os.environ.pop("INDEXER_ROOT", None)
        self.src = os.path.join(self.tmp, "src")
        self.legacy = os.path.join(self.home, "Claude", "Transcripts")
        self.new = os.path.join(self.home, "Claude", "Transcripts.noindex")

    def session(self, sid, *lines, proj="-p"):
        d = os.path.join(self.src, proj)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, sid + ".jsonl"), "a") as f:
            for e in lines:
                f.write(json.dumps(e) + "\n")

    def ix(self, **kw):
        kw.setdefault("cache", os.path.join(self.tmp, "cache"))
        kw.setdefault("source", self.src)
        kw.setdefault("ledger", False)
        return T.Indexer(**kw)


class Counters(Base):
    def test_denied_counts_distinct_sessions_not_scans(self):
        a, b = "aaaa0000-0000-0000-0000-000000000001", "bbbb0000-0000-0000-0000-000000000002"
        self.session(a, user("one"))
        self.session(b, user("two"))
        ix = self.ix()
        for i in range(4):
            ix.once()
            self.session(a, user("more %d" % i))                    # the file keeps growing, as a live chat does
        st = self.ix().status()
        self.assertEqual(st["denied_sessions"], 2)                   # was 2 per pass before 0.17.0
        self.assertNotIn("denied_sessions_scans", st)

    def test_allowed_later_leaves_the_denied_set(self):
        a = "aaaa0000-0000-0000-0000-000000000001"
        self.session(a, user("hello"))
        ix = self.ix()
        ix.once()
        self.assertEqual(ix.status()["denied_sessions"], 1)
        with open(os.path.join(ix.root, ".allow"), "w") as f:
            f.write(a + "\n")
        ix.once()
        self.assertEqual(ix.status()["denied_sessions"], 0)
        self.assertEqual(len([x for x in os.listdir(ix.root) if x.endswith(".md")]), 1)

    def test_ledger_read_once_per_pass(self):
        for n in range(3):
            self.session("cccc0000-0000-0000-0000-00000000000%d" % n, user("x"))
        ix = self.ix(ledger=os.path.join(self.tmp, "events.jsonl"))
        with mock.patch.object(T, "ledger_sessions", return_value=set()) as ls:
            ix.once()
            self.assertEqual(ls.call_count, 1)
            ix.once()
            self.assertEqual(ls.call_count, 2)                       # fresh read each pass: new registrations count

    def test_status_reports_real_counters_and_time(self):
        self.session("aaaa0000-0000-0000-0000-000000000001", user("hi"))
        self.ix().once()
        st = self.ix().status()
        self.assertEqual(st["files_tracked"], 1)
        self.assertGreater(st["last_run"], 0)
        self.assertNotEqual(st["last_run_at"], "never")
        self.assertNotIn("state_error", st)
        self.assertTrue(st["state_path"].endswith("state.json"))


class UnreadableState(Base):
    def test_corrupt_state_is_reported_and_blocks_a_pass(self):
        sid = "aaaa0000-0000-0000-0000-000000000001"
        self.session(sid, user("hello"))
        ix = self.ix()
        with open(os.path.join(ix.root, ".allow"), "w") as f:
            f.write(sid + "\n")
        ix.once()
        vault = [x for x in os.listdir(ix.root) if x.endswith(".md")][0]
        before = open(os.path.join(ix.root, vault)).read()
        with open(ix.state_path, "w") as f:
            f.write("{not json")
        again = self.ix()
        self.assertIn("state_error", again.status())
        with self.assertRaises(RuntimeError):
            again.once()                                             # would append the whole transcript a second time
        self.assertEqual(open(os.path.join(ix.root, vault)).read(), before)

    def test_unreadable_state_is_reported(self):
        ix = self.ix()
        ix.once()
        with mock.patch("builtins.open", side_effect=PermissionError("sandbox")):
            st = T.Indexer.__new__(T.Indexer)
            st.root, st.state_path = ix.root, ix.state_path
            st.state = st._load_state()
        self.assertIn("PermissionError", st.state_error)

    def test_missing_state_is_a_first_run_not_an_error(self):
        self.assertIsNone(self.ix().state_error)


class Root(Base):
    def test_default_root_is_noindex_and_env_wins(self):
        self.assertEqual(T.default_root(), self.new)
        with mock.patch.dict(os.environ, {"INDEXER_ROOT": "/x/y"}):
            self.assertEqual(T.default_root(), "/x/y")

    def test_unmigrated_machine_keeps_the_old_vault_until_install(self):
        os.makedirs(self.legacy)
        ix = self.ix()
        self.assertEqual(ix.root, self.legacy)
        self.assertFalse(os.path.exists(self.new))                   # status never creates an empty new folder

    def test_migrate_renames_and_leaves_a_symlink(self):
        os.makedirs(self.legacy)
        with open(os.path.join(self.legacy, "a.md"), "w") as f:
            f.write("keep")
        ino = os.stat(os.path.join(self.legacy, "a.md")).st_ino
        r = T.migrate_root()
        self.assertEqual(r["action"], "renamed")
        self.assertTrue(os.path.islink(self.legacy))
        self.assertEqual(os.path.realpath(self.legacy), os.path.realpath(self.new))
        self.assertEqual(os.stat(os.path.join(self.new, "a.md")).st_ino, ino)   # moved, not copied
        self.assertEqual(T.migrate_root()["action"], "none")         # second run: nothing to do

    def test_migrate_conflict_moves_nothing(self):
        os.makedirs(self.legacy)
        os.makedirs(self.new)
        for d in (self.legacy, self.new):
            with open(os.path.join(d, "x.md"), "w") as f:
                f.write(d)
        self.assertEqual(T.migrate_root()["action"], "conflict")
        self.assertEqual(open(os.path.join(self.legacy, "x.md")).read(), self.legacy)
        self.assertEqual(open(os.path.join(self.new, "x.md")).read(), self.new)

    def test_migrate_over_an_empty_new_folder(self):
        os.makedirs(self.legacy)
        os.makedirs(self.new)
        self.assertEqual(T.migrate_root()["action"], "renamed")

    def test_migrate_without_old_vault_is_a_no_op(self):
        self.assertEqual(T.migrate_root()["action"], "none")

    def test_vault_paths_in_state_follow_the_rename(self):
        sid = "aaaa0000-0000-0000-0000-000000000001"
        self.session(sid, user("first"))
        os.makedirs(self.legacy)
        with open(os.path.join(self.legacy, ".allow"), "w") as f:
            f.write(sid + "\n")
        old = self.ix()
        old.once()
        T.migrate_root()
        new = self.ix()
        self.assertEqual(new.root, self.new)
        recs = [r for r in new.state["files"].values() if r.get("vault")]
        self.assertTrue(recs and all(r["vault"].startswith(self.new + os.sep) for r in recs))

    def test_install_unloads_first_migrates_and_pins_the_root(self):
        os.makedirs(self.legacy)
        calls = []

        class R:
            returncode, stderr = 0, ""
        ix = self.ix()
        r = T.install(ix, run=lambda cmd: (calls.append(cmd[1]), R())[1])
        self.assertEqual(calls, ["bootout", "bootstrap"])
        self.assertEqual(r["migration"]["action"], "renamed")
        self.assertEqual(r["root"], self.new)
        plist = open(r["plist"]).read()
        self.assertIn("<key>INDEXER_ROOT</key><string>%s</string>" % self.new, plist)


class Spotlight(Base):
    def fake(self, out=None, err=None):
        class R:
            returncode = 0
            stdout = out or ""
        self.cmds = []

        def run(cmd):
            self.cmds.append(cmd)
            if err:
                raise err
            return R()
        return run

    def probes_left(self, root):
        return [x for x in os.listdir(root) if x.startswith(".probe-")]

    def test_found_by_mdfind_warns(self):
        root = os.path.join(self.tmp, "Transcripts")
        r = T.spotlight(root, True, probe_s=5, run=self.fake("/some/hit\n"), sleep=lambda s: None)
        self.assertEqual(r["probe"], "found")
        self.assertIn(".noindex", r["warning"])
        self.assertEqual(self.cmds[0][:3], ["mdfind", "-onlyin", os.path.realpath(root)])
        self.assertEqual(self.probes_left(root), [])

    def test_not_found_is_quiet(self):
        root = os.path.join(self.tmp, "V.noindex")
        r = T.spotlight(root, True, probe_s=0.01, run=self.fake(""), sleep=lambda s: None)
        self.assertEqual((r["probe"], r["noindex_name"]), ("not-found", True))
        self.assertNotIn("warning", r)
        self.assertEqual(self.probes_left(root), [])

    def test_no_mdfind_is_unavailable(self):
        root = os.path.join(self.tmp, "T")
        r = T.spotlight(root, True, probe_s=5, run=self.fake(err=FileNotFoundError("mdfind")), sleep=lambda s: None)
        self.assertEqual(r["probe"], "unavailable")
        self.assertEqual(self.probes_left(root), [])

    def test_on_and_zero_seconds_skip_the_probe(self):
        root = os.path.join(self.tmp, "T")
        self.assertEqual(T.spotlight(root, False)["probe"], "skipped")
        self.assertEqual(T.spotlight(root, True, probe_s=0)["probe"], "skipped")


if __name__ == "__main__":
    unittest.main()
