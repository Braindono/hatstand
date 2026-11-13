"""cc 0.25.0 item 18: id check hook, observe mode. Silent on a match; one line under 40 tokens for an unknown id or a title that does not match;
every checked id logs hook.idcheck; never blocks; role-less chats do nothing; both MCP tool prefixes match. Run: python3 -B tests/test_c250_item18.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _env  # noqa: F401  isolate HOME and HARNESS_* first
import json, os, subprocess, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(HERE, "..", "scripts")
sys.path.insert(0, SCRIPTS)
import harness as H
import idcheck as I

MODEL = "claude-sonnet-5-5"
P1 = "mcp__plugin_crew-coordinator_crew-coordinator__harness_send"
P2 = "mcp__crew-coordinator__harness_send"


class Pure(unittest.TestCase):
    def test_verdicts_and_lines(self):
        titles = {"D-aaaaa": "Operator rule: one command per message"}
        self.assertEqual(I.verdicts(["The operator rule on one command per message (D-aaaaa) applies."], titles), [("D-aaaaa", "match")])
        self.assertEqual(I.verdicts(["Install the plugin now D-aaaaa."], titles), [("D-aaaaa", "mismatch")])
        # a reference in parentheses is not a title claim: the D-5c037 style citation must not false-warn
        titles2 = {"D-5c037": "Operator 10-29: to the operator, never a bare id; say what the item is"}
        self.assertEqual(I.verdicts(["Ids only in parentheses afterwards (D-5c037)."], titles2), [("D-5c037", "match")])
        self.assertEqual(I.verdicts(["Dry runs stay internal [D-5c037]."], titles2), [("D-5c037", "match")])
        self.assertEqual(I.verdicts(["Dry runs stay internal (D-beeef)."], titles2), [("D-beeef", "unknown")])   # existence is still checked
        self.assertEqual(I.verdicts(["see D-bbbbb"], titles), [("D-bbbbb", "unknown")])
        self.assertIsNone(I.line_for([("D-aaaaa", "match")]))
        for line in (I.LINE_UNKNOWN % "D-aaaaa", I.LINE_MISMATCH % "D-aaaaa"):
            self.assertLess(I.tokens(line), 40)
        self.assertEqual(I.verdicts(["a `D-ccccc` code span"], {}), [])               # code spans are skipped

    def test_stopwords_never_make_a_match_and_an_id_at_either_end_is_not_parenthetical(self):
        titles = {"D-aaaaa": "Tags are not allowed for you but its own"}
        # only stop words in common (and, for, are, not, you, was, but, can, has, its): a mismatch, not a match
        self.assertEqual(I.verdicts(["Install the plugin and run it for them: D-aaaaa"], titles), [("D-aaaaa", "mismatch")])
        self.assertEqual(I.verdicts(["You can run it, but was it ready? D-aaaaa"], titles), [("D-aaaaa", "mismatch")])
        # an id at the very start or the very end of the message is a bare citation, never a bracketed one
        self.assertEqual(I.cited(["D-aaaaa plugin install"])[0][2], False)
        self.assertEqual(I.cited(["install the plugin D-aaaaa"])[0][2], False)
        self.assertEqual(I.verdicts(["D-aaaaa plugin install"], titles), [("D-aaaaa", "mismatch")])
        self.assertEqual(I.verdicts(["install the plugin D-aaaaa"], titles), [("D-aaaaa", "mismatch")])
        self.assertEqual(I.cited(["(D-aaaaa) is it"])[0][2], True)
        self.assertEqual(I.cited(["see [D-aaaaa]"])[0][2], True)

    def test_tool_names_with_either_prefix_match(self):
        self.assertTrue(I.TOOL_RE.search(P1) and I.TOOL_RE.search(P2) and I.TOOL_RE.search("mcp__x__harness_record"))
        self.assertFalse(I.TOOL_RE.search("mcp__x__harness_sync"))


class Hook(unittest.TestCase):
    def setUp(self):
        self.home = os.path.join(tempfile.mkdtemp(), "h")
        os.makedirs(os.path.join(self.home, "_harness"))
        self.st = tempfile.mkdtemp()
        self.h = H.Harness(self.home)
        self.h.role_define("operator", "ops-coder", "harness-ops", carry="none")
        self.a = self.h.register(project="harness-ops", model=MODEL, session_id="s-18", role="ops-coder")["id"]
        self.h.store.append("session.bound", self.a, {"session_id": "s-18", "agent": self.a})
        self.did = self.h.record(self.a, "decision", "Operator rule: one command per message", "body", None, "harness-ops")["id"]

    def run_hook(self, body, tool=P1, sid="s-18"):
        env = dict(os.environ, HARNESS_HOME=self.home, HARNESS_STATE_DIR=self.st)
        r = subprocess.run([sys.executable, "-B", os.path.join(SCRIPTS, "harness.py"), "hook", "idcheck"],
                           input=json.dumps({"session_id": sid, "tool_name": tool, "tool_input": {"subject": "s", "body": body}}),
                           capture_output=True, text=True, env=env)
        return r.stdout.strip()

    def events(self):
        return [e["data"] for e in H.Harness(self.home).store.read_all() if e["type"] == "hook.idcheck"]

    def test_a_matching_id_prints_nothing_and_logs(self):
        self.assertEqual(self.run_hook("The one command per message rule (%s) applies." % self.did), "")
        self.assertEqual([(e["id"], e["verdict"], e["tokens"]) for e in self.events()], [(self.did, "match", 0)])

    def test_an_unknown_id_prints_one_line_under_40_tokens_and_never_blocks(self):
        out = json.loads(self.run_hook("per D-deadb there is a rule"))
        ctx = out["hookSpecificOutput"]["additionalContext"]
        self.assertEqual(out["hookSpecificOutput"]["hookEventName"], "PostToolUse")
        self.assertNotIn("decision", out)                                              # observe mode: no block
        self.assertIn("D-deadb", ctx)
        self.assertLess(I.tokens(ctx), 40)
        self.assertEqual([(e["id"], e["verdict"]) for e in self.events()], [("D-deadb", "unknown")])

    def test_a_mismatched_title_prints_one_line(self):
        out = json.loads(self.run_hook("Install the plugin now: %s." % self.did))
        self.assertIn("does not match", out["hookSpecificOutput"]["additionalContext"])
        self.assertEqual([e["verdict"] for e in self.events()], ["mismatch"])

    def test_the_event_is_logged_each_time_and_both_prefixes_match(self):
        for tool in (P1, P2):
            self.run_hook("the one command per message rule %s" % self.did, tool=tool)
        self.assertEqual(len(self.events()), 2)

    def test_a_role_less_chat_and_other_tools_do_nothing(self):
        lone = self.h.register(project="harness-ops", model=MODEL, session_id="s-lone")["id"]
        self.h.store.append("session.bound", lone, {"session_id": "s-lone", "agent": lone})
        self.assertEqual(self.run_hook("see D-deadb", sid="s-lone"), "")
        self.assertEqual(self.run_hook("see D-deadb", tool="mcp__x__harness_sync"), "")
        self.assertEqual(self.events(), [])


if __name__ == "__main__":
    unittest.main()
