"""cc 0.24.0 item 2 (scope A-b2950; curator spec 2026-11-10_cc024-update-command-build-spec.md v2.1): scripts/plugin_update.py.
T1-T15 as numbered in the spec. A fake `claude` on PATH records its arguments and rewrites the scratch installed_plugins.json; HOME and
HARNESS_HOME are scratch folders. Every test fails on 0.23.0 (the script does not exist).
Run: python3 -B tests/test_c240_plugin_update.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _env  # noqa: F401  isolate HOME and HARNESS_* first
import hashlib, json, os, shutil, stat, subprocess, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(os.path.dirname(HERE), "scripts", "plugin_update.py")
COWORK = "Cowork and the desktop Code tab are not updated by this command"

FAKE = r'''#!/usr/bin/env python3
import json, os, sys
a = sys.argv[1:]
with open(os.environ["FAKE_LOG"], "a") as f:
    f.write(json.dumps(a) + "\n")
if a[:3] == ["plugin", "marketplace", "update"]:
    if os.environ.get("FAKE_MK_RC", "0") != "0":
        sys.stderr.write("marketplace update failed")
        sys.exit(int(os.environ["FAKE_MK_RC"]))
    sys.exit(0)
if a[:2] == ["plugin", "update"]:
    name = a[2].split("@")[0]
    mode = os.environ.get("FAKE_MODE_" + name.replace("-", "_"), "ok")
    if mode in ("ok", "rc1_ok", "first_only"):
        p = os.path.join(os.environ["HOME"], ".claude", "plugins", "installed_plugins.json")
        d = json.load(open(p))
        ins = d["plugins"][a[2]] if isinstance(d["plugins"][a[2]], list) else [d["plugins"][a[2]]]
        for x in (ins[:1] if mode == "first_only" else ins):
            x["version"] = os.environ["FAKE_TO_" + name.replace("-", "_")]
        json.dump(d, open(p, "w"))
    if mode == "fail":
        sys.stderr.write("E" * 400)
        sys.exit(1)
    if mode == "rc1_ok":
        sys.stderr.write("warning but updated")
        sys.exit(1)
    sys.exit(0)
sys.exit(3)
'''


class T(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.home = os.path.join(self.tmp, "home")
        self.xh = os.path.join(self.tmp, "Exchange")
        self.mk = os.path.join(self.xh, "_harness", "marketplace")
        os.makedirs(os.path.join(self.home, ".claude", "plugins"))
        os.makedirs(os.path.join(self.mk, ".claude-plugin"))
        self.bin = os.path.join(self.tmp, "bin")
        os.makedirs(self.bin)
        fake = os.path.join(self.bin, "claude")
        with open(fake, "w") as f:
            f.write(FAKE)
        os.chmod(fake, 0o755)
        self.log = os.path.join(self.tmp, "fake.log")
        self.extra = {}
        self.known()

    # ---- fixtures in the real files' shapes
    def market(self, **plugins):
        """plugins: name=(marketplace.json version, plugin.json version)"""
        m = {"name": "harness-local", "plugins": []}
        for n, (mv, pv) in plugins.items():
            n = n.replace("_", "-")
            m["plugins"].append({"name": n, "source": "./plugins/" + n, "version": mv})
            d = os.path.join(self.mk, "plugins", n, ".claude-plugin")
            os.makedirs(d, exist_ok=True)
            json.dump({"name": n, "version": pv}, open(os.path.join(d, "plugin.json"), "w"))
        json.dump(m, open(os.path.join(self.mk, ".claude-plugin", "marketplace.json"), "w"))

    def inst(self, as_list=True, **plugins):
        d = {"version": 2, "plugins": {}}
        for n, v in plugins.items():
            n = n.replace("_", "-")
            path = os.path.join(self.home, ".claude", "plugins", "cache", "harness-local", n, v)
            os.makedirs(path, exist_ok=True)
            e = {"scope": "user", "installPath": path, "version": v}
            d["plugins"][n + "@harness-local"] = [e] if as_list else e
        json.dump(d, open(os.path.join(self.home, ".claude", "plugins", "installed_plugins.json"), "w"))

    def known(self, folder=None, kind="directory"):
        folder = folder or self.mk
        json.dump({"harness-local": {"source": {"source": kind, "path": folder}, "installLocation": folder}},
                  open(os.path.join(self.home, ".claude", "plugins", "known_marketplaces.json"), "w"))

    def run_it(self, *args, fake=True):
        env = dict(os.environ, HOME=self.home, HARNESS_HOME=self.xh, FAKE_LOG=self.log,
                   PATH=(self.bin + os.pathsep if fake else "") + "/usr/bin:/bin", **self.extra)
        r = subprocess.run([sys.executable, "-B", SCRIPT] + list(args), capture_output=True, text=True, env=env)
        return r.returncode, r.stdout + r.stderr

    def calls(self):
        if not os.path.exists(self.log):
            return []
        return [json.loads(x) for x in open(self.log)]

    def installed_now(self, name):
        d = json.load(open(os.path.join(self.home, ".claude", "plugins", "installed_plugins.json")))
        v = d["plugins"][name + "@harness-local"]
        return (v[0] if isinstance(v, list) else v)["version"]

    def tree_hash(self, root):
        h = hashlib.sha256()
        for dp, dns, fns in sorted(os.walk(root)):
            dns.sort()
            for fn in sorted(fns):
                p = os.path.join(dp, fn)
                h.update(p.encode() + b"\0" + open(p, "rb").read())
        return h.hexdigest()

    def to(self, **kw):
        for n, v in kw.items():
            self.extra["FAKE_TO_" + n] = v

    def mode(self, **kw):
        for n, v in kw.items():
            self.extra["FAKE_MODE_" + n] = v

    # ---- tests
    def test_t1_none_installed(self):
        self.market(excellent_etiquette=("0.2.13", "0.2.13"))
        json.dump({"version": 2, "plugins": {"other@claude-plugins-official": []}},
                  open(os.path.join(self.home, ".claude", "plugins", "installed_plugins.json"), "w"))
        code, out = self.run_it("--apply")
        self.assertEqual(code, 0, out)
        self.assertIn("no harness-local plugin installed in Claude Code", out)
        self.assertEqual(self.calls(), [])

    def test_t2_dry_run_one_outdated(self):
        self.market(excellent_etiquette=("0.2.14", "0.2.14"))
        self.inst(excellent_etiquette="0.2.13")
        before = self.tree_hash(os.path.join(self.home, ".claude"))
        code, out = self.run_it()
        self.assertEqual(code, 10, out)
        self.assertIn("excellent-etiquette      0.2.13       0.2.14       update", out)
        self.assertIn("claude plugin marketplace update harness-local", out)
        self.assertIn("claude plugin update excellent-etiquette@harness-local", out)
        self.assertEqual(self.calls(), [])
        self.assertEqual(self.tree_hash(os.path.join(self.home, ".claude")), before)

    def test_t3_apply_calls_in_order_and_logs(self):
        self.market(excellent_etiquette=("0.2.14", "0.2.14"))
        self.inst(excellent_etiquette="0.2.13")
        self.to(excellent_etiquette="0.2.14")
        code, out = self.run_it("--apply")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.calls(), [["plugin", "marketplace", "update", "harness-local"],
                                        ["plugin", "update", "excellent-etiquette@harness-local"]])
        self.assertIn("updated excellent-etiquette: 0.2.13 -> 0.2.14", out)
        log = open(os.path.join(self.xh, "_logs", "plugin_update.log")).read().split("\t")
        self.assertEqual(log[1:], ["excellent-etiquette", "0.2.13", "0.2.14", "updated\n"])

    def test_t4_one_fails_the_other_updates(self):
        self.market(alpha=("1.1.0", "1.1.0"), beta=("2.1.0", "2.1.0"))
        self.inst(alpha="1.0.0", beta="2.0.0")
        self.to(alpha="1.1.0", beta="2.1.0")
        self.mode(alpha="fail")
        code, out = self.run_it("--apply")
        self.assertEqual(code, 1, out)
        self.assertIn("not updated alpha: installed 1.0.0, expected 1.1.0", out)
        self.assertIn("E" * 300 + ")", out)                                         # cut at 300
        self.assertNotIn("E" * 301, out)
        self.assertIn("updated beta: 2.0.0 -> 2.1.0", out)

    def test_t5_bad_names_are_refused_without_a_subprocess(self):
        self.market(alpha=("1.1.0", "1.1.0"))
        self.inst(alpha="1.0.0")
        for bad in ("a b", "a/b", "a;rm"):
            with self.subTest(name=bad):
                code, out = self.run_it("--apply", "--plugin", bad)
                self.assertEqual(code, 1, out)
                self.assertIn("refused", out)
        code, out = self.run_it("--apply", "--marketplace", "x;y")
        self.assertEqual(code, 2, out)
        d = json.load(open(os.path.join(self.home, ".claude", "plugins", "installed_plugins.json")))
        d["plugins"]["bad;name@harness-local"] = [{"version": "1"}]
        json.dump(d, open(os.path.join(self.home, ".claude", "plugins", "installed_plugins.json"), "w"))
        self.to(alpha="1.1.0")
        code, out = self.run_it("--apply")
        self.assertIn("refused: installed plugin name 'bad;name'", out)
        self.assertNotIn(["plugin", "update", "bad;name@harness-local"], self.calls())
        self.assertEqual(code, 1, out)

    def test_t6_claude_missing(self):
        self.market(alpha=("1.1.0", "1.1.0"))
        self.inst(alpha="1.0.0")
        code, out = self.run_it(fake=False)
        self.assertEqual(code, 10, out)
        self.assertIn("claude binary: not found", out)
        code, out = self.run_it("--apply", fake=False)
        self.assertEqual(code, 2, out)
        self.assertIn("claude binary is not on PATH", out)

    def test_t7_cowork_note_ends_every_mode(self):
        self.market(alpha=("1.1.0", "1.1.0"))
        self.inst(alpha="1.0.0")
        self.to(alpha="1.1.0")
        for args in ((), ("--apply",), ("--marketplace", "x;y")):
            with self.subTest(args=args):
                code, out = self.run_it(*args)
                self.assertTrue(out.rstrip().endswith("click save plugin in claude.ai once for each plugin file (the secretary's queue)."), out)
                self.assertIn(COWORK, out)
                self.assertIn("this command updates Claude Code CLI installs only", out)

    def test_t8_dry_run_writes_nothing(self):
        self.market(alpha=("1.1.0", "1.1.0"))
        self.inst(alpha="1.0.0")
        before = self.tree_hash(self.tmp)
        self.run_it()
        self.assertEqual(self.tree_hash(self.tmp), before)

    def test_t9_version_disagreement_blocks(self):
        self.market(excellent_etiquette=("0.2.14", "0.2.13"), beta=("2.1.0", "2.1.0"))
        self.inst(excellent_etiquette="0.2.12", beta="2.0.0")
        code, out = self.run_it()
        self.assertEqual(code, 1, out)                                                # blocked beats pending
        self.assertIn("blocked: version disagrees: marketplace 0.2.14, plugin 0.2.13", out)
        self.to(beta="2.1.0")
        code, out = self.run_it("--apply")
        self.assertEqual(code, 1, out)
        self.assertNotIn(["plugin", "update", "excellent-etiquette@harness-local"], self.calls())
        self.assertIn(["plugin", "update", "beta@harness-local"], self.calls())

    def test_t10_marketplace_points_elsewhere(self):
        self.market(alpha=("1.1.0", "1.1.0"))
        self.inst(alpha="1.0.0")
        other = os.path.join(self.tmp, "OldExchange", "_harness", "marketplace")
        os.makedirs(other)
        self.known(other)
        for args in ((), ("--apply",)):
            with self.subTest(args=args):
                code, out = self.run_it(*args)
                self.assertEqual(code, 2, out)
                self.assertIn(other, out)
                self.assertIn(self.mk, out)
        self.assertEqual(self.calls(), [])

    def test_t11_exit_0_but_not_updated(self):
        self.market(alpha=("1.1.0", "1.1.0"))
        self.inst(alpha="1.0.0")
        self.mode(alpha="stuck")
        code, out = self.run_it("--apply")
        self.assertEqual(code, 1, out)
        self.assertIn("not updated alpha: installed 1.0.0, expected 1.1.0", out)

    def test_t12_marketplace_update_fails(self):
        self.market(alpha=("1.1.0", "1.1.0"))
        self.inst(alpha="1.0.0")
        self.extra["FAKE_MK_RC"] = "1"
        self.known(kind="git")
        code, out = self.run_it("--apply")
        self.assertEqual(code, 1, out)
        self.assertEqual(self.calls(), [["plugin", "marketplace", "update", "harness-local"]])
        # directory source: the run goes on; a plugin that stays old is "not updated"
        os.remove(self.log)
        self.known(kind="directory")
        self.mode(alpha="stuck")
        code, out = self.run_it("--apply")
        self.assertEqual(code, 1, out)
        self.assertIn("marketplace update exited 1: marketplace update failed", out)
        self.assertIn(["plugin", "update", "alpha@harness-local"], self.calls())
        self.assertIn("not updated alpha", out)

    def test_t13_names_binary_pending_and_reload(self):
        self.market(alpha=("1.1.0", "1.1.0"))
        self.inst(alpha="1.0.0")
        code, out = self.run_it()
        self.assertIn("claude binary: " + os.path.join(self.bin, "claude"), out)
        self.assertIn("exit 10 means updates are pending, not an error", out)
        os.makedirs(os.path.join(self.home, ".claude", "plugins", "cache", "harness-local", "alpha", "1.0.0", "hooks"))
        self.to(alpha="1.1.0")
        code, out = self.run_it("--apply")
        self.assertEqual(code, 0, out)
        self.assertIn("alpha: reload: running chats keep the old version until reloaded", out)

    def test_t14_nonzero_exit_but_updated_counts(self):
        self.market(alpha=("1.1.0", "1.1.0"))
        self.inst(alpha="1.0.0")
        self.to(alpha="1.1.0")
        self.mode(alpha="rc1_ok")
        code, out = self.run_it("--apply")
        self.assertEqual(code, 0, out)
        self.assertIn("updated alpha: 1.0.0 -> 1.1.0 (command exited 1: warning but updated)", out)

    def test_t15_one_install_per_key_reads_like_a_list(self):
        self.market(alpha=("1.1.0", "1.1.0"))
        for as_list in (True, False):
            with self.subTest(as_list=as_list):
                self.inst(as_list=as_list, alpha="1.0.0")
                code, out = self.run_it()
                self.assertEqual(code, 10, out)
                self.assertIn("alpha                    1.0.0        1.1.0        update", out)

    def test_fix1_a_newer_copy_in_another_scope_does_not_fail_the_check(self):
        """critic read 1: user scope 0.2.12, project scope 0.2.14 (a dev copy), marketplace 0.2.13; the update touches the user copy."""
        self.market(excellent_etiquette=("0.2.13", "0.2.13"))
        p = os.path.join(self.home, ".claude", "plugins", "installed_plugins.json")
        json.dump({"version": 2, "plugins": {"excellent-etiquette@harness-local": [
            {"scope": "user", "installPath": os.path.join(self.tmp, "u"), "version": "0.2.12"},
            {"scope": "project", "installPath": os.path.join(self.tmp, "p"), "version": "0.2.14"}]}}, open(p, "w"))
        code, out = self.run_it()
        self.assertEqual(code, 10, out)
        self.to(excellent_etiquette="0.2.13")
        self.mode(excellent_etiquette="first_only")
        code, out = self.run_it("--apply")
        self.assertEqual(code, 0, out)
        self.assertIn("updated excellent-etiquette: 0.2.12, 0.2.14 -> 0.2.13", out)
        code, out = self.run_it()
        self.assertEqual(code, 0, out)                                                # no copy below 0.2.13: current

    def test_fix1_a_broken_installed_file_stops_with_exit_2(self):
        self.market(alpha=("1.1.0", "1.1.0"))
        with open(os.path.join(self.home, ".claude", "plugins", "installed_plugins.json"), "w") as f:
            f.write("{not json")
        for args in ((), ("--apply",)):
            with self.subTest(args=args):
                code, out = self.run_it(*args)
                self.assertEqual(code, 2, out)
                self.assertIn("stop: cannot read", out)
                self.assertNotIn("no harness-local plugin installed", out)
        self.assertEqual(self.calls(), [])
        os.remove(os.path.join(self.home, ".claude", "plugins", "installed_plugins.json"))
        code, out = self.run_it()                                                      # no file at all: nothing installed yet
        self.assertEqual(code, 0, out)
        self.assertIn("no harness-local plugin installed in Claude Code", out)

    def test_crew_coordinator_is_never_hinted_for_a_cli_install(self):
        self.market(crew_coordinator=("0.24.0", "0.24.0"), alpha=("1.1.0", "1.1.0"), beta=("1.0.0", "1.0.0"))
        self.inst(alpha="1.1.0")
        code, out = self.run_it()
        self.assertIn("claude plugin install beta@harness-local", out)
        self.assertNotIn("crew-coordinator@harness-local", out)


if __name__ == "__main__":
    unittest.main()
