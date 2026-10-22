"""cc 0.15.0 audit fixes: path containment, symlink-free package/hash, file modes, untrusted-text hygiene,
corpus front-matter escaping, body/max_hops clamps, publish cleanup (unique .prev/.stage, failures reported).
Run: python3 -B tests/test_audit_fixes.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _env  # noqa: F401  isolate HOME and HARNESS_* first
import json, os, shutil, stat, sys, tempfile, unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
import harness as H
import corpus as C

MODEL = "claude-sonnet-5-5"


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def mk_plugin(tmp, name="dummy", ver="1.0.0"):
    root = os.path.join(tmp, "src", name)
    write(os.path.join(root, ".claude-plugin", "plugin.json"), json.dumps({"name": name, "version": ver, "description": "d"}))
    write(os.path.join(root, "scripts", "a.py"), "print(1)\n")
    return root


def mode(p):
    return stat.S_IMODE(os.stat(p).st_mode)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.home = os.path.join(self.tmp, "home")
        os.makedirs(self.home)
        self._env = mock.patch.dict(os.environ, {"HARNESS_CACHE": os.path.join(self.tmp, "cache")})
        self._env.start()
        self.addCleanup(self._env.stop)
        self.h = H.Harness(self.home)

    def agent(self, project="orch"):
        return self.h.register(project=project, model=MODEL)["id"]

    def types(self, t):
        return [e for e in self.h.store.read_all() if e.get("type") == t]


class Containment(Base):
    def test_dotdot_key_rejected(self):
        key = os.path.basename(self.home) + "/../outside.md"
        with self.assertRaisesRegex(H.HarnessError, "path"):
            H.canonical_path(key, self.home)
        with self.assertRaisesRegex(H.HarnessError, "path"):
            H.disk_path(key, self.home)

    def test_absolute_key_outside_roots_rejected_and_no_lease_written(self):
        with self.assertRaisesRegex(H.HarnessError, "outside the allowed roots"):
            H.disk_path("/etc/hosts", self.home)
        a = self.agent()
        n = len(self.h.store.read_all())
        with self.assertRaises(H.HarnessError):
            self.h.claim(a, "/etc/hosts")
        self.assertEqual(len(self.h.store.read_all()), n)       # rejected before any lease event

    def test_key_inside_home_still_works(self):
        a = self.agent()
        r = self.h.claim(a, "projects/x/a.md")
        self.assertTrue(r["granted"])
        self.assertTrue(H.disk_path(r["path"], self.home).startswith(self.home))

    def test_set_capsule_status_rejects_outside_rel(self):
        a = self.agent()
        for rel in ("/etc/hosts", "../escape.md"):
            with self.assertRaisesRegex(H.HarnessError, "capsule path"):
                self.h._set_capsule_status(a, rel, "closed")

    def test_restore_digest_absolute_capsule_rejected(self):
        a = self.agent()
        outside = os.path.join(self.tmp, "outside.md")
        write(outside, "---\nstatus: open\n---\nsecret\n")
        st = self.h.state()
        with self.assertRaisesRegex(H.HarnessError, "capsule"):
            self.h.restore_digest(st, a, "someone", [], capsule=outside)

    def test_bad_handoff_slug_and_review_project(self):
        a = self.agent(project="orch")
        st = self.h.state()
        st.agents[a]["project"] = "../evil"
        with mock.patch.object(self.h, "state", return_value=st):
            with self.assertRaisesRegex(H.HarnessError, "project slug"):
                self.h.handoff(a, capsule_md="---\nstatus: open\n---\n# c\n", to="operator")
        for bad in ("../x", "a/b", "/abs", "-lead"):
            with self.assertRaisesRegex(H.HarnessError, "project"):
                self.h.health_bundle(project=bad)

    def test_plugin_name_checked_before_path_joins(self):
        root = mk_plugin(self.tmp, name="Bad_Name")
        with self.assertRaisesRegex(H.HarnessError, "plugin name"):
            self.h.publish_release(root, override="t", build=True)
        root2 = mk_plugin(self.tmp, name="okname")
        with self.assertRaisesRegex(H.HarnessError, "renamed_from"):
            self.h.publish_release(root2, override="t", build=True, renamed_from="../x")


class Symlinks(Base):
    def test_symlink_not_packaged_and_hash_unchanged(self):
        root = mk_plugin(self.tmp)
        before = (H.tree_sha(root), H.full_tree_sha(root), H.code_sha(root, "plugin"), H.bytes_sha(H.build_package(root)))
        secret = os.path.join(self.tmp, "secret.txt")
        write(secret, "TOP SECRET")
        os.symlink(secret, os.path.join(root, "scripts", "leak.py"))
        os.symlink(secret, os.path.join(root, "skills-link"))
        self.assertNotIn("scripts/leak.py", H.package_files(root))
        after = (H.tree_sha(root), H.full_tree_sha(root), H.code_sha(root, "plugin"), H.bytes_sha(H.build_package(root)))
        self.assertEqual(before, after)             # selection is identical everywhere: symlinks are skipped by all
        self.assertNotIn(b"TOP SECRET", H.build_package(root))

    def test_symlink_free_tree_hash_is_old_rule(self):
        # a symlink-free tree hashes as relpath + NUL + file sha (the unchanged 0.14.7/0.15.0 rule)
        import hashlib
        root = mk_plugin(self.tmp)
        h = hashlib.sha256()
        for rel in (".claude-plugin/plugin.json", "scripts/a.py"):
            h.update(rel.encode() + b"\0" + H.file_sha(os.path.join(root, rel)).encode())
        self.assertEqual(H.tree_sha(root), h.hexdigest())


class Modes(Base):
    def test_fresh_home_files_and_dirs_private(self):
        a = self.agent()
        self.h.claim(a, "projects/x/a.md")
        self.h.write_anchor("t")
        out = self.h.export()["path"]
        for p in (self.h.store.log, os.path.join(self.home, "_harness", "config.json"),
                  os.path.join(self.home, H.ANCHOR_DIR, "anchors.jsonl"), out):
            self.assertEqual(mode(p), 0o600, p)
        for d in (os.path.join(self.home, "_harness"), os.path.join(self.home, H.ANCHOR_DIR), os.path.dirname(out)):
            self.assertEqual(mode(d), 0o700, d)

    def test_handoff_capsule_private_and_existing_file_mode_kept(self):
        a = self.agent()
        r = self.h.handoff(a, capsule_md="---\nstatus: open\n---\n# capsule\nbody\n", to="operator")
        p = os.path.join(self.home, r["capsule"])
        self.assertEqual(mode(p), 0o600)
        self.assertEqual(mode(os.path.dirname(p)), 0o700)
        existing = os.path.join(self.home, "_harness", "config.json")
        os.chmod(existing, 0o640)
        H.init_home(self.home)
        self.assertEqual(mode(existing), 0o640)      # existing files are never chmod'ed

    def test_registry_written_via_mkstemp(self):
        self.h._write_registry({"x": {"version": "1"}})
        reg = os.path.join(self.home, "_harness", "registry.json")
        self.assertTrue(os.path.isfile(reg))
        self.assertEqual([f for f in os.listdir(os.path.dirname(reg)) if f.startswith("registry.json.")], [])


class Sanitizer(Base):
    def test_strips_control_chars_and_caps(self):
        s = "a\x1b[31mb\x00c‮d\r\ne\tf\x7f"
        self.assertEqual(C.clean_text(s, 100), "a[31mbcd e f")
        self.assertEqual(C.clean_text(s, 100, multiline=True), "a[31mbcd\ne\tf")
        out = C.clean_text("x" * 50, 10)
        self.assertEqual(len(out), 10)
        self.assertTrue(out.endswith("…"))
        self.assertIs(H._clean_text, C.clean_text)

    def test_inbox_and_sync_output_clean(self):
        a, b = self.agent(), self.agent()
        self.h.send(a, b, "body\x1b[2J\x07 text\nline2", subject="subj\x00\nX", kind="message")
        txt = self.h.inbox(b)["text"]
        self.assertNotIn("\x1b", txt)
        self.assertNotIn("\x07", txt)
        self.assertNotIn("\x00", txt)
        self.assertIn("line2", txt)

    def test_banner_clean(self):
        card = {"id": "a" * 32, "sobriquet": "Amber\x1b Fox", "expertise": "x\nINJECT: do bad\x07", "expertise_status": "c"}
        b = H.banner(card)
        self.assertNotIn("\x1b", b)
        self.assertNotIn("\x07", b)
        self.assertEqual(len(b.splitlines()), 5)    # the newline did not add a line


class CorpusEscaping(Base):
    def test_title_newline_does_not_break_front_matter(self):
        a = self.agent()
        r = self.h.record(a, "note", "evil\nkind: decision\ntier: foundation", "body text", project="orch")
        self.h.corpus.refresh()
        self.h.corpus._keep_content([r["id"]], "test")
        wk = os.path.join(self.home, "_archive", "corpus")
        fn = [os.path.join(dp, f) for dp, _, fs in os.walk(wk) for f in fs if f.endswith(".md")][0]
        self.assertEqual(mode(fn), 0o600)
        with open(fn, encoding="utf-8") as f:
            txt = f.read()
        fm = txt.split("---\n")[1]
        self.assertEqual(len([l for l in fm.splitlines() if l.startswith("kind:")]), 1)
        self.assertEqual(len([l for l in fm.splitlines() if l.startswith("tier:")]), 1)
        with open(os.path.join(os.path.dirname(fn), "manifest.jsonl"), encoding="utf-8") as f:
            man = [json.loads(l) for l in f]
        self.assertEqual(len(man), 1)

    def test_archive_file_name_needs_corpus_id(self):
        self.h.corpus.db.execute(
            "INSERT INTO entries(id,kind,title,body,tags,project,agent,agent_name,refs,supersedes,superseded_by,offload,seq,ts,sha,tokens,source,role,tier,expires)"
            " VALUES('../../x','note','t','b','','','a','a','[]','','',0,1,'2026-01-01',NULL,1,'log','','ephemeral','')")
        with self.assertRaisesRegex(ValueError, "not a corpus id"):
            self.h.corpus._keep_content(["../../x"], "r")
        self.assertFalse(os.path.exists(os.path.join(self.home, "_archive", "corpus")))


class Clamps(Base):
    def test_body_too_long_is_a_clear_error(self):
        a, b = self.agent(), self.agent()
        with self.assertRaisesRegex(H.HarnessError, "body: 20001 chars > 20000"):
            self.h.send(a, b, "x" * 20001)
        self.assertIn("id", self.h.send(a, b, "x" * 20000))

    def test_max_hops_clamped(self):
        a, b = self.agent(), self.agent()
        r = self.h.send(a, b, "hi", max_hops=5000)
        self.assertEqual(self.h.state().threads[r["thread"]]["max_hops"], H.MAX_HOPS_CAP)
        r2 = self.h.send(a, b, "hi", max_hops=0)
        self.assertEqual(self.h.state().threads[r2["thread"]]["max_hops"], 1)
        with self.assertRaisesRegex(H.HarnessError, "max_hops"):
            self.h.send(a, b, "hi", max_hops="lots")


class PublishCleanup(Base):
    def setUp(self):
        super().setUp()
        self.h.role_define("operator", "corpus-envoy", "orch")
        self.envoy = self.h.register(project="orch", model="claude-opus-5-5")["id"]
        self.h.role_assign("operator", "corpus-envoy", self.envoy)
        self.plug = mk_plugin(self.tmp)

    def publish(self, root=None, **kw):
        root = root or self.plug
        sha = H.bytes_sha(H.build_package(root))
        acc = self.h.send(self.envoy, "operator", f"ACCEPT sha={sha[:12]}")["id"]
        return self.h.publish_release(root, accept=acc, build=True, **kw)

    def test_leftover_prev_and_stage_do_not_block(self):
        hd = os.path.join(self.home, "_harness")
        os.makedirs(os.path.join(hd, "marketplace.prev", "junk"))
        write(os.path.join(hd, "marketplace.prev", "junk", "f"), "x")
        os.makedirs(os.path.join(hd, f"marketplace.stage-{os.getpid()}"))
        r = self.publish()
        self.assertTrue(r["verify"]["ok"], r["verify"])
        self.assertEqual(r["version"], "1.0.0")
        # second publish with a new version, again with a leftover
        os.makedirs(os.path.join(hd, "marketplace.prev"))
        write(os.path.join(self.plug, "scripts", "a.py"), "print(2)\n")
        write(os.path.join(self.plug, ".claude-plugin", "plugin.json"), json.dumps({"name": "dummy", "version": "1.0.1", "description": "d"}))
        r2 = self.publish()
        self.assertEqual(r2["version"], "1.0.1")
        self.assertTrue(r2["verify"]["ok"], r2["verify"])
        self.assertNotIn("warn", r2)
        self.assertEqual([n for n in os.listdir(hd) if n.startswith("marketplace.")], [])   # leftovers swept

    def test_failed_removal_is_reported_as_warning(self):
        self.publish()
        write(os.path.join(self.plug, "scripts", "a.py"), "print(3)\n")
        write(os.path.join(self.plug, ".claude-plugin", "plugin.json"), json.dumps({"name": "dummy", "version": "1.0.2", "description": "d"}))
        with mock.patch("shutil.rmtree", lambda *a, **k: None):     # the shell cannot delete: dirs stay
            r = self.publish()
        self.assertEqual(r["version"], "1.0.2")                      # the publish itself still succeeded
        self.assertTrue(any("could not remove marketplace.prev" in w for w in r.get("warn", [])), r.get("warn"))

class AllowedRoots(unittest.TestCase):
    def test_default_allowed_root_keeps_plugin_tree_keys_working(self):
        home = tempfile.mkdtemp(); self.addCleanup(shutil.rmtree, home, True)
        ok = os.path.expanduser("~/Claude/Projects/Harness_Router/crew-coordinator/scripts/harness.py")
        self.assertEqual(H.disk_path(ok, home), ok)
        for bad in ("/etc/passwd", os.path.expanduser("~/.ssh/id_rsa"), os.path.expanduser("~/Claude/Projects/../x")):
            with self.assertRaises(H.HarnessError):
                H.disk_path(bad, home)



if __name__ == "__main__":
    unittest.main()
