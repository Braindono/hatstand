"""cc 0.24.0 item 1 (scope A-b2950; build spec 2026-11-10_cc024-hook2-ids-build-spec.md v1.1; design hook-2-real-record-ids.md v2.1):
record ids must be real, a server check on agent writes. F1-F4, F6-F14 as numbered there; F5 (replay of the real ledger, seqs 1 to
27,400) runs outside this suite, because ledger lines may not enter the plugin tree (D-c92cb); its result is in the hand-back.
Each test but the guards fails on 0.23.0.
Run: python3 -B tests/test_c240_ids.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _env  # noqa: F401  isolate HOME and HARNESS_* first
import os, time, unittest
from unittest import mock

import test_c220_nudge as C
from test_c220_nudge import H, M

REFUSED = r"Unknown id\(s\): "


class Ids(C.Base):
    def setUp(self):
        super().setUp()
        for r in ("harness-critic", "ops-coder"):
            self.h.role_define("operator", r, "harness-ops", carry="none")
        self.env = self.reg("envoy", "local_env")
        self.dec = self.h.record(self.env, "decision", "a real decision", "body")["id"]
        self.note = self.h.record(self.env, "note", "a real note", "body")["id"]

    def send(self, body, **kw):
        a = dict({"agent": self.env, "to": "role:curator", "body": body}, **kw)
        return self.call("harness_send", **a)

    def refused(self, body, **kw):
        n = len(self.events("message.sent"))
        with self.assertRaisesRegex(H.HarnessError, REFUSED):
            self.send(body, **kw)
        self.assertEqual(len(self.events("message.sent")), n)        # nothing written

    def rec(self, body, **kw):
        a = dict({"agent": self.env, "kind": "note", "title": "t", "body": body}, **kw)
        return self.call("harness_record", **a)

    def flags(self, reason=None):
        return [e["data"] for e in self.events("ids.unverified") if reason is None or e["data"]["reason"] == reason]

    # F1 placeholders and look-alikes
    def test_f1_lookalikes_pass_placeholders_are_refused(self):
        self.assertTrue(self.send(f"decision {self.dec}; Pinned by SHA-256; K-means; N-gram").get("id"))
        for bad in ("see N-number", "id m-?", "per D-...", "per N-…"):
            with self.subTest(body=bad):
                self.refused(bad)
        with self.assertRaisesRegex(H.HarnessError, r"An id not known yet: write it in backticks or quotes \(`D-\?`\)"):
            self.send("asked m-…")                                                  # critic read 1: say how to write it
        self.assertTrue(self.send("asked `m-…` and \"D-?\"").get("id"))

    # F2 an old real id passes after a big ledger
    def test_f2_old_real_id_passes(self):
        for _ in range(5):
            self.h.store.append("test.filler", "system", {"pad": "x" * 500000})
        self.assertTrue(self.send(f"old one: {self.dec}").get("id"))

    # F3 a fake id stays fake after its first mention
    def test_f3_fake_stays_fake(self):
        self.refused("see D-abcde")
        self.assertTrue(self.send('the bad id was "D-abcde"').get("id"))        # quoted: allowed, and it creates nothing
        self.refused("see D-abcde")

    # F4 quoted correction passes; unquoted needs the override line
    def test_f4_quotes_code_and_override(self):
        self.assertTrue(self.send('you wrote "N-a8ea1?"; the right one is ' + self.note).get("id"))
        self.assertTrue(self.send("in code `N-a8ea1` and\n```\nD-00000\n```").get("id"))
        self.refused("you wrote N-a8ea1, the right one is " + self.note)
        r = self.send("you wrote N-a8ea1\nids-unverified: quoting the bad id")
        self.assertTrue(r.get("id"))
        f = self.flags()[-1]
        self.assertEqual((f["call"], f["ref"], f["ids"], f["reason"], f["note"]), ("send", r["id"], ["N-a8ea1"], "override", "quoting the bad id"))

    def test_f4_a_long_quote_is_not_exempt(self):
        self.refused('"' + "x" * 81 + ' D-abcde"')

    # F6 m- and t- ids
    def test_f6_message_and_thread_ids(self):
        m = self.send("first")
        self.assertTrue(self.send(f"re {m['id']} on {m['thread']}").get("id"))
        self.refused("re m-0123456789ab")
        self.refused("on t-0123456789")

    # F7 a riding state note is written and flagged, never refused
    def test_f7_state_note_on_a_send_is_flagged(self):
        r = self.send("plain body", state_note="state: next is D-fffff")
        self.assertTrue(r.get("id"))
        self.assertIn("Unknown id(s) flagged: D-fffff", r["state_note"])
        f = self.flags("flagged")[-1]
        self.assertEqual((f["call"], f["ids"]), ("state_note", ["D-fffff"]))
        self.assertTrue(f["ref"].startswith("C-"))                               # the note was written

    def test_f7_state_note_on_sync_is_flagged(self):
        r = self.call("harness_sync", agent=self.env, state_note="see N-00000")
        self.assertIn("Unknown id(s) flagged: N-00000", str(r))

    # F8 handoff: written and flagged
    def test_f8_handoff_with_a_fake_id(self):
        cap = "# capsule\nNext: finish D-eeeee and N-" + self.note[2:] + "\n"
        r = self.call("harness_handoff", agent=self.env, capsule_md=cap)
        self.assertTrue(os.path.isfile(os.path.join(self.home, r["capsule"])) or os.path.isfile(r["capsule"]))
        self.assertIn("Unknown id(s) flagged: D-eeeee", r["ids_flagged"])
        self.assertIn("Unknown id(s) flagged: D-eeeee", r.get("text", ""))
        fl = self.flags("flagged")
        self.assertEqual(len(fl), 1)
        self.assertEqual((fl[0]["call"], fl[0]["ids"]), ("handoff", ["D-eeeee"]))

    # F9 offload record flagged, plain record refused
    def test_f9_offload_flagged_plain_refused(self):
        r = self.rec("see D-ddddd", offload=True)
        self.assertTrue(r.get("id"))
        self.assertIn("Unknown id(s) flagged: D-ddddd", r["ids_flagged"])
        n = len(self.events("corpus.recorded"))
        with self.assertRaisesRegex(H.HarnessError, REFUSED + "D-ddddd"):
            self.rec("see D-ddddd")
        self.assertEqual(len(self.events("corpus.recorded")), n)
        self.assertTrue(self.rec(f"supersede it", supersedes=self.note, title="see " + self.note).get("id"))   # supersedes counts

    # F10 RD- ids
    def test_f10_rd_ids(self):
        self.refused("defect RD-12345")
        crit = self.reg("harness-critic", "local_crit")
        self.h.store.append("release.published", "human", {"name": "crew-coordinator", "version": "0.23.0", "kind": "plugin", "code": "c" * 64})
        rd = self.h.release_defect(crit, {"plugin": "crew-coordinator", "version": "0.23.0", "found_in": "runtime", "severity": "S3",
                                          "summary": "a gap"})["id"]
        self.assertTrue(self.send(f"defect {rd}").get("id"))

    # F11 an error in the check never blocks
    def test_f11_check_error_lets_the_call_through(self):
        with mock.patch.object(H.Harness, "ids_unknown", side_effect=RuntimeError("boom")):
            self.assertTrue(self.send("see D-abcde").get("id"))
        cf = [e["data"] for e in self.events("call.failed") if e["data"].get("tool") == "ids_check:send"]
        self.assertEqual(len(cf), 1)
        self.assertIn("RuntimeError: boom", cf[0]["error"])
        self.assertEqual(self.flags(), [])

    # F12 replay and the harness's own writes never check
    def test_f12_replay_and_internal_writes_write_nothing(self):
        self.h.send(self.env, "role:curator", "internal D-abcde")                   # no ids_check: a harness write
        self.h.record(self.env, "note", "t", "internal N-abcde")
        n = len(self.h.store.read_all())
        st = H.State(self.h.store.read_all())
        self.assertNotIn("D-abcde", st.known_ids)
        self.assertEqual(len(self.h.store.read_all()), n)
        self.assertEqual(self.flags(), [])

    # F13 override is counted in health; flagged is not
    def test_f13_override_counted_flagged_not(self):
        self.send("see N-12345\nids-unverified: test fixture")
        self.send("plain", state_note="riding D-54321")
        self.assertEqual([f["reason"] for f in self.flags()], ["override", "flagged"])
        txt = self.h.health()
        self.assertIn("ids-unverified overrides this week: 1", txt)
        self.h.store.append("ids.unverified", self.env, {"call": "send", "ref": None, "ids": ["N-1"], "reason": "Override"})
        self.h.store.append("ids.unverified", self.env, {"call": "send", "ref": None, "ids": ["N-1"], "reason": "override please"})
        self.assertIn("ids-unverified overrides this week: 1", self.h.health())      # exact match only

    # F14 archived and superseded entries stay real
    def test_f14_archived_and_superseded_stay_real(self):
        new = self.h.record(self.env, "decision", "replaces", "body", supersedes=self.dec)["id"]
        self.h.store.append("corpus.archived", "human", {"ids": [self.note], "reason": "test"})
        for body in (f"old decision {self.dec}", f"archived note {self.note}", f"new {new}"):
            with self.subTest(body=body):
                self.assertTrue(self.send(body).get("id"))
                self.assertTrue(self.rec(body).get("id"))
        self.assertEqual(self.flags(), [])

    def test_fix1_cli_record_checks_agents_not_the_operator(self):
        import contextlib, io
        seen = []
        with mock.patch.object(H.Harness, "record", autospec=True, side_effect=lambda *a, **k: seen.append(k.get("ids_check")) or {"id": "N-00000"}):
            for who in ("operator", "human", self.env):
                with contextlib.redirect_stdout(io.StringIO()):
                    H.main(["--home", self.home, "record", "--agent", who, "--kind", "note", "--title", "t", "--body", "see D-abcde"])
        self.assertEqual(seen, [False, False, True])
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            rc = H.main(["--home", self.home, "record", "--agent", self.env, "--kind", "note", "--title", "t", "--body", "see D-abcde"])
        self.assertNotIn("D-abcde", " ".join(e["data"].get("body", "") for e in self.events("corpus.recorded")))
        self.assertTrue(rc)                                                      # refused: a non-zero exit

    # guards
    def test_guard_operator_send_is_not_checked(self):
        self.assertTrue(self.h.send("operator", "role:envoy", "see D-abcde", ids_check=True).get("id"))

    def test_guard_hooks_json_unchanged(self):
        import hashlib
        p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "hooks", "hooks.json")
        self.assertEqual(hashlib.sha256(open(p, "rb").read()).hexdigest()[:12], HOOKS_JSON_023)


HOOKS_JSON_023 = "43cbd3620e41"   # sha256 first 12 of hooks/hooks.json: v0.23.0 e30459bce78a; 0.25.0 93642c97f444 (items 18, 27a, 32); 0.26.0 adds the virtue hook (item 20); 0.27.1 adds the mistake pointer hook and the correction hook


if __name__ == "__main__":
    unittest.main()
