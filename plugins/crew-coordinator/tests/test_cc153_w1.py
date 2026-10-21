"""cc 0.15.3 Wave 1: project-folder resolver (E), registry path portability (D), brief_hosts (C), robustness (A / P7).
Run: python3 -B tests/test_cc153_w1.py"""
import hashlib, io, json, os, sys, tempfile, unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
import harness as H
import mcp_server as M
import ctx_hook as C
import hash_vectors as HV
import inbox_ladder as IL
from test_cc151_w1 import Base
from test_release_gates import mkzip


def mkdir(*p):
    d = os.path.join(*p)
    os.makedirs(d, exist_ok=True)
    return d


class Resolver(Base):
    def setUp(self):
        super().setUp()
        self.ops = os.path.join(self.tmp, "ops")
        self._e = mock.patch.dict(os.environ, {"HARNESS_OPS_ROOT": "", "HOME": self.tmp})
        self._e.start()
        self.addCleanup(self._e.stop)
        os.environ.pop("HARNESS_OPS_ROOT", None)

    def alias(self, root, **extra):
        mkdir(root, "_alias")
        with open(os.path.join(root, "_alias", "alias-map.json"), "w") as f:
            json.dump({"project_aliases": {"orchestration": "harness-ops", "skill-curation": "harness-ops"}, **extra}, f)

    def test_none_names_every_path_tried(self):
        with self.assertRaisesRegex(H.HarnessError, "legacy=.*projects.orchestration"):
            H.project_dir(self.home, "orchestration")

    def test_legacy_only(self):
        d = mkdir(self.home, "projects", "orchestration")
        self.assertEqual(H.project_dir(self.home, "orchestration"), d)

    def test_alias_map_used_when_legacy_absent(self):
        os.environ["HARNESS_OPS_ROOT"] = self.ops
        # explicit env but folder missing there and no legacy: fall through to alias candidate (also under ops)
        new = mkdir(self.ops, "projects", "orchestration")
        self.alias(self.ops)
        self.assertEqual(H.project_dir(self.home, "orchestration"), new)

    def test_alias_map_discovered_default_root(self):
        default = os.path.join(self.tmp, "Claude", "Code", "harness-ops")   # HOME is the temp dir
        new = mkdir(default, "projects", "skill-curation")
        self.alias(default)
        self.assertEqual(H.project_dir(self.home, "skill-curation"), new)

    def test_both_trees_legacy_wins_unless_env_explicit(self):
        old = mkdir(self.home, "projects", "orchestration")
        new = mkdir(self.ops, "projects", "orchestration")
        self.alias(self.ops)
        os.environ["HARNESS_OPS_ROOT"] = self.ops + "-not-yet"
        self.assertEqual(H.project_dir(self.home, "orchestration"), old)
        os.environ["HARNESS_OPS_ROOT"] = self.ops
        self.assertEqual(H.project_dir(self.home, "orchestration"), new)

    def test_project_roots_from_operator_file_wins(self):
        mkdir(self.home, "projects", "orchestration")
        elsewhere = mkdir(self.tmp, "elsewhere", "orchestration")
        opf = os.path.join(self.tmp, "operator.json")
        with open(opf, "w") as f:
            json.dump({"project_roots": {"orchestration": elsewhere}}, f)
        os.chmod(opf, 0o600)
        with mock.patch.object(H, "OPERATOR_FILE", opf):
            self.assertEqual(H.project_dir(self.home, "orchestration"), elsewhere)

    def test_project_roots_in_agent_writable_config_outside_ceiling_ignored(self):
        mkdir(self.home, "_harness")
        evil = mkdir(self.tmp, "evil", "orchestration")
        with open(os.path.join(self.home, "_harness", "config.json"), "w") as f:
            json.dump({"project_roots": {"orchestration": evil}}, f)
        old = mkdir(self.home, "projects", "orchestration")
        self.assertEqual(H.project_dir(self.home, "orchestration"), old)
        self.assertTrue(any("project_roots" in w for w in H.path_config(self.home)["warnings"]))

    def test_slug_traversal_refused(self):
        for bad in ("../x", "a/b", "", "."):
            with self.assertRaises(H.HarnessError):
                H.project_dir(self.home, bad)

    def test_old_tree_absent_simulated_r6(self):
        # R6: Exchange/projects/orchestration gone; folder only under harness-ops. corpus_index path and roles resolve.
        new = mkdir(self.ops, "projects", "orchestration", "scripts")
        with open(os.path.join(new, "corpus_index.py"), "w") as f:
            f.write("# stub\n")
        os.environ["HARNESS_OPS_ROOT"] = self.ops
        self.assertEqual(self.h._ci_script(), os.path.join(self.ops, "projects", "orchestration", "scripts", "corpus_index.py"))
        mkdir(self.ops, "projects", "orchestration")
        with open(os.path.join(self.ops, "projects", "orchestration", "ROLES.md"), "w") as f:
            f.write("## orchestration\n| role | carry |\n|---|---|\n| corpus-envoy | none |\n")
        self.assertIn("corpus-envoy", self.h.defined_roles(self.h.state(), "orchestration"))

    def test_capsule_path_is_canonical_outside_home(self):
        os.environ["HARNESS_OPS_ROOT"] = self.ops
        hd = mkdir(self.ops, "projects", "orchestration", "handoffs")
        p = os.path.join(hd, "2026-10-14-x.md")
        open(p, "w").write("---\nstatus: open\n---\n")
        rel = self.h._canon_rel(p)
        self.assertEqual(rel, "projects/orchestration/handoffs/2026-10-14-x.md")
        self.assertEqual(self.h._home_file(rel, "capsule"), os.path.realpath(p))
        with self.assertRaises(H.HarnessError):   # '..' cannot leave the project folder
            self.h._home_file("projects/orchestration/../../x.md", "capsule")

    def test_handoff_writes_to_resolved_tree(self):
        os.environ["HARNESS_OPS_ROOT"] = self.ops
        mkdir(self.ops, "projects", "orch")
        a = self.agent(project="orch")
        r = self.h.handoff(a, "# capsule\nsmall body", None, False, None)
        self.assertTrue(any(os.path.isfile(os.path.join(self.ops, "projects", "orch", "handoffs", n))
                            for n in os.listdir(os.path.join(self.ops, "projects", "orch", "handoffs"))))
        self.assertFalse(os.path.isdir(os.path.join(self.home, "projects", "orch")))

    def test_explicit_role_validates_against_original_project(self):
        # envoy is defined under 'orchestration'; the project is aliased to harness-ops. A record with role=corpus-envoy
        # from an agent registered under orchestration must still be accepted.
        mkdir(self.home, "_harness")
        with open(os.path.join(self.home, "_harness", "project-aliases.json"), "w") as f:
            json.dump({"aliases": {"orchestration": "harness-ops"}}, f)
        self.h.role_define("operator", "corpus-envoy", "orchestration")
        a = self.h.register(project="orchestration", model="claude-sonnet-5-5")["id"]
        self.h.role_assign("operator", "corpus-envoy", a)
        r = self.h.record(a, "note", "n", "body text here", role="corpus-envoy")
        self.assertTrue(r["id"])


class RegistryPaths(unittest.TestCase):
    def test_portable_and_legacy_mapping(self):
        self.assertEqual(H.portable_source_path("/sessions/rcw-abc/mnt/Harness_Router/crew-coordinator"), "Harness_Router/crew-coordinator")
        self.assertEqual(H.portable_source_path("/Users/x/Claude/Projects/Exchange/skills/a"), "Exchange/skills/a")
        self.assertEqual(H.portable_source_path("/Users/x/Claude/Code/harness-ops/harness-hub/pixel-pilot"), "harness-hub/pixel-pilot")
        self.assertEqual(H.portable_source_path("/somewhere/else/pkg"), "/somewhere/else/pkg")

    def test_resolve_across_sandboxes_and_names(self):
        tmp = tempfile.mkdtemp()
        home = mkdir(tmp, "Exchange")
        hub = mkdir(tmp, "harness-hub", "dummy")
        self.assertEqual(H.resolve_source_path("Harness_Router/dummy", home), hub)                       # old name, new folder
        self.assertEqual(H.resolve_source_path("/sessions/rcw-1/mnt/Harness_Router/dummy", home), hub)   # legacy sandbox
        self.assertEqual(H.resolve_source_path("harness-hub/dummy", home), hub)
        self.assertEqual(H.resolve_source_path("Harness_Router/missing", home), "Harness_Router/missing")

    def _publish(self, tmp, folder):
        home = mkdir(tmp, "Exchange")
        h = H.Harness(home)
        h.role_define("operator", "corpus-envoy", "orch")
        env = h.register(project="orch", model="claude-opus-5-5")["id"]
        h.role_assign("operator", "corpus-envoy", env)
        plug = mkdir(tmp, folder, "dummy", ".claude-plugin")
        with open(os.path.join(plug, "plugin.json"), "w") as f:
            json.dump({"name": "dummy", "version": "1.0.0"}, f)
        src = os.path.dirname(plug)
        pkg = os.path.join(os.path.dirname(src), "dummy-1.0.0.plugin")
        mkzip(pkg, src)
        sha = hashlib.sha256(open(pkg, "rb").read()).hexdigest()
        m = h.send(env, "operator", f"ACCEPT sha={sha[:12]}")["id"]
        h.publish_release(src, pkg=pkg, accept=m)
        return h

    def test_publish_stores_relative_path_and_verify_survives_rename(self):
        tmp = tempfile.mkdtemp()
        h = self._publish(tmp, "Harness_Router")
        self.assertEqual(h.state().registry["dummy"]["path"], "Harness_Router/dummy")
        self.assertNotIn("source path missing", json.dumps(h.verify_plugins()))
        os.rename(os.path.join(tmp, "Harness_Router"), os.path.join(tmp, "harness-hub"))   # R3 rename
        v = h.verify_plugins()
        self.assertNotIn("source path missing", json.dumps(v))

    def test_verify_skips_renamed_and_replaced_as_notes(self):
        tmp = tempfile.mkdtemp()
        h = self._publish(tmp, "Harness_Router")
        h.flag_release("dummy", retired=True, replaced_by="other-plugin")
        v = h.verify_plugins()
        self.assertTrue(v["ok"])
        self.assertTrue(any("dummy: skipped (replaced by other-plugin)" in n for n in v.get("notes", [])))


class BriefHosts(Base):
    def test_config_json_brief_hosts_ignored(self):
        mkdir(self.home, "_harness")
        with open(os.path.join(self.home, "_harness", "config.json"), "w") as f:
            json.dump({"brief_hosts": ["evil.example"]}, f)
        pc = H.path_config(self.home)
        self.assertNotIn("evil.example", pc["brief_hosts"])
        self.assertTrue(any("brief_hosts in config.json ignored" in w for w in pc["warnings"]))

    def test_operator_json_brief_hosts_accepted(self):
        opf = os.path.join(self.tmp, "operator.json")
        with open(opf, "w") as f:
            json.dump({"brief_hosts": ["Example.org"]}, f)
        os.chmod(opf, 0o600)
        with mock.patch.object(H, "OPERATOR_FILE", opf):
            self.assertIn("example.org", H.path_config(self.home)["brief_hosts"])


class Robustness(Base):
    def test_non_dict_ledger_lines_do_not_break_commands(self):
        a = self.agent()
        with open(self.h.store.log, "a", encoding="utf-8") as f:
            f.write("null\n7\n[1,2]\n\"str\"\n{\"type\":\"_corrupt\",\"seq\":3}\n")
        evs = self.h.store.read_all()
        self.assertEqual(sum(1 for e in evs if e.get("type") == "_corrupt"), 5)
        self.assertEqual(self.h.state().agents[a]["id"] if "id" in self.h.state().agents[a] else a, a)
        v = self.h.verify()
        self.assertFalse(v["ok"])
        self.assertEqual(len([p for p in v["problems"] if p.get("problem") == "unparseable line"]), 5)

    def test_hash_vectors_corrupt_label_is_not_an_exemption_and_malformed_line_counts(self):
        good = {"v": 1, "seq": 1, "type": "t", "actor": "a", "data": {}, "prev": "0"}
        good["hash"] = HV.event_hash(good)
        tampered = dict(good, type="_corrupt")
        ok, n, bad = HV.check_events([good, tampered, {"_unparseable": True}, 7])
        self.assertEqual((ok, n), (1, 4))
        self.assertEqual(len(bad), 3)
        p = os.path.join(self.tmp, "e.jsonl")
        with open(p, "w") as f:
            f.write(json.dumps(good) + "\nnot json\n")
        self.assertEqual(HV.main(["--log", p]), 1)

    def test_retire_is_idempotent_and_flags_lease_release(self):
        a = self.agent()
        r1 = self.h.retire(a, "done", by=a)
        r2 = self.h.retire(a, "again", by=a)
        self.assertTrue(r2.get("already"))
        self.assertEqual(len(self.types("agent.retired")), 1)

    def test_multi_claim_rolls_back_on_refusal(self):
        a, b = self.agent(), self.agent()
        self.h.claim(b, "held.md")
        r = self.h.claim(a, ["free.md", "held.md"])
        self.assertTrue(all(not c["granted"] for c in r["claims"]))
        self.assertEqual([k for k, L in self.h.state().leases.items() if L["holder"] == a], [])
        self.assertTrue(self.h.claim(a, "free.md")["granted"])

    def test_multi_claim_validates_before_first_lease(self):
        a = self.agent()
        with self.assertRaises(H.HarnessError):
            self.h.claim(a, ["ok.md", ".DS_Store"])
        self.assertEqual([k for k, L in self.h.state().leases.items() if L["holder"] == a], [])

    def test_handoff_lease_checked_before_write(self):
        a, b = self.agent(project="orch"), self.agent(project="orch")
        d = mkdir(self.home, "projects", "orch", "handoffs")
        cap = os.path.join(d, "2026-10-14-x.md")
        txt = "---\nstatus: open\nfrom: x #aaaa1111\n---\n# cap\nbody\n"
        open(cap, "w").write(txt)
        self.h.claim(b, "projects/orch/handoffs/2026-10-14-x.md")
        with self.assertRaisesRegex(H.HarnessError, "nothing was written"):
            self.h.handoff(a, "projects/orch/handoffs/2026-10-14-x.md", None, False, "state note")
        self.assertEqual(open(cap).read(), txt)

    def test_mkt_swap_restores_live_tree_when_second_rename_fails(self):
        live = self.h._mkt_dir()
        os.makedirs(live, exist_ok=True)
        open(os.path.join(live, "keep"), "w").write("x")
        stage = os.path.join(self.tmp, "stage-missing")   # rename(stage, live) fails
        with self.assertRaises(OSError):
            self.h._mkt_swap(stage)
        self.assertTrue(os.path.isfile(os.path.join(live, "keep")))

    def test_inbox_limit_and_wait_clamped(self):
        a = self.agent()
        self.assertEqual(M.call(self.h, "harness_inbox", {"agent": a, "limit": -5, "wait": "x"}) is not None, True)
        self.assertEqual(M._bounded_int(-1, 1, 200, 20), 1)
        self.assertEqual(M._bounded_int("junk", 30, 86400, 900), 900)
        self.assertEqual(M._bounded_int(10**9, 0, 60, 0), 60)

    def test_send_dedupe_within_window(self):
        a = self.agent()
        M.SEND_SEEN.clear()
        r1 = M.call(self.h, "harness_send", {"agent": a, "to": "operator", "body": "once", "subject": "s"})
        n = len(self.types("message.sent"))
        r2 = M.call(self.h, "harness_send", {"agent": a, "to": "operator", "body": "once", "subject": "s"})
        self.assertEqual(len(self.types("message.sent")), n)
        self.assertTrue(r2.get("deduped"))

    def test_jsonrpc_garbage_gets_replies(self):
        inp = io.StringIO('{bad json\n[1,2]\n{"jsonrpc":"2.0","id":true,"method":"ping"}\n{"jsonrpc":"2.0","id":4,"method":"ping"}\n')
        out = io.StringIO()
        with mock.patch.object(sys, "stdin", inp):
            M.serve_loop(self.h, None, out)
        lines = [json.loads(l) for l in out.getvalue().splitlines()]
        self.assertEqual([l.get("error", {}).get("code") for l in lines], [-32700, -32600, -32600, None])
        self.assertEqual(lines[-1]["id"], 4)

    def test_ctx_hook_band_resets_after_compact(self):
        state = tempfile.mkdtemp()
        with mock.patch.dict(os.environ, {"CLAUDE_CODE_SESSION_ID": "s1"}), \
                mock.patch.object(C, "state_dir", lambda: state), \
                mock.patch.object(C, "last_usage", lambda p: (10_000, "claude-sonnet-5-5")):
            mark = C.state_path("harness-ctx-" + C._sid({"session_id": "s1"}))
            C.write_state(mark, "now")
            C.gauge({"session_id": "s1"}, "x")
            self.assertEqual(C.read_state(mark).strip(), "")

    def test_ladder_caps_rungs(self):
        r = IL.parse_ladder("5,999999,1,1,1,1,1,1,1,1")
        self.assertLessEqual(len(r), 8)
        self.assertLessEqual(max(r), 600)


if __name__ == "__main__":
    unittest.main()
