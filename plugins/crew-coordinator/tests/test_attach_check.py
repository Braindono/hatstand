"""0.27.2 I1: the 8 tests of tools/attach_check (classify() and the messages mode), ported unchanged except the import path. Run: python3 -B tests/test_attach_check.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _env  # noqa: F401  isolate HOME and HARNESS_* first
import io, json, os, shutil, sys, tempfile, unittest
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import attach_state as A, attach_hook as H

ADD = {"files": [{"path": "attach-noop.txt", "content": "x"}], "remove": []}
REM = {"files": [], "remove": ["attach-noop.txt"]}


class T(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="at-")
        self.st = os.path.join(self.d, "attach_state.json")
        self._real = A.STATE
        A.STATE = self.st                                  # main() uses the default path: never touch the real state file

    def tearDown(self):
        A.STATE = self._real
        shutil.rmtree(self.d, ignore_errors=True)

    def test_toggle_follows_the_recorded_successes(self):
        self.assertEqual(A.next_op(self.st)["op"], "add")
        self.assertEqual(H.run({"tool_input": ADD, "tool_response": {"unchanged": False, "version": "1"}}, self.st), None)
        self.assertEqual(A.next_op(self.st)["op"], "remove")
        self.assertEqual(A.next_op(self.st)["publish"], {"files": [], "remove": ["attach-noop.txt"]})
        H.run({"tool_input": REM, "tool_response": "version: 2 published"}, self.st)
        self.assertEqual(A.next_op(self.st)["op"], "add")

    def test_unchanged_true_is_a_failed_step_and_does_not_flip_the_state(self):
        for resp in ({"unchanged": True}, '{"unchanged":true}', [{"type": "text", "text": "ok: {\"unchanged\": true}"}], "unchanged: True"):
            ctx = H.run({"tool_input": REM, "tool_response": resp, "session_id": "s1"}, self.st)
            self.assertIn("FAILED", ctx, resp)
        self.assertEqual(A.next_op(self.st)["op"], "add")                                              # state unchanged by failures
        lines = open(os.path.join(self.d, "attach_failures.jsonl")).read().splitlines()
        self.assertEqual((len(lines), json.loads(lines[0])["op"]), (4, "remove"))

    def test_only_positive_evidence_records_a_success(self):
        bad = [{"error": "forbidden"}, "Error: permission denied", None, {"changed": False}, {"unchanged": 1, "version": "3"}, {}, "ok", "",
               [{"type": "text", "text": "{\"error\": \"x\"}"}], {"version": "4", "error": "partial"}, {"a": {"b": {"c": {"d": {"e": {"f": {"g": {"unchanged": True}}}}}}}}]
        for r in bad:
            ctx = H.run({"tool_input": ADD, "tool_response": r}, self.st)
            self.assertIsNotNone(ctx, r)
            self.assertFalse(os.path.exists(self.st), r)                                                  # nothing recorded
        late = [{"type": "text", "text": "x"}] * 80 + [{"type": "text", "text": '{"unchanged": true}'}]
        self.assertIn("FAILED", H.run({"tool_input": ADD, "tool_response": late}, self.st))               # unchanged after 80 blocks still seen
        self.assertIn("NOT CONFIRMED", H.run({"tool_input": ADD, "tool_response": "x" * 3_000_000}, self.st))
        self.assertIsNone(H.run({"tool_input": ADD, "tool_response": [{"type": "text", "text": '{"version": "7", "url": "https://claude.ai/artifact/x"}'}]}, self.st))
        self.assertTrue(A.present(self.st))

    def test_real_hub_publish_results_verbatim(self):
        ok = ("Published /path/to/hub-home/dist/index.html at https://claude.ai/artifact/Bh95vCZDid4tqAZog6EYP8 (Version 105, version id 1795453942-64e0)\n\n"
              "Stored \u2014 contract 0.2.87 (newest 0.2.98) \u00b7 capabilities mcp: host hub-renderer[6 tools]; assets; db; downloads \u00b7 readable by only you.\n\nWarning: unobserved host:hub-renderer interface")
        refused1 = ("Publish refused \u2014 nothing was merged or published: a newer version (1795451518-acee) published elsewhere (by another session, or by someone saving from the page itself) is live "
                    "and this publish was not built on it. That version now counts as viewed.")
        refused2 = "Publish refused \u2014 nothing was merged or published: this is the identical content already refused against the newer version 1795451518-acee, resent unchanged."
        self.assertEqual(H.classify(ok), "success")
        self.assertEqual(H.classify([{"type": "text", "text": ok}]), "success")
        self.assertEqual(H.classify(refused1), "unknown")
        self.assertEqual(H.classify(refused2), "unknown")
        self.assertIsNone(H.run({"tool_input": ADD, "tool_response": ok}, self.st))
        self.assertTrue(A.present(self.st))
        self.assertIn("NOT CONFIRMED", H.run({"tool_input": REM, "tool_response": refused1}, self.st))
        self.assertTrue(A.present(self.st))                                                               # a refusal changes nothing

    def test_map_form_removal_and_other_artifacts(self):
        self.assertEqual(H.marker_op({"files": {"attach-noop.txt": None}}), "remove")
        self.assertEqual(H.marker_op({"files": {"attach-noop.txt": "x"}}), "add")
        H.run({"tool_input": {"files": {"attach-noop.txt": "x"}}, "tool_response": {"version": "1"}}, self.st)
        H.run({"tool_input": {"files": {"attach-noop.txt": None}}, "tool_response": {"version": "2"}}, self.st)
        self.assertFalse(A.present(self.st))                                                              # map-form removal toggled the right way
        other = dict(ADD, url="https://claude.ai/artifact/SomeOtherArtifact123456")
        self.assertIsNone(H.run({"tool_input": other, "tool_response": {"version": "9"}}, self.st))
        self.assertFalse(A.present(self.st))                                                              # not the Hub: ignored
        hub = dict(ADD, url="https://claude.ai/artifact/Bh95vCZDid4tqAZog6EYP8")
        H.run({"tool_input": hub, "tool_response": {"version": "9"}}, self.st)
        self.assertTrue(A.present(self.st))

    def test_other_publishes_are_ignored(self):
        self.assertIsNone(H.run({"tool_input": {"files": [{"path": "index.html"}], "remove": []}, "tool_response": {"unchanged": True}}, self.st))
        self.assertFalse(os.path.exists(self.st) or os.path.exists(os.path.join(self.d, "attach_failures.jsonl")))
        self.assertIsNone(H.run({"tool_input": "garbage", "tool_response": None}, self.st))

    def test_hook_never_fails_and_prints_json_only_on_failure(self):
        for raw in ("", "not json", "[]", json.dumps({"tool_input": ADD, "tool_response": {"version": "1"}}), json.dumps({"tool_input": 5})):
            out, old = io.StringIO(), sys.stdout
            sys.stdout = out
            try:
                self.assertEqual(H.main(io.StringIO(raw)), 0)
            finally:
                sys.stdout = old
            self.assertEqual(out.getvalue(), "")

    def test_symlinked_failure_log_is_not_followed(self):
        victim = os.path.join(self.d, "v")
        open(victim, "w").write("KEEP")
        os.symlink(victim, os.path.join(self.d, "attach_failures.jsonl"))
        with self.assertRaises(OSError):
            H.run({"tool_input": REM, "tool_response": {"unchanged": True}}, self.st)
        self.assertEqual(open(victim).read(), "KEEP")


if __name__ == "__main__":
    unittest.main()
