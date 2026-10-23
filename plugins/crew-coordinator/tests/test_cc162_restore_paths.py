"""cc 0.16.2 item 10: restore auto-confirm canonicalises the capsule path. Run: python3 -B tests/test_cc162_restore_paths.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _env  # noqa: F401  isolate HOME and HARNESS_* first
import os, sys, tempfile, unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
import harness as H
import mcp_server as M

MODEL = "claude-sonnet-5-5"


class Paths(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.home = os.path.join(self.tmp, "Exchange")
        self.code = os.path.join(self.tmp, "Code", "portfolio")
        os.makedirs(os.path.join(self.home, "projects", "portfolio", "handoffs"))
        os.makedirs(self.code)
        op = ({"workspaces": [self.code], "project_roots": {"portfolio": self.code}, "release_scope_gate": False}, [])
        p = mock.patch.object(H, "_operator_file", return_value=op)
        p.start()
        self.addCleanup(p.stop)
        self.h = H.Harness(self.home)
        self.h.role_define("operator", "design-coder", "portfolio")
        self.a = self.h.register(project="portfolio", role="design-coder", model=MODEL)["id"]
        sob = self.h.state().agents[self.a]["sobriquet"]
        cap = (f"---\nhandoff: portfolio/x\nfrom: {sob} #{self.a[:8]} (design-coder)\nproject: portfolio\nstatus: open\n---\n"
               "# Handoff\n\n## 0. Bootstrap\nnone\n")
        r = self.h.handoff(self.a, cap, None, False, None)
        self.canon = r["capsule"]                               # projects/portfolio/handoffs/<file>
        self.file = os.path.join(self.code, "handoffs", os.path.basename(self.canon))

    def check(self, capsule):
        return self.h.restore_auto_check("design-coder", capsule, None)

    def restore(self, capsule):
        M.BOUND.update(home=None, id=None)
        return M.call(self.h, "harness_restore", {"role": "design-coder", "model": MODEL, "confirmed": True, "capsule": capsule})

    def test_capsule_lives_in_the_project_root_folder(self):
        self.assertTrue(os.path.isfile(self.file))
        self.assertFalse(os.listdir(os.path.join(self.home, "projects", "portfolio", "handoffs")))

    def test_absolute_path_in_the_project_root_is_accepted(self):
        ok, why, _ = self.check(self.file)
        self.assertTrue(ok, why)

    def test_exchange_relative_and_projects_relative_still_accepted(self):
        self.assertTrue(self.check("Exchange/" + self.canon)[0])
        self.assertTrue(self.check(self.canon)[0])

    def test_absolute_restore_auto_confirms_end_to_end(self):
        r = self.restore(self.file)
        self.assertNotIn("pending", r)
        self.assertIn("accepted by", open(self.file).read())

    def test_unrelated_absolute_path_rejected(self):
        other = os.path.join(self.tmp, "elsewhere", "2026-10-23-x.md")
        os.makedirs(os.path.dirname(other))
        open(other, "w").write("---\nstatus: open\n---\n")
        ok, why, _ = self.check(other)
        self.assertFalse(ok)
        self.assertIn("rejected", why)

    def test_dotdot_and_symlink_rejected(self):
        ok, why, _ = self.check("Exchange/projects/portfolio/handoffs/../../portfolio/handoffs/x.md")
        self.assertFalse(ok)                                              # '..' never slips through
        link = os.path.join(self.code, "handoffs", "2026-10-23-link.md")
        os.symlink(self.file, link)
        ok, why, _ = self.check(link)
        self.assertFalse(ok)
        self.assertIn("rejected", why)
        ok, why, _ = self.check("Exchange/projects/portfolio/../../../etc/passwd")
        self.assertFalse(ok)

    def test_missing_file_and_other_project_rejected(self):
        ok, why, _ = self.check(self.code + "/handoffs/2026-10-23-nope.md")
        self.assertFalse(ok)
        ok, why, _ = self.check("Exchange/projects/other/handoffs/2026-10-23-x.md")
        self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main()
