"""cc 0.15.5 WP5: /compress (deterministic half). Run: python3 -B tests/test_cc155_compress.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _env  # noqa: F401  isolate HOME and HARNESS_* first
import json, os, shutil, sys, unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
import compress as CP
import harness as H
from test_cc151_w1 import Base, MODEL

RULE = "Always run the release gate before publish and cite the ACCEPT sha."
QS = f"""# Restore questions
## Q1: What must run before publish?
cites: PROJECT.md
expect: release gate; accept
## Q2: What is the naming rule?
cites: NAMING.md
expect: kebab
rule-bearing: no
"""


class CB(Base):
    def setUp(self):
        super().setUp()
        self.h.role_define("operator", "corpus-envoy", "proj")
        self.h.role_define("operator", "proj-lead", "proj")
        self.h.role_define("operator", "verifier", "proj")
        self.envoy = self.agent("corpus-envoy", "proj")
        self.lead = self.agent("proj-lead", "proj")
        self.ver = self.agent("verifier", "proj")
        self.root = os.path.join(self.home, "projects", "proj")
        os.makedirs(os.path.join(self.root, "notes"))
        self.w("PROJECT.md", f"# Project\n\n{RULE}\nOther text.\n")
        self.w("NAMING.md", "Use kebab-case names.\n")
        self.w("notes/old.md", "stale status from last month\n")
        self.w("restore-questions.md", QS)
        os.makedirs(os.path.join(self.root, "x-build"))
        self.w("x-build/code.md", "build tree is skipped\n")

    def w(self, rel, text):
        p = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        open(p, "w").write(text)

    def prop(self, **kw):
        d = {"chunk": 1, "candidates": [{"kind": "rule", "title": "Release gate", "body": RULE, "source": "PROJECT.md", "lines": "3-3",
                                         "quote": RULE, "rule_bearing": True}],
             "archive": [{"path": "notes/old.md", "reason": "stale"}]}
        d.update(kw)
        p = os.path.join(self.tmp, "proposal-1.json")
        json.dump(d, open(p, "w"))
        return p

    def flow_to_review(self):
        r = CP.start(self.h, "proj", self.envoy)
        run = r["run"]
        CP.snapshot(self.h, "proj", run, self.envoy)
        CP.propose(self.h, "proj", run, self.envoy, [self.prop()])
        CP.review(self.h, "proj", run, self.lead, {"k1": "accept", "archive:notes/old.md": "accept"})
        CP.review(self.h, "proj", run, self.envoy, {"k1": "accept", "archive:notes/old.md": "accept"})
        return run


class Start(CB):
    def test_dry_run_writes_only_the_run_folder(self):
        before = sorted(os.path.relpath(os.path.join(d, f), self.root) for d, _, fs in os.walk(self.root) for f in fs)
        r = CP.start(self.h, "proj", self.envoy)
        after = sorted(os.path.relpath(os.path.join(d, f), self.root) for d, _, fs in os.walk(self.root) for f in fs)
        new = [x for x in after if x not in before]
        self.assertTrue(new and all(x.startswith(f"compress{os.sep}{r['run']}{os.sep}") for x in new), new)
        self.assertEqual(r["report"]["files"], 4)          # build tree skipped
        self.assertTrue(r["report"]["restore_questions"] != "MISSING")
        inv = json.load(open(os.path.join(r["dir"], "inventory.json")))
        self.assertNotIn("x-build/code.md", [f["path"] for f in inv["files"]])
        self.assertTrue(os.path.isfile(os.path.join(r["dir"], "WORKER-SPEC.md")))
        self.assertTrue(self.types("compress.started"))

    def test_scheduled_run_is_report_only_and_filed_to_envoy(self):
        r = CP.start(self.h, "proj", self.lead, scheduled=True)
        self.assertEqual(r["report"]["mode"], "scheduled report-only dry run")
        self.assertFalse(os.path.exists(os.path.join(self.root, "_archive")))
        self.assertTrue(any("compress report" in (m.get("subject") or "") for m in self.h.state().messages.values()))


class Preconditions(CB):
    def test_apply_without_snapshot_refused(self):
        run = CP.start(self.h, "proj", self.envoy)["run"]
        CP.propose(self.h, "proj", run, self.envoy, [self.prop()])
        CP.review(self.h, "proj", run, self.lead, {"k1": "accept"})
        CP.review(self.h, "proj", run, self.envoy, {"k1": "accept"})
        with self.assertRaisesRegex(H.HarnessError, "snapshot"):
            CP.apply(self.h, "proj", run, self.envoy)
        self.assertTrue(os.path.isfile(os.path.join(self.root, "PROJECT.md")))

    def test_apply_needs_both_reviews_and_the_envoy_role(self):
        run = CP.start(self.h, "proj", self.envoy)["run"]
        CP.snapshot(self.h, "proj", run, self.envoy)
        CP.propose(self.h, "proj", run, self.envoy, [self.prop()])
        CP.review(self.h, "proj", run, self.envoy, {"k1": "accept"})
        with self.assertRaisesRegex(H.HarnessError, "lead's review"):
            CP.apply(self.h, "proj", run, self.envoy)
        CP.review(self.h, "proj", run, self.lead, {"k1": "accept"})
        with self.assertRaisesRegex(H.HarnessError, "curation grants"):
            CP.apply(self.h, "proj", run, self.lead)
        with self.assertRaisesRegex(H.HarnessError, "curation grants"):
            CP.apply(self.h, "proj", run, "operator")

    def test_restore_questions_changed_after_the_pin_refuses(self):
        run = self.flow_to_review()
        self.w("restore-questions.md", QS + "\n## Q3: added later\ncites: PROJECT.md\nexpect: x\n")
        with self.assertRaisesRegex(H.HarnessError, "restore-questions"):
            CP.apply(self.h, "proj", run, self.envoy)

    def test_fingerprint_change_forces_a_new_dry_run(self):
        run = self.flow_to_review()
        n = self.note(self.envoy)
        self.h.pin("operator", [n], True, '"rule line text"')     # the set of pins changed
        with self.assertRaisesRegex(H.HarnessError, "new dry run"):
            CP.apply(self.h, "proj", run, self.envoy)

    def test_snapshot_tampering_is_caught(self):
        run = self.flow_to_review()
        snap = os.path.join(self.root, "_archive", "snapshots")
        os.remove(os.path.join(snap, os.listdir(snap)[0], "NAMING.md"))
        with self.assertRaisesRegex(H.HarnessError, "snapshot"):
            CP.apply(self.h, "proj", run, self.envoy)

    def test_review_before_a_validated_proposal_refused(self):
        run = CP.start(self.h, "proj", self.envoy)["run"]
        with self.assertRaisesRegex(H.HarnessError, "propose"):
            CP.review(self.h, "proj", run, self.envoy, {"k1": "accept"})


class Proposal(CB):
    def test_unverbatim_quote_and_bad_paths_rejected(self):
        run = CP.start(self.h, "proj", self.envoy)["run"]
        bad = self.prop(candidates=[
            {"kind": "rule", "title": "t", "body": "b", "source": "PROJECT.md", "lines": "3-3", "quote": "invented rule text", "rule_bearing": True},
            {"kind": "rule", "title": "t", "body": "b", "source": "../../etc/passwd", "lines": "1-1", "quote": "x", "rule_bearing": True},
            {"kind": "rule", "title": "t", "body": "b", "source": "PROJECT.md", "lines": "40-41", "quote": RULE, "rule_bearing": True}],
            archive=[{"path": "restore-questions.md", "reason": "no"}, {"path": "nope.md", "reason": "no"}])
        r = CP.propose(self.h, "proj", run, self.envoy, [bad])
        self.assertEqual((r["candidates"], r["archive"], len(r["problems"])), (0, 0, 5))

    def test_proof_hash_is_stable(self):
        run = CP.start(self.h, "proj", self.envoy)["run"]
        a = CP.propose(self.h, "proj", run, self.envoy, [self.prop()])["proof"]
        b = CP.propose(self.h, "proj", run, self.envoy, [self.prop()])["proof"]
        self.assertEqual(a, b)


class ApplyVerify(CB):
    def test_pin_first_then_archive_and_resolve(self):
        run = self.flow_to_review()
        r = CP.apply(self.h, "proj", run, self.envoy)
        self.assertEqual(r["moved"], 1)
        self.assertFalse(os.path.exists(os.path.join(self.root, "notes", "old.md")))
        self.assertTrue(os.path.isfile(os.path.join(self.root, "_archive", "compressed", run, "notes", "old.md")))
        rid = r["records"][0]
        self.assertTrue(self.h.corpus.entry_meta(rid)["pinned"])
        self.assertEqual(CP.resolve(self.h, "proj", "notes/old.md")["archived"], True)
        order = [e["type"] for e in self.h.store.read_all() if e["type"] in ("corpus.pinned", "compress.applied")]
        self.assertEqual(order, ["corpus.pinned", "compress.applied"])
        with self.assertRaisesRegex(H.HarnessError, "already applied|needs a reviewed run"):
            CP.apply(self.h, "proj", run, self.envoy)

    def test_nothing_deleted_and_envoy_gate_decides(self):
        run = CP.start(self.h, "proj", self.envoy)["run"]
        CP.snapshot(self.h, "proj", run, self.envoy)
        CP.propose(self.h, "proj", run, self.envoy, [self.prop()])
        CP.review(self.h, "proj", run, self.lead, {"k1": "accept", "archive:notes/old.md": "accept"})
        CP.review(self.h, "proj", run, self.envoy, {"k1": "accept", "archive:notes/old.md": "reject"})
        CP.apply(self.h, "proj", run, self.envoy)
        self.assertTrue(os.path.isfile(os.path.join(self.root, "notes", "old.md")))     # envoy rejected the archive

    def test_verify_pass_fail_and_who_may_verify(self):
        run = self.flow_to_review()
        rec = CP.apply(self.h, "proj", run, self.envoy)["records"][0]
        good = {"Q1": {"answer": "The release gate must run; cite the ACCEPT sha", "cites": ["PROJECT.md"]},
                "Q2": {"answer": "kebab-case", "cites": ["NAMING.md"]}}
        for who in (self.envoy, self.lead, "operator"):
            with self.assertRaisesRegex(H.HarnessError, "fresh, non-gated"):
                CP.verify(self.h, "proj", run, who, good)
        bad = dict(good, Q1={"answer": "no idea", "cites": []})
        r = CP.verify(self.h, "proj", run, self.ver, bad)
        self.assertFalse(r["ok"])
        self.assertEqual((r["wrong"], r["uncited"]), (["Q1"], ["Q1"]))
        self.assertIn("compress restore", r["offer"])
        with self.assertRaisesRegex(H.HarnessError, "fresh, non-gated"):    # a verifier that already ran is no longer fresh
            CP.verify(self.h, "proj", run, self.ver, good)
        ver2 = self.agent(None, "proj")
        ok = CP.verify(self.h, "proj", run, ver2, good)
        self.assertTrue(ok["ok"], ok)

    def test_restore_brings_files_back_and_archives_records(self):
        run = self.flow_to_review()
        rec = CP.apply(self.h, "proj", run, self.envoy)["records"][0]
        r = CP.restore(self.h, "proj", run, self.envoy)
        self.assertEqual(r["files_restored"], 1)
        self.assertTrue(os.path.isfile(os.path.join(self.root, "notes", "old.md")))
        self.assertTrue(self.h.corpus.entry_meta(rec)["archived"])


class LintTune(CB):
    def test_lint_checks_questions_pin_and_cites(self):
        self.assertTrue(CP.lint(self.h, "proj")["ok"])
        run = CP.start(self.h, "proj", self.envoy)["run"]
        self.assertTrue(CP.lint(self.h, "proj")["ok"])
        self.w("restore-questions.md", QS.replace("PROJECT.md", "GONE.md"))
        r = CP.lint(self.h, "proj")
        self.assertFalse(r["ok"])
        self.assertTrue(any("does not resolve" in p for p in r["problems"]) and any("!= pin" in p for p in r["problems"]))
        os.remove(os.path.join(self.root, "restore-questions.md"))
        self.assertFalse(CP.lint(self.h, "proj")["ok"])

    def test_tuner_writes_only_a_proposal_in_the_run_folder(self):
        run = self.flow_to_review()
        pins_before = len([e for e in self.h.store.read_all() if e["type"] == "corpus.pinned"])
        out = CP.tune(self.h, "proj", run, self.envoy)
        self.assertTrue(out["proposal"].startswith(f"compress{os.sep}{run}{os.sep}"))
        self.assertEqual(len([e for e in self.h.store.read_all() if e["type"] == "corpus.pinned"]), pins_before)
        with self.assertRaisesRegex(H.HarnessError, "never writes rules or pins"):
            CP._guard("/x/rules/digest.json", "/x")

    def test_feedback_log_is_bounded(self):
        run = CP.start(self.h, "proj", self.envoy)["run"]
        d = os.path.join(self.root, "compress", run)
        for i in range(80):
            CP._feedback(d, "review", {"accept": i})
        self.assertEqual(len(json.load(open(os.path.join(d, "feedback.json")))), 50)

    def test_snapshot_report_lists_prunable_never_deletes(self):
        run = CP.start(self.h, "proj", self.envoy)["run"]
        base = os.path.join(self.root, "_archive", "snapshots")
        for n in ("20200101-000001", "20200101-000002", "20200101-000003", "20200101-000004", "20200101-000005"):
            os.makedirs(os.path.join(base, n))
            json.dump({"files": [], "sha": "x"}, open(os.path.join(base, n, "manifest.json"), "w"))
        rep = CP.start(self.h, "proj", self.envoy)["report"]
        self.assertEqual(len(rep["snapshots"]["prunable"]), 2)
        self.assertEqual(len(os.listdir(base)), 5)


class Cli(CB):
    def test_cli_start_and_lint(self):
        import subprocess
        env = dict(os.environ, HARNESS_HOME=self.home, PYTHONDONTWRITEBYTECODE="1")
        sc = os.path.join(HERE, "..", "scripts", "harness.py")
        out = subprocess.run([sys.executable, sc, "compress", "--project", "proj", "--agent", self.envoy[:8]], capture_output=True, text=True, env=env, stdin=subprocess.DEVNULL)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn('"run": "c-', out.stdout)
        out = subprocess.run([sys.executable, sc, "compress", "lint", "--project", "proj", "--agent", self.envoy[:8]], capture_output=True, text=True, env=env, stdin=subprocess.DEVNULL)
        self.assertIn('"ok": true', out.stdout)

    def test_skill_is_terse_and_states_the_flow(self):
        t = open(os.path.join(HERE, "..", "skills", "compress", "SKILL.md"), encoding="utf-8").read()
        self.assertLess(len(t.split("---", 2)[2]) / 4, 600)
        for must in ("dry run", "never deletes", "FRESH", "restore-questions.md", "S5 gate"):
            self.assertIn(must, t)


if __name__ == "__main__":
    unittest.main()
