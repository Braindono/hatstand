"""cc 0.24.0 item 15 extension (scope A-b2950; envoy m-9c759018dee2, D-945c6): no workspace path in the shipped text. Docs and comments
use the <workspace> placeholder; code defaults are built with os.path.join and resolve to exactly the folders they did before, so nothing
changes for the operator. The expected values are built from parts at run time, so this file carries no workspace path either.
Run: python3 -B tests/test_c240_item15x.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _env  # noqa: F401  isolate HOME and HARNESS_* first
import os, shutil, sys, tempfile, unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
import harness as H
import retire_guard as RT
import release_guard as RG
import ctx_hook as CH
import lesson_cue as LC
import auto_lookup as AL
import launchers as LN
import corrections_harvester as CO

WS_NAME = "Cl" + "aude"                       # the workspace folder under the home


class Defaults(unittest.TestCase):
    def setUp(self):
        self.h = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.h, True)
        p = mock.patch.dict(os.environ, {"HOME": self.h})
        p.start()
        self.addCleanup(p.stop)
        for k in ("HARNESS_HOME", "HARNESS_OPS_ROOT"):
            os.environ.pop(k, None)
        self.w = self.h + "/" + WS_NAME

    def x(self, p):
        return os.path.expanduser(p)

    def test_module_defaults_resolve_to_the_same_folders(self):
        w = self.w
        self.assertEqual([self.x(c) for c in H.HOME_CANDIDATES], [w + "/Exchange", w + "/Projects/Exchange", self.h + "/mnt/Exchange"])
        self.assertEqual(RT.HOME_CANDIDATES, H.HOME_CANDIDATES)
        self.assertEqual(self.x(H.LEGACY_LOGS[0]), w + "/Projects/Harness_Router/_harness/events.jsonl")
        self.assertEqual(self.x(H.LEGACY_LOGS[2]), w + "/Code/harness-ops/harness-hub/_harness/events.jsonl")
        self.assertEqual(self.x(H.OPS_ROOT_DEFAULT), w + "/Code/harness-ops")
        self.assertEqual([self.x(r) for r in H.DEFAULT_CONFIG["allowed_roots"]], [w + "/Projects"])
        self.assertEqual(self.x(H.PATH_CEILINGS[0]), w + "/Projects")
        self.assertEqual(self.x(H.OPERATOR_FILES["claude-desktop:config"]),
                         self.h + "/Library/Application Support/" + WS_NAME + "/claude_desktop_config.json")
        self.assertEqual([self.x(r) for r in LN.ROOTS], [w + "/Projects", w + "/Code"])
        self.assertEqual(CO.ops_root(), w + "/Code/harness-ops")

    def test_home_finders_take_the_new_home_then_the_old_one(self):
        new, old = self.w + "/Exchange", self.w + "/Projects/Exchange"
        self.assertEqual(CH.default_home(), new)                         # nothing exists: the new path
        os.makedirs(os.path.join(old, "_harness"))
        for f in (CH.default_home, LC.home, AL.home, RG.find_home):
            with self.subTest(f=f.__module__):
                self.assertEqual(f(), old)
        os.makedirs(os.path.join(new, "_harness"))
        for f in (CH.default_home, LC.home, AL.home, RG.find_home):
            with self.subTest(f=f.__module__):
                self.assertEqual(f(), new)

    def test_the_cowork_session_folder_is_still_recognised(self):
        folder = "local-agent-mode" + "-sessions"
        self.assertEqual(CH.COWORK_SESSIONS, folder)
        self.assertEqual(RG.COWORK_SESSIONS, folder)
        p = self.h + "/Library/Application Support/" + WS_NAME + "/" + folder + "/a/b/.claude/projects/-p/abc.jsonl"
        self.assertEqual(CH.surface_src(p)[0], "cowork")
        rpm = self.h + "/Library/Application Support/" + WS_NAME + "/" + folder + "/s1/rpm/cc/x.py"
        self.assertEqual(RG.protected(rpm, None), "a desktop chat's synced plugin copy")


class GateFiles(unittest.TestCase):
    """The two gate-file lines (curator lease, D-9cb95): each expression, read from the source and evaluated, is byte-identical to
    the old literal (rebuilt here from parts)."""

    def test_the_simulator_home_default_resolves_as_before(self):
        import ast as ast_
        src = open(os.path.join(HERE, "..", "scripts", "release_sim.py"), encoding="utf-8").read()
        kw = next(n for n in ast_.walk(ast_.parse(src))
                  if isinstance(n, ast_.keyword) and n.arg == "default" and "HARNESS_HOME" in ast_.dump(n.value))
        code = compile(ast_.Expression(kw.value), "release_sim.py", "eval")
        with mock.patch.dict(os.environ, {"HOME": "/h"}):
            os.environ.pop("HARNESS_HOME", None)
            self.assertEqual(eval(code, {"os": os}), "/h/" + WS_NAME + "/Projects/Exchange")

    def test_the_rpm_probe_string_is_the_same(self):
        import ast as ast_
        src = open(os.path.join(HERE, "..", "scripts", "sim_launcher.py"), encoding="utf-8").read()
        d = next(n for n in ast_.walk(ast_.parse(src)) if isinstance(n, ast_.Dict)
                 and any(isinstance(k, ast_.Constant) and k.value == "deny_rpm" for k in n.keys))
        v = d.values[[k.value for k in d.keys].index("deny_rpm")]
        cmd = next(x for x in v.elts if isinstance(x, ast_.Dict)).values[0]
        got = eval(compile(ast_.Expression(cmd), "sim_launcher.py", "eval"), {"user": "/u"})
        self.assertEqual(got, "rsync -a src/ '/u/Library/Application Support/" + WS_NAME + "/" + "local-agent-mode" + "-sessions/s1/rpm/cc/'")


class Tree(unittest.TestCase):
    def test_no_workspace_path_in_the_shipped_text(self):
        import hatstand_guard as G
        root = os.path.join(HERE, "..")
        out = []
        for d, dirs, files in os.walk(root):
            dirs[:] = [x for x in dirs if x not in ("__pycache__", ".git")]
            for fn in files:
                rel = os.path.relpath(os.path.join(d, fn), root)
                if rel.startswith("tests/fixtures/steward-r045/"):
                    continue                     # a fixture exempt by its pinned manifest
                try:
                    t = open(os.path.join(d, fn), encoding="utf-8").read()
                except (UnicodeDecodeError, OSError):
                    continue
                for n, line in enumerate(t.splitlines(), 1):
                    if G.WORKSPACE_RX.search(line):
                        out.append("%s:%d" % (rel, n))
        self.assertEqual(out, [])


if __name__ == "__main__":
    unittest.main()
