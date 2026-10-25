"""cc 0.17.0 R-077: the handoff bootstrap line names a path that exists. A capsule in a project folder outside home
(project_roots) is printed by its absolute path; one under home keeps "Exchange/projects/...". The printed path then
auto-confirms in restore. Run: python3 -B tests/test_c170_r077.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _env  # noqa: F401  isolate HOME and HARNESS_* first
import os, re, sys, tempfile, unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
import harness as H
import mcp_server as M

MODEL = "claude-sonnet-5-5"


def capsule_for(h, aid, project, role):
    sob = h.state().agents[aid]["sobriquet"]
    return (f"---\nhandoff: {project}/x\nfrom: {sob} #{aid[:8]} ({role})\nproject: {project}\nstatus: open\n---\n"
            "# Handoff\n\n## 0. Bootstrap\nnone\n")


def boot_path(text):
    m = re.search(r"restore as \S+ from (\S+)", text)
    return m.group(1) if m else None


class BootPath(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.home = os.path.join(self.tmp, "Exchange")
        self.code = os.path.join(self.tmp, "Code", "portfolio")
        os.makedirs(os.path.join(self.home, "projects", "portfolio", "handoffs"))
        os.makedirs(os.path.join(self.home, "projects", "orch", "handoffs"))
        os.makedirs(self.code)
        op = ({"workspaces": [self.code], "project_roots": {"portfolio": self.code}, "release_scope_gate": False}, [])
        p = mock.patch.object(H, "_operator_file", return_value=op)
        p.start()
        self.addCleanup(p.stop)
        self.h = H.Harness(self.home)
        self.h.role_define("operator", "design-coder", "portfolio")
        self.h.role_define("operator", "ops-coder", "orch")

    def handoff(self, role, project):
        aid = self.h.register(project=project, role=role, model=MODEL)["id"]
        return self.h.handoff(aid, capsule_for(self.h, aid, project, role), None, False, None)

    def test_project_root_outside_home_prints_the_real_absolute_path(self):
        r = self.handoff("design-coder", "portfolio")
        bp = boot_path(r["text"])
        self.assertTrue(os.path.isabs(bp), r["text"])
        self.assertTrue(os.path.isfile(bp))
        self.assertTrue(bp.startswith(os.path.abspath(self.code)))
        self.assertEqual(r["capsule"], "projects/portfolio/handoffs/" + os.path.basename(bp))   # ledger name unchanged
        body = self.h.state().messages[r["message"]]["body"]
        self.assertEqual(boot_path(body), bp)                                                   # the handoff mail too

    def test_capsule_under_home_keeps_the_exchange_form(self):
        r = self.handoff("ops-coder", "orch")
        bp = boot_path(r["text"])
        self.assertTrue(bp.startswith("Exchange/projects/orch/handoffs/"), r["text"])
        self.assertTrue(os.path.isfile(os.path.join(self.tmp, bp)))

    def test_printed_path_auto_confirms_and_restores(self):
        r = self.handoff("design-coder", "portfolio")
        bp = boot_path(r["text"])
        ok, why, _ = self.h.restore_auto_check("design-coder", bp, None)
        self.assertTrue(ok, why)
        M.BOUND.update(home=None, id=None)
        out = M.call(self.h, "harness_restore", {"role": "design-coder", "model": MODEL, "confirmed": True, "capsule": bp})
        self.assertNotIn("pending", out)
        self.assertIn("accepted by", open(bp).read())


if __name__ == "__main__":
    unittest.main()
