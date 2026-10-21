"""cc 0.14.6 Wave 1 hardening: steps 1-10 (lease.expired, aliases, refs, hosts, history report, legacy gate,
check_reason, release verdict, torn tail, proof fail-closed, bad events, anchors, hash vectors, H-003).
Run: python3 -B tests/test_hardening_w1.py"""
import json, os, shutil, subprocess, sys, tempfile, unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(HERE, "..", "scripts")
sys.path.insert(0, HERE)
sys.path.insert(0, SCRIPTS)
import harness as H
import mcp_server as M
import history_report as HR
import hash_vectors as HV
from test_release_gates import _mk

MODEL = "claude-sonnet-5-5"


def home():
    d = tempfile.mkdtemp()
    p = os.path.join(d, "home")
    os.makedirs(p)
    return p


class Base(unittest.TestCase):
    def setUp(self):
        self.home = home()
        self.h = H.Harness(self.home)

    def types(self, t):
        return [e for e in self.h.store.read_all() if e.get("type") == t]


class LeaseExpired(Base):          # step 1
    def test_logged_once_per_expired_claim(self):
        a = self.h.register(project="orchestration", model=MODEL)["id"]
        b = self.h.register(project="orchestration", model=MODEL)["id"]
        self.h.claim(a, "specs/x.md", ttl=30)
        now = __import__("time").time()
        with mock.patch("time.time", return_value=now + 500):
            self.h.claim(b, "specs/other.md")            # any claim sweeps expired leases
            self.h.claim(b, "specs/other.md")            # and a second one must not log again
            self.h.sync(b)
        ev = self.types("lease.expired")
        self.assertEqual(len(ev), 1)
        self.assertEqual(ev[0]["data"]["holder"], a)
        self.assertEqual(ev[0]["actor"], "system")
        # a fresh claim on the same path is a new claim: it expires (and is logged) once more
        with mock.patch("time.time", return_value=now + 501):
            self.assertTrue(self.h.claim(b, "specs/x.md", ttl=30)["granted"])
        with mock.patch("time.time", return_value=now + 900):
            self.h.claim(a, "specs/z.md")
        self.assertEqual(len(self.types("lease.expired")), 2)

    def test_unexpired_and_released_not_logged(self):
        a = self.h.register(project="orchestration", model=MODEL)["id"]
        self.h.claim(a, "specs/x.md")
        self.h.claim(a, "specs/y.md", ttl=30)
        self.h.release(a, "specs/y.md")
        self.h.sync(a)
        self.assertEqual(self.types("lease.expired"), [])


class Aliases(Base):               # step 2
    def test_alias_applied_at_write(self):
        a = self.h.register(project="code", model=MODEL)["id"]
        r = self.h.record(a, "note", "alias check")
        ev = self.types("corpus.recorded")[-1]
        self.assertEqual(ev["data"]["project"], "claude-code")
        r2 = self.h.record(a, "note", "explicit Claude", project="Claude")
        self.assertEqual(self.types("corpus.recorded")[-1]["data"]["project"], "claude-code")

    def test_all_table_entries(self):
        al = H.load_project_aliases()
        self.assertEqual({k: al[k] for k in ("orchestration", "cv-management", "code", "claude")},
                         {"orchestration": "orchestration", "cv-management": "cv-management",
                          "code": "claude-code", "claude": "claude-code"})

    def test_null_and_unknown_rejected(self):
        aid = "f" * 64   # an agent with no project (as in 14 live registrations)
        self.h.store.append("agent.registered", aid, {"id": aid, "sobriquet": "Quiet Lynx", "project": "", "model": MODEL})
        with self.assertRaises(H.HarnessError) as c:
            self.h.record(aid, "note", "no project")
        self.assertIn("project required", str(c.exception))
        a = self.h.register(project="orchestration", model=MODEL)["id"]
        with self.assertRaises(H.HarnessError) as c:
            self.h.record(a, "note", "typo", project="orchestraton")
        self.assertIn("unknown project", str(c.exception))
        self.assertEqual(self.types("corpus.recorded"), [])

    def test_live_projects_known_and_scratch_wildcard(self):
        a = self.h.register(project="orchestration", model=MODEL)["id"]
        for given, want in (("Harness_Router", "skill-curation"), ("Lucent Design System", "design-system"),
                            ("design-system", "design-system"), ("scratch-abc", "scratch-abc"), ("code", "claude-code")):
            self.h.record(a, "note", f"rec {given}", project=given)
            self.assertEqual(self.types("corpus.recorded")[-1]["data"]["project"], want, given)
        with self.assertRaises(H.HarnessError):
            self.h.record(a, "note", "still unknown", project="scratchy")

    def test_home_alias_file_extends_map(self):
        os.makedirs(os.path.join(self.home, "_harness"), exist_ok=True)
        json.dump({"aliases": {"Harness Router": "harness-ops"}}, open(os.path.join(self.home, "_harness", "project-aliases.json"), "w"))
        self.assertEqual(H.load_project_aliases(self.home)["harness-router"], "harness-ops")

    def test_report_lists_existing_offenders(self):
        evs = [{"seq": 1, "type": "agent.registered", "data": {"id": "a" * 64, "project": "orchestration", "sobriquet": "A B"}},
               {"seq": 2, "type": "corpus.recorded", "data": {"project": None}},
               {"seq": 3, "type": "corpus.recorded", "data": {"project": "Orchestration"}},
               {"seq": 4, "type": "corpus.recorded", "data": {"project": "ghost"}},
               {"seq": 5, "type": "corpus.recorded", "data": {"project": "orchestration"}}]
        o = HR.project_offenders(evs, {"code": "claude-code"})
        self.assertEqual((o["null"], o["not_canonical"], o["unknown"]), ([2], [3], [4]))


class RefsHosts(Base):             # steps 3, 4
    def test_refs_always_list(self):
        a = self.h.register(project="orchestration", model=MODEL)["id"]
        self.h.record(a, "note", "string refs", refs="specs/a.md")
        self.assertEqual(self.types("corpus.recorded")[-1]["data"]["refs"], ["specs/a.md"])
        self.h.record(a, "note", "none refs", refs=None)
        self.assertEqual(self.types("corpus.recorded")[-1]["data"]["refs"], [])
        self.h.send(a, "operator", "hi", refs="specs/b.md")
        r = self.types("message.sent")[-1]["data"]["refs"]
        self.assertEqual((len(r), r[0].endswith("specs/b.md")), (1, True))
        self.assertEqual(H.as_list(("x", None, "y")), ["x", "y"])

    def test_string_refs_report(self):
        evs = [{"seq": 1, "type": "corpus.recorded", "data": {"refs": "a"}},
               {"seq": 2, "type": "message.sent", "data": {"refs": ["a"]}},
               {"seq": 3, "type": "message.sent", "data": {"refs": "b"}}]
        self.assertEqual([x["seq"] for x in HR.string_refs(evs)], [1, 3])

    def test_host_normalised(self):
        self.assertEqual(H.norm_host("MacBookPro.haven.lan"), "MacBookPro")
        self.assertEqual(H.norm_host("MacBookPro"), "MacBookPro")
        self.assertEqual(H.norm_host("10.0.0.5"), "10.0.0.5")
        self.assertEqual(H.norm_host(""), "")
        self.assertNotIn(".", H.HOSTNAME)
        a = self.h.register(project="orchestration", model=MODEL)["id"]
        ev = [e for e in self.types("agent.registered") if e["data"]["id"] == a][0]
        self.assertEqual(ev["data"]["host"], H.HOSTNAME)
        self.assertEqual(ev["via"]["host"], H.HOSTNAME)


class HistoryReport(unittest.TestCase):   # step 5
    def test_missing_via_and_actors(self):
        regs = [{"seq": i, "type": "agent.registered", "actor": f"{i:064x}", "via": {"t": "cli"},
                 "data": {"id": f"{i:064x}"}} for i in (1, 2)]
        evs = [{"seq": 0, "type": "t", "actor": "human", "data": {}}] + regs + \
              [{"seq": 3, "type": "server.started", "actor": "system", "via": {}, "data": {}}]
        self.assertEqual(HR.missing_via(evs), [0, 3])
        r = HR.actors_vs_registrations(evs)
        self.assertEqual((r["actors"], r["registrations"]), (4, 2))
        self.assertEqual(sorted(r["unregistered_writers"]), ["human", "system"])


class LegacyGate(Base):            # step 6
    def test_tools_list_unchanged(self):
        names = [t["name"] for t in M.tool_list()]
        self.assertEqual(names, ["harness_register", "harness_sync", "harness_send", "harness_inbox", "harness_claim",
                                 "harness_release", "harness_commit", "harness_record", "harness_recall",
                                 "harness_restore", "harness_handoff", "harness_admin"])
        self.assertFalse(set(names) & set(M.LEGACY_TOOLS))
        self.assertEqual(len(M.LEGACY_TOOLS), 10)

    def test_legacy_refused_with_message_then_flag(self):
        a = self.h.register(project="orchestration", model=MODEL)["short"]
        with mock.patch.dict(os.environ, {"HARNESS_LEGACY_TOOLS": ""}):
            with self.assertRaises(H.HarnessError) as c:
                M.call(self.h, "harness_whoami", {"agent": a})
            self.assertIn("harness_admin op=whoami", str(c.exception))
            self.assertEqual(M.call(self.h, "harness_admin", {"op": "whoami", "agent": a})["short"], a)
        with mock.patch.dict(os.environ, {"HARNESS_LEGACY_TOOLS": "1"}):
            self.assertEqual(M.call(self.h, "harness_whoami", {"agent": a})["short"], a)


class Reasons(Base):               # step 7a
    def test_none_bypass_dropped(self):
        a = self.h.register(project="orchestration", model=MODEL)["id"]
        cid = self.h.record(a, "decision", "rule one", "Always sign the release line.")["id"]
        n = len(self.h.store.read_all())
        for fn in (lambda r: self.h.archive("operator", [cid], r), lambda r: self.h.pin("operator", [cid], True, r)):
            for bad in ("none", "none: not needed", "None."):
                with self.assertRaises(H.HarnessError):
                    fn(bad)
        self.assertEqual(len(self.h.store.read_all()), n)
        self.h.pin("operator", [cid], True, 'rule: "Always sign the release line."')
        self.assertEqual(len(self.types("corpus.pinned")), 1)


class ReleaseVerdict(unittest.TestCase):   # step 7b
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.h, self.envoy, self.lead, self.plug, self.pkg, self.sha = _mk(self.tmp)

    def pub(self, body):
        mid = self.h.send(self.envoy, "operator", body)["id"]
        return self.h.publish_release(self.plug, pkg=self.pkg, accept=mid)

    def test_mention_is_not_a_verdict(self):
        for body in (f"I will not ACCEPT sha={self.sha[:12]} until tests pass",
                     f"see ACCEPT sha={self.sha[:12]} in the thread",
                     f"ACCEPT {self.sha}",                    # old unanchored form
                     f"ACCEPT sha={self.sha[:8]}"):           # 8 hex is not enough
            with self.assertRaises(H.HarnessError, msg=body):
                self.pub(body)

    def test_reject_line_wins(self):
        with self.assertRaises(H.HarnessError):
            self.pub(f"ACCEPT sha={self.sha[:12]}\nREJECT: one nit")

    def test_line_anchored_accept_passes_and_word_reject_in_text_ok(self):
        out = self.pub(f"review notes: no REJECT reasons found\nACCEPT sha={self.sha[:12]}\nlooks fine")
        self.assertEqual(out["version"], "1.0.0")


class Recovery(Base):              # step 8
    def test_torn_tail_quarantined(self):
        a = self.h.register(project="orchestration", model=MODEL)["id"]
        n = len(self.h.store.read_all())
        with open(self.h.store.log, "ab") as f:
            f.write(b'{"v":1,"seq":999,"type":"message.sent","da')       # a crash mid-write
        self.h.send(a, "operator", "after the crash")
        evs = self.h.store.read_all()
        self.assertFalse([e for e in evs if e.get("type") == "_corrupt"])
        rep = [e for e in evs if e["type"] == "log.repaired"]
        self.assertEqual(len(rep), 1)
        q = os.path.join(self.home, rep[0]["data"]["quarantine"])
        self.assertTrue(os.path.isfile(q))
        self.assertEqual(open(q, "rb").read(), b'{"v":1,"seq":999,"type":"message.sent","da')
        self.assertEqual(len(evs), n + 2)
        self.assertTrue(self.h.verify()["ok"])

    def test_tail_guard_and_missing_newline(self):
        a = self.h.register(project="orchestration", model=MODEL)["id"]
        data = open(self.h.store.log, "rb").read()
        open(self.h.store.log, "wb").write(data.rstrip(b"\n"))         # valid last line, newline lost
        self.h.send(a, "operator", "x")
        self.assertTrue(self.h.verify()["ok"])
        open(self.h.store.log, "ab").write(b"not json at all")
        self.assertIsNotNone(self.h.store._tail())                      # guard: newest parseable event, no raise

    def test_proof_fails_closed_without_corpus_index(self):
        self.h.role_define("operator", "corpus-steward", "orchestration")
        s = self.h.register(project="orchestration", model=MODEL)["id"]
        self.h.role_assign("operator", "corpus-steward", s)
        with self.assertRaises(H.HarnessError) as c:
            self.h.send(s, "operator", "done exit=0 hash=deadbeefdeadbeef", kind="result")
        self.assertIn("corpus_index.py not found", str(c.exception))

    def test_bad_event_skipped_and_counted(self):
        good = {"seq": 1, "t": 1.0, "type": "agent.synced", "actor": "x", "data": {"id": "nobody", "seq": 1}, "hash": "h1"}
        bad = {"seq": 2, "t": 2.0, "type": "agent.registered", "actor": "x", "data": {"id": "a" * 64}, "hash": "h2"}   # no sobriquet
        bad2 = {"seq": 3, "type": "message.sent", "actor": "x", "hash": "h3"}                                          # no t / data
        st = H.State([good, bad, bad2, dict(good, seq=4, hash="h4")])
        self.assertEqual(st.skipped, [2, 3])
        self.assertEqual(st.last_seq, 4)


class Anchors(Base):               # step 9
    def setUp(self):
        super().setUp()
        self.a = self.h.register(project="orchestration", model=MODEL)["id"]
        for i in range(4):
            self.h.send(self.a, "operator", f"m{i}")

    def test_anchor_written_and_verify_ok(self):
        an = self.h.write_anchor("test")
        self.assertTrue(os.path.isfile(os.path.join(self.home, "_harness_anchors", "anchors.jsonl")))
        self.assertEqual(an["sha256"], H.Harness.anchor_sha(an["seq"], an["head"]))
        v = self.h.verify()
        self.assertTrue(v["ok"])
        self.assertEqual(v["anchor"], {"seq": an["seq"], "ok": True})
        self.h.send(self.a, "operator", "later")           # a growing log still matches its anchor
        self.assertTrue(self.h.verify()["ok"])

    def test_daily_anchor_once_per_day(self):
        self.h.sync(self.a)
        self.h.sync(self.a)
        self.assertEqual(len(self.h.anchors()), 1)

    def test_tamper_copy_fails_verify(self):
        self.h.write_anchor("test")
        cp = tempfile.mkdtemp()
        shutil.copytree(self.home, os.path.join(cp, "h"))
        h2 = H.Harness(os.path.join(cp, "h"))
        self.assertTrue(h2.verify()["ok"])
        lines = open(h2.store.log).read().splitlines()
        j = json.loads(lines[3])
        j["data"]["body"] = "edited"
        lines[3] = json.dumps(j, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        open(h2.store.log, "w").write("\n".join(lines) + "\n")
        v = h2.verify()
        self.assertFalse(v["ok"])
        self.assertTrue(any("hash mismatch" in p["problem"] for p in v["problems"]))

    def test_rechained_log_caught_by_anchor(self):
        self.h.write_anchor("test")
        cp = os.path.join(tempfile.mkdtemp(), "h")
        shutil.copytree(self.home, cp)
        h2 = H.Harness(cp)
        evs = [json.loads(l) for l in open(h2.store.log) if l.strip()]
        prev = H.GENESIS
        for e in evs:                      # an editor who recomputes every hash passes the plain chain check
            if e["seq"] == 3:
                e["data"] = {"id": "x"} if e["type"] != "message.sent" else dict(e["data"], body="rewritten")
            e["prev"] = prev
            e["hash"] = H.event_hash(e)
            prev = e["hash"]
        open(h2.store.log, "w").write("\n".join(H.canon(e) for e in evs) + "\n")
        v = h2.verify()
        self.assertFalse(v["ok"])
        self.assertTrue(any("anchor" in p for p in v["problems"]))

    def test_publish_writes_anchor(self):
        tmp = tempfile.mkdtemp()
        h, envoy, lead, plug, pkg, sha = _mk(tmp)
        mid = h.send(envoy, "operator", f"ACCEPT sha={sha[:12]}")["id"]
        h.publish_release(plug, pkg=pkg, accept=mid)
        self.assertEqual([x["reason"] for x in h.anchors()], ["publish dummy 1.0.0"])


class Vectors(unittest.TestCase):  # step 9 (#6)
    def test_vectors_match_and_agree_with_harness(self):
        v = json.load(open(HV.VECTORS))
        self.assertEqual(HV.check_vectors(v), (len(v), len(v), []))
        for x in v:
            self.assertEqual(H.canon(x["event"]), x["canonical"])
        r = subprocess.run([sys.executable, "-B", os.path.join(SCRIPTS, "hash_vectors.py")], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0)
        self.assertIn(f"{len(v)}/{len(v)} match", r.stdout)

    def test_log_recompute_and_tamper(self):
        h = H.Harness(home())
        a = h.register(project="orchestration", model=MODEL)["id"]
        h.send(a, "operator", "x")
        evs = h.store.read_all()
        self.assertEqual(HV.check_events(evs)[:2], (len(evs), len(evs)))
        evs[1]["data"] = {"changed": 1}
        self.assertEqual(HV.check_events(evs)[2], [evs[1]["seq"]])


class RetireCapsule(Base):         # step 10
    def test_retire_closes_open_capsule_and_flags_missing_model(self):
        self.h.role_define("operator", "claude-code", "orchestration")
        a = self.h.register(project="orchestration", model=MODEL, role="claude-code")["id"]
        d = os.path.join(self.home, "projects", "orchestration", "handoffs")
        os.makedirs(d)
        cap = os.path.join(d, "2026-10-13-test.md")
        open(cap, "w").write(f"---\nstatus: open\nfrom: Someone #{a[:8]}\n---\n# cap\n")
        other = os.path.join(d, "2026-10-13-other.md")
        open(other, "w").write("---\nstatus: open\nfrom: Other #11111111\nmodel: x\n---\n# other\n")
        r = self.h.retire(a, "done", by=a)
        self.assertEqual(r["capsules_closed"], ["2026-10-13-test.md"])
        self.assertTrue(any("no model: field" in f for f in r["flags"]))
        self.assertFalse(H._status_is_open(__import__("re").search(r"^status:(.*)$", open(cap).read(), __import__("re").M).group(1)))
        self.assertIn("status: open", open(other).read())
        self.assertEqual(self.h.state().agents[a]["status"], "retired")

    def test_retire_unknown_model_flagged(self):
        a = self.h.register(project="orchestration")["id"]
        r = self.h.retire(a, by=a)
        self.assertTrue(any("no model recorded" in f for f in r["flags"]))


if __name__ == "__main__":
    unittest.main()
