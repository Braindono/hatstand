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
        r = self.lesson("ops-coder", "free text", "", body="I did a thing wrong")
        self.assertIn("id", r)
        self.assertIn("lacks 'What happened:', 'Cause:', 'Rule:'", r["warn"])
        self.assertNotIn("warn", self.lesson("ops-coder", "ok", "a rule"))

    def test_only_curator_or_operator_lessons_reach_a_digest(self):
        self.lesson("ops-coder", "agent lesson", "agent rule")
        self.assertIsNone(self.section("ops-coder"))
        self.lesson("curator", "curator lesson", "curator rule")
        sec = self.section("ops-coder")
        self.assertIn("rule: curator rule", sec)
        self.assertNotIn("agent rule", sec)
        self.assertIn("⟦untrusted from peers", sec)

    def test_operator_seat_gets_only_role_operator_lessons(self):
        self.h.role_define("operator", "operator", "harness-ops")
        op = self.h.register(project="harness-ops", model=MODEL)["id"]
        self.h.role_assign("operator", "operator", op)
        self.ids["operator"] = op
        self.lesson("curator", "agent conduct", "agents only")
        self.assertIsNone(self.section("operator"))                 # role:all = agent roles
        self.lesson("curator", "for the seat", "operator rule", roles=("operator",))
        sec = self.section("operator")
        self.assertIn("operator rule", sec)
        self.assertNotIn("agents only", sec)
        self.assertLessEqual(est_tokens("▸ Lessons" + sec), 90)

    def test_role_tags_select(self):
        self.lesson("curator", "for envoy", "envoy only", roles=("envoy",))
        self.assertIsNone(self.section("ops-coder"))
        self.assertIn("envoy only", self.section("envoy"))

    def test_newest_n_and_whole_section_within_cap(self):
        for k in range(8):
            self.lesson("curator", "case %d" % k, ("rule %d " % k) + "long words " * 20)
        sec = self.section("ops-coder")
        self.assertLessEqual(est_tokens("▸ Lessons" + sec), 90)    # heading, fence and more-line inside the cap
        self.assertIn("rule 7", sec)
        self.assertNotIn("rule 4", sec)                             # newest 3 at most
        self.assertNotIn("[digest cut", self.h.restore_digest(self.h.state(), self.ids["ops-coder"], "ops-coder", []))
        with open(os.path.join(self.home, "_harness", "config.json"), "w") as f:
            json.dump({"restore_lessons": 0}, f)
        self.assertIsNone(self.section("ops-coder"))

    def test_superseded_or_incomplete_lessons_hidden(self):
        old = self.lesson("curator", "old", "old rule")
        self.h.record(self.ids["curator"], "note", "Lesson: new", BODY.format(w="new", r="new rule"), ["lesson", "role:all"],
                      supersedes=old["id"])
        self.h.record(self.ids["curator"], "note", "Lesson: half", "What happened: x\nRule: y", ["lesson", "role:all"])
        sec = self.section("ops-coder")
        self.assertIn("new rule", sec)
        self.assertNotIn("old rule", sec)
        self.assertNotIn("half", sec)

    def test_view_is_generated_from_curator_records(self):
        self.lesson("curator", "a | piped", "rule A")
        self.lesson("ops-coder", "hidden", "rule B")
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
        sec = self.section("ops-coder")
        self.assertIn("Compare live-ledger counts", sec)
        self.assertIn("L-002 (ops-coder, 2026-10-23)", self.h.corpus.get([r["recorded"][1]])[0])


if __name__ == "__main__":
    unittest.main()
