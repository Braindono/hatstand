"""cc 0.15.5 WP3: corpus retag op (harness side). Run: python3 -B tests/test_cc155_retag.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _env  # noqa: F401  isolate HOME and HARNESS_* first
import json, os, subprocess, sys, unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
import harness as H
import mcp_server as M
from test_cc151_w1 import Base, MODEL


class RetagBase(Base):
    def setUp(self):
        super().setUp()
        for role, proj in (("corpus-envoy", "orch"), ("cv-lead", "cv-management"), ("orch-lead", "orch"), ("other-lead", "design")):
            self.h.role_define("operator", role, proj)
        self.envoy = self.agent("corpus-envoy", "orch")
        self.cv = self.agent("cv-lead", "cv-management")
        self.orch = self.agent("orch-lead", "orch")
        self.other = self.agent("other-lead", "design")
        self.e_orch = self.h.record(self.orch, "decision", "orch rule", "keep it terse")["id"]
        # an old entry with no project and no role (a logged event whose actor had no project)
        self.legacy = "N-0aaaa"
        self.h.store.append("corpus.recorded", "legacy-agent", {
            "id": self.legacy, "kind": "note", "title": "legacy untagged", "body": "no project here", "tags": [],
            "project": None, "refs": [], "supersedes": None, "offload": False, "sha": None, "model": "unknown",
            "role": None, "tier": "ephemeral", "expires": None})
        self.h.corpus.refresh()

    def meta(self, i):
        return self.h.corpus.entry_meta(i)

    def events(self):
        return self.types("corpus.retagged")


class Basics(RetagBase):
    def test_envoy_retags_untagged_entry(self):
        self.assertEqual(self.meta(self.legacy)["project"], "")
        r = self.h.retag(self.envoy, self.legacy, "cv-management", "cv-lead")
        self.assertTrue(r["retagged"])
        m = self.meta(self.legacy)
        self.assertEqual((m["project"], m["role"]), ("cv-management", "cv-lead"))
        ev = self.events()
        self.assertEqual(len(ev), 1)
        d = ev[0]["data"]
        self.assertEqual((d["id"], d["old_project"], d["new_project"], d["new_role"], d["by"]),
                         (self.legacy, "", "cv-management", "cv-lead", self.envoy))
        self.assertIn(self.legacy, [x["id"] for x in self.h.corpus.search(None, project="cv-management", limit=20)])

    def test_role_omitted_keeps_role(self):
        self.h.retag(self.envoy, self.e_orch, "cv-management")
        m = self.meta(self.e_orch)
        self.assertEqual((m["project"], m["role"]), ("cv-management", "orch-lead"))

    def test_latest_of_two_wins(self):
        self.h.retag(self.envoy, self.legacy, "cv-management")
        self.h.retag(self.envoy, self.legacy, "design", "other-lead")
        self.assertEqual(self.meta(self.legacy)["project"], "design")
        self.assertEqual(len(self.events()), 2)

    def test_archived_and_pinned_state_kept(self):
        self.h.pin("operator", [self.e_orch], True, '"keep it terse"')
        self.h.corpus.refresh()
        self.h.retag(self.envoy, self.e_orch, "cv-management")
        m = self.meta(self.e_orch)
        self.assertTrue(m["pinned"])
        n = self.h.record(self.orch, "note", "to archive", "archive me please now")["id"]
        self.h.archive("operator", [n], '"archive me please now"')
        self.h.retag(self.envoy, n, "cv-management")
        self.assertTrue(self.meta(n)["archived"])

    def test_moves_between_project_totals(self):
        before = {p: len(self.h.corpus.search(None, project=p, limit=100)) for p in ("orch", "cv-management")}
        self.h.retag(self.envoy, self.e_orch, "cv-management")
        after = {p: len(self.h.corpus.search(None, project=p, limit=100)) for p in ("orch", "cv-management")}
        self.assertEqual(after["orch"], before["orch"] - 1)
        self.assertEqual(after["cv-management"], before["cv-management"] + 1)

    def test_rebuild_from_the_log_keeps_the_retag(self):
        self.h.retag(self.envoy, self.legacy, "cv-management", "cv-lead")
        c = self.h.corpus
        c.db.execute("DELETE FROM entries WHERE source='log'")
        c._meta("last_seq", 0)
        c.refresh()
        m = self.meta(self.legacy)
        self.assertEqual((m["project"], m["role"]), ("cv-management", "cv-lead"))

    def test_chain_verifies_and_export_has_the_event(self):
        self.h.retag(self.envoy, self.legacy, "cv-management")
        v = self.h.verify()
        self.assertTrue(v.get("ok", True), v)
        out = os.path.join(self.home, "exp.jsonl")
        self.h.export(out)
        self.assertIn("corpus.retagged", open(out).read())


class Rejections(RetagBase):
    def test_unknown_entry_project_role(self):
        n = len(self.h.store.read_all())
        for args in (("N-ffffff", "orch"), (self.legacy, "no-such-project"), (self.legacy, "orch", "no-such-role"), (self.legacy, "")):
            with self.assertRaises(H.HarnessError):
                self.h.retag(self.envoy, *args)
        self.assertEqual(len(self.h.store.read_all()), n)

    def test_noop_is_an_error_not_an_event(self):
        with self.assertRaisesRegex(H.HarnessError, "no change"):
            self.h.retag(self.envoy, self.e_orch, "orch")
        with self.assertRaisesRegex(H.HarnessError, "no change"):
            self.h.retag(self.envoy, self.e_orch, "orch", "orch-lead")
        self.assertEqual(self.events(), [])

    def test_dry_run_writes_nothing(self):
        n = len(self.h.store.read_all())
        r = self.h.retag(self.envoy, self.legacy, "cv-management", "cv-lead", dry_run=True)
        self.assertTrue(r["dry_run"])
        self.assertIn("-> cv-management/cv-lead", r["change"])
        self.assertEqual(len(self.h.store.read_all()), n)
        d = self.h.retag(self.other, self.legacy, "cv-management", dry_run=True)
        self.assertIn("needs operator approval", d["authority"])

    def test_bad_refs(self):
        for ref in ("m-000000000000", "D-00000", "garbage"):
            with self.assertRaises(H.HarnessError):
                self.h.retag(self.envoy, self.legacy, "cv-management", ref=ref)
        self.assertEqual(self.events(), [])


class Authority(RetagBase):
    def msg(self, frm, body="ok, move it"):
        return self.h.send(frm, "operator", body)["id"]

    def test_unauthorised_is_gated_and_becomes_an_approval(self):
        with self.assertRaises(H.RetagGate):
            self.h.retag(self.other, self.e_orch, "design")
        r = self.adm("retag", self.other, entry=self.e_orch, project="design")
        self.assertIn("pending", r)
        self.assertEqual(self.events(), [])
        done = self.approve(r["pending"])
        self.assertEqual(done["state"], "granted", done)
        self.assertEqual(self.meta(self.e_orch)["project"], "design")
        self.assertEqual(self.events()[0]["data"]["by"], "operator")

    def test_pending_card_shows_old_to_new(self):
        r = self.adm("retag", self.other, entry=self.e_orch, project="design")
        rec = self.h._approval_records()[r["pending"]]
        self.assertEqual(self.h.approval_change(rec["action"], rec["args"]), "change: orch/orch-lead -> design/orch-lead")

    def test_owning_project_role_direct(self):
        r = self.adm("retag", self.orch, entry=self.e_orch, project="cv-management")
        self.assertTrue(r.get("retagged"), r)

    def test_target_role_needs_ref_from_owner_or_operator(self):
        with self.assertRaises(H.RetagGate):
            self.h.retag(self.cv, self.e_orch, "cv-management")                       # no ref
        bad = self.msg(self.other)
        with self.assertRaises(H.RetagGate):
            self.h.retag(self.cv, self.e_orch, "cv-management", ref=bad)              # not from the owner
        good = self.msg(self.orch)
        r = self.h.retag(self.cv, self.e_orch, "cv-management", ref=good)
        self.assertTrue(r["retagged"])
        self.assertEqual(self.events()[-1]["data"]["ref"], good)

    def test_no_project_entry_needs_envoy_or_operator_ref(self):
        with self.assertRaises(H.RetagGate):
            self.h.retag(self.cv, self.legacy, "cv-management", ref=self.msg(self.orch))
        r = self.h.retag(self.cv, self.legacy, "cv-management", ref=self.msg(self.envoy))
        self.assertTrue(r["retagged"])

    def test_operator_ref_counts(self):
        # a message from the operator: appended as the human actor
        self.h.store.append("message.sent", "human", {"id": "m-0123456789ab", "thread": "t-0123456789", "hop": 0, "from": "human",
                            "to": [self.cv], "to_resolved": [self.cv], "kind": "message", "subject": "ok", "body": "move it",
                            "priority": "normal", "refs": [], "parent": None, "expects_reply": False})
        r = self.h.retag(self.cv, self.e_orch, "cv-management", ref="m-0123456789ab")
        self.assertTrue(r["retagged"])

    def test_envoy_default_has_retag_and_agents_cannot_widen_by_argument(self):
        self.assertIn("retag", H.curation_roles(self.home)["envoy"])
        with self.assertRaisesRegex(H.HarnessError, "not accepted over MCP"):
            self.adm("retag", self.other, entry=self.e_orch, project="design", by="operator")


class Handler(RetagBase):
    def test_bad_events_are_skipped_never_raise(self):
        base = {"id": self.legacy, "old_project": "", "old_role": "", "new_project": "design", "new_role": None, "ref": None, "ts": "x"}
        for d in (dict(base, by=None), dict(base, id=None), dict(base, new_project=""), dict(base, id="N-unknown", by="x")):
            self.h.store.append("corpus.retagged", "human", d)
        self.h.corpus.refresh()
        self.assertEqual(self.meta(self.legacy)["project"], "")
        self.assertIsNone(self.meta("N-unknown"))

    def test_cli_dry_run(self):
        env = dict(os.environ, HARNESS_HOME=self.home, PYTHONDONTWRITEBYTECODE="1")
        out = subprocess.run([sys.executable, os.path.join(HERE, "..", "scripts", "harness.py"), "retag", "--agent", self.envoy[:8],
                              "--entry", self.legacy, "--project", "cv-management", "--dry-run"],
                             capture_output=True, text=True, env=env, stdin=subprocess.DEVNULL)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("dry_run", out.stdout)
        self.assertEqual(self.events(), [])


if __name__ == "__main__":
    unittest.main()
