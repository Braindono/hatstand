"""cc 0.25.0 item 32: ask_gate, data-driven, observe mode first, role scoped. The 15 tests ported from Secretary/bin/gates/test_ask_gate.py (run as a
secretary: the CV rules, enforce mode) plus the new ones: observe never denies and logs hook.askgate, harness roles use the harness section,
labels and paths only in a deny reason, the 400 kB stop cap, the critic's 5 regression samples, a changed gates.json changes behaviour without a
release. Run: python3 -B tests/test_c250_item32.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _env  # noqa: F401  isolate HOME and HARNESS_* first
import json, os, subprocess, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(HERE, "..", "scripts")
GATE = os.path.join(SCRIPTS, "ask_gate.py")
sys.path.insert(0, SCRIPTS)
import harness as H

DEFAULT_CFG = os.path.join(HERE, "fixtures", "gates.default.json")
TEST_SOURCES = [
    {"label": "intake", "path": "Projects/CV_Management/skills_repository.INTAKE.md"},
    {"label": "approved base r\u00e9sum\u00e9",
     "path": "Projects/CV_Management/Claude outputs/resumes/2026-10-21/Base/_build/content.json"},
    {"label": "secretary rules", "path": "Projects/Secretary/rules/*.md"},
]


def w(root, rel, txt):
    p = os.path.join(root, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write(txt)
    return p


class T(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        r = cls.root = os.path.join(cls.tmp, "Claude")
        w(r, "Projects/CV_Management/Claude outputs/resumes/2026-10-21/Base/_build/content.json",
          json.dumps({"jobs": [{"company": "Acme", "dates": "Jul 2010 – Dec 2016",
                                "title": "Staff Widget Engineer"}]}))
        w(r, "Projects/CV_Management/skills_repository.INTAKE.md",
          "# Intake\nDegree: BA Underwater Basket Studies\n")
        w(r, "Projects/Secretary/rules/a.md", "Nothing relevant here\n")
        cls.home = os.path.join(cls.tmp, "Exchange")
        os.makedirs(os.path.join(cls.home, "_harness"))
        h = cls.h = H.Harness(cls.home)
        for role, proj in (("secretary", "secretary"), ("ops-coder", "harness-ops")):
            h.role_define("operator", role, proj, carry="none")
        for role, sid in (("secretary", "s-sec"), ("ops-coder", "s-ops")):
            a = h.register(model="claude-sonnet-5-5", session_id=sid, role=role)["id"]
            h.store.append("session.bound", a, {"session_id": sid, "agent": a})

    def cfg(self, edit=None, raw=None, name="gates.test.json"):
        p = os.path.join(self.tmp, name)
        if raw is not None:
            txt = raw
        else:
            c = json.load(open(DEFAULT_CFG, encoding="utf-8"))
            c["ask_gate"]["sources"] = list(TEST_SOURCES)
            c["ask_gate"]["mode"] = "enforce"                    # the ported tests exercise the blocking behaviour
            if edit:
                edit(c["ask_gate"])
            txt = json.dumps(c)
        with open(p, "w", encoding="utf-8") as f:
            f.write(txt)
        return p

    def run_gate(self, mode, inp, raw=False, cfg=None, sid="s-sec"):
        env = dict(os.environ, ASK_GATE_ROOTS=self.root, HOME=self.tmp, GATES_CONFIG=cfg or self.cfg(), HARNESS_HOME=self.home,
                   HARNESS_STATE_DIR=self.tmp)
        if not raw and isinstance(inp, dict):
            inp = dict(inp, session_id=sid)
        p = subprocess.run([sys.executable, GATE, mode], input=inp if raw else json.dumps(inp),
                           capture_output=True, text=True, env=env)
        self.assertEqual(p.returncode, 0)
        return p.stdout.strip(), p.stderr

    def ask(self, q):
        return {"tool_name": "AskUserQuestion", "tool_input": {"questions": [{"question": q}]}}

    def test1_recorded(self):
        out, _ = self.run_gate("pre", self.ask("Acme end date: Dec 2016 or Jan 2017?"))
        d = json.loads(out)["hookSpecificOutput"]
        self.assertEqual(d["permissionDecision"], "deny")
        self.assertNotIn("Jul 2010 – Dec 2016", d["permissionDecisionReason"])     # labels and paths only, never an excerpt of the facts
        self.assertIn("approved base résumé (", d["permissionDecisionReason"])
        self.assertIn("_build/content.json", d["permissionDecisionReason"])

    def test2_marked(self):
        out, _ = self.run_gate("pre", self.ask(
            "Acme end date: Dec 2016 or Jan 2017? [searched: approved base résumé]"))
        self.assertEqual(out, "")

    def test3_unrecorded(self):
        out, _ = self.run_gate("pre", self.ask("Which color do you prefer for the Hub header?"))
        self.assertEqual(out, "")

    def test4_sendusermessage(self):
        msg = "Status update.\n\n## Your input needed\n1. Is your degree in Underwater Basket Studies\n2. Anything else\n"
        out, _ = self.run_gate("pre", {"tool_name": "SendUserMessage", "tool_input": {"message": msg}})
        self.assertEqual(json.loads(out)["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertIn("intake (", out)

    def test4b_harness_send(self):
        msg = "What degree do you hold?"
        ti = {"to": "operator", "message": msg}
        out, _ = self.run_gate("pre", {"tool_name": "mcp__x__harness_send", "tool_input": ti})
        self.assertIn("deny", out)
        ti["to"] = "cv-management"
        out, _ = self.run_gate("pre", {"tool_name": "mcp__x__harness_send", "tool_input": ti})
        self.assertEqual(out, "")

    def transcript(self, text):
        p = os.path.join(self.tmp, "t.jsonl")
        with open(p, "w") as f:
            f.write(json.dumps({"type": "user", "message": {"role": "user", "content": "hi"}}) + "\n")
            f.write(json.dumps({"type": "assistant", "message": {"role": "assistant",
                    "content": [{"type": "text", "text": text}]}}) + "\n")
        return p

    def test5_stop_block(self):
        p = self.transcript("Done. Confirm the title Staff Widget Engineer?")
        out, _ = self.run_gate("stop", {"transcript_path": p})
        self.assertEqual(json.loads(out)["decision"], "block")

    def test6_loop_guard(self):
        p = self.transcript("Done. Confirm the title Staff Widget Engineer?")
        out, _ = self.run_gate("stop", {"transcript_path": p, "stop_hook_active": True})
        self.assertEqual(out, "")

    def test7_malformed(self):
        out, err = self.run_gate("pre", "{not json", raw=True)
        self.assertEqual(out, "")
        self.assertIn("ask_gate error", err)

    def test8_session(self):
        out, _ = self.run_gate("session", {"hook_event_name": "SessionStart"})
        d = json.loads(out)["hookSpecificOutput"]
        self.assertEqual(d["hookEventName"], "SessionStart")
        self.assertIn("WHERE FACTS LIVE", d["additionalContext"])
        self.assertEqual(len(d["additionalContext"].splitlines()), 6)
        self.assertIn("Never ask the operator for a fact before searching these.", d["additionalContext"])
        self.assertIn("approved base résumé", d["additionalContext"])

    # ---- config-driven behavior ----
    def test9_config_edit_new_source(self):
        q = self.ask("Is your favorite Fruit Mango?")
        out, _ = self.run_gate("pre", q)
        self.assertEqual(out, "")
        w(self.root, "Projects/Exchange/extra.md", "Favorite Fruit: Mango\n")
        cfg = self.cfg(lambda a: a["sources"].append({"label": "extra", "path": "Projects/Exchange/extra.md"}))
        out, _ = self.run_gate("pre", q, cfg=cfg)
        self.assertEqual(json.loads(out)["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertIn("extra (", out)

    def test10_enabled_false(self):
        cfg = self.cfg(lambda a: a.update(enabled=False))
        out, _ = self.run_gate("pre", self.ask("Acme end date: Dec 2016 or Jan 2017?"), cfg=cfg)
        self.assertEqual(out, "")
        out, _ = self.run_gate("session", {"hook_event_name": "SessionStart"}, cfg=cfg)
        self.assertEqual(out, "")
        p = self.transcript("Confirm the title Staff Widget Engineer?")
        out, _ = self.run_gate("stop", {"transcript_path": p}, cfg=cfg)
        self.assertEqual(out, "")

    def test11_broken_config_defaults(self):
        for raw in ("{not json", "[]", '{"ask_gate": 5}'):
            out, err = self.run_gate("session", {}, cfg=self.cfg(raw=raw))
            self.assertIn("using built-in defaults", err)
            ctx = json.loads(out)["hookSpecificOutput"]["additionalContext"]
            self.assertIn("operator facts (single source)", ctx)  # default source list
        out, err = self.run_gate("pre", self.ask("Acme end date?"), cfg=os.path.join(self.tmp, "nope.json"))
        self.assertIn("warning", err)

    def test12_hub_header_real_like_fixtures(self):
        r = os.path.join(self.tmp, "Real")
        w(r, "Projects/CV_Management/skills_repository.json",
          json.dumps({"projects": [{"name": "Hub", "notes": "Hub header color is navy; Hub title bar"}]}))
        w(r, "Projects/Exchange/OPERATOR.md", "Hub: the Secretary Hub. Header preferences live in the Hub.\n")
        env = dict(os.environ, ASK_GATE_ROOTS=r, HOME=self.tmp, GATES_CONFIG=DEFAULT_CFG, HARNESS_HOME=self.home, HARNESS_STATE_DIR=self.tmp)
        q = {"tool_name": "AskUserQuestion",
             "tool_input": {"questions": [{"question": "Which color do you prefer for the Hub header?"}]}}
        p = subprocess.run([sys.executable, GATE, "pre"], input=json.dumps(dict(q, session_id="s-sec")), capture_output=True,
                           text=True, env=env)
        self.assertEqual(p.stdout, "")

    def test13_session_index_mentions_config(self):
        out, _ = self.run_gate("session", {})
        ctx = json.loads(out)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("gates.test.json", ctx)
        self.assertIn("To add a source or rule, edit gates.json and append to history", ctx)

    def test14_defaults_match_file(self):
        sys.path.insert(0, HERE)
        import ask_gate
        c = json.load(open(DEFAULT_CFG, encoding="utf-8"))
        for k, v in c["ask_gate"].items():                  # every key of the real gates.json equals the built-in default
            self.assertEqual(v, ask_gate.DEFAULTS[k], k)

    # ---------------- 0.25.0 additions ----------------
    def harness_cfg(self, mode="enforce", extra_sources=None, enabled=True):
        c = {"ask_gate": {"sources": list(TEST_SOURCES), "mode": "enforce"},
             "harness": {"enabled": enabled, "mode": mode, "fact_words": [],
                         "sources": [{"label": "operator rules", "path": "Projects/Exchange/OPERATOR.md"}] + (extra_sources or [])}}
        p = os.path.join(self.tmp, "gates.harness.json")
        with open(p, "w", encoding="utf-8") as f:
            json.dump(c, f)
        return p

    def events(self):
        return [e for e in H.Harness(self.home).store.read_all() if e["type"] == "hook.askgate"]

    def test15_observe_never_denies_and_logs_verdict_tokens_role(self):
        cfg = self.cfg(lambda a: a.update(mode="observe"))
        before = len(self.events())
        out, _ = self.run_gate("pre", self.ask("Acme end date: Dec 2016 or Jan 2017?"), cfg=cfg)
        self.assertEqual(out, "")                                                 # observe: nothing printed, nothing denied
        ev = self.events()[before:]
        self.assertEqual([(e["data"]["verdict"], e["data"]["role"]) for e in ev], [("would_block", "secretary")])
        self.assertGreater(ev[0]["data"]["tokens"], 0)
        self.assertNotIn("Acme", json.dumps(ev[0]))                             # no question text in the event
        p = self.transcript("Confirm the title Staff Widget Engineer?")
        out, _ = self.run_gate("stop", {"transcript_path": p}, cfg=cfg)
        self.assertEqual(out, "")                                                 # stop mode never blocks in observe

    def test16_the_default_mode_is_observe(self):
        import ask_gate
        self.assertEqual((ask_gate.DEFAULTS["mode"], ask_gate.HARNESS_DEFAULTS["mode"]), ("observe", "observe"))
        c = json.load(open(DEFAULT_CFG, encoding="utf-8"))                       # the real file has no mode key: observe applies
        c["ask_gate"]["sources"] = list(TEST_SOURCES)
        p = os.path.join(self.tmp, "nomode.json")
        json.dump(c, open(p, "w", encoding="utf-8"))
        out, _ = self.run_gate("pre", self.ask("Acme end date: Dec 2016 or Jan 2017?"), cfg=p)
        self.assertEqual(out, "")

    def test17_a_harness_role_never_gets_the_cv_fact_rules(self):
        out, _ = self.run_gate("pre", self.ask("Acme end date: Dec 2016 or Jan 2017?"), cfg=self.harness_cfg(), sid="s-ops")
        self.assertEqual(out, "")                                                 # the CV sources are not the harness section's
        ev = self.events()
        self.assertTrue(all(e["data"]["section"] != "ask_gate" or e["data"]["role"] == "secretary" for e in ev))

    def test18_the_critics_samples_are_allowed_for_harness_roles_in_enforce_mode(self):
        w(self.root, "Projects/Exchange/OPERATOR.md",
          "Operator rule: install steps are one command, with the file path, run by the operator.\nThe title of every handoff names the role.\n"
          "Start date of the week is Monday for reports.\n")
        for q in ("Run the install script now?", "Approve the restore command? It restores the critic from its capsule.",
                  "Is the title of the new role correct and does the start date work?",
                  "Should I install the update now or wait for the next release window?",
                  "Which color do you prefer for the Hub header?"):
            out, _ = self.run_gate("pre", self.ask(q), cfg=self.harness_cfg(), sid="s-ops")
            self.assertEqual(out, "", q)

    def test19_a_harness_question_the_records_answer_is_flagged_by_label_and_path_only(self):
        w(self.root, "Projects/Exchange/OPERATOR.md", "Rule 7: Pacific Standard timezone is the operator's reference. Zephyr budget is fixed.\n")
        q = self.ask("Which Pacific timezone and Zephyr budget do you want?")
        out, _ = self.run_gate("pre", q, cfg=self.harness_cfg(mode="enforce"), sid="s-ops")
        reason = json.loads(out)["hookSpecificOutput"]["permissionDecisionReason"]
        self.assertIn("operator rules (Projects/Exchange/OPERATOR.md)", reason)
        self.assertNotIn("Zephyr budget is fixed", reason)                        # never an excerpt
        out, _ = self.run_gate("pre", q, cfg=self.harness_cfg(mode="observe"), sid="s-ops")
        self.assertEqual(out, "")

    def test20_harness_enabled_false_allows_everything_and_the_session_index_is_not_injected(self):
        out, _ = self.run_gate("session", {"hook_event_name": "SessionStart"}, cfg=self.harness_cfg(), sid="s-ops")
        self.assertEqual(out, "")                                                 # no facts index in harness chats
        out, _ = self.run_gate("session", {"hook_event_name": "SessionStart"}, cfg=self.harness_cfg(), sid="s-sec")
        self.assertIn("WHERE FACTS LIVE", out)                                    # still there for the secretary
        w(self.root, "Projects/Exchange/OPERATOR.md", "Zephyr budget fixed Pacific\n")
        out, _ = self.run_gate("pre", self.ask("Zephyr budget and Pacific zone?"), cfg=self.harness_cfg(enabled=False), sid="s-ops")
        self.assertEqual(out, "")

    def test21_stop_reads_at_most_the_last_400_kb(self):
        p = os.path.join(self.tmp, "big.jsonl")
        with open(p, "w") as f:
            f.write(json.dumps({"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "Confirm the title Staff Widget Engineer?"}]}}) + "\n")
            f.write(json.dumps({"type": "user", "message": {"role": "user", "content": "x" * 450000}}) + "\n")
        out, _ = self.run_gate("stop", {"transcript_path": p})
        self.assertEqual(out, "")                                                 # the question sits before the last 400 kB: not read
        import ask_gate
        self.assertEqual(ask_gate.TAIL_BYTES, 400000)

    def test22_a_changed_harness_gates_json_changes_behaviour_without_a_release(self):
        w(self.root, "Projects/Exchange/extra-h.md", "Quartz limit: seven Quartz jobs per night. The Zephyr scheduler runs them.\n")
        q = self.ask("How many Quartz jobs does the Zephyr scheduler run?")
        out, _ = self.run_gate("pre", q, cfg=self.harness_cfg(), sid="s-ops")
        self.assertEqual(out, "")
        cfg = self.harness_cfg(extra_sources=[{"label": "extra", "path": "Projects/Exchange/extra-h.md"}])
        out, _ = self.run_gate("pre", q, cfg=cfg, sid="s-ops")
        self.assertEqual(json.loads(out)["hookSpecificOutput"]["permissionDecision"], "deny")

    def test23_a_missing_harness_section_falls_back_to_the_built_in_defaults_with_a_warning(self):
        out, err = self.run_gate("pre", self.ask("Anything?"), cfg=self.cfg(), sid="s-ops")
        self.assertIn("using built-in defaults", err)
        self.assertEqual(out, "")

    def test24_a_role_less_or_unknown_chat_uses_the_harness_section(self):
        out, _ = self.run_gate("pre", self.ask("Acme end date: Dec 2016 or Jan 2017?"), sid="s-nobody")
        self.assertEqual(out, "")

    # ---------------- critic notes (a) to (d) ----------------
    def test25_the_cheap_exit_runs_before_the_ledger_is_touched(self):
        import ask_gate
        for name, ti, want in (("mcp__x__harness_send", {"to": "role:envoy", "body": "What degree?"}, True),     # not to the operator
                               ("mcp__x__harness_send", {"to": "operator", "body": "No question here."}, True),   # operator but no "?"
                               ("Bash", {"command": "ls"}, True),
                               ("mcp__x__harness_send", {"to": "operator", "body": "What degree?"}, False),
                               ("AskUserQuestion", {"questions": [{"question": "x"}]}, False)):
            self.assertEqual(ask_gate.cheap_skip("pre", {"tool_name": name, "tool_input": ti}), want, (name, ti))
        self.assertFalse(ask_gate.cheap_skip("stop", {}))
        # the timing path: a skipped call never opens the harness (a poisoned HARNESS_HOME proves no ledger read)
        env = dict(os.environ, HARNESS_HOME=os.path.join(self.tmp, "no-such-home", "x"), GATES_CONFIG=self.cfg(), HOME=self.tmp)
        p = subprocess.run([sys.executable, GATE, "pre"], input=json.dumps({"tool_name": "Bash", "tool_input": {"command": "ls"}}),
                           capture_output=True, text=True, env=env)
        self.assertEqual((p.returncode, p.stdout, p.stderr), (0, "", ""))
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "no-such-home")))

    def test26_an_evaluated_and_allowed_question_logs_verdict_allow_with_zero_tokens(self):
        cfg = self.cfg(lambda a: a.update(mode="observe"))
        before = len(self.events())
        out, _ = self.run_gate("pre", self.ask("Which color do you prefer for the Hub header?"), cfg=cfg)
        self.assertEqual(out, "")
        ev = self.events()[before:]
        self.assertEqual([(e["data"]["verdict"], e["data"]["tokens"]) for e in ev], [("allow", 0)])
        before = len(self.events())
        self.run_gate("pre", {"tool_name": "mcp__x__harness_send", "tool_input": {"to": "operator", "body": "No question."}}, cfg=cfg)
        self.assertEqual(len(self.events()), before)                                # nothing evaluated: nothing logged

    def test27_a_decimal_point_does_not_split_a_question(self):
        import ask_gate
        ask_gate.load_config("ask_gate")
        self.assertEqual(ask_gate.extract_questions("Is the pi value 3.14?"), ["Is the pi value 3.14?"])
        self.assertEqual(ask_gate.extract_questions("Done. Is version 2.5.1 ok? Fine."), ["Is version 2.5.1 ok?"])

    def test28_the_career_defaults_use_globs_and_the_fixture_matches(self):
        import ask_gate
        paths = [s["path"] for s in ask_gate.DEFAULTS["sources"]]
        self.assertIn("Projects/CV_Management/*skills_repository.json", paths)
        self.assertIn("Projects/CV_Management/*skills_repository.INTAKE.md", paths)
        c = json.load(open(DEFAULT_CFG, encoding="utf-8"))
        self.assertEqual(c["ask_gate"]["sources"], ask_gate.DEFAULTS["sources"])
        r = os.path.join(self.tmp, "GlobRoot")
        w(r, "Projects/CV_Management/old_skills_repository.json", json.dumps({"x": "Quartz"}))     # an older prefixed name still resolves
        from unittest import mock
        with mock.patch.dict(os.environ, {"ASK_GATE_ROOTS": r}):
            found = ask_gate.resolve("Projects/CV_Management/*skills_repository.json")
        self.assertEqual([os.path.basename(f) for f in found], ["old_skills_repository.json"])


if __name__ == "__main__":
    unittest.main()
