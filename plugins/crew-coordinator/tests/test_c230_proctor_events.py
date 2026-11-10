"""cc 0.23.0 item 2 (scope A-08480; spec 2026-11-10_cc0230-proctor-events-spec.md v2.1): proctor case events, ledger only, no judging.
P1-P14 as numbered in the spec. Each fails on 0.22.5 (op=case and the approval actions do not exist) and each checks its own rule.
Run: python3 -B tests/test_c230_proctor_events.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _env  # noqa: F401  isolate HOME and HARNESS_* first
import hashlib, json, os, subprocess, time, unittest
from unittest import mock

import test_c220_nudge as C
from test_c220_nudge import D, H, M

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
MAG = {"recoverability": 2, "radius": 1, "cost": 1}


class P(C.Base):
    def setUp(self):
        super().setUp()
        for r in ("proctor", "harness-critic"):
            self.h.role_define("operator", r, "harness-ops", carry="none")
        self.A = self.reg("proctor", "local_A")
        self.crit = self.reg("harness-critic", "local_crit")

    # ---- helpers
    def ca(self, agent, **a):
        M.BOUND.update(home=None, id=None)
        return M.call(self.h, "harness_admin", {"agent": agent, "op": "case", "args": a})

    def bad(self, regex, agent, **a):
        with self.assertRaisesRegex(H.HarnessError, regex):
            self.ca(agent, **a)

    def source(self):
        return self.send(self.plain, "role:envoy", kind="notice")["id"]

    def open(self, sev="S2", mag=None, **kw):
        return self.ca(self.plain, action="open", source={"msg_id": self.source()}, severity=sev, magnitude=mag or MAG, summary="s", **kw)["case"]

    def grant(self, pid):
        code = self.h._approval_records()[pid]["args_digest"][:4]
        return self.h.approve(pid, code=code, tty=True)

    def shadow(self, on):
        r = M.call(self.h, "harness_admin", {"agent": self.plain, "op": "proctor_shadow", "args": {"on": on, "reason": "test"}})
        return self.grant(r["pending"])

    def new_proctor(self, host, **kw):
        """A second proctor instance takes the role (role claim, or the given predecessor/spawn_reason)."""
        return self.reg("proctor", host, **kw)

    def classified(self, sev="S2", owner="curator"):
        x = self.open(sev)
        self.ca(self.A, action="classify", case=x, cause="execution", owner=owner)
        return x

    def case(self, x):
        return self.h.state().cases[x]

    # P1
    def test_p1_open(self):
        mid = self.source()
        o = self.ca(self.plain, action="open", source={"msg_id": mid}, severity="S2", magnitude=MAG, summary="line one\nline two")
        self.assertTrue(o["case"].startswith("X-"))
        c = self.case(o["case"])
        self.assertEqual(c["summary"], "line one line two")
        m = self.h.state().messages[mid]
        self.assertEqual(self.ca(self.plain, action="open", source={"seq": m["seq"]}, severity="S3", magnitude=MAG),
                         {"case": o["case"], "duplicate": True})                 # the same event by another key: the first case
        f = self.ca(self.plain, action="open", source={"msg_id": self.source()}, severity="S2",
                    magnitude=dict(MAG, recoverability=5))
        self.assertEqual(f["severity"], "S0")
        self.assertEqual([e for e in self.events("case.opened") if e["data"]["case"] == f["case"]][0]["data"]["forced"], "irreversible")
        self.bad("no ledger event", self.plain, action="open", source={"seq": 99999}, severity="S2", magnitude=MAG)
        self.bad("no message", self.plain, action="open", source={"msg_id": "m-nope"}, severity="S2", magnitude=MAG)
        self.bad("magnitude", self.plain, action="open", source={"msg_id": self.source()}, severity="S2", magnitude={"cost": 9})

    # P2
    def test_p2_card(self):
        x = self.open()
        r = self.ca(self.plain, action="card", case=x, subject=self.plain, rationale="a" * 400 + "\nb")
        card = [e for e in self.events("trace.card")][-1]["data"]
        self.assertTrue(r["card"].startswith("TC-"))
        self.assertEqual(card["source"], "self")
        self.assertEqual(card["label"], "ledger events only")
        self.assertTrue(card["preceding"] and all(p["seq"] <= self.case(x)["source_seq"] for p in card["preceding"]))
        self.assertIn("message.sent", [p["type"] for p in card["preceding"]])           # a msg_id source: its message.sent seq
        self.assertLessEqual(len(card["rationale"]), 300)
        self.assertNotIn("\n", card["rationale"])
        self.bad("unknown (args|or server-set keys).*preceding", self.plain, action="card", case=x, subject=self.plain, preceding=[])
        other = self.reg(host="local_other")
        self.bad("a peer card is written by", other, action="card", case=x, subject=self.plain)
        self.assertEqual(self.ca(self.crit, action="card", case=x, subject=self.plain)["source"], "peer")
        self.bad("no corpus entry", self.plain, action="card", case=x, subject=self.plain, rule_ids=["D-00000"])
        self.bad("never content", self.plain, action="card", case=x, subject=self.plain, diff={"path": "a", "sha": "abcdef12", "content": "x"})
        r2 = self.ca(self.plain, action="card", case=x, subject=self.plain, diff={"path": "scripts/a.py", "sha": "abcdef12"})
        self.assertEqual([e for e in self.events("trace.card")][-1]["data"]["supersedes"], r["card"])
        self.assertTrue(r2["card"].startswith("TC-"))

    # P3
    def test_p3_classify(self):
        x = self.open()
        self.bad("proctor only", self.plain, action="classify", case=x, cause="execution", owner="curator")
        r = self.ca(self.A, action="classify", case=x, cause="execution", owner="curator", contributing=["rule"])
        self.assertIs(r["shadow"], True)
        self.assertEqual(self.events("proctor.shadow"), [])
        self.bad("one classification per instance", self.A, action="classify", case=x, cause="rule", owner="curator")
        self.bad("owner must be a defined role", self.A, action="classify", case=self.open(), cause="rule", owner="nobody")

    # P4
    def test_p4_shadow_is_ledger_state(self):
        x = self.classified()
        self.bad("refused while the proctor is in shadow", self.A, action="route", case=x, to="curator")
        cfg = os.path.join(self.home, "_harness", "config.json")
        json.dump({"proctor": {"shadow": False}, "proctor_shadow": False}, open(cfg, "w"))
        self.op["proctor"] = {"shadow": False}
        self.bad("in shadow", self.A, action="route", case=x, to="curator")                # config files are not read
        self.h.store.append("proctor.shadow", "human", {"on": False})                      # hand-appended, no grant
        self.assertTrue(self.h.state().shadow_on())
        self.assertEqual(self.shadow(False)["state"], "granted")
        self.assertFalse(self.h.state().shadow_on())
        self.bad("to must be the classified owner", self.A, action="route", case=x, to="envoy")
        self.ca(self.A, action="route", case=x, to="curator")
        self.shadow(True)
        live = self.h.state()
        full = H.State(self.h.store.read_all())
        self.assertEqual(len(full.cases[x]["routed"]), 1)                                  # the earlier route still applies
        self.assertEqual(full.case_rejected, live.case_rejected)
        self.assertEqual(len(full.case_rejected), 1)                                       # only the hand-appended shadow event

    # P5
    def test_p5_severity(self):
        x = self.open("S2")
        self.bad("stale: current is S2", self.A, action="severity", case=x, old="S1", new="S3")
        self.ca(self.A, action="severity", case=x, old="S2", new="S0")
        self.bad("may not lower an S0", self.A, action="severity", case=x, old="S0", new="S1")
        y = self.open("S1")
        self.ca(self.A, action="severity", case=y, old="S1", new="S3")
        self.bad("only the proctor", self.plain, action="severity", case=y, old="S3", new="S2")
        r = self.ca(self.A, action="propose", case=x, new="S1", reason="false alarm")
        rec = self.h._approval_records()[r["pending"]]
        self.assertEqual(rec["action"], "case_severity")
        self.assertIsNone(rec["expires"])
        self.assertEqual(len(self.events("case.severity_proposed")), 1)
        self.bad("still pending", self.A, action="propose", case=x, new="S2")
        self.assertEqual(self.case(x)["severity"], "S0")
        g = self.grant(r["pending"])
        self.assertEqual(g["state"], "granted", g)
        sv = self.events("case.severity")[-1]
        self.assertEqual((sv["actor"], sv["data"]["old"], sv["data"]["new"], sv["data"]["approval"]), ("human", "S0", "S1", r["pending"]))
        self.assertEqual(self.case(x)["severity"], "S1")
        g_idx = [e["seq"] for e in self.events("approval.granted") if e["data"]["id"] == r["pending"]][0]
        self.assertLess(g_idx, sv["seq"])                                                  # the grant comes before the event it allows

    def test_p5b_a_grant_whose_old_is_no_longer_current_writes_nothing(self):
        x = self.open("S0")
        r = self.ca(self.A, action="propose", case=x, new="S2")
        req = self.ca(self.plain, action="request_severity", case=x, old="S0", new="S3")
        self.grant(req["pending"])                                                         # the case is now S3
        n = len(self.events("case.severity"))
        g = self.grant(r["pending"])
        self.assertEqual(g["state"], "failed")
        self.assertIn("stale", g["result"])
        self.assertEqual(len(self.events("case.severity")), n)

    # P6
    def test_p6_self_audit_by_chat_line_and_session(self):
        x = self.classified()
        a2 = self.new_proctor("local_A", predecessor=self.A, spawn_reason="compaction")      # same chat, compacted
        s = self.ca(self.crit, action="sample", cases=[x], expires=7)["sample"]
        self.bad("took part in case", a2, action="audit_blind", case=x, sample=s, cause="rule", owner="curator", severity="S2")
        b = self.new_proctor("local_A")                                                    # a role claim from A's app session
        self.bad("took part in case", b, action="audit_blind", case=x, sample=s, cause="rule", owner="curator", severity="S2")
        r_ = self.new_proctor("local_R", predecessor=self.A, spawn_reason="restore")       # restore into a new chat: fresh
        self.ca(r_, action="audit_blind", case=x, sample=s, cause="rule", owner="curator", severity="S2")
        c_ = self.new_proctor("local_C")                                                   # unrelated
        self.ca(c_, action="audit_blind", case=x, sample=s, cause="execution", owner="curator", severity="S2")

    # P7
    def test_p7_sample(self):
        x = self.classified()
        c_ = self.new_proctor("local_C")
        self.bad("not in an open sample", c_, action="audit_blind", case=x, sample="S-00000", cause="rule", owner="curator", severity="S2")
        self.bad("only the harness-critic draws", self.plain, action="sample", cases=[x], expires=7)
        self.bad("at most 14", self.crit, action="sample", cases=[x], expires=30)
        s = self.ca(self.crit, action="sample", cases=[x], expires=1)["sample"]
        self.bad("already in an open sample", self.crit, action="sample", cases=[x], expires=1)
        with mock.patch.object(H.time, "time", return_value=time.time() + 2 * 86400):
            self.h._sc = None
            st = H.State(self.h.store.read_all())
            self.assertIn("not in an open sample", st.case_error("case.audit_blind", c_, {"case": x, "sample": s, "cause": "rule",
                                                                                          "owner": "curator", "severity": "S2"}))
        self.ca(c_, action="audit_blind", case=x, sample=s, cause="rule", owner="curator", severity="S2")

    # P8
    def test_p8_blind_before_verdict_and_show_hides(self):
        x = self.classified()
        cls_seq = self.events("case.classified")[-1]["seq"]
        s = self.ca(self.crit, action="sample", cases=[x], expires=7)["sample"]
        c_ = self.new_proctor("local_C")
        self.bad("write your case.audit_blind first", c_, action="audit", case=x, verdict="uphold", of_seq=cls_seq)
        before = self.ca(c_, action="show", case=x)["text"]
        self.assertIn("hidden until your blind", before)
        self.assertNotIn("execution", before)
        self.ca(c_, action="audit_blind", case=x, sample=s, cause="rule", owner="curator", severity="S2")
        after = self.ca(c_, action="show", case=x)["text"]
        self.assertIn("classified seq", after)
        self.bad("of_seq must be", c_, action="audit", case=x, verdict="uphold", of_seq=1)
        self.ca(c_, action="audit", case=x, verdict="overturn", of_seq=cls_seq, reason="cause was rule")
        self.assertEqual(self.case(x)["classifications"][0]["cause"], "execution")         # the audit never changes the case

    # P9
    def test_p9_s0_cannot_be_dismissed_without_the_operator(self):
        x = self.classified("S0")
        self.bad("S0 case cannot be closed as shadow", self.A, action="close", case=x, outcome="shadow")
        self.bad("needs the operator", self.A, action="close", case=x, outcome="wont_fix")
        self.assertIsNone(self.case(x)["closed"])
        y = self.classified("S2")
        self.bad("routed needs a case.routed", self.A, action="close", case=y, outcome="routed")
        self.bad("fixed needs a ref", self.A, action="close", case=y, outcome="fixed")
        low = self.open("S3")
        self.bad("equal or higher severity", self.A, action="close", case=x, outcome="duplicate", ref=low)
        twin = self.open("S0")
        self.bad("needs the operator", self.A, action="close", case=x, outcome="duplicate", ref=twin)
        req = self.ca(self.plain, action="request_close", case=x, outcome="duplicate", ref=twin, reason="same incident")
        self.assertIsNone(self.h._approval_records()[req["pending"]]["expires"])
        self.assertEqual(self.grant(req["pending"])["state"], "granted")
        self.assertEqual(self.case(x)["closed"]["outcome"], "duplicate")
        z = self.classified("S1")
        self.ca(self.A, action="close", case=z, outcome="shadow")
        self.bad("another OPEN case", self.A, action="close", case=y, outcome="duplicate", ref=z)
        self.bad("is closed", self.A, action="severity", case=z, old="S1", new="S0")

    # P10
    def test_p10_server_set_fields_are_refused_as_input(self):
        x = self.open()
        for k in ("by", "instance", "sessions", "shadow", "preceding"):
            with self.subTest(key=k):
                self.bad("unknown|not accepted over MCP", self.A, action="classify", case=x, cause="rule", owner="curator", **{k: "x"})
                with self.assertRaisesRegex(H.HarnessError, "server-set"):        # the harness method refuses it too, behind the MCP check
                    self.h.case_op(self.A, {"action": "classify", "case": x, "cause": "rule", "owner": "curator", k: "x"})

    # P11
    def test_p11_replay_rejects_and_the_sync_line_counts_once(self):
        x = self.classified("S0")
        self.h.store.append("case.severity", self.A, {"case": x, "old": "S2", "new": "S3"})
        self.h.store.append("case.closed", self.A, {"case": x, "outcome": "wont_fix"})
        st = H.State(self.h.store.read_all())
        self.assertEqual(st.cases[x]["severity"], "S0")
        self.assertIsNone(st.cases[x]["closed"])
        self.assertEqual(len(st.case_rejected), 2)
        first = json.dumps(self.call("harness_sync", agent=self.plain), default=str)
        self.assertIn("rejected case events: 2", first)
        again = json.dumps(self.call("harness_sync", agent=self.plain), default=str)
        self.assertNotIn("rejected case events", again)

    # P12
    def test_p12_cli_is_read_only(self):
        self.open()
        env = dict(os.environ, HARNESS_HOME=self.home)
        hp = os.path.join(ROOT, "scripts", "harness.py")
        r = subprocess.run([_sys.executable, "-B", hp, "cases"], capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("X-", r.stdout)
        w = subprocess.run([_sys.executable, "-B", hp, "case", "open"], capture_output=True, text=True, env=env)
        self.assertNotEqual(w.returncode, 0)
        self.assertIn("invalid choice", w.stderr)

    # P13
    def test_p13_proctor_sync_line(self):
        self.open("S0")
        self.assertIn("proctor queue: 1 open (S0 1, S1 0); shadow on", json.dumps(self.call("harness_sync", agent=self.A), default=str))
        self.assertNotIn("proctor queue", json.dumps(self.call("harness_sync", agent=self.plain), default=str))

    def test_p13b_restore_digest_omits_the_previous_instance_for_the_proctor(self):
        st = self.h.state()
        txt = self.h.restore_digest(st, self.A, "proctor", [])
        txt = txt if isinstance(txt, str) else json.dumps(txt, default=str)
        self.assertIn("omitted for the proctor", txt)

    # P14
    def test_p14_hatstand_guard_pins_the_new_events_md(self):
        import hatstand_guard as HG
        pin = [v for k, v in HG.__dict__.items() if isinstance(v, dict)]
        sha = hashlib.sha256(open(os.path.join(ROOT, "docs", "EVENTS.md"), "rb").read()).hexdigest()
        self.assertTrue(any(sha in d.values() for d in pin), "EVENTS.md sha not pinned in hatstand_guard.py")
        txt = open(os.path.join(ROOT, "docs", "EVENTS.md"), encoding="utf-8").read()
        for t in H.CASE_EVENTS + ("proctor.shadow",):
            self.assertIn(f"`{t}`", txt)

    def test_rubric3_nothing_classifies_on_its_own(self):
        self.open("S1")
        self.call("harness_sync", agent=self.A)
        self.assertEqual(self.events("case.classified") + self.events("case.routed") + self.events("case.severity"), [])


if __name__ == "__main__":
    unittest.main(verbosity=1)
