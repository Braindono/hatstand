"""0.27.3 cluster C1 (capture fix, guru design pieces 1-4): capsule pointer gate, proposal store + harness_propose, AskUserQuestion capture hook, pointer audit.
Run: python3 -B -m unittest tests.test_0273_cluster_c1"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _env  # noqa: F401  isolate HOME and HARNESS_* first
import json, os, sys, tempfile, unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
import ask_gate, ask_payload, capsule_pointer as CP, harness as H, mcp_server as M, propose_hook, proposals

CAP = "---\nhandoff: x\n---\n# Handoff\n## Open questions\n"
LOST = [      # the three lost cases: a choice offered, nothing recorded
    "- Which of the three drafts should the secretary send?",
    "- Pick the default option for the weekly report (A/B/C).",
    "- Choose between the short and long alternatives for the intake form.",
]
FINE = [      # five self-contained questions or choices with a pointer
    "- Should the report include costs?",
    "- Which draft? See /Users/" + "bt" + "f/Claude/Projects/Exchange/projects/secretary/proposals/2026-11-24_drafts.md",
    "- Pick an option: P-1a2b3c4",
    "- Pick an option: https://claude.ai/artifact/abc",
    "- Which of these?\n  - A: ship now\n  - B: wait a week",
]


class Pointer(unittest.TestCase):      # piece 1
    def test_the_three_lost_cases_are_found(self):
        self.assertEqual(len(CP.unpointed(CAP + "\n".join(LOST) + "\n")), 3)

    def test_five_pointed_or_plain_items_pass(self):
        self.assertEqual(CP.unpointed(CAP + "\n".join(FINE) + "\n"), [])

    def test_only_the_open_questions_section_counts(self):
        t = "# Handoff\n## Done\n- Pick the option later\n## Open questions\n- Is the build green?\n## Notes\n- Which of these?\n"
        self.assertEqual(CP.choice_items(t), [])

    def test_one_option_line_is_not_enough(self):
        self.assertTrue(CP.unpointed(CAP + "- Which of these?\n  - A: ship now\n"))

    def test_audit_counts_per_role(self):
        ev = [{"type": "handoff.pointer_warn", "actor": "a1", "data": {"count": 2, "role": "guru"}},
              {"type": "handoff.pointer_blocked", "actor": "a2", "data": {"count": 1}},
              {"type": "handoff.pointer_warn", "actor": "a3", "data": {"count": 3, "role": "guru"}}, {"type": "spend.sample", "data": {}}, "junk"]
        self.assertEqual(CP.pointer_audit(ev), {"guru": 5, "a2": 1})


class Gate(unittest.TestCase):         # piece 1 wired into the handoff
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.home = os.path.join(self.tmp, "Exchange")
        os.makedirs(os.path.join(self.home, "_harness"))
        self.h = H.Harness(self.home)
        self.h.role_define("operator", "ops-coder", "harness-ops")
        self.aid = self.h.register(project="harness-ops", model="claude-opus-5-5")["id"]
        self.h.role_assign("operator", "ops-coder", self.aid)

    def cfg(self, **d):
        with open(os.path.join(self.home, "_harness", "config.json"), "w") as f:
            json.dump(d, f)

    def events(self, typ):
        return [e for e in self.h.store.read_all() if e["type"] == typ]

    def test_default_is_warn_writes_and_logs(self):
        out = self.h.handoff(self.aid, CAP + LOST[0] + "\n")
        self.assertTrue(any("no pointer" in n for n in out.get("notes", []) + [out.get("warn") or ""] + [str(out)]))
        ev = self.events("handoff.pointer_warn")
        self.assertEqual((len(ev), ev[0]["data"]["count"], ev[0]["data"]["role"]), (1, 1, "ops-coder"))
        self.assertEqual(self.events("handoff.pointer_blocked"), [])

    def test_block_refuses_then_override_is_logged(self):
        self.cfg(handoff_gate="block")
        with self.assertRaises(H.HarnessError) as cm:
            self.h.handoff(self.aid, CAP + LOST[1] + "\n")
        self.assertIn("Nothing was written", str(cm.exception))
        self.assertEqual(len(self.events("handoff.pointer_blocked")), 1)
        self.h.handoff(self.aid, CAP + LOST[1] + "\n", gate_override="operator said ship")
        self.assertEqual(self.events("handoff.gate_override")[-1]["data"]["source"], "pointer")

    def test_pointed_capsule_logs_nothing_in_block(self):
        self.cfg(handoff_gate="block")
        self.h.handoff(self.aid, CAP + "\n".join(FINE) + "\n")
        self.assertEqual(self.events("handoff.pointer_warn") + self.events("handoff.pointer_blocked"), [])


class Store(unittest.TestCase):        # piece 2
    def setUp(self):
        self.home = tempfile.mkdtemp()

    def test_id_round_trip_and_file_layout(self):
        r = proposals.save(self.home, "secretary", "drafts", "Weekly report drafts", ["draft one", "draft two"], "1")
        self.assertRegex(r["id"], r"^P-[0-9a-f]{7}$")
        self.assertIn(os.path.join("projects", "secretary", "proposals"), r["path"])
        got = proposals.load(self.home, r["id"])
        self.assertEqual(got["path"], r["path"])
        self.assertIn("draft two", got["text"])

    def test_p_ids_are_not_corpus_ids_and_unknown_is_none(self):
        self.assertIsNone(proposals.load(self.home, "P-0000000"))
        self.assertIsNone(proposals.load(self.home, "../etc"))
        self.assertNotRegex("P-1a2b3c4", H.ID_RE.pattern if hasattr(H, "ID_RE") else r"^[ND]-[0-9a-f]{5}$")

    def test_bad_kind_or_empty_items_refused(self):
        with self.assertRaises(ValueError):
            proposals.save(self.home, "x", "poem", "t", ["a"])
        with self.assertRaises(ValueError):
            proposals.save(self.home, "x", "options", "t", [])

    def test_tool_saves_and_records_event(self):
        home = os.path.join(self.home, "Ex")
        os.makedirs(os.path.join(home, "_harness"))
        h = H.Harness(home)
        aid = h.register(project="harness-ops", model="claude-opus-5-5")["id"]
        r = M._call(h, "harness_propose", {"agent": aid, "project": "harness-ops", "kind": "options", "title": "Pick one", "items": ["A", "B"]})
        self.assertTrue(os.path.exists(r["path"]))
        ev = [e for e in h.store.read_all() if e["type"] == "proposal.saved"]
        self.assertEqual((ev[0]["data"]["id"], ev[0]["data"]["n"]), (r["id"], 2))
        self.assertIn("harness_propose", [t["name"] for t in M.tool_list()])


class Hook(unittest.TestCase):         # piece 3
    D = {"tool_name": "AskUserQuestion",
         "tool_input": {"questions": [{"question": "Ship now?", "header": "Ship", "multiSelect": False,
                                       "options": [{"label": "Yes", "description": "ship"}, {"label": "No", "description": "wait", "preview": "later"}]}]},
         "tool_response": 'User has answered: "Ship now?"="Yes"'}

    def test_one_call_writes_one_file_with_options_and_answer(self):
        home = tempfile.mkdtemp()
        r = propose_hook.run(self.D, home)
        text = open(r["path"]).read()
        self.assertIn("source: hook", text)
        self.assertIn("- No: wait", text)
        self.assertIn("Ship now?: Yes", text)

    def test_other_tools_and_empty_questions_write_nothing(self):
        home = tempfile.mkdtemp()
        self.assertIsNone(propose_hook.run({"tool_name": "Bash", "tool_input": {}}, home))
        self.assertIsNone(propose_hook.run({"tool_name": "AskUserQuestion", "tool_input": {"questions": []}}, home))
        self.assertFalse(os.path.exists(os.path.join(home, "projects")))

    def test_one_parser_ask_gate_uses_it(self):
        ti = self.D["tool_input"]
        self.assertEqual(ask_gate.message_texts({"tool_name": "AskUserQuestion", "tool_input": ti}), ["Ship now?"])
        src = open(os.path.join(HERE, "..", "scripts", "ask_gate.py")).read()
        self.assertNotIn('q.get("question"', src)
        self.assertIn("ask_payload.question_texts", src)

    def test_parser_skips_bad_entries(self):
        self.assertEqual(ask_payload.questions({"questions": [1, {"question": 3}, {"question": "ok", "options": ["x", {"label": ""}]}]}),
                         [{"question": "ok", "header": "", "multi": False, "options": [{"label": "x", "description": "", "preview": ""}]}])


class AnswersShapes(unittest.TestCase):    # C1b B2: the pair regex must see raw strings, not json-escaped ones
    TXT = {"answered": 'Your questions have been answered: "Which one?"="Draft 2". You can now continue with these answers in mind.',
           "user": 'The user answered: "Which one?"="Draft 2". Read the answers carefully...'}
    SKIP = 'Your questions have been answered: "Which one?"="[User did not answer this question \u2014 they sent a message instead. Treat that message as their response; do not re-ask.]". Go on.'

    def shapes(self, t):
        return [t, {"content": t}, {"result": {"text": t}}, [t], [{"type": "text", "text": t}], {"content": [{"type": "text", "text": t}]}]

    def test_each_text_in_each_shape(self):
        for t in self.TXT.values():
            for r in self.shapes(t):
                self.assertEqual(ask_payload.answers(r), {"Which one?": "Draft 2"}, r)

    def test_skip_form_maps_to_message(self):
        for r in self.shapes(self.SKIP):
            self.assertEqual(ask_payload.answers(r), {"Which one?": "(answered in a message)"}, r)

    def test_answers_dict_still_works_and_junk_is_empty(self):
        self.assertEqual(ask_payload.answers({"answers": {"Q?": "A"}}), {"Q?": "A"})
        self.assertEqual((ask_payload.answers(None), ask_payload.answers(5), ask_payload.answers({"a": [1, None]})), ({}, {}, {}))


class ProjectResolve(unittest.TestCase):   # C1b S1: project from the bound agent's ledger record
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.home = os.path.join(self.tmp, "Exchange")
        os.makedirs(os.path.join(self.home, "_harness"))
        self.h = H.Harness(self.home)
        self.aid = self.h.register(project="secretary", model="claude-opus-5-5", session_id="sess-1")["id"]
        self.d = dict(Hook.D, session_id="sess-1", cwd="/x/y/other")

    def test_session_id_resolves_project_and_file_lands_there(self):
        self.assertEqual(propose_hook.project_for(self.d, self.h), "secretary")
        r = propose_hook.run(self.d, self.home, self.h.store, project=propose_hook.project_for(self.d, self.h))
        self.assertIn(os.path.join("projects", "secretary", "proposals"), r["path"])

    def test_cwd_hint_when_session_unknown(self):
        d = dict(Hook.D, session_id="nope", cwd="/Users/x/Secretary")
        self.assertEqual(propose_hook.project_for(d, self.h), "secretary")

    def test_falls_back_to_harness(self):
        d = dict(Hook.D, session_id="nope", cwd="/Users/x/unrelated")
        self.assertIsNone(propose_hook.project_for(d, self.h))
        r = propose_hook.run(d, self.home, self.h.store, project=None)
        self.assertIn(os.path.join("projects", "harness", "proposals"), r["path"])


# Real open-question items from capsules in Exchange/projects/*/handoffs (11-18 to 11-24), short quotes.
TRUE5 = [
    "Generalist line pick (default Draft 2).",
    "Carried, unasked this session: detective urgent findings to envoy first? (default unchanged); generalist line pick (default Draft 2).",
    "3/3 Generalist line pick? Default Draft 2.",
    "3/3: which layout in the options artifact becomes the production template? Recommended: light grey, page 1 only. No default: wait.",
    "3 Generalist line: no drafts on disk (lost, N-f0c11); no default until he sees the rewrite (Next 4).",
]
FALSE9 = [
    "2/3: page 2 of the resume ends short: leave it, more content, or the chart band? Default: leave it.",
    "3/3: which two-page layout becomes the production template? Recommended: light grey, page 1 only. No default.",
    "2/3: page 2 of the resume ends short: leave it, more content, or the chart band? Default: leave it.",
    "None pending. Unconfirmed: his choice of envoy model for the rebuild.",
    "None. All picks given.",
    "Detective urgent findings -> envoy first? (default: unchanged)",
    "1/1 Will he paste the final Why Anthropic and Additional Information text he submitted? Default: record stays \"not captured\".",
    "1/3 Will he paste his final submitted Why Anthropic / Additional Information text? Default: \"not captured\".",
    "2/3 Detective urgent findings to envoy first? Default unchanged.",
]


class RealCapsuleItems(unittest.TestCase):  # C1b regex: five true items flagged, nine false ones not
    def test_five_true_flagged(self):
        for t in TRUE5:
            self.assertEqual(len(CP.unpointed(CAP + "- " + t + "\n")), 1, t)

    def test_nine_false_not_flagged(self):
        for t in FALSE9:
            self.assertEqual(CP.unpointed(CAP + "- " + t + "\n"), [], t)

    def test_default_alone_is_not_a_choice_and_none_is_skipped(self):
        self.assertEqual(CP.choice_items(CAP + "- Ship it? Default: yes.\n"), [])
        self.assertEqual(CP.choice_items(CAP + "- None. Pick nothing.\n"), [])

    def test_inline_list_counts_as_written_out_but_bare_pick_does_not(self):
        self.assertEqual(CP.unpointed(CAP + "- Pick a colour: red, green, or blue?\n"), [])
        self.assertEqual(len(CP.unpointed(CAP + "- Pick a colour for the page?\n")), 1)


class PointerF(unittest.TestCase):      # 0.27.3 F N3: critic examples, wider pointers, a choice word needs a question mark or "or"
    def one(self, t):
        return CP.unpointed(CAP + "- " + t + "\n")

    def test_critic_examples_not_flagged(self):
        for t in ("Pick the reels fix: see reels_run.py in the tools folder", "Which of the two sync paths? Answer in the Hub Questionnaire tab (Q7)",
                  "The option parser fails on empty input; fix it next turn"):
            self.assertEqual(self.one(t), [], t)

    def test_bare_file_names_with_common_extensions_are_pointers(self):
        for ext in ("py", "sh", "md", "json", "jsonl", "txt", "html", "yaml", "yml", "toml", "csv", "tsv", "plist"):
            self.assertEqual(self.one(f"Which of these? See choices.{ext}"), [], ext)
        self.assertEqual(len(self.one("Which of these? See choices.exe")), 1)

    def test_hub_codes_corpus_ids_and_thread_ids_are_pointers(self):
        for ref in ("(R3)", "(T17)", "Questionnaire tab Q7", "D-1a2b3c", "N-abcde", "A-0123456", "M-abcdef12", "m-abcdef12", "t-9f8e7d6c"):
            self.assertEqual(self.one(f"Which of these? Recorded at {ref}"), [], ref)
        self.assertEqual(len(self.one("Which of these? Recorded at D-xyz")), 1)
        self.assertEqual(len(self.one("Which of these? Recorded at (maybe)")), 1)

    def test_choice_word_needs_a_question_or_or(self):
        self.assertEqual(self.one("Option work is done; fix it next turn"), [])
        self.assertEqual(len(self.one("Pick the colour?")), 1)
        self.assertEqual(len(self.one("Pick red or blue")), 1)

    def test_a_lost_record_id_is_no_pointer(self):
        self.assertEqual(len(self.one("Which draft? Lost (N-f0c11), no default")), 1)


if __name__ == "__main__":
    unittest.main()
