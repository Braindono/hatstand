"""cc 0.17.0 R-053 (Harness confinement: ceiling, publish paths, watch): narrower path ceiling; publish paths that come
over MCP are confined; watch and plugin_dirs come from operator.json only; warnings name file and key, never the value.
Run: python3 -B tests/test_c170_r053.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _env  # noqa: F401  isolate HOME and HARNESS_* first
import json, os, sys, tempfile, unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
import harness as H
import mcp_server as M

MODEL = "claude-opus-5-5"


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.home = os.path.join(self.tmp, "Exchange")
        os.makedirs(self.home)
        self.h = H.Harness(self.home)
        self.op = {}
        p = mock.patch.object(H, "_operator_file", side_effect=lambda: (dict(self.op), []))
        p.start()
        self.addCleanup(p.stop)
        self.HOME = os.path.expanduser("~")

    def cfg(self, **kw):
        cp = os.path.join(self.home, "_harness", "config.json")
        c = json.load(open(cp))
        c.update(kw)
        json.dump(c, open(cp, "w"))


class Ceiling(Base):
    def test_dot_claude_itself_is_outside_the_ceiling(self):
        bad = os.path.join(self.HOME, ".claude", "projects", "x")
        ok1 = os.path.join(self.HOME, ".claude", "crew-coordinator", "x")
        ok2 = os.path.join(self.HOME, ".claude", "plugins", "x")
        ok3 = os.path.join(self.HOME, "Claude", "Projects", "x")
        self.cfg(workspaces=[bad, ok1, ok2, ok3])
        pc = H.path_config(self.home)
        self.assertEqual(pc["workspaces"], [ok1, ok2, ok3])
        self.assertIn("config.json workspaces[0] ignored: outside the ceiling (set it in operator.json)", pc["warnings"])

    def test_warnings_never_carry_the_value(self):
        secret_path = os.path.join(self.HOME, ".ssh", "id_secret_name")
        self.cfg(workspaces=[secret_path], allowed_roots=[secret_path], project_roots={"pp": secret_path},
                 watch=[secret_path], plugin_dirs=[secret_path])
        warns = H.path_config(self.home)["warnings"]
        self.assertTrue(warns)
        self.assertFalse(any("id_secret_name" in w or ".ssh" in w for w in warns), warns)

    def test_operator_file_is_unrestricted(self):
        anywhere = os.path.join(self.tmp, "anywhere")
        self.op = {"workspaces": [anywhere], "allowed_roots": [anywhere]}
        pc = H.path_config(self.home)
        self.assertIn(anywhere, pc["workspaces"])
        self.assertIn(anywhere, pc["allowed_roots"])


class WatchAndPluginDirs(Base):
    def test_config_json_values_ignored_with_one_warning_each(self):
        self.cfg(watch=["~/x.txt"], plugin_dirs=["~/plugins-x"])
        pc = H.path_config(self.home)
        self.assertEqual((pc["watch"], pc["plugin_dirs"]), ([], []))
        self.assertIn("config.json watch ignored: set it in operator.json", pc["warnings"])
        self.assertIn("config.json plugin_dirs ignored: set it in operator.json", pc["warnings"])
        fp = H.config_fingerprint(self.home)
        self.assertFalse(any(k.startswith("watch:") for k in fp))

    def test_operator_json_values_honoured(self):
        f = os.path.join(self.tmp, "watched.txt")
        open(f, "w").write("x")
        self.op = {"watch": [f], "plugin_dirs": [self.tmp]}
        pc = H.path_config(self.home)
        self.assertEqual((pc["watch"], pc["plugin_dirs"]), ([f], [self.tmp]))
        self.assertIn("watch:" + f, H.config_fingerprint(self.home))

    def test_default_empty_watch_in_config_is_quiet(self):
        pc = H.path_config(self.home)          # DEFAULT_CONFIG has "watch": []
        self.assertFalse(any("watch" in w for w in pc["warnings"]))


class PublishOverMcp(Base):
    def test_outside_path_refused_before_approval(self):
        a = self.h.register(project="orch", model=MODEL)["id"]
        M.BOUND.update(home=self.home, id=a)
        outside = os.path.join(self.tmp, "elsewhere-plugin")
        os.makedirs(outside)
        n = len(self.h.store.read_all())
        with self.assertRaisesRegex(H.HarnessError, "outside the Exchange home, workspaces and allowed roots"):
            M.call(self.h, "harness_admin", {"op": "publish_release", "agent": a,
                                             "args": {"path": outside, "override": "ship"}})
        self.assertFalse([e for e in self.h.store.read_all()[n:] if e["type"] in ("approval.requested", "release.published")])

    def test_inside_path_is_queued_for_approval(self):
        a = self.h.register(project="orch", model=MODEL)["id"]
        M.BOUND.update(home=self.home, id=a)
        r = M.call(self.h, "harness_admin", {"op": "publish_release", "agent": a, "args": {"path": self.home, "override": "ship"}})
        self.assertTrue(r.get("pending"))

    def test_outside_pkg_refused(self):
        with self.assertRaisesRegex(H.HarnessError, "pkg:"):
            self.h.confine_publish_args({"path": self.home, "pkg": os.path.join(self.tmp, "x.plugin")})

    def test_cli_publish_is_not_confined(self):
        outside = os.path.join(self.tmp, "not-a-plugin")
        os.makedirs(outside)
        with self.assertRaisesRegex(H.HarnessError, "is not a plugin"):   # gets past any confinement to the plugin check
            self.h.publish_release(outside, by="operator")


if __name__ == "__main__":
    unittest.main()
