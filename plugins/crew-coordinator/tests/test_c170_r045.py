"""cc 0.17.0 R-045 steward pass quality checks: frozen fixture, canary + bait, golden recall, unarchive round trip,
digest format adapter. Run: python3 -B tests/test_c170_r045.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _env  # noqa: F401  isolate HOME and HARNESS_* first
import json, os, shutil, sys, tempfile, unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
sys.path.insert(0, HERE)
import steward_check as S

HAVE_CI = os.path.isfile(S.CORPUS_INDEX)


class Fixture(unittest.TestCase):
    def test_fixture_is_frozen_and_complete(self):
        self.assertEqual(S.verify_frozen(), [])
        m = S.load_manifest()
        self.assertGreaterEqual(len(m["golden"]), 30)
        self.assertTrue(set(m["canary"]) <= set(m["flagged"]) and set(m["bait"]) <= set(m["flagged"]))
        self.assertEqual([g["present"] for g in m["golden"] if g["expect"] in m["bait"]], [False])

    def test_a_changed_fixture_is_refused(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        cp = os.path.join(tmp, "fx")
        shutil.copytree(S.FIXTURE, cp)
        with open(os.path.join(cp, "home", "OPERATOR.md"), "a") as f:
            f.write("tampered\n")
        open(os.path.join(cp, "home", "extra.md"), "w").close()
        probs = S.verify_frozen(cp)
        self.assertIn("changed: OPERATOR.md", probs)
        self.assertIn("added: extra.md", probs)
        with self.assertRaises(RuntimeError):
            S.stage(os.path.join(tmp, "work"), cp)


class Adapter(unittest.TestCase):
    V4 = {"schema": 1, "proof": {"exit": 3, "hash": "abc"}, "health": {"flagged": [{"id": "N-12345"}, {"id": "D-12345"}]}}

    def test_v4_bits_and_flagged(self):
        d = S.read_digest(self.V4)
        self.assertEqual((d["format"], d["exit"], d["bits"], d["flagged"]), ("v4", 3, ["lint", "over"], ["N-12345", "D-12345"]))
        self.assertIsNone(d["projects"])

    def test_unknown_format_is_an_error(self):
        with self.assertRaises(ValueError):
            S.read_digest({"schema": 9})

    def test_v5_is_a_data_change(self):
        v5 = {"detect": {"schema": 2}, "bits": {"lint_error": 1, "lint_warn": 8, "project_over": 2, "step_failed": 4},
              "exit": "proof.exit", "hash": "proof.hash", "flagged": "health.flagged", "projects": "projects"}
        with mock.patch.dict(S.FORMATS, {"v5": v5}):
            d = S.read_digest({"schema": 2, "proof": {"exit": 9, "hash": "h"}, "health": {"flagged": []},
                               "projects": [{"project": "secretary", "status": "▲"}]})
        self.assertEqual((d["format"], d["bits"]), ("v5", ["lint_error", "lint_warn"]))
        self.assertEqual(d["projects"][0]["project"], "secretary")

    def test_no_digest_fails(self):
        r = S.score("/nonexistent", "/nonexistent", None, S.load_manifest())
        self.assertEqual((r["verdict"], r["checks"][0]["name"]), ("FAIL", "digest_written"))


@unittest.skipUnless(HAVE_CI, "corpus_index.py not beside the build (ops/projects/orchestration/scripts)")
class Pass(unittest.TestCase):
    def failed(self, mode):
        r = S.check(mode)
        return r, sorted(c["name"] for c in r["checks"] if not c["ok"])

    def test_reference_steward_passes(self):
        r, bad = self.failed("reference")
        self.assertEqual((r["verdict"], bad), ("PASS", []), r)
        m = S.load_manifest()
        self.assertEqual(r["refused"], m["canary"])                 # the S6 gate keeps the canary
        self.assertIn(m["bait"][0], r["archived"])

    def test_a_pass_that_does_nothing_fails(self):
        r, bad = self.failed("none")
        self.assertEqual(r["verdict"], "FAIL")
        self.assertIn("bait_archived", bad)
        self.assertNotIn("canary_survived", bad)

    def test_an_eager_prune_fails(self):
        r, bad = self.failed("eager")
        self.assertEqual(r["verdict"], "FAIL")
        self.assertIn("canary_survived", bad)
        self.assertNotIn("bait_archived", bad)


if __name__ == "__main__":
    unittest.main()
