"""cc 0.17.0 R-041 ruled-out: kind=note + tag ruled-out with Option / Reason / Decision lines (no new kind); its own
recall tier labelled "rejected, not advice"; orphans (decision superseded, archived or missing) listed for the steward.
Spec: skill-curation/specs/2026-10-24-stage2-context-loss.md section 8. Run: python3 -B tests/test_c170_r041.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _env  # noqa: F401  isolate HOME and HARNESS_* first
import contextlib, io, json, os, sys, tempfile, unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
import harness as H
import mcp_server as M

MODEL = "claude-opus-5-5"


class RuledOut(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.home = os.path.join(self.tmp, "Exchange")
        os.makedirs(os.path.join(self.home, "_harness"))
        e = mock.patch.dict(os.environ, {"HARNESS_STATE_CACHE": "0"})
        e.start()
        self.addCleanup(e.stop)
        self.h = H.Harness(self.home)
        self.a = self.h.register(project="harness-ops", model=MODEL)["id"]
        self.dec = self.h.record(self.a, "decision", "Use a vault folder under Exchange", "body")["id"]

    def ro(self, option, reason, decision=None, **kw):
        body = f"Option: {option}\nReason: {reason}\nDecision: {decision or self.dec}"
        return self.h.record(self.a, "note", f"Ruled out: {option}", body, ["ruled-out", "vault"], **kw)

    def test_fields_required_and_decision_must_exist(self):
        for body in ("Option: x\nReason: y", "Reason: y\nDecision: " + "D-12345", "free text"):
            with self.assertRaises(H.HarnessError):
                self.h.record(self.a, "note", "Ruled out", body, ["ruled-out"])
        with self.assertRaises(H.HarnessError) as cm:
            self.ro("sqlite as source of truth", "corrupts on shared mounts", decision="D-00000")
        self.assertIn("existing corpus id", str(cm.exception))
        self.assertEqual(self.h.corpus.tagged_notes("ruled-out"), [])

    def test_decision_added_to_refs(self):
        r = self.ro("sqlite as source of truth", "corrupts on shared mounts")
        ev = [e for e in self.h.store.read_all() if e["type"] == "corpus.recorded" and e["data"]["id"] == r["id"]][0]
        self.assertIn(self.dec, ev["data"]["refs"])

    def test_own_tier_and_label(self):
        self.ro("sqlite as source of truth", "corrupts on shared mounts")
        plain = self.h.recall("sqlite source truth")["text"]
        self.assertIn("(no matches)", plain)                                   # not in ordinary search
        t = self.h.recall("sqlite", tags=["ruled-out"])["text"]
        self.assertIn("REJECTED, not advice · N-", t)
        self.assertIn("1 in corpus", t)
        self.assertIn("REJECTED, not advice", self.h.recall(kind="ruled-out")["text"])
        rid = self.h.corpus.tagged_notes("ruled-out")[0]["id"]
        self.assertTrue(self.h.recall(ids=[rid])["text"].startswith("REJECTED, not advice · " + rid))
        r = M._call(self.h, "harness_recall", {"agent": self.a, "tags": ["ruled-out"]})
        self.assertIn("REJECTED, not advice", r["text"])

    def test_other_notes_unaffected(self):
        self.h.record(self.a, "note", "A sqlite note", "sqlite is fine for the per-host cache", ["vault"])
        self.ro("sqlite as source of truth", "corrupts on shared mounts")
        t = self.h.recall("sqlite")["text"]
        self.assertIn("A sqlite note", t)
        self.assertNotIn("REJECTED", t)

    def test_orphans_listed_when_decision_superseded_or_archived(self):
        self.ro("live one", "reason")
        self.assertEqual(self.h.ruled_out_orphans(), [])
        new = self.h.record(self.a, "decision", "Vault under Exchange, v2", "body2", supersedes=self.dec)["id"]
        self.assertTrue(new)
        o = self.h.ruled_out_orphans()
        self.assertEqual([(x["decision"], x["state"]) for x in o], [(self.dec, "superseded")])
        with contextlib.redirect_stdout(io.StringIO()) as out:
            H.main(["--home", self.home, "ruled-out-orphans"])
        self.assertIn(self.dec, out.getvalue())


if __name__ == "__main__":
    unittest.main()
