"""cc 0.14.7 tests: drift prevention A-J (marketplace, verify, notice, retired/external, --build, dry-run,
running-code rows, /upgrade registry helper). Run: python3 -B tests/test_drift_prevention.py"""
import json, os, shutil, stat, sys, tempfile, types, unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import harness as H


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text)


def mk_plugin(tmp, name="dummy", ver="1.0.0"):
    root = os.path.join(tmp, "src", name)
    write(os.path.join(root, ".claude-plugin", "plugin.json"), json.dumps({"name": name, "version": ver, "description": "d"}))
    write(os.path.join(root, "scripts", "a.py"), "print(1)\n")
    return root


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.home = os.path.join(self.tmp, "home"); os.makedirs(self.home)
        self.h = H.Harness(self.home)
        self.h.role_define("operator", "corpus-envoy", "orch")
        self.envoy = self.h.register(project="orch", model="claude-opus-5-5")["id"]
        self.h.role_assign("operator", "corpus-envoy", self.envoy)
        self.peer = self.h.register(project="p", model="claude-opus-5-5")["id"]
        self.plug = mk_plugin(self.tmp)

    def accept_for(self, root):
        sha = H.bytes_sha(H.build_package(root))
        return self.h.send(self.envoy, "operator", f"ACCEPT sha={sha[:12]}")["id"]

    def publish(self, root=None, **kw):
        root = root or self.plug
        return self.h.publish_release(root, accept=self.accept_for(root), build=True, **kw)

    def n_events(self):
        return len(self.h.store.read_all())


class BuildTests(Base):
    def test_build_twice_same_sha(self):   # envoy condition c
        a = H.build_package(self.plug)
        os.utime(os.path.join(self.plug, "scripts", "a.py"), (1, 1))
        b = H.build_package(self.plug)
        self.assertEqual(H.bytes_sha(a), H.bytes_sha(b))

    def test_ignored_files_excluded(self):   # envoy condition a
        before = H.bytes_sha(H.build_package(self.plug))
        write(os.path.join(self.plug, ".DS_Store"), "x")
        write(os.path.join(self.plug, "scripts", "__pycache__", "a.pyc"), "x")
        write(os.path.join(self.plug, "._a"), "x")
        self.assertEqual(before, H.bytes_sha(H.build_package(self.plug)))
        self.assertEqual(H.full_tree_sha(self.plug), H.full_tree_sha(self.plug))

    def test_content_change_changes_sha(self):
        before = H.bytes_sha(H.build_package(self.plug))
        write(os.path.join(self.plug, "scripts", "a.py"), "print(2)\n")
        self.assertNotEqual(before, H.bytes_sha(H.build_package(self.plug)))


class PublishTests(Base):
    def test_publish_builds_marketplace_notice_and_verifies(self):
        r = self.publish()
        self.assertEqual(r["version"], "1.0.0")
        self.assertTrue(r["verify"]["ok"], r["verify"])
        self.assertEqual(r["notice"], "sent")
        pkg = os.path.join(self.tmp, "src", "dummy-1.0.0.plugin")
        self.assertTrue(os.path.isfile(pkg))
        self.assertEqual(r["pkg_sha"], H.file_sha(pkg)[:12])
        mj = json.load(open(os.path.join(self.home, "_harness", "marketplace", ".claude-plugin", "marketplace.json")))
        self.assertEqual([(p["name"], p["version"]) for p in mj["plugins"]], [("dummy", "1.0.0")])
        self.assertTrue(os.path.isfile(os.path.join(self.home, "_harness", "marketplace", "plugins", "dummy", "scripts", "a.py")))
        notes = [m for m in self.h.state().messages.values() if m["kind"] == "notice"]
        self.assertEqual(notes[-1]["body"], "dummy 1.0.0 published, reload to load")
        self.assertIn(self.peer, notes[-1]["to_resolved"])
        self.assertFalse(os.path.exists(os.path.join(self.home, "_harness", "marketplace.prev")))

    def test_rebuild_sha_matches_accept(self):
        r = self.publish()
        self.assertEqual(H.bytes_sha(H.build_package(self.plug))[:12], r["pkg_sha"])

    def test_dry_run_writes_nothing(self):
        acc = self.accept_for(self.plug)
        n = self.n_events()
        r = self.h.publish_release(self.plug, accept=acc, build=True, dry_run=True)
        self.assertTrue(r["dry_run"])
        self.assertEqual(self.n_events(), n)
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "src", "dummy-1.0.0.plugin")))
        self.assertFalse(os.path.exists(os.path.join(self.home, "_harness", "marketplace")))
        self.assertEqual(self.h.registry(), {})

    def test_dry_run_with_override_logs_no_event(self):
        n = self.n_events()
        r = self.h.publish_release(self.plug, override="test", build=True, dry_run=True)
        self.assertTrue(r["dry_run"])
        self.assertEqual(self.n_events(), n)

    def test_marketplace_mismatch_aborts_cleanly(self):   # condition d
        n = self.n_events()
        orig = self.h._mkt_stage
        def bad(*a, **k):
            raise H.HarnessError("marketplace version/code != registry version")
        self.h._mkt_stage = bad
        with self.assertRaises(H.HarnessError):
            self.publish()
        self.h._mkt_stage = orig
        self.assertEqual(self.n_events(), n + 1)   # only the envoy ACCEPT message; no release, no notice
        self.assertEqual(self.h.registry(), {})
        self.assertFalse(os.path.exists(os.path.join(self.home, "_harness", "marketplace")))

    def test_ledger_failure_rolls_marketplace_back(self):
        self.publish()
        write(os.path.join(self.plug, "scripts", "a.py"), "print(2)\n")
        write(os.path.join(self.plug, ".claude-plugin", "plugin.json"), json.dumps({"name": "dummy", "version": "1.0.1"}))
        acc = self.accept_for(self.plug)
        real = self.h.store.append
        def boom(etype, *a, **k):
            if etype == "release.published":
                raise OSError("disk")
            return real(etype, *a, **k)
        self.h.store.append = boom
        with self.assertRaises(OSError):
            self.h.publish_release(self.plug, accept=acc, build=True)
        self.h.store.append = real
        mj = json.load(open(os.path.join(self.home, "_harness", "marketplace", ".claude-plugin", "marketplace.json")))
        self.assertEqual(mj["plugins"][0]["version"], "1.0.0")
        self.assertEqual(self.h.registry()["dummy"]["v"], "1.0.0")

    def test_pkg_sha_required_even_with_override(self):
        with self.assertRaises(H.HarnessError):
            self.h.publish_release(self.plug, override="no package")
        self.assertEqual(self.h.registry(), {})


class VerifyTests(Base):
    def test_verify_ok_then_each_mismatch(self):
        self.publish()
        self.assertTrue(self.h.verify_plugins()["ok"])
        mkt_json = os.path.join(self.home, "_harness", "marketplace", ".claude-plugin", "marketplace.json")
        good = open(mkt_json).read()
        j = json.loads(good); j["plugins"][0]["version"] = "0.9.0"
        write(mkt_json, json.dumps(j))
        v = self.h.verify_plugins()
        self.assertFalse(v["ok"]); self.assertIn("marketplace version", v["problems"][0])
        write(mkt_json, good)
        write(os.path.join(self.plug, "scripts", "a.py"), "print('drift')\n")   # S moved after publish (F)
        v = self.h.verify_plugins()
        self.assertFalse(v["ok"])
        self.assertTrue(any("source code" in p for p in v["problems"]))
        self.assertTrue(any("source tree" in p for p in v["problems"]))

    def test_package_replaced_by_hand_fails(self):
        self.publish()
        write(os.path.join(self.tmp, "src", "dummy-1.0.0.plugin"), "not the published bytes")
        v = self.h.verify_plugins()
        self.assertFalse(v["ok"]); self.assertTrue(any("pkg_sha" in p for p in v["problems"]))

    def test_cli_verify_exit_codes(self):
        self.publish()
        os.environ["HARNESS_HOME"] = self.home
        self.assertEqual(H.main(["--home", self.home, "verify", "--plugins-only"]) or 0, 0)
        write(os.path.join(self.plug, "scripts", "a.py"), "print('drift')\n")
        self.assertEqual(H.main(["--home", self.home, "verify", "--plugins-only"]), 1)

    def test_null_pkg_sha_fails(self):
        self.h.store.append("release.published", "human", {"name": "old", "kind": "plugin", "version": "1.0.0", "code": "ab",
                                                           "required": False, "path": self.plug, "pkg_sha": None})
        v = self.h.verify_plugins(only="old")
        self.assertFalse(v["ok"]); self.assertIn("pkg_sha is null", v["problems"][0])


class FlagTests(Base):
    def test_retired_ignored_and_external_never_required(self):
        self.publish()
        self.h.flag_release("dummy", retired=True, replaced_by="newer")
        self.assertTrue(self.h.registry()["dummy"]["retired"])
        self.assertEqual(self.h.registry()["dummy"]["replaced_by"], "newer")
        st = self.h.state()
        rows, worst = H.health_rows(st, self.peer, {}, True)
        self.assertEqual(rows, [])
        self.assertTrue(self.h.verify_plugins()["ok"])   # retired skipped
        self.h.flag_release("cowork-plugin-management", external=True)
        st = self.h.state()
        rows, worst = H.health_rows(st, self.peer, {}, True)
        self.assertEqual((rows, worst), ([], 0))
        rows, _ = H.health_rows(st, self.peer, {"cowork-plugin-management": {"v": "1", "code": "x"}}, True)
        self.assertIn("reg ext", rows[0][2])
        self.assertTrue(json.load(open(os.path.join(self.home, "_harness", "registry.json")))["cowork-plugin-management"]["external"])

    def test_bad_names_rejected(self):
        with self.assertRaises(H.HarnessError):
            self.h.flag_release("Bad Name", retired=True)

    def test_external_survives_republish(self):
        self.h.flag_release("dummy", external=True)
        self.publish()
        self.assertTrue(self.h.registry()["dummy"].get("external"))


class FleetAgeTests(unittest.TestCase):
    def st(self, age_h):
        now = 1_000_000.0
        reg = {"p": {"name": "p", "version": "2.0.0", "code": "bbbb", "t": now - age_h * 3600, "kind": "plugin"}}
        mk = lambda i, code: {"id": i, "status": "active", "last_seen": now, "inventory": {"p": {"v": "1.0.0", "code": code}}}
        agents = {"me": mk("me", "bbbb"), "x": mk("x", "aaaa")}
        return types.SimpleNamespace(registry=reg, agents=agents, now=now)

    def test_rolling_then_warning(self):
        inv = {"p": {"v": "2.0.0", "code": "bbbb"}}
        rows, worst = H.health_rows(self.st(1), "me", inv, True, 12, 6)
        self.assertIn("rolling 1h", rows[0][2]); self.assertEqual(worst, 0)
        rows, worst = H.health_rows(self.st(9), "me", inv, True, 12, 6)
        self.assertIn("▼1/2 9h", rows[0][2]); self.assertNotIn("rolling", rows[0][2]); self.assertEqual(worst, 1)

    def test_health_key_ignores_age_not_rolling(self):
        a, b = "● p 2.0 reg ✓ fleet ▼1/2 rolling 1h", "● p 2.0 reg ✓ fleet ▼1/2 rolling 2h"
        self.assertEqual(H.health_key(a), H.health_key(b))
        self.assertNotEqual(H.health_key(a), H.health_key("● p 2.0 reg ✓ fleet ▼1/2 7h"))


class RunningRowTests(Base):
    def test_install_rebuild_reload_lines(self):
        self.publish()
        st = self.h.state()
        L = H.drift_lines(st, self.peer, {"dummy": "0.9.0"}, "harness-local")
        self.assertTrue(L["flags"][0].startswith("install ▼ dummy 0.9.0 -> 1.0.0: claude plugin marketplace update harness-local"))
        self.assertIn("src=", L["lines"][0]); self.assertIn("installed=0.9.0", L["lines"][0])
        L = H.drift_lines(st, self.peer, {"dummy": "1.0.0"})
        self.assertEqual(L["flags"], [])
        write(os.path.join(self.plug, "scripts", "a.py"), "print('new')\n")
        L = H.drift_lines(st, self.peer, {"dummy": "1.0.0"})
        self.assertTrue(L["flags"][0].startswith("rebuild"))

    def test_installed_reader(self):
        p = os.path.join(self.tmp, "ip.json")
        write(p, json.dumps({"version": 2, "plugins": {"dummy@harness-local": [{"version": "1.0.0"}], "Bad;x@m": [{"version": "9"}]}}))
        self.assertEqual(H.installed_versions(p), {"dummy": "1.0.0"})
        self.assertEqual(H.installed_versions(os.path.join(self.tmp, "none.json")), {})


class UpgradeTests(Base):
    def shim(self, rc_for=None):
        d = os.path.join(self.tmp, "bin"); os.makedirs(d, exist_ok=True)
        log = os.path.join(self.tmp, "claude.log")
        sh = os.path.join(d, "claude")
        write(sh, '#!/bin/sh\necho "$@" >> "%s"\ncase "$*" in *"%s"*) exit 1;; esac\nexit 0\n' % (log, rc_for or "NEVERMATCH"))
        os.chmod(sh, os.stat(sh).st_mode | stat.S_IXUSR)
        self.addCleanup(lambda p=os.environ["PATH"]: os.environ.__setitem__("PATH", p))
        os.environ["PATH"] = d + os.pathsep + os.environ["PATH"]
        return log

    def test_nothing_behind(self):
        self.publish()
        p = self.h.upgrade_plan(installed={"dummy": "1.0.0"}, running={"dummy": "1.0.0"})
        self.assertEqual([i["action"] for i in p["plugins"]], ["current"])
        self.assertEqual((p["commands"], p["reload"]), ([], False))

    def test_one_behind(self):
        self.publish()
        p = self.h.upgrade_plan(installed={"dummy": "0.9.0"})
        self.assertEqual(p["plugins"][0]["action"], "update")
        self.assertEqual(p["commands"], [["claude", "plugin", "marketplace", "update", "harness-local"],
                                         ["claude", "plugin", "update", "dummy@harness-local"]])
        self.assertTrue(p["reload"])

    def test_installed_not_reloaded_is_reload_only(self):
        self.publish()
        p = self.h.upgrade_plan(installed={"dummy": "1.0.0"}, running={"dummy": "0.9.0"})
        self.assertEqual(p["plugins"][0]["action"], "reload")
        self.assertEqual(p["commands"], []); self.assertTrue(p["reload"])

    def test_bad_name_rejected(self):
        self.h.store.append("release.published", "human", {"name": "evil;rm -rf", "kind": "plugin", "version": "2", "code": "x",
                                                           "required": False, "path": "/nope", "pkg_sha": "ab" * 32})
        p = self.h.upgrade_plan(installed={})
        self.assertEqual(p["plugins"][0]["action"], "refused")
        self.assertEqual(p["commands"], [])

    def test_unapproved_plugin_refused(self):
        self.h.store.append("release.published", "human", {"name": "noacc", "kind": "plugin", "version": "2", "code": "x",
                                                           "required": False, "path": self.plug, "pkg_sha": "ab" * 32, "accept": None})
        p = self.h.upgrade_plan(installed={"noacc": "1"})
        self.assertEqual(p["plugins"][0]["action"], "refused")
        self.assertIn("ACCEPT", p["plugins"][0]["reason"])
        self.assertEqual(p["commands"], [])

    def test_null_pkg_sha_refused(self):
        self.h.store.append("release.published", "human", {"name": "nopkg", "kind": "plugin", "version": "2", "code": "x",
                                                           "required": False, "path": self.plug, "pkg_sha": None})
        p = self.h.upgrade_plan(installed={})
        self.assertIn("pkg_sha", p["plugins"][0]["reason"])

    def test_publications_ordered_last(self):
        for n in ("plugin-publications", "aaa"):
            r = mk_plugin(self.tmp, n)
            self.publish(r)
        p = self.h.upgrade_plan(installed={})
        self.assertEqual(p["commands"][-1][-1], "plugin-publications@harness-local")

    def test_run_with_shim_and_failure_stops(self):
        self.publish(mk_plugin(self.tmp, "aaa"))
        self.publish(mk_plugin(self.tmp, "bbb"))
        log = self.shim()
        plan = self.h.upgrade_plan(installed={})
        r = H.run_upgrade(plan)
        self.assertTrue(r["ok"]); self.assertEqual(r["mode"], "run")
        self.assertEqual(len(open(log).read().splitlines()), 1 + 3)   # auth status + marketplace update + 2 updates
        os.remove(log)
        self.shim(rc_for="update aaa")
        r = H.run_upgrade(plan)
        self.assertFalse(r["ok"]); self.assertFalse(r["reload"])
        self.assertNotIn("bbb", open(log).read())

    def test_dry_run_and_no_cli_print_block(self):
        self.publish()
        plan = self.h.upgrade_plan(installed={})
        r = H.run_upgrade(plan, dry_run=True)
        self.assertEqual(r["mode"], "print"); self.assertIn("claude plugin update dummy@harness-local", r["block"])
        r = H.run_upgrade(plan, which=lambda n: None)
        self.assertEqual(r["mode"], "print")

    def test_probe_failure_falls_back_to_print_and_runs_nothing(self):
        self.publish()
        plan = self.h.upgrade_plan(installed={})
        calls = []
        def runner(argv):
            calls.append(argv)
            return types.SimpleNamespace(returncode=1 if argv[:3] == ["claude", "auth", "status"] else 0)
        r = H.run_upgrade(plan, which=lambda n: "/usr/bin/claude", runner=runner)
        self.assertEqual((r["mode"], r["ok"], r["ran"]), ("print", True, []))
        self.assertIn("not logged in", r["why"])
        self.assertEqual(calls, [["claude", "auth", "status"]])   # only the probe ran, no install command


class NoticeAndVerifyNoteTests(Base):
    def test_notice_one_short_line_to_live_agents_only(self):
        r = self.publish()
        notes = [m for m in self.h.state().messages.values() if m["kind"] == "notice"]
        self.assertEqual(len(notes[-1]["body"].splitlines()), 1)
        self.assertLessEqual(len(notes[-1]["body"]) // 4 + 1, 40)   # <=40 tokens, 4 chars/token
        self.assertNotIn("group:all", notes[-1]["to"])

    def test_stale_agent_gets_no_notice(self):
        st = self.h.state()
        st.agents[self.peer]["last_seen"] = st.now - 48 * 3600
        live = H.live_peers(st, None, 12)
        self.assertNotIn(self.peer, [a["id"] for a in live])

    def test_verify_not_yet_published_is_not_a_failure(self):
        self.publish()
        shutil.rmtree(os.path.join(self.home, "_harness", "marketplace"))
        v = self.h.verify_plugins()
        self.assertTrue(v["ok"], v)
        self.assertIn("not yet published to the marketplace", v["notes"][0])


if __name__ == "__main__":
    unittest.main()
