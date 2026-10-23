"""cc 0.16.2 harness bits: handoff untagged-asks warning, recall kind=transcript, health transcripts line.
Run: python3 -B tests/test_cc162_harness.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _env  # noqa: F401  isolate HOME and HARNESS_* first
import json, os, sys, tempfile, time, unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
import harness as H
import health as HL
import mcp_server as M
import transcript_indexer as T

MODEL = "claude-sonnet-5-5"
SID = "abcdef12-3333-4444-5555-666677778888"


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.home = os.path.join(self.tmp, "home")
        self.root = os.path.join(self.tmp, "Transcripts")
        self.cache = os.path.join(self.tmp, "cache")
        os.makedirs(self.home)
        e = mock.patch.dict(os.environ, {"INDEXER_ROOT": self.root, "INDEXER_CACHE": self.cache})
        e.start()
        self.addCleanup(e.stop)
        self.h = H.Harness(self.home)
        self.h.role_define("operator", "curator", "p")
        self.a = self.h.register(project="p", model=MODEL, role="curator", session_id=SID)["id"]
        M.BOUND.update(home=None, id=None)

    def vault(self, asks):
        os.makedirs(self.root, exist_ok=True)
        ts = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(time.time() + 5))
        body = "".join(f"### operator {ts}\n> ask number {i} walrus\n\n" for i in range(asks))
        open(os.path.join(self.root, f"2026-10-23-proj-{SID[:8]}.md"), "w").write("# t\n\n" + body)


class HandoffWarn(Base):
    def cap(self, tags):
        lines = "".join(f"- [{t}] ask {i}\n" for i, t in enumerate(tags))
        return f"---\nhandoff: p/x\nstatus: open\n---\n# Handoff\n\n## 0. Bootstrap\nnone\n\n## Asks\n{lines}"

    def test_warns_when_asks_exceed_tagged(self):
        self.vault(3)
        r = self.h.handoff(self.a, self.cap(["done"]), None, False, None)
        self.assertIn("2 of 3 operator asks", r["warn"])
        self.assertIn("warning only", r["text"])
        self.assertIn("capsule", r)                       # never blocks the handoff

    def test_quiet_when_all_tagged_or_no_vault(self):
        self.vault(2)
        self.assertNotIn("warn", self.h.handoff(self.a, self.cap(["done", "open"]), None, False, None))

    def test_no_vault_no_warning(self):
        self.assertNotIn("warn", self.h.handoff(self.a, self.cap([]), None, False, None))


class Recall(Base):
    def seed(self):
        self.ix = T.Indexer(root=self.root, cache=self.cache, source=os.path.join(self.tmp, "src"), ledger=False)
        db = self.ix._db()
        db.execute("INSERT INTO t(text, role, session, ts, project) VALUES (?,?,?,?,?)",
                   ("the walrus plan is approved", "operator", SID, "2026-10-23 10:00:00", "p"))
        db.commit()
        db.close()

    def test_curator_gets_fenced_cards(self):
        self.seed()
        r = M.call(self.h, "harness_recall", {"kind": "transcript", "query": "walrus", "agent": self.a})
        self.assertIn("walrus", r["text"])
        self.assertIn("untrusted", r["text"])
        self.assertIn(H.FENCE_OPEN, r["text"])

    def test_other_roles_refused(self):
        self.seed()
        b = self.h.register(project="p", model=MODEL)["id"]
        with self.assertRaisesRegex(H.HarnessError, "allowed for roles"):
            M.call(self.h, "harness_recall", {"kind": "transcript", "query": "walrus", "agent": b})

    def test_no_agent_no_query_refused(self):
        with self.assertRaises(H.HarnessError):
            M.call(self.h, "harness_recall", {"kind": "transcript", "query": "x"})
        with self.assertRaisesRegex(H.HarnessError, "query required"):
            M.call(self.h, "harness_recall", {"kind": "transcript", "agent": self.a})

    def test_normal_recall_unaffected(self):
        M.call(self.h, "harness_recall", {"query": "anything"})


class Health(Base):
    def test_line_absent_without_indexer_and_present_with(self):
        self.assertIsNone(HL._transcripts(self.h))
        os.makedirs(self.cache)
        json.dump({"files": {"a": {}, "b": {}}, "counters": {"last_run": time.time() - 120, "dropped_error": 1, "denied": 14, "bad_lines": 0}},
                  open(os.path.join(self.cache, "state.json"), "w"))
        d = HL.health(self.h)
        txt = HL.text(d)
        self.assertIn("transcripts: 2 files", txt)
        self.assertIn("redaction failures 1", txt)
        self.assertIn("denied sessions 14", txt)
        self.assertIn("▲ transcripts", txt)               # a redaction failure raises the flag

    def test_stale_run_flagged(self):
        os.makedirs(self.cache)
        json.dump({"files": {}, "counters": {"last_run": time.time() - 3600}}, open(os.path.join(self.cache, "state.json"), "w"))
        self.assertIn("▲ transcripts", HL.text(HL.health(self.h)))


if __name__ == "__main__":
    unittest.main()
