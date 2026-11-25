"""0.27.3 cluster C2 (capture fix pieces 5-6): decision rules + ledger writer, expiry sweep. Synthetic transcripts only.
Run: python3 -B -m unittest tests.test_0273_cluster_c2"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _env  # noqa: F401  isolate HOME and HARNESS_* first
import json, os, sys, tempfile, time, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
import decision_rules as DR, expiry_sweep as ES, vault as V, vault_decisions as VD

B = lambda role, text, ts="2026-10-20 10:00:00": {"role": role, "ts": ts, "text": text}
BLOCKS = [
    B("operator", "Should the report include costs?"),
    B("assistant", "Options:\n- A: include costs\n- B: leave them out (Recommended)"),
    B("operator", "Go with A, because the totals matter to me."),
    B("assistant", "Root cause: the hook ran twice. Fixed per D-12345."),
    B("assistant", "Short reply with nothing to keep."),
]


def entry(role, text):
    return {"type": "user" if role == "operator" else "assistant", "timestamp": "2026-10-20T10:00:00Z", "origin": {"kind": "human"},
            "message": {"role": "user" if role == "operator" else "assistant", "content": text}}


class Rules(unittest.TestCase):          # piece 5
    def test_five_kinds_found(self):
        self.assertEqual({c["kind"] for c in DR.candidates(BLOCKS)}, set(DR.KINDS))

    def test_quotes_are_substrings_and_capped(self):
        long = B("operator", "I decided " + "x" * 600)
        src = "\n".join(b["text"] for b in BLOCKS + [long])
        for c in DR.candidates(BLOCKS + [long]):
            self.assertIn(c["text"], src)
            self.assertLessEqual(len(c["text"]), DR.QUOTE_CAP)

    def test_kinds_parameter_narrows(self):
        self.assertEqual({c["kind"] for c in DR.candidates(BLOCKS, ("insight",))}, {"insight"})

    def test_plain_chatter_and_shell_lines_give_nothing(self):
        self.assertEqual(DR.candidates([B("assistant", "ok"), B("operator", "! ls"), B("operator", "/clear")]), [])

    def test_because_alone_is_not_a_rationale(self):
        self.assertEqual(DR.candidates([B("assistant", "It broke because of rain.")], ("rationale",)), [])


class RulesC2c(unittest.TestCase):       # guru re-grade: rationale and insight precision
    def kinds(self, role, text, prev=None):
        bl = ([prev] if prev else []) + [B(role, text)]
        return {c["kind"] for c in DR.candidates(bl) if c["line"] == len(bl) - 1}

    def test_status_lines_are_not_rationale(self):
        for t in ("- rationale pointing at the new row", "Now names the gate as the reason", "| row | the reason is speed |"):
            self.assertNotIn("rationale", self.kinds("assistant", t), t)

    def test_decision_with_reason_is_rationale(self):
        self.assertIn("rationale", self.kinds("assistant", "We decided to wait because the gate is closed."))

    def test_reason_in_block_after_decision(self):
        prev = B("assistant", "We decided to wait.")
        self.assertIn("rationale", self.kinds("assistant", "The gate is closed so that nothing ships.", prev))
        self.assertNotIn("rationale", self.kinds("assistant", "The gate is closed so that nothing ships."))

    def test_insight_verbs_only(self):
        self.assertNotIn("insight", self.kinds("assistant", "Following today's lesson"))
        self.assertNotIn("insight", self.kinds("assistant", "| Option | insight |\n|---|---|\n| A | x |"))
        self.assertIn("insight", self.kinds("assistant", "It turns out the pin was stale."))


class RulesC2b(unittest.TestCase):       # guru review fixes: measured 40% on real transcripts
    def kinds(self, role, text):
        return {c["kind"] for c in DR.candidates([B(role, text)])}

    def test_assistant_approval_wording_is_not_a_decision(self):
        for t in ("That is the 8k he approved.", "We are about 2k past the cap, agreed.", "the operator approved the full build"):
            self.assertNotIn("decision", self.kinds("assistant", t))

    def test_assistant_first_person_decision_is_one(self):
        for t in ("I decided to keep the cache.", "Going with option A.", "We will ship Friday.", "Settled on the short form."):
            self.assertIn("decision", self.kinds("assistant", t))

    def test_operator_short_approval_only_when_short(self):
        self.assertIn("decision", self.kinds("operator", "yes, approved"))
        self.assertNotIn("decision", self.kinds("operator", "I went through the notes and he approved " + "x" * 200))

    def test_option_table_is_a_proposal_not_a_rationale(self):
        t = "| Option | Trade-off |\n|---|---|\n| A | cheap, the reason is speed |\n| B | slow |"
        k = self.kinds("assistant", t)
        self.assertIn("proposal", k)
        self.assertNotIn("rationale", k)
        self.assertIn("proposal", self.kinds("assistant", "Keep it simple (Recommended)\nOr rewrite it"))

    def test_numbered_steps_are_not_proposals(self):
        self.assertNotIn("proposal", self.kinds("assistant", "1. Sign in to the console\n2. Paste this once\n3. Save"))
        self.assertIn("proposal", self.kinds("assistant", "Options:\n1. keep\n2. drop"))

    def test_operator_paths_commands_banners_skipped(self):
        for t in ("/Users/x/file.md decided yes", "python3 run.py because I decided", "Operator act waiting. I decided nothing",
                  "~/notes go ahead", "git status; going with it"):
            self.assertEqual(DR.candidates([B("operator", t)]), [], t)


class Distill(unittest.TestCase):
    def test_no_model_entries_are_unclear_and_ids_cited(self):
        es, info = VD.distill(BLOCKS, "s1")
        self.assertTrue(es and all(e["tag"] == "unclear" for e in es))
        self.assertIn(["D-12345"], [e["ids"] for e in es])
        self.assertEqual(info["quote"], 0)

    def test_model_tags_closed_set_and_off_vocab_ignored(self):
        def model(prompt, m):
            return json.dumps({"tags": [{"n": 1, "tag": "settled"}, {"n": 2, "tag": "invented"}]})
        es, _ = VD.distill(BLOCKS, "s1", model_fn=model)
        self.assertEqual([e["tag"] for e in es][:2], ["settled", "unclear"])

    def test_verifier_drops_a_quote_not_in_the_source(self):
        es, info = VD.distill(BLOCKS, "s1", source_text="nothing here")
        self.assertEqual(es, [])
        self.assertGreater(info["quote"], 0)

    def test_model_failure_still_writes_entries(self):
        def bad(prompt, m):
            raise RuntimeError("down")
        es, info = VD.distill(BLOCKS, "s1", model_fn=bad)
        self.assertTrue(es)
        self.assertIn("model skipped", info["note"])

    def test_ledger_file_by_month_and_idempotent(self):
        ex = tempfile.mkdtemp()
        es, _ = VD.distill(BLOCKS, "s1")
        n = VD.write_ledger(ex, es)
        self.assertEqual(n, len(es))
        self.assertEqual(VD.write_ledger(ex, es), 0)
        p = os.path.join(ex, "ledger", "decisions", "2026-10.jsonl")
        self.assertEqual(len(open(p).read().splitlines()), n)
        self.assertEqual(oct(os.stat(p).st_mode & 0o777), "0o600")


class Sweep(unittest.TestCase):          # piece 6
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.src, self.root, self.ex = (os.path.join(self.d, x) for x in ("src", "root", "ex"))
        os.makedirs(os.path.join(self.src, "proj"))
        os.makedirs(self.ex)
        self.now = time.time()
        self.log = os.path.join(self.d, "log.jsonl")
        with open(self.log, "w") as f:
            f.write(json.dumps({"type": "session.bound", "data": {"session_id": "aaaa1111"}}) + "\n")
        self.settings = os.path.join(self.d, "settings.json")

    def mk(self, sid, age_days, lines=("Go with A, because totals matter.",)):
        p = os.path.join(self.src, "proj", sid + ".jsonl")
        with open(p, "w") as f:
            for t in lines:
                f.write(json.dumps(entry("operator", t)) + "\n")
        t = self.now - age_days * 86400
        os.utime(p, (t, t))

    def put(self, d):
        with open(self.settings, "w") as f:
            json.dump(d, f)

    def sweep(self, **kw):
        return ES.run(self.ex, source=self.src, root=self.root, cache=os.path.join(self.d, "cache"), ledger=self.log,
                      settings=self.settings, now=self.now, **kw)

    def test_period_read_live_default_30(self):
        self.assertEqual(ES.read_period(self.settings), 30)
        self.put({"cleanupPeriodDays": 10})
        self.assertEqual(ES.read_period(self.settings), 10)
        self.put({"cleanupPeriodDays": "x"})
        self.assertEqual(ES.read_period(self.settings), 30)

    def test_due_is_day_25_of_30_and_follows_the_setting(self):
        self.mk("aaaa1111", 26)
        self.mk("cccc3333", 10)
        s = ES.list_sessions(self.src)
        self.assertEqual(ES.due(s, self.now, 30), ["aaaa1111"])
        self.assertEqual(ES.due(s, self.now, 14), ["aaaa1111", "cccc3333"])

    def test_dry_run_lists_due_reads_nothing_writes_nothing(self):
        self.mk("aaaa1111", 26)
        self.mk("bbbb2222", 27)
        r = self.sweep(dry_run=True)
        self.assertEqual((r["due"], r["unregistered"]), (["aaaa1111"], ["bbbb2222"]))
        self.assertFalse(os.path.exists(os.path.join(self.ex, "ledger")))
        self.assertFalse(os.path.exists(self.root))
        self.assertFalse(os.path.exists(os.path.join(self.ex, "_harness")))

    def test_run_distils_registered_never_reads_unregistered(self):
        self.mk("aaaa1111", 26)
        self.mk("bbbb2222", 27, ("Go with B, secret plan.",))
        r = self.sweep()
        self.assertEqual(r["distilled"], ["aaaa1111"])
        self.assertEqual(r["unregistered_count"], 1)
        led = ""
        for base in (os.path.join(self.ex, "ledger"), self.root):
            for dp, _d, fs in os.walk(base):
                for fn in fs:
                    led += open(os.path.join(dp, fn)).read()
        self.assertIn("totals matter", led)
        self.assertNotIn("secret plan", led)

    def test_second_run_does_nothing_for_done_sessions(self):
        self.mk("aaaa1111", 26)
        self.sweep()
        r = self.sweep()
        self.assertEqual((r["due"], r["distilled"], r["entries"]), ([], [], 0))

    def test_growing_session_adds_only_the_new_tail(self):
        self.mk("aaaa1111", 26, ("Go with A, because totals matter.",))
        r1 = self.sweep()
        n1 = r1["entries"]
        self.assertGreater(n1, 0)
        self.mk("aaaa1111", 26, ("Go with A, because totals matter.", "I decided to keep the weekly cadence."))
        os.utime(os.path.join(self.src, "proj", "aaaa1111.jsonl"), (self.now - 26 * 86400 + 5,) * 2)
        r2 = self.sweep()
        self.assertEqual(r2["distilled"], ["aaaa1111"])
        self.assertGreater(r2["entries"], 0)
        led = "".join(open(os.path.join(self.ex, "ledger", "decisions", f)).read() for f in os.listdir(os.path.join(self.ex, "ledger", "decisions")))
        self.assertEqual(sum(1 for ln in led.splitlines() if "weekly cadence" in ln), 1)
        self.assertEqual(sum(1 for ln in led.splitlines() if '"line": 0' in ln and '"kind": "decision"' in ln), 1)
        self.assertEqual(len(led.splitlines()), n1 + r2["entries"])


if __name__ == "__main__":
    unittest.main()
