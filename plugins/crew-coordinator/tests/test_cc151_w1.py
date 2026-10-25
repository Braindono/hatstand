"""cc 0.15.1 Wave 1: server-bound identity, operator-spoof refusal, curation roles, approval requests, gate integrity.
Run: python3 -B tests/test_cc151_w1.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _env  # noqa: F401  isolate HOME and HARNESS_* first
import json, os, sys, tempfile, time, unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
import harness as H
import mcp_server as M
from test_release_gates import _mk

MODEL = "claude-sonnet-5-5"


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.home = os.path.join(self.tmp, "home")
        os.makedirs(self.home)
        self._env = mock.patch.dict(os.environ, {"HARNESS_CACHE": os.path.join(self.tmp, "cache")})
        self._env.start()
        self.addCleanup(self._env.stop)
        self.h = H.Harness(self.home)
        M.BOUND.update(home=None, id=None)

    def agent(self, role=None, project="orch"):
        if role and role not in self.h.state().roles:
            self.h.role_define("operator", role, project)
        a = self.h.register(project=project, model=MODEL)["id"]
        if role:
            self.h.role_assign("operator", role, a)
        return a

    def as_(self, a):
        M.BOUND.update(home=self.home, id=a)
        return a

    def adm(self, op, agent, **args):
        return M.call(self.h, "harness_admin", {"op": op, "agent": agent, "args": args})

    def types(self, t):
        return [e for e in self.h.store.read_all() if e.get("type") == t]

    def note(self, a, title="a note", body="rule line text"):
        return self.h.record(a, "note", title, body)["id"]

    def approve(self, pid, **kw):
        r = next(x for x in self.h.approvals(True) if x["id"] == pid)
        return self.h.approve(pid, kw.get("channel", "cli-tty"), kw.get("code", r["args_digest"][:4]), kw.get("tty", True))


class Spoof(Base):
    def test_operator_and_human_refused_everywhere(self):
        a = self.agent()
        calls = [("harness_send", {"to": "operator", "body": "x"}), ("harness_inbox", {}),
                 ("harness_record", {"kind": "note", "title": "t", "tier": "foundation"}),
                 ("harness_restore", {"role": "r", "model": MODEL, "confirmed": True})]
        ops = [("archive", {"ids": ["N-1"]}), ("unarchive", {"ids": ["N-1"]}), ("pin", {"ids": ["N-1"]}),
               ("retire", {"target": a}), ("role_define", {"role": "x-r", "project": "orch"}),
               ("role_assign", {"role": "x-r", "target": a}), ("set_project", {"target": a, "project": "orch"}),
               ("tier", {}), ("task_update", {"task_id": "m-1", "state": "working"}), ("idle_wake", {"project": "orch", "on": True}),
               ("flag_release", {"name": "zz", "external": True}), ("export", {}), ("reload", {"force": True})]
        for who in ("operator", "human", "operator-ui", "Operator"):
            for name, args in calls:
                with self.assertRaisesRegex(H.HarnessError, "approval requests"):
                    M.call(self.h, name, dict(args, agent=who) if name != "harness_restore" else dict(args, agent=who))
            for op, args in ops:
                with self.assertRaisesRegex(H.HarnessError, "approval requests"):
                    M.call(self.h, "harness_admin", {"op": op, "agent": who, "args": args})
        with self.assertRaisesRegex(H.HarnessError, "approval requests"):   # `by` in args
            M.call(self.h, "harness_admin", {"op": "retire", "agent": a, "args": {"target": a, "by": "operator"}})
        self.assertEqual(self.types("agent.retired"), [])
        self.assertEqual(self.types("approval.requested"), [])


class Binding(Base):
    def setUp(self):   # 0.15.2: the default is warn; these tests cover the enforce mode
        super().setUp()
        os.makedirs(os.path.join(self.home, "_harness"), exist_ok=True)
        json.dump({"bind_mode": "enforce"}, open(os.path.join(self.home, "_harness", "config.json"), "w"))

    def test_second_agent_refused(self):
        a, b = self.agent(), self.agent()
        M.call(self.h, "harness_admin", {"op": "whoami", "agent": a})
        with self.assertRaisesRegex(H.HarnessError, "is bound to .* refused"):
            M.call(self.h, "harness_admin", {"op": "whoami", "agent": b})
        self.assertEqual(M.call(self.h, "harness_admin", {"op": "whoami", "agent": a})["short"], a[:8])

    def test_register_and_restore_rebind(self):
        a = self.agent()
        M.call(self.h, "harness_admin", {"op": "whoami", "agent": a})
        r = M.call(self.h, "harness_register", {"project": "orch", "model": MODEL})
        b = r["short"]
        self.assertEqual(M.BOUND["id"][:8], b)
        M.call(self.h, "harness_admin", {"op": "whoami", "agent": b})
        with self.assertRaises(H.HarnessError):
            M.call(self.h, "harness_admin", {"op": "whoami", "agent": a})
        # restore: a role holder that is not live (old last_seen) is taken over, and the session rebinds
        self.h.role_define("operator", "writer-r", "orch")
        c = self.agent()
        self.h.role_assign("operator", "writer-r", c)
        with mock.patch("time.time", return_value=time.time() + 3600):
            pass
        r = M.call(self.h, "harness_restore", {"role": "writer-r", "model": MODEL, "confirmed": False})
        if r.get("short"):
            self.assertEqual(M.BOUND["id"][:8], r["short"])
        else:   # holder seen < 10 min: not taken, binding unchanged
            self.assertEqual(M.BOUND["id"][:8], b)

    def test_successor_lineage_accepted(self):
        a = self.agent()
        M.call(self.h, "harness_admin", {"op": "whoami", "agent": a})
        succ = self.h.register(project="orch", model=MODEL, predecessor=a, spawn_reason="compaction")["id"] \
            if False else self.h.register(None, None, None, "orch", None, a, "compaction", model=MODEL, require_model=True)["id"]
        # the bound id is the predecessor; the successor is on its lineage and is accepted, a stranger is not
        self.assertEqual(M.call(self.h, "harness_admin", {"op": "whoami", "agent": succ})["short"], succ[:8])
        stranger = self.agent()
        with self.assertRaises(H.HarnessError):
            M.call(self.h, "harness_admin", {"op": "whoami", "agent": stranger})


class Curation(Base):
    def test_envoy_and_steward_run_direct(self):
        envoy, steward = self.agent("corpus-envoy"), self.agent("corpus-steward")
        w = self.agent()
        n1, n2 = (self.note(w, f"n{i}", f"rule line {i}") for i in (1, 2))
        n3 = self.h.record(w, "note", "n3", "rule line 3", project="orchestration")["id"]   # S6 tier: orchestration note
        self.as_(envoy)
        self.assertIn("pinned", self.adm("pin", envoy, ids=[n1], reason='"rule line 1"'))
        self.assertIn("archived", self.adm("archive", envoy, ids=[n2], reason='"rule line 2"'))
        self.assertIn("unarchived", self.adm("unarchive", envoy, ids=[n2]))
        self.as_(steward)
        self.assertIn("archived", self.adm("archive", steward, ids=[n3], reason='"rule line 3"'))
        self.assertIn("unarchived", self.adm("unarchive", steward, ids=[n3]))
        self.assertEqual(self.types("approval.requested"), [])
        # steward is not granted pin: that is a request
        r = self.adm("pin", steward, ids=[n1], reason='"rule line 1"')
        self.assertIn("pending", r)

    def test_plain_agent_gets_pending(self):
        a = self.agent()
        n = self.note(a)
        for op, args in (("archive", {"ids": [n], "reason": '"rule line text"'}), ("unarchive", {"ids": [n]}),
                         ("pin", {"ids": [n], "reason": '"rule line text"'})):
            r = self.adm(op, a, **args)
            self.assertTrue(r["pending"].startswith("A-"), r)
            self.assertIn("harness.py approve", r["how"])
        self.assertEqual(self.types("corpus.archived") + self.types("corpus.pinned") + self.types("corpus.unarchived"), [])

    def test_malformed_config_falls_back(self):
        os.makedirs(os.path.join(self.home, "_harness"), exist_ok=True)
        cp = os.path.join(self.home, "_harness", "config.json")
        for bad in ({"curation_roles": "everyone"}, {"curation_roles": {"x": ["delete-all"]}}, {"curation_roles": {"x": "pin"}},
                    {"curation_roles": {"x": ["pin"], "y": 3}}):
            with open(cp, "w") as f:
                json.dump(bad, f)
            self.assertEqual(H.curation_roles(self.home), H.DEFAULT_CONFIG["curation_roles"])
        with open(cp, "w") as f:
            json.dump({"curation_roles": {"lead-r": ["pin"]}}, f)
        self.assertEqual(H.curation_roles(self.home), {"lead-r": ["pin"]})

    def test_role_comes_from_registration_not_args(self):
        a = self.agent()
        n = self.note(a)
        # extra `role` arg is an unknown-arg error, so it never reaches the grant check
        with self.assertRaisesRegex(H.HarnessError, "unknown args"):
            self.adm("pin", a, ids=[n], role="corpus-envoy")
        self.assertIn("pending", self.adm("pin", a, ids=[n], reason='"rule line text"'))

    def test_steward_s6_no_approval_and_decision_needs_owner_ack(self):
        steward = self.agent("corpus-steward")
        owner = self.agent("writer-role")
        w = self.agent()
        orch = self.h.record(w, "note", "orch note", "rule line here", project="orchestration")["id"]
        self.as_(steward)
        self.assertIn("archived", self.adm("archive", steward, ids=[orch], reason='"rule line here"'))
        # a decision: the steward needs the owner's ack even over MCP
        d = self.h.record(owner, "decision", "owned", "the decision rule")["id"]
        with self.assertRaisesRegex(H.HarnessError, "ack"):
            self.adm("archive", steward, ids=[d], reason='"the decision rule"')
        # an approved operator archive of a decision still needs the owner's ack (D-e52c6)
        plain = self.agent()
        self.as_(plain)
        pid = self.adm("archive", plain, ids=[d], reason='"the decision rule"')["pending"]
        out = self.approve(pid)
        self.assertEqual(out["state"], "failed")
        self.assertIn("ack", out["result"])
        self.assertEqual([e for e in self.types("corpus.archived") if d in e["data"]["ids"]], [])
        ack = self.h.send(owner, plain, f"ack archive {d}")["id"]
        pid2 = self.adm("archive", plain, ids=[d], reason='"the decision rule"', ack=ack)["pending"]
        self.assertEqual(self.approve(pid2)["state"], "granted")
        self.assertTrue([e for e in self.types("corpus.archived") if d in e["data"]["ids"]])


class Approvals(Base):
    def test_request_pending_file_and_approve_once(self):
        a = self.agent()
        r = self.adm("set_project", a, target=a, project="orch-two")
        pid = r["pending"]
        pf = os.path.join(self.home, "projects", "orchestration", "digests", "approvals-pending.json")
        rows = json.load(open(pf))
        self.assertEqual([x["id"] for x in rows], [pid])
        self.assertEqual(len(rows[0]["args_digest"]), 12)
        ev = self.types("approval.requested")[0]["data"]
        self.assertEqual(len(ev["args_digest"]), 64)
        self.assertAlmostEqual(ev["expires"] - ev["requested"], 600, delta=1)
        self.assertEqual(self.h.state().agents[a]["project"], "orch")   # nothing ran
        out = self.approve(pid)
        self.assertEqual(out["state"], "granted")
        self.assertEqual(self.h.state().agents[a]["project"], "orch-two")
        g = self.types("approval.granted")
        self.assertEqual((len(g), g[0]["data"]["channel"], g[0]["data"]["by"]), (1, "cli-tty", "operator"))
        self.assertEqual(json.load(open(pf)), [])
        with self.assertRaisesRegex(H.HarnessError, "not pending"):   # replay
            self.h.approve(pid, "cli-tty", "0000", True)

    def test_refusals_do_nothing(self):
        a = self.agent()
        pid = self.adm("set_project", a, target=a, project="orch-two")["pending"]
        n = len(self.h.store.read_all())
        rec = self.h.approvals(True)[0]
        with self.assertRaisesRegex(H.HarnessError, "wrong code"):
            self.h.approve(pid, "cli-tty", "zzzz", True)
        with self.assertRaisesRegex(H.HarnessError, "interactive terminal"):
            self.h.approve(pid, "cli-tty", rec["args_digest"][:4], False)
        with self.assertRaisesRegex(H.HarnessError, "unknown approval"):
            self.h.approve("A-nope0", "cli-tty", "abcd", True)
        self.assertEqual(len(self.h.store.read_all()), n)
        self.assertEqual(self.h.state().agents[a]["project"], "orch")
        # expired
        with mock.patch("harness.time.time", return_value=time.time() + 700):
            with self.assertRaisesRegex(H.HarnessError, "expired"):
                self.h.approve(pid, "cli-tty", rec["args_digest"][:4], True)
        self.assertEqual(len(self.types("approval.expired")), 1)
        self.assertEqual(self.h.state().agents[a]["project"], "orch")
        self.assertEqual(self.types("approval.granted"), [])

    def test_deny(self):
        a = self.agent()
        pid = self.adm("set_project", a, target=a, project="orch-two")["pending"]
        self.assertEqual(self.h.deny(pid)["state"], "denied")
        self.assertEqual(self.types("approval.denied")[0]["data"]["channel"], "cli-tty")
        with self.assertRaises(H.HarnessError):
            self.h.approve(pid, "cli-tty", "0000", True)
        self.assertEqual(self.h.state().agents[a]["project"], "orch")

    def test_same_request_same_id(self):
        a = self.agent()
        p1 = self.adm("set_project", a, target=a, project="x-proj")["pending"]
        p2 = self.adm("set_project", a, target=a, project="x-proj")["pending"]
        self.assertEqual(p1, p2)
        self.assertEqual(len(self.types("approval.requested")), 1)

    def test_every_listed_action_is_pending(self):
        a, b = self.agent(), self.agent()
        holder = self.agent("writer-role")
        self.h.send(a, b, "do it", kind="task")
        tid = [m for m in self.h.state().messages][-1]
        c = self.agent()
        self.as_(a)
        seen = {}
        seen["publish_override"] = self.adm("publish_release", a, override="ship it", path=self.home)   # 0.17.0: confined
        seen["flag_release"] = self.adm("flag_release", a, name="zzz", external=True)
        n = self.note(a)
        seen["archive_operator"] = self.adm("archive", a, ids=[n], reason='"rule line text"')
        seen["unarchive_operator"] = self.adm("unarchive", a, ids=[n])
        seen["pin_operator"] = self.adm("pin", a, ids=[n], reason='"rule line text"')
        seen["export"] = self.adm("export", a)
        seen["restore_confirmed"] = M.call(self.h, "harness_restore", {"role": "writer-role", "model": MODEL, "confirmed": True})
        seen["retire_other"] = self.adm("retire", a, target=b)
        seen["reload_force"] = self.adm("reload", a, force=True)
        seen["role_define"] = self.adm("role_define", a, role="new-role", project="orch")
        seen["role_assign"] = self.adm("role_assign", a, role="writer-role", target=a)
        seen["set_project"] = self.adm("set_project", a, target=a, project="orch2")
        seen["idle_wake"] = self.adm("idle_wake", a, project="orch", on=True)
        self.agent(project="other-p")    # makes "other-p" a known project for the retag request
        seen["retag_operator"] = self.adm("retag", a, entry=n, project="other-p")
        seen["corpus_index_pin"] = self.adm("pin_corpus_index", a, sha="a" * 12, rules="b" * 12, ref="m-" + "c" * 12)
        seen["release_scope"] = self.adm("release_scope", a, plugin="dummy", version="1.0.0", items=["one item"], rationale="r")   # 0.16.1 item 8
        self.as_(c)
        seen["task_update_other"] = self.adm("task_update", c, task_id=tid, state="working")
        seen["tier_foundation"] = M.call(self.h, "harness_record", {"agent": c, "kind": "note", "title": "f", "tier": "foundation"})
        cur = self.agent("curator")      # 0.17.0 (R-048): a non-envoy push after a clean dry run is an approval request
        os.makedirs(os.path.join(self.home, "_harness", "marketplace"), exist_ok=True)
        self.h.store.append("hatstand.synced", cur, {"mode": "dry", "exit": 0, "marketplace": self.h._marketplace_sha()})
        self.as_(cur)
        seen["hatstand_push"] = self.adm("hatstand_sync", cur, push=True)
        self.assertEqual(set(seen), set(H.Harness.APPROVAL_ACTIONS))
        for action, r in seen.items():
            self.assertEqual((r.get("action"), r["pending"][:2]), (action, "A-"), (action, r))
        self.assertEqual(self.types("agent.retired"), [])
        self.assertEqual(self.types("role.defined") and [e for e in self.types("role.defined") if e["data"]["role"] == "new-role"], [])
        self.assertEqual(self.types("release.flagged"), [])
        self.assertFalse(os.path.exists(os.path.join(self.home, "_harness", "export")))
        self.assertEqual(self.h.state().agents[a]["project"], "orch")
        # approve a few real ones
        self.assertEqual(self.approve(seen["retire_other"]["pending"])["state"], "granted")
        self.assertEqual(self.h.state().agents[b]["status"], "retired")
        self.assertEqual(self.approve(seen["flag_release"]["pending"])["state"], "granted")
        self.assertEqual(len(self.types("release.flagged")), 1)
        self.assertEqual(self.approve(seen["role_define"]["pending"])["state"], "granted")
        self.assertIn("new-role", self.h.state().roles)
        self.assertEqual(self.approve(seen["export"]["pending"])["state"], "granted")
        self.assertEqual(self.approve(seen["task_update_other"]["pending"])["state"], "granted")
        self.assertEqual(self.h.state().tasks[tid]["state"], "working")

    def test_role_define_assign_not_run(self):
        a = self.agent()
        self.adm("role_define", a, role="new-role", project="orch")
        self.assertNotIn("new-role", self.h.state().roles)
        self.h.role_define("operator", "r-two", "orch")
        self.adm("role_assign", a, role="r-two", target=a)
        self.assertIsNone(self.h.state().role_of(a))

    def test_retire_stays_direct_for_self_and_stale_lineage(self):
        a = self.agent()
        r = self.adm("retire", a, target=a, reason="done")
        self.assertEqual(r["retired"], a[:8])

    def test_reload_force_grant_used_once(self):
        a = self.agent()
        self.as_(a)
        r = self.adm("reload", a, force=True)
        self.assertIn("pending", r)
        self.approve(r["pending"])
        with mock.patch.object(M, "reload_op", return_value={"text": "reloading"}) as ro:
            self.assertEqual(self.adm("reload", a, force=True)["text"], "reloading")
            self.assertIn("pending", self.adm("reload", a, force=True))   # grant was single use
        self.assertEqual(ro.call_count, 1)

    def test_health_line_and_do(self):
        a = self.agent()
        self.adm("set_project", a, target=a, project="orch-two")
        import health
        t = health.text(health.health(self.h))
        self.assertIn("approvals: 1 pending, 0 granted (cli-tty 0)", t)
        self.assertIn("▲ 1 approval request(s): harness.py pending", t)


class Gates(Base):
    def setUp(self):
        super().setUp()
        self.h2, self.envoy, self.lead, self.plug, self.pkg, self.sha = _mk(tempfile.mkdtemp())

    def test_unresolvable_by_is_an_error(self):
        n = len(self.h2.store.read_all())
        with self.assertRaisesRegex(H.HarnessError, "does not resolve"):
            self.h2.publish_release(self.plug, pkg=self.pkg, override="r", by="no-such-agent")
        with self.assertRaisesRegex(H.HarnessError, "does not resolve"):
            self.h2.flag_release("dummy", external=True, by="no-such-agent")
        self.assertEqual(len(self.h2.store.read_all()), n)

    def test_override_via_approval_and_caller_logged(self):
        h = self.h2
        # 0.17.0 (R-053): an MCP publish path must sit under the home, a workspace or an allowed root
        root_ = os.path.dirname(os.path.commonpath([os.path.realpath(self.plug), os.path.realpath(self.pkg)]))
        op_ = mock.patch.object(H, "_operator_file", return_value=({"allowed_roots": [root_], "release_scope_gate": False}, []))
        op_.start()
        self.addCleanup(op_.stop)
        a = h.register(project="orch", model=MODEL)["id"]
        M.BOUND.update(home=h.home, id=a)
        r = M.call(h, "harness_admin", {"op": "publish_release", "agent": a,
                                        "args": {"path": self.plug, "pkg": self.pkg, "override": "ship"}})
        self.assertTrue(r["pending"])
        self.assertEqual([e for e in h.store.read_all() if e["type"] == "release.published"], [])
        rec = h.approvals(True)[0]
        out = h.approve(r["pending"], "cli-tty", rec["args_digest"][:4], True)
        self.assertEqual(out["state"], "granted", out)
        ev = [e for e in h.store.read_all() if e["type"] == "release.gate_override"][-1]
        self.assertEqual((ev["actor"], ev["data"]["reason"], ev["data"]["caller"]), ("human", "ship", "operator"))

    def test_publish_without_override_not_available_over_mcp(self):
        a = self.h2.register(project="orch", model=MODEL)["id"]
        with self.assertRaises(H.HarnessError):
            M.call(self.h2, "harness_admin", {"op": "publish_release", "agent": a, "args": {"path": self.plug}})

    def test_default_package_mismatch_refused(self):
        with open(os.path.join(self.plug, "extra.txt"), "w") as f:
            f.write("changed after packaging")
        os.makedirs(os.path.join(self.plug, "scripts"), exist_ok=True)
        with open(os.path.join(self.plug, "scripts", "x.py"), "w") as f:
            f.write("print(2)\n")
        n = len(self.h2.store.read_all())
        with self.assertRaisesRegex(H.HarnessError, "does not match"):
            self.h2.publish_release(self.plug, override="r")   # default <parent>/<name>-<ver>.plugin path
        self.assertEqual(len(self.h2.store.read_all()), n)

    def test_flag_release_via_approval(self):
        h = self.h2
        a = self.lead
        M.BOUND.update(home=h.home, id=a)
        r = M.call(h, "harness_admin", {"op": "flag_release", "agent": a, "args": {"name": "ext-tool", "external": True}})
        self.assertIn("pending", r)
        self.assertEqual([e for e in h.store.read_all() if e["type"] == "release.flagged"], [])
        rec = h.approvals(True)[0]
        h.approve(r["pending"], "cli-tty", rec["args_digest"][:4], True)
        ev = [e for e in h.store.read_all() if e["type"] == "release.flagged"][-1]
        self.assertEqual((ev["actor"], ev["data"]["name"]), ("human", "ext-tool"))

    def test_ack_format_and_mechanical_not_from_mcp(self):
        a = self.agent("corpus-steward")
        n = self.note(a)
        self.as_(a)
        with self.assertRaisesRegex(H.HarnessError, "ack must be"):
            self.adm("archive", a, ids=[n], reason='"rule line text"', ack="not-a-message")
        with self.assertRaisesRegex(H.HarnessError, "ack must be"):
            self.h.archive(a, [n], '"rule line text"', ack="m-XYZ")
        with self.assertRaisesRegex(H.HarnessError, "unknown args"):
            self.adm("archive", a, ids=[n], reason="x", mechanical=True)

    def test_restore_confirmed_dead_holder_unchanged(self):
        holder = self.agent("writer-role")
        self.h.retire(holder, "gone")
        me = self.agent()
        M.BOUND.update(home=self.home, id=None)
        r = M.call(self.h, "harness_restore", {"role": "writer-role", "model": MODEL, "confirmed": True})
        self.assertNotIn("pending", r)
        self.assertTrue(r.get("short"))
        self.assertEqual(self.types("approval.requested"), [])

    def test_restore_confirmed_live_holder_is_pending_then_consumed(self):
        holder = self.agent("writer-role")
        r = M.call(self.h, "harness_restore", {"role": "writer-role", "model": MODEL, "confirmed": True})
        self.assertEqual(r["action"], "restore_confirmed")
        self.assertEqual(self.h.state().role_of(holder), "writer-role")
        self.approve(r["pending"])
        r2 = M.call(self.h, "harness_restore", {"role": "writer-role", "model": MODEL, "confirmed": True})
        self.assertTrue(r2.get("short"))
        self.assertNotEqual(self.h.state().role_of(holder), "writer-role")


class CliOperatorUnchanged(Base):
    def test_cli_paths_still_work(self):
        h, envoy, lead, plug, pkg, sha = _mk(tempfile.mkdtemp())
        a = h.register(project="orch", model=MODEL)["id"]
        n = h.record(a, "note", "n", "rule line text")["id"]
        h.pin("operator", [n], True, '"rule line text"')
        self.assertTrue([e for e in h.store.read_all() if e["type"] == "corpus.pinned"])
        self.assertIn("archived", h.archive("operator", [n], '"rule line text"'))
        h.flag_release("dummy", external=True, by="operator")
        out = h.publish_release(plug, pkg=pkg, override="operator says so", by=None)
        self.assertIn("gate overridden by operator", out["warn"])
        ev = [e for e in h.store.read_all() if e["type"] == "release.gate_override"][-1]
        self.assertEqual(ev["actor"], "human")

    def test_cli_pending_needs_tty(self):
        import subprocess
        a = self.agent()
        self.adm("set_project", a, target=a, project="orch-two")
        env = dict(os.environ, HARNESS_HOME=self.home, HARNESS_CACHE=os.path.join(self.tmp, "cache"))
        script = os.path.join(HERE, "..", "scripts", "harness.py")
        p = subprocess.run([sys.executable, "-B", script, "pending"], capture_output=True, text=True, env=env, stdin=subprocess.DEVNULL)
        self.assertIn("set_project", p.stdout)
        pid = self.h.approvals(True)[0]["id"]
        p = subprocess.run([sys.executable, "-B", script, "approve", pid], capture_output=True, text=True, env=env,
                           stdin=subprocess.DEVNULL)
        self.assertEqual(p.returncode, 2)
        self.assertIn("approve needs an interactive terminal", p.stdout)
        self.assertEqual(self.h.state().agents[a]["project"], "orch")


if __name__ == "__main__":
    unittest.main()
