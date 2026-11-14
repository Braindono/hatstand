"""cc 0.26.0 item 19: quality-gate is an alias of the concept act.review. Run: python3 -B tests/test_c260_item19.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _env  # noqa: F401  isolate HOME and HARNESS_* first
import json
import os
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
_sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
import ontology as ON


class Alias(unittest.TestCase):
    def test_quality_gate_is_an_alias_of_act_review_and_a_known_tag(self):
        o = ON.load()
        self.assertEqual(o.names.get("quality-gate"), "act.review")
        self.assertEqual(o.tag_state("quality-gate"), ("known", None))
        self.assertIn("quality-gate", o.concepts["act.review"]["aliases"])

    def test_no_other_concept_claims_the_alias_and_the_file_is_valid_json(self):
        d = json.load(open(os.path.join(HERE, "..", "data", "ontology.json")))
        owners = [c["id"] for c in d["concepts"] if "quality-gate" in (c.get("aliases") or []) or c["id"].endswith(".quality-gate")]
        self.assertEqual(owners, ["act.review"])
        self.assertEqual(len({c["id"] for c in d["concepts"]}), len(d["concepts"]))


if __name__ == "__main__":
    unittest.main()
