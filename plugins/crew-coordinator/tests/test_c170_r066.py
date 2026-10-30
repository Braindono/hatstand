"""cc 0.17.0 R-066 lessons: kind=note + tag lesson with a three-field body; the restore digest shows the newest N for the
role, fenced and capped, from curator or operator records only (critic 8); docs/lessons.md becomes a generated view; a
one-time import of the old table. Spec: skill-curation/specs/2026-10-24-stage2-context-loss.md section 7.
Run: python3 -B tests/test_c170_r066.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _env  # noqa: F401  isolate HOME and HARNESS_* first
import contextlib, io, json, os, sys, tempfile, unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
import harness as H
from corpus import est_tokens

MODEL = "claude-opus-5-5"
BODY = "What happened: {w}\nCause: a cause\nRule: {r}"
TABLE = """# Harness lessons

| # | Found by, date | What happened | Cause | Rule to apply |
|---|---|---|---|---|
| L-001 | envoy, 2026-10-23 | Called a split a failed cutover | Took a pattern as proof | Search the corpus for a decision first |
| L-002 | ops-coder, 2026-10-23 | Shipped an alias change that flooded unread | Fresh-ledger tests only | Compare live-ledger counts before and after |
"""


class Lessons(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.home = os.path.join(self.tmp, "Exchange")
        os.makedirs(os.path.join(self.home, "_harness"))
        e = mock.patch.dict(os.environ, {"HARNESS_STATE_CACHE": "0"})
        e.start()
        self.addCleanup(e.stop)
        self.h = H.Harness(self.home)
        self.ids = {}
        for role in ("curator", "ops-coder", "envoy"):
            self.h.role_define("operator", role, "harness-ops")
            a = self.h.register(project="harness-ops", model=MODEL)["id"]
            self.h.role_assign("operator", role, a)
            self.ids[role] = a

    def lesson(self, by, what, rule, roles=("all",), body=None):
        return self.h.record(self.ids[by], "note", "Lesson: " + what, body or BODY.format(w=what, r=rule),
                             ["lesson"] + ["role:" + r for r in roles])

    def section(self, role):
        d = self.h.restore_digest(self.h.state(), self.ids[role], role, [])
        return d.split("▸ Lessons", 1)[1].split("\n▸ ", 1)[0] if "▸ Lessons" in d else None

    def test_fields_parse(self):
        f = H.lesson_fields("intro\nWHAT HAPPENED: x\ncause:  y \nRule: z\nRule: second")
        self.assertEqual(f, {"What happened": "x", "Cause": "y", "Rule": "z"})
        self.assertEqual(H.lesson_fields("Rule:"), {})

    def test_template_warns_but_never_rejects(self):
        r = self.lesson("ops-coder", "free text", "", body="What happened: only this one line")
        self.assertIn("id", r)
        self.assertIn("lacks 'Cause:', 'Rule:'", r["warn"])
        with self.assertRaises(H.HarnessError):   # 0.19.0 (D-4de9e): a line that is not a field line is refused
            self.lesson("ops-coder", "free text", "", body="I did a thing wrong")
        self.assertNotIn("warn", self.lesson("ops-coder", "ok", "a rule"))

    def cur(self, *ids):
        """0.19.0 (R-122): a lesson reaches a digest only after the operator's grant of the curator's proposal."""
        r = self.h.lesson_curate_propose(self.ids["curator"], list(ids))
        return self.h.approve(r["pending"], "cli-tty", self.h._approval_records()[r["pending"]]["args_digest"][:4], True)

    def test_only_curated_lessons_reach_a_digest_whoever_wrote_them(self):
        a = self.lesson("ops-coder", "agent lesson", "agent rule")
        self.assertNotIn("agent rule", self.section("ops-coder") or "")
        self.assertIn("1 uncurated lesson waits", self.section("ops-coder"))
        self.cur(a["id"])
        sec = self.section("ops-coder")
        self.assertIn("rule: agent rule", sec)
        self.assertIn("⟦lesson approved by the operator, proposed by curator", sec)
        self.assertNotIn("⟦untrusted from peers", sec)

    def test_operator_seat_gets_only_role_operator_lessons(self):
        self.h.role_define("operator", "operator", "harness-ops")
        op = self.h.register(project="harness-ops", model=MODEL)["id"]
        self.h.role_assign("operator", "operator", op)
        self.ids["operator"] = op
        a = self.lesson("curator", "agent conduct", "agents only")
        b = self.lesson("curator", "for the seat", "operator rule", roles=("operator",))
        self.cur(a["id"], b["id"])
        sec = self.section("operator")
        self.assertIn("operator rule", sec)
        self.assertNotIn("agents only", sec)
        self.assertLessEqual(est_tokens("▸ Lessons" + sec), 110)

    def test_role_tags_select(self):
        a = self.lesson("curator", "for envoy", "envoy only", roles=("envoy",))
        self.cur(a["id"])
        self.assertNotIn("envoy only", self.section("ops-coder") or "")
        self.assertIn("envoy only", self.section("envoy"))

    def test_newest_n_and_whole_section_within_cap(self):
        ids = [self.lesson("curator", "case %d" % k, ("rule %d " % k) + "long words " * 10)["id"] for k in range(8)]
        self.cur(*ids[-3:])
        sec = self.section("ops-coder")
        self.assertLessEqual(est_tokens("▸ Lessons" + sec), 110)    # heading, fence, more-line and count line inside the cap
        self.assertIn("rule 7", sec)
        self.assertNotIn("rule 5", sec)                             # newest 2 at most
        self.assertNotIn("[digest cut", self.h.restore_digest(self.h.state(), self.ids["ops-coder"], "ops-coder", []))
        with open(os.path.join(self.home, "_harness", "config.json"), "w") as f:
            json.dump({"restore_lessons": 0}, f)
        self.assertIsNone(self.section("ops-coder"))

    def test_superseded_or_incomplete_lessons_hidden(self):
        old = self.lesson("curator", "old", "old rule")
        new = self.h.record(self.ids["curator"], "note", "Lesson: new", BODY.format(w="new", r="new rule"), ["lesson", "role:all"],
                            supersedes=old["id"])
        half = self.h.record(self.ids["curator"], "note", "Lesson: half", "What happened: x\nRule: y", ["lesson", "role:all"])
        self.cur(new["id"])
        with self.assertRaises(H.HarnessError):
            self.cur(half["id"])                                    # incomplete: not a live, complete lesson
        sec = self.section("ops-coder")
        self.assertIn("new rule", sec)
        self.assertNotIn("old rule", sec)
        self.assertNotIn("half", sec)

    def test_view_is_generated_from_curated_records(self):
        a = self.lesson("curator", "a | piped", "rule A")
        self.lesson("ops-coder", "hidden", "rule B")
        self.cur(a["id"])
        v = self.h.lessons_view()
        self.assertTrue(v.startswith("# Harness lessons (GENERATED"))
        self.assertIn("| a / piped | a cause | rule A |", v)
        self.assertNotIn("rule B", v)
        out = os.path.join(self.tmp, "lessons.md")
        with contextlib.redirect_stdout(io.StringIO()):
            H.main(["--home", self.home, "lessons-view", "--out", out])
        self.assertEqual(open(out).read(), v)
        self.assertEqual(os.stat(out).st_mode & 0o777, 0o600)

    def test_import_dry_run_apply_and_rerun(self):
        p = os.path.join(self.tmp, "old.md")
        with open(p, "w") as f:
            f.write(TABLE)
        with self.assertRaises(H.HarnessError):
            self.h.lessons_import(self.ids["ops-coder"], p)
        dry = self.h.lessons_import(self.ids["curator"], p)
        self.assertEqual(len(dry["planned"]), 2)
        self.assertEqual(self.h.corpus.tagged_notes("lesson"), [])
        r = self.h.lessons_import(self.ids["curator"], p, dry_run=False)
        self.assertEqual(len(r["recorded"]), 2)
        self.assertEqual(self.h.lessons_import(self.ids["curator"], p, dry_run=False), {"recorded": [], "skipped": ["L-001", "L-002"]})
        self.assertNotIn("Compare live-ledger counts", self.section("ops-coder"))      # imported, not yet curated by the operator
        self.cur(*r["recorded"])
        self.assertIn("Compare live-ledger counts", self.section("ops-coder"))
        self.assertIn("L-002 (ops-coder, 2026-10-23)", self.h.corpus.get([r["recorded"][1]])[0])


if __name__ == "__main__":
    unittest.main()
