"""cc 0.15.6: archive before overwrite (P1/P2), set_project/role mismatch (N-dacca).
Run: python3 -B tests/test_cc156.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _env  # noqa: F401  isolate HOME and HARNESS_* first
import os, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
import harness as H

MODEL = "claude-sonnet-5-5"


class Roles(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.home = os.path.join(self.tmp, "home")
        os.makedirs(self.home)
        self.h = H.Harness(self.home)
        self.h.role_define("operator", "coder", "oldp")
        self.a = self.h.register(project="oldp", model=MODEL)["id"]
        self.h.role_assign("operator", "coder", self.a)
        self.b = self.h.register(project="other", model=MODEL)["id"]

    def test_set_project_warns_for_holder(self):
        r = self.h.set_project(self.a, "newp", by="operator")
        self.assertIn("role_define", r["warn"])
        self.assertIn("coder", r["warn"])

    def test_set_project_unrelated_agent_no_warning(self):
        self.assertNotIn("warn", self.h.set_project(self.b, "newp", by="operator"))

    def test_pending_approval_carries_the_note(self):
        r = self.h.request_approval(self.a, "set_project", {"target": self.a, "project": "newp"})
        self.assertIn("role_define", r["note"])

    def test_roster_and_verify_flag_mismatch(self):
        self.h.set_project(self.a, "newp", by="operator")
        self.assertIn("⚠", self.h.roster()["text"])
        self.assertEqual(len(self.h.verify()["warnings"]), 1)

    def test_role_define_move_rebinds_holder_in_new_project(self):
        self.h.set_project(self.a, "newp", by="operator")
        r = self.h.role_define("operator", "coder", "newp")
        self.assertEqual(r["rebound"], self.a[:8])
        st = self.h.state()
        self.assertEqual(st.role_holder("coder"), self.a)
        self.assertEqual(self.h.verify()["warnings"], [])

    def test_role_define_move_warns_when_holder_elsewhere(self):
        r = self.h.role_define("operator", "coder", "newp")
        self.assertIn("set_project", r["warn"])
        self.assertNotIn("rebound", r)


class Archive(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.home = os.path.join(self.tmp, "home")
        d = os.path.join(self.home, "projects", "p", "handoffs")
        os.makedirs(d)
        self.f = os.path.join(d, "c.md")
        open(self.f, "w").write("---\nstatus: open\n---\n# c\n")
        self.h = H.Harness(self.home)
        self.aid = self.h.register(project="p", model=MODEL)["id"]

    def test_status_change_archives_old_file_with_manifest(self):
        self.assertTrue(self.h._set_capsule_status(self.aid, "projects/p/handoffs/c.md", "accepted by x"))
        self.assertIn("status: accepted by x", open(self.f).read())
        dirs = [x for x in os.listdir(os.path.join(self.home, "_archive")) if x.endswith("handoff-status")]
        self.assertEqual(len(dirs), 1)
        d = os.path.join(self.home, "_archive", dirs[0])
        self.assertIn("status: open", open(os.path.join(d, "projects/p/handoffs/c.md")).read())
        line = open(os.path.join(d, "MANIFEST.sha256")).read().split("\n")[0].split("  ")
        self.assertEqual(line[2], "projects/p/handoffs/c.md")
        self.assertEqual(len(line[0]), 64)

    def test_failed_archive_aborts_rewrite(self):
        self.h._archive_copy = lambda *a, **k: (_ for _ in ()).throw(OSError("disk full"))
        with self.assertRaises(OSError):
            self.h._set_capsule_status(self.aid, "projects/p/handoffs/c.md", "accepted by x")
        self.assertIn("status: open", open(self.f).read())

    def test_second_archive_does_not_overwrite_first(self):
        a = self.h._archive_copy(self.f, "handoff-status")
        open(self.f, "a").write("more\n")
        b = self.h._archive_copy(self.f, "handoff-status")
        self.assertNotEqual(a, b)
        self.assertNotIn("more", open(a).read())


class Hermetic(unittest.TestCase):
    def test_tests_run_in_a_private_home(self):
        real = os.path.realpath(os.path.expanduser("~"))
        self.assertIn("cc-tests-", real)
        self.assertEqual([k for k in os.environ if k.startswith("HARNESS_") and k != "HARNESS_STATE_DIR"], [])
        self.assertTrue(os.environ["HARNESS_STATE_DIR"].startswith(os.environ["HOME"]))


if __name__ == "__main__":
    unittest.main()
