"""Operator seat stage 3: append gate, replay filter, signed apply, seat assignment only through the signed path.
Run: python3 -B tests/test_operator_gate.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _env  # noqa: F401
import io, os, subprocess, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
sys.path.insert(0, os.path.join(HERE, "..", "root"))
import harness as H
import operator_sign as OS
import harness_grant_helper as G
import harness_verify as V

TTY = "/dev/ttys042"


class Gate(unittest.TestCase):
    def setUp(self):
        self.d = os.path.realpath(tempfile.mkdtemp())
        self.home = os.path.join(self.d, "home"); os.makedirs(self.home)
        self.h = H.Harness(self.home)
        self.h.role_define("operator", "operator", "claude", carry="full")
        self.h.role_define("operator", "envoy", "harness-ops")
        self.a = self.h.register(project="claude", model="claude-sonnet-5-5")["id"]
        sd = os.path.join(self.d, "state"); os.makedirs(sd); os.makedirs(os.path.join(self.home, "_harness", "operator-pending"), exist_ok=True)
        key, pub = os.path.join(sd, "key"), os.path.join(self.d, "pub.pem")
        subprocess.run(["/usr/bin/openssl", "genrsa", "-out", key, "2048"], capture_output=True, check=True)
        subprocess.run(["/usr/bin/openssl", "rsa", "-in", key, "-pubout", "-out", pub], capture_output=True, check=True)
        self.cfg = dict(G.CFG, state_dir=sd, key=key, pub=pub, log=os.path.join(self.d, "grants.log"),
                        pending=os.path.join(self.home, "_harness", "operator-pending"), ledger=self.h.store.log,
                        uid=os.getuid(), min_gap_s=0)
        self._old = (OS.LOG, OS.PUB, OS.FLAG)
        OS.LOG, OS.PUB, OS.FLAG = self.cfg["log"], pub, os.path.join(self.d, "off")      # tests move the module constants; no env seam ships
        OS._cache["mark"] = None
        G.cmd_cutover(self.cfg)

    def tearDown(self):
        OS.LOG, OS.PUB, OS.FLAG = self._old

    def test_approval_request_carries_its_text_and_the_helper_checks_it_and_shows_it(self):
        """0.27.0: the scope text is in the request; the root helper recomputes the digest from it with the harness's own canonical form."""
        import time
        items = ["SCOPE-ITEM-ONE verbatim", "SCOPE-ITEM-TWO verbatim"]
        r = self.h.request_approval(self.a, "release_scope", {"plugin": "p", "version": "1.2.3", "items": items, "rationale": "because"})
        rid = H._file_approval_request(self.h, r["pending"] if isinstance(r, dict) else r)
        name = rid + ".json"
        raw, req, digests = G._vet(self.cfg, name, time.time())             # passes: digest recomputed from the shown text equals the event's
        shown = "\n".join(G.render(req))
        for w in ("ACTION: release_scope", "SCOPE-ITEM-ONE verbatim", "SCOPE-ITEM-TWO verbatim", "1.2.3"):
            self.assertIn(w, shown)
        import json
        path = os.path.join(self.cfg["pending"], name)
        doc = json.load(open(path))
        for tamper in (lambda d: d["detail"]["args"].update(rationale="other"), lambda d: d["detail"].update(action="retag"),
                       lambda d: d.pop("detail"), lambda d: d["events"].append(d["events"][0])):
            d2 = json.loads(json.dumps(doc)); tamper(d2)
            with open(os.path.join(self.cfg["pending"], "cccccccccccc.json"), "wb") as f:
                f.write(OS._MAP.canonical(d2).encode())
            with self.assertRaises(G.Refuse): G._vet(self.cfg, "cccccccccccc.json", time.time())

    def test_non_ascii_args_and_float_args(self):
        import time
        r = self.h.request_approval(self.a, "release_scope", {"version": "1.0.0", "plugin": "p", "rationale": "caf\u00e9 \u2014 ok", "items": ["z", "\u00fcber"]})
        rid = H._file_approval_request(self.h, r["pending"] if isinstance(r, dict) else r)
        G._vet(self.cfg, rid + ".json", time.time())                       # key order and non-ASCII text do not change the recomputed digest
        with self.assertRaises(H.HarnessError):
            self.h.request_approval(self.a, "release_scope", {"plugin": "p", "version": "1.0.0", "items": ["abc"], "rationale": 1.5})

    def test_human_append_refused_outside_ctx(self):
        self.assertTrue(OS.gate_on())
        with self.assertRaises(H.HarnessError):
            self.h.store.append("role.assigned", "human", {"role": "operator", "agent": self.a})
        with self.assertRaises(H.HarnessError):
            self.h.role_assign("operator", "operator", self.a)       # seat only through a signed act

    def test_forged_human_event_ignored_at_replay(self):
        before = self.h.state()
        self.h.store._append_locked("role.assigned", "human", {"role": "operator", "agent": self.a})   # raw write, as a forger would
        st = self.h.state()
        self.assertIsNone(st.role_holder("operator"))
        self.assertTrue(st.ignored_human)

    def test_g1_forged_operator_effect_ignored_for_any_actor(self):
        for actor in (self.a, "system", "human"):
            self.h.store._append_locked("role.assigned", actor, {"role": "operator", "agent": self.a})
        self.h.store._append_locked("message.sent", self.a, {"from": "human", "to": ["human"], "id": "m-forged", "body": "x"})
        self.h.store._append_locked("approval.granted", self.a, {"id": "A-forged", "args_digest": "abcd"})
        st = self.h.state()
        self.assertIsNone(st.role_holder("operator"))
        self.assertEqual(len(st.ignored_human), 5)
        probs = V.audit(self.cfg["ledger"], self.cfg["log"], self.cfg["pub"])
        self.assertEqual(len([p for p in probs if "no signed grant" in p]), 5)

    def test_i1_alias_of_the_seat_does_not_bypass(self):
        import json as _j
        al = os.path.join(HERE, "..", "data", "role-aliases.json")
        self.assertEqual(H.role_alias_table.__name__, "role_alias_table")
        H._ROLE_ALIASES = None
        orig = open(al).read()
        try:
            d = _j.loads(orig); d["aliases"]["seat"] = "operator"; d["aliases"]["operator"] = "envoy"
            open(al, "w").write(_j.dumps(d))
            H._ROLE_ALIASES = None
            self.assertNotIn("seat", H.role_alias_table()[0]); self.assertNotIn("operator", H.role_alias_table()[0])
        finally:
            open(al, "w").write(orig); H._ROLE_ALIASES = None
        self.h.store._append_locked("role.assigned", self.a, {"role": "seat", "agent": self.a})       # unknown name: enforced anyway
        self.h.store._append_locked("role.assigned", self.a, {"role": "#Operator", "agent": self.a})
        st = self.h.state()
        self.assertEqual(len(st.ignored_human), 2)
        self.assertEqual(len([p for p in V.audit(self.cfg["ledger"], self.cfg["log"], self.cfg["pub"]) if "no signed grant" in p]), 2)
        self.h.store._append_locked("role.assigned", self.a, {"role": "envoy", "agent": self.a})      # a known role self-claim still works
        self.assertEqual(len(self.h.state().ignored_human), 2)

    def test_g3_unbuilt_kinds_keep_working_after_cutover(self):
        self.h.store.append("release.scope", "human", {"x": 1})          # not enforced: written, counted, not ignored
        self.h.store.append("corpus.pinned", "human", {"id": "N-1"})
        st = self.h.state()
        self.assertEqual(st.ignored_human, [])

    def test_g2_no_environment_seam_in_shipped_code(self):
        for f in ("scripts/operator_sign.py", "root/harness_grant_helper.py", "root/harness_verify.py", "root/harness_event_map.py"):
            src = open(os.path.join(HERE, "..", f)).read()
            if "grant_helper" not in f:           # the helper reads only SUDO_TTY and SUDO_USER, set by sudo itself
                self.assertNotIn("os.environ", src, f)
            self.assertNotIn("HARNESS_GRANT", src)

    def test_apply_all_then_root_consume_then_files_away(self):
        import time
        first, _, _ = OS.request_file(self.home, "role_assign", OS.role_assign_events(self.h, "operator", self.a))
        now = time.time()
        acts = G.cmd_approve(self.cfg, TTY, io.StringIO("ab12\n"), io.StringIO(), now, G.ledger_id(self.cfg), rnd=lambda n: "ab12")
        self.assertEqual(len(acts), 1)
        tail = G.ledger_tail_seq(self.cfg)
        res = OS.apply_all(self.h)
        self.assertEqual([r["request"] for r in res], [first])
        self.assertEqual(G.consume_matched(self.cfg, acts, tail, now), [f"{acts[0]['id']}: consumed 1 event(s)"])
        self.assertEqual(self.h.state().role_holder("operator"), self.a)
        OS.apply_all(self.h, file_only=True)
        pend = os.path.join(self.home, "_harness", "operator-pending")
        self.assertTrue(os.path.exists(os.path.join(pend, "done", first + ".json")))
        self.assertFalse(os.path.exists(os.path.join(pend, first + ".json")))
        self.assertEqual(OS.apply_all(self.h), [])
        self.assertEqual(V.audit(self.cfg["ledger"], self.cfg["log"], self.cfg["pub"]), [])

    def test_file_only_never_applies(self):
        rid, _, _ = OS.request_file(self.home, "role_assign", OS.role_assign_events(self.h, "operator", self.a))
        import time
        G.cmd_approve(self.cfg, TTY, io.StringIO("ab12\n"), io.StringIO(), time.time(), G.ledger_id(self.cfg), rnd=lambda n: "ab12")
        self.assertEqual(OS.apply_all(self.h, file_only=True), [])
        self.assertIsNone(self.h.state().role_holder("operator"))

    def test_apply_without_grant_refused(self):
        rid, _, _ = OS.request_file(self.home, "role_assign", [{"type": "role.assigned", "data": {"role": "operator", "agent": self.a}}])
        with self.assertRaises(RuntimeError):
            OS.apply(self.h, rid)

    def test_break_glass_flag_turns_gate_off(self):
        open(OS.FLAG, "w").close()
        self.assertFalse(OS.gate_on())

    def test_cli_has_no_password_or_sudo_prompt(self):
        src = open(os.path.join(HERE, "..", "scripts", "operator_sign.py")).read()
        for w in ("getpass", "input(", "sudo\", \"-S", "-S\""):
            self.assertNotIn(w, src)

    def test_scripts_notices_are_not_sent_as_the_operator(self):
        """The daily Hatstand check and the drift notice run unattended; a send as the operator needs his signature once the seat is installed."""
        import re
        for f in ("harness.py", "hatstand_check.py", "compress.py"):
            src = open(os.path.join(HERE, "..", "scripts", f)).read()
            self.assertIsNone(re.search(r'\.send\(\s*"(operator|human)"', src), f)
            self.assertNotIn('else "operator",', src, f)   # a human/operator actor falls back to the system sender, never to the operator


if __name__ == "__main__":
    unittest.main()
