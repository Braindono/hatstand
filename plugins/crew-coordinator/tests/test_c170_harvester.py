"""cc 0.17.0 stage 0, R-052 phase 2: corrections harvester. Fixture vault only. Run: python3 -B tests/test_c170_harvester.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _env  # noqa: F401  isolate HOME and HARNESS_* first
import json, os, stat, sys, tempfile, unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
import corrections_harvester as C
import transcript_indexer as T


def vault_file(root, session, turns, day="2026-10-24"):
    lines = ["# Transcript %s (-p)\n" % session]
    for i, (role, text) in enumerate(turns):
        lines.append("### %s %s 10:%02d:00" % (role, day, i))
        lines += ["> " + x for x in text.splitlines()] or [">"]
        lines.append("")
    p = os.path.join(root, "%s--p-%s.md" % (day, session[:8]))
    with open(p, "w") as f:
        f.write("\n".join(lines) + "\n")
    return p


class Harvest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.root = os.path.join(self.tmp, "Transcripts.noindex")
        self.out = os.path.join(self.tmp, "cands")
        os.makedirs(self.root)
        vault_file(self.root, "aaaaaaaa-1111", [
            ("operator", "please build the report"),
            ("assistant", "I split it into two releases."),
            ("operator", "You should have asked me before splitting the release."),       # correct (strong)
            ("assistant", "Understood."),
            ("operator", "Remember this: one copyable command per block, no leading bang."),  # memory (strong)
            ("operator", "ok"),
            ("operator", "continue"),
            ("operator", "the weather is nice, never mind"),                                   # nothing
        ])
        vault_file(self.root, "bbbbbbbb-2222", [
            ("operator", "Please answer the mail from the envoy on the open thread today"),
            ("assistant", "Working on the build first."),
            ("operator", "please answer the mail from the envoy on the open thread, today!"),  # repeat
            ("operator", "No, that is the old path."),                                         # weak only: not enough
        ])

    def test_rules_find_the_three_corrections_only(self):
        hits = C.harvest(self.root)
        got = sorted((h["session"], tuple(h["signals"])) for h in hits)
        self.assertEqual(got, [("aaaaaaaa", ("correct",)), ("aaaaaaaa", ("memory",)), ("bbbbbbbb", ("repeat",))])
        prev = [h for h in hits if h["signals"] == ["correct"]][0]
        self.assertIn("split it into two releases", prev["before"])

    def test_writes_private_candidates_once(self):
        r = C.write_candidates(C.harvest(self.root), self.out)
        self.assertEqual(r, {"written": 3, "seen_before": 0, "skipped_redaction": 0})
        files = [os.path.join(dp, f) for dp, _, fs in os.walk(self.out) for f in fs if f.startswith("C-")]
        self.assertEqual(len(files), 3)
        for p in files:
            self.assertEqual(stat.S_IMODE(os.stat(p).st_mode), 0o600)
            txt = open(p).read()
            self.assertIn("status: candidate", txt)
            self.assertIn("untrusted", txt)
        self.assertEqual(stat.S_IMODE(os.stat(self.out).st_mode), 0o700)
        os.remove(files[0])                                    # the curator drops one (moves it away)
        again = C.write_candidates(C.harvest(self.root), self.out)
        self.assertEqual(again, {"written": 0, "seen_before": 3, "skipped_redaction": 0})

    def test_redaction_reapplied_and_fail_closed(self):
        vault_file(self.root, "cccccccc-3333", [
            ("operator", "I told you the key is " + "sk-" + "ant-abcdefghijklmnopqrstuvwxyz0123 stop using it"),   # split: hatstand scan
            ("operator", "You should have said so [private] details here"),
        ])
        hits = [h for h in C.harvest(self.root) if h["session"] == "cccccccc"]
        self.assertEqual(len(hits), 2)
        r = C.write_candidates(hits, self.out)
        self.assertEqual((r["written"], r["skipped_redaction"]), (1, 1))     # the [private] one is skipped
        txt = "".join(open(os.path.join(dp, f)).read() for dp, _, fs in os.walk(self.out) for f in fs if f.startswith("C-"))
        self.assertNotIn("sk-" + "ant-abcdefghijklmnopqrstuvwxyz0123", txt)
        with mock.patch.object(T, "redact", side_effect=RuntimeError("boom")):
            hits2 = C.harvest(self.root)
            r2 = C.write_candidates(hits2, os.path.join(self.tmp, "c2"))
        self.assertEqual(r2["written"], 0)

    def test_since_filters_but_keeps_repeat_memory(self):
        vault_file(self.root, "dddddddd-4444", [("operator", "Please answer the mail from the envoy on the thread now")], day="2026-10-01")
        vault_file(self.root, "dddddddd-4444", [
            ("operator", "Please answer the mail from the envoy on the thread now"),
            ("operator", "please answer the mail from the envoy on the thread now!!")], day="2026-10-24")
        hits = [h for h in C.harvest(self.root, since="2026-10-20") if h["session"] == "dddddddd"]
        self.assertEqual([h["signals"] for h in hits], [["repeat"]])

    def test_refuses_the_raw_transcript_folder(self):
        with mock.patch.dict(os.environ, {"INDEXER_SOURCE": self.root}):
            with self.assertRaises(SystemExit):
                C.harvest(self.root)

    def test_dry_run_prints_counts_only_and_writes_nothing(self):
        import io, contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            C.main(["--root", self.root, "--out", self.out, "--dry-run"])
        d = json.loads(buf.getvalue())
        self.assertEqual((d["hits"], d["sessions"]), (3, 2))
        self.assertNotIn("splitting", buf.getvalue())
        self.assertFalse(os.path.exists(self.out))


class Precision(unittest.TestCase):
    """0.17.0 precision fix: the curator's live run (10-25) dropped 19 'repeat' hits, all pasted commands run twice or
    affirmations. These exact shapes must not be flagged; a real repeated ask still is."""

    def test_commands_affirmations_and_pasted_paths_are_not_repeats(self):
        tmp = tempfile.mkdtemp()
        root = os.path.join(tmp, "Transcripts.noindex")
        os.makedirs(root)
        approve = "! python3 /Users/btf/Claude/Projects/Exchange/_harness/bin/harness.py approve A-0f819"
        turns = [
            ("operator", "! sh /Users/btf/Claude/Code/harness-ops/scripts/retag-cleanup.sh --dry-run"),
            ("operator", "! sh /Users/btf/Claude/Code/harness-ops/scripts/retag-cleanup.sh --dry-run"),
            ("operator", approve), ("operator", approve),
            ("operator", "! python3 /Users/btf/Claude/Projects/Exchange/_harness/bin/harness.py deny A-0f819"),
            ("operator", "python3 /Users/btf/Claude/Projects/Exchange/_harness/bin/harness.py role-define --role x"),
            ("operator", "python3 /Users/btf/Claude/Projects/Exchange/_harness/bin/harness.py role-define --role x"),
            ("operator", "/plan the stage two vault writer and the gate"),
            ("operator", "/plan the stage two vault writer and the gate"),
            ("operator", "Yes, add R-086 and R-087 to the 0.17.0 scope"),
            ("operator", "Yes, add R-086 and R-087 to the 0.17.0 scope."),
            ("operator", "ok"), ("operator", "ok"),
            ("operator", "Please write the stage two package for the envoy now"),
            ("operator", "please write the stage two package for the envoy now!"),     # a real repeat: still flagged
        ]
        vault_file(root, "cccccccc-3333", turns)
        hits = C.harvest(root)
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["signals"], ["repeat"])
        self.assertIn("stage two package", hits[0]["text"])

    def test_commands_are_never_scored_even_with_correction_words(self):
        tmp = tempfile.mkdtemp()
        root = os.path.join(tmp, "Transcripts.noindex")
        os.makedirs(root)
        vault_file(root, "dddddddd-4444", [("operator", "! echo 'you should have asked me first'"),
                                            ("operator", "/note remember this for next time")])
        self.assertEqual(C.harvest(root), [])


if __name__ == "__main__":
    unittest.main()
