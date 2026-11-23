"""0.27.1 item 1 (ops-coder's correction cues, hook and ingest, curator-adapted). Run: python3 -B tests/test_correction_capture.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _env  # noqa: F401
import time, io, json, os, shutil, sys, tempfile, unittest
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import mistake_record as MR, mistake_pointer as P, correction_cues as C, correction_hook as H, mistake_ingest as I

SID = "a3acee45-423d-4a2c-9fa6-5ccb2279eb4e"
GOOD = "Act: I wrote 'his credentials still apply' without checking the system config.\nFound by: operator\nKind: claim"


def asst(text=None, tool=None):
    blocks = ([{"type": "text", "text": text}] if text else []) + ([{"type": "tool_use", "name": tool, "input": {}}] if tool else [])
    return json.dumps({"type": "assistant", "message": {"content": blocks}})


class T(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="mc-")
        self.proj = os.path.join(self.d, "projects", "-x")
        os.makedirs(self.proj)
        self.tr = os.path.join(self.proj, SID + ".jsonl")
        with open(self.tr, "w") as f:
            f.write(json.dumps({"type": "user", "message": {"content": "hi"}}) + "\n" + asst("I ran the thing", "Bash") + "\n" + json.dumps({"type": "user", "message": {"content": "That's wrong"}}) + "\n")
        self.home = os.path.join(self.d, "home")
        os.makedirs(os.path.join(self.home, "_harness"))

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    # item 3
    # item 2
    # item 1: cues
    def test_cues_hit_real_corrections(self):
        for t in ("That's wrong, the file is in the other folder.", "I said use the private repo.", "the checklist in hub is not updated as how I had requested it",
                  "Why was the pilot floor set to 12, 11 is close, so what disqualifies it?", "Why did you delete it?", "did you check the file first", "you were supposed to ask",
                  "you've completely removed the section", "this still doesn't show the title"):
            self.assertIsNotNone(C.match(t), t)

    def test_cues_ignore_praise_and_non_corrections(self):
        for t in ("Thanks, that's perfect", "great job, thank you, that's wrong in no way", "Congratulations, well done",
                  "/review why did you", "What is the status?", "Please continue with the build.", "Looks good, continue", "x" * 4100 + " that's wrong",
                  "> that's wrong (quoted)", "<pasted_content id=1>you forgot everything</pasted_content id=1> ok go on",
                  '<cross-session-message from="x">you forgot</cross-session-message>', "<system-reminder>that's wrong</system-reminder> next step please", ""):
            self.assertIsNone(C.match(t), t)

    def test_cue_inside_pasted_or_unclosed_blocks_never_flags(self):
        self.assertIsNone(C.match('There is no X.\n<pasted_content id="1">you forgot, that is wrong</pasted_content id="1>'))
        self.assertIsNone(C.match("Please look. <system-reminder>that's wrong, you forgot"))            # unclosed: dropped to the end
        self.assertIsNone(C.match("ok <side-sessions-event>that's wrong</side-sessions-event> go on"))
        self.assertEqual(C.match("<pasted_content>fine</pasted_content> That's wrong, redo it.")["cue"], "wrong")

    def test_dotted_capital_i_does_not_shift_the_cut(self):
        out = C.own_words("\u0130\u0130\u0130\u0130\u0130 <pasted_content>one</pasted_content> keep this words <pasted_content>two</pasted_content> tail")
        self.assertIn("keep this words", out); self.assertNotIn("<past", out); self.assertNotIn("one", out); self.assertIn("tail", out)

    def test_generic_cue_catches_short_corrections(self):
        for t in ("no, that's not it", "stop, undo that", "I didn't ask for that", "don't do that again", "nope", "Great work, but you forgot the tests"):
            self.assertEqual(C.match(t)["cue"], "generic", t)
        self.assertIsNone(C.match("Great job, thank you"))

    def test_cue_quote_is_the_matching_sentence(self):
        h = C.match("Good morning. That's wrong, redo it. Then continue.")
        self.assertEqual((h["cue"], h["quote"]), ("wrong", "That's wrong, redo it."))

    # item 1: hook
    def payload(self, prompt):
        return {"session_id": SID, "transcript_path": self.tr, "prompt": prompt}

    def test_hook_files_one_candidate_pointing_at_the_previous_turn(self):
        ctx = H.run(self.payload("That's wrong, why did you run it?"), out_home=self.home)
        self.assertIn("line 2", ctx)
        spool = [json.loads(l) for l in open(os.path.join(self.home, "_harness", "mistake_spool.jsonl"))]
        self.assertEqual(len(spool), 1)
        r = spool[0]
        self.assertEqual((r["line"], r["kind"], r["found_by"], r["session_id"]), (2, "code", "operator", SID))
        self.assertIn("I ran the thing", r["act"])
        self.assertIsNone(H.run(self.payload("That's wrong, why did you run it?"), out_home=self.home))     # same prompt: no duplicate
        self.assertEqual(len(open(os.path.join(self.home, "_harness", "mistake_spool.jsonl")).read().splitlines()), 1)

    def test_hook_claim_kind_for_text_only_turns_and_silence_on_no_match(self):
        with open(self.tr, "a") as f:
            f.write(asst("It is done and verified.") + "\n" + json.dumps({"type": "user"}) + "\n")
        H.run(self.payload("That's wrong, you were supposed to verify it"), out_home=self.home)
        self.assertEqual(json.loads(open(os.path.join(self.home, "_harness", "mistake_spool.jsonl")).readline())["kind"], "claim")
        self.assertIsNone(H.run(self.payload("Looks good, continue"), out_home=self.home))

    def test_hook_never_fails_the_prompt(self):
        for raw in ("", "not json", "[]", json.dumps({"prompt": "that's wrong"}), json.dumps(self.payload("that's wrong")).replace(SID, "x")):
            out = io.StringIO()
            old = sys.stdout
            sys.stdout = out
            try:
                self.assertEqual(H.main(io.StringIO(raw)), 0)
            finally:
                sys.stdout = old
        os.remove(self.tr)
        self.assertIsNone(H.run(self.payload("that's wrong"), out_home=self.home))              # transcript gone: nothing, no crash

    # ingest
    def test_ingest_files_candidates_keeps_unresolved_and_drops_torn_lines(self):
        H.run(self.payload("That's wrong"), out_home=self.home)
        with open(os.path.join(self.home, "_harness", "mistake_spool.jsonl"), "a") as f:
            f.write("torn line {\n" + json.dumps({"session_id": "bbbbbbbb-0000", "key": "kk9", "quote": "x", "act": "x", "line": 5, "ts": "2020-01-01T00:00:00"}) + "\n")
        got = []
        n = I.ingest(self.home, lambda sid: "agent1" if sid == SID else None, lambda a, t, b, tags: got.append((a, t, b, tags)), os.path.dirname(self.proj))
        self.assertEqual(n, 1)
        a, t, b, tags = got[0]
        self.assertEqual((a, tags), ("agent1", ["mistake", "hindsight", "candidate"]))
        self.assertIn("Found by: operator", b); self.assertIn("Kind: code", b); self.assertIn("Session: " + self.tr, b); self.assertIn("Line: 2", b)
        self.assertEqual(MR.problems(tags, b + "\nModel: m", candidate=True), [])                                  # a candidate satisfies the same schema once the model is added
        left = open(os.path.join(self.home, "_harness", "mistake_spool.jsonl")).read().splitlines()
        self.assertEqual(len(left), 1)                                                           # the unresolved one stays
        self.assertEqual(I.ingest(self.home, lambda s: None, lambda *a: None, os.path.dirname(self.proj)), 0)

    def test_end_to_end_spool_to_record_through_the_real_harness(self):
        import harness as HH
        h = HH.Harness(os.path.join(self.d, "hh")); aid = h.register(project="claude", model="claude-sonnet-5-5")["id"]
        h.store.append("session.bound", aid, {"session_id": SID, "agent": aid})
        os.makedirs(os.path.join(h.home, "_harness"), exist_ok=True)
        H.run(self.payload("That's wrong"), out_home=h.home)
        self.assertEqual(h.ingest_mistake_spool(os.path.dirname(self.proj)), 1)                    # filed through _record, so the schema accepted the candidate body
        self.assertEqual(h.ingest_mistake_spool(os.path.dirname(self.proj)), 0)                    # spool read once

    def test_forged_spool_line_dropped_old_one_and_young_one_kept(self):
        base = os.path.join(self.home, "_harness"); os.makedirs(os.path.join(base, "mistake_seen"), exist_ok=True)
        forged = {"session_id": SID, "key": "k1", "quote": "I never said anything like this at all", "act": "x", "kind": "code", "line": 2, "cue": "wrong", "ts": "2020-01-01T00:00:00"}
        young = dict(forged, key="k2", ts=time.strftime("%Y-%m-%dT%H:%M:%S"))
        with open(os.path.join(base, "mistake_spool.jsonl"), "w") as f:
            f.write(json.dumps(forged) + "\n" + json.dumps(young) + "\n")
        got = []
        n = I.ingest(self.home, lambda s: "agent1", lambda *a: got.append(a), os.path.dirname(self.proj))
        self.assertEqual((n, got), (0, []))
        left = open(os.path.join(base, "mistake_spool.jsonl")).read().splitlines()
        self.assertEqual([json.loads(l)["key"] for l in left], ["k2"])

    def test_spool_symlink_is_not_followed_and_no_double_filing(self):
        base = os.path.join(self.home, "_harness"); target = os.path.join(self.d, "victim"); open(target, "w").write("keep")
        os.symlink(target, os.path.join(base, "mistake_spool.jsonl"))
        self.assertEqual(H.run(self.payload("That's wrong"), out_home=self.home) if False else I.ingest(self.home, lambda s: "a", lambda *a: None, os.path.dirname(self.proj)), 0)
        self.assertEqual(open(target).read(), "keep")
        os.unlink(os.path.join(base, "mistake_spool.jsonl"))
        H.run(self.payload("That's wrong"), out_home=self.home)
        got = []
        self.assertEqual(I.ingest(self.home, lambda s: "a", lambda *a: got.append(a), os.path.dirname(self.proj)), 1)
        self.assertIn("Session: " + self.tr, got[0][2])
        self.assertEqual(I.ingest(self.home, lambda s: "a", lambda *a: got.append(a), os.path.dirname(self.proj)), 0)

    def test_huge_paste_is_decided_fast(self):
        t0 = time.time()
        self.assertIsNone(C.match("<system-reminder>" * 30000))
        self.assertLess(time.time() - t0, 1.0)

    def _spool(self, *lines):
        base = os.path.join(self.home, "_harness")
        with open(os.path.join(base, "mistake_spool.jsonl"), "a") as f:
            f.write("".join(json.dumps(l) + "\n" for l in lines))
        return base

    def test_poison_line_does_not_stall_the_spool_and_short_act_refused(self):
        H.run(self.payload("That's wrong"), out_home=self.home)
        good = json.loads(open(os.path.join(self.home, "_harness", "mistake_spool.jsonl")).read().splitlines()[0])
        os.unlink(os.path.join(self.home, "_harness", "mistake_spool.jsonl"))
        short = dict(good, key="p1", act="I")
        base = self._spool(short, dict(good, key="g1"))
        calls = []
        def rec(*a):
            calls.append(a)
            if len(calls) == 1:
                raise ValueError("poison")
        n = I.ingest(self.home, lambda s: "a", rec, os.path.dirname(self.proj))
        self.assertFalse(os.path.exists(os.path.join(base, "mistake_spool.claimed")))     # always cleared
        self.assertEqual(n, 0)                                   # the short act never reached record_fn; the good line raised once and was rejected
        self.assertTrue(os.path.exists(os.path.join(base, "mistake_spool.rejected.jsonl")))
        self._spool(dict(good, key="g2"))
        self.assertEqual(I.ingest(self.home, lambda s: "a", lambda *a: None, os.path.dirname(self.proj)), 1)   # a later good line is filed

    def test_replay_of_one_correction_files_once(self):
        H.run(self.payload("That's wrong"), out_home=self.home)
        good = json.loads(open(os.path.join(self.home, "_harness", "mistake_spool.jsonl")).read().splitlines()[0])
        os.unlink(os.path.join(self.home, "_harness", "mistake_spool.jsonl"))
        self._spool(*[dict(good, key="k%d" % i) for i in range(5)])
        got = []
        self.assertEqual(I.ingest(self.home, lambda s: "a", lambda *a: got.append(a), os.path.dirname(self.proj)), 1)

    def test_flood_is_capped_per_sync(self):
        H.run(self.payload("That's wrong"), out_home=self.home)
        good = json.loads(open(os.path.join(self.home, "_harness", "mistake_spool.jsonl")).read().splitlines()[0])
        os.unlink(os.path.join(self.home, "_harness", "mistake_spool.jsonl"))
        self._spool(*[dict(good, key="f%d" % i, quote="no such words %d" % i) for i in range(I.MAX_PER_SYNC + 20)])
        I.ingest(self.home, lambda s: None, lambda *a: None, os.path.dirname(self.proj))
        left = open(os.path.join(self.home, "_harness", "mistake_spool.jsonl")).read().splitlines()
        self.assertEqual(len(left), I.MAX_PER_SYNC + 20)           # nothing was dropped or processed past the cap; unresolved lines return


if __name__ == "__main__":
    unittest.main()
