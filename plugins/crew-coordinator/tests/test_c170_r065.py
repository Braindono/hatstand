"""cc 0.17.0 R-065: the restore digest shows ALL pinned decisions first (ranked, capped), not only pins among the newest
60 decisions; corpus search and harness_recall page past the 100-row clamp. Run: python3 -B tests/test_c170_r065.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _env  # noqa: F401  isolate HOME and HARNESS_* first
import json, os, re, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
import harness as H

MODEL = "claude-opus-5-5"


def decisions_section(dg):
    return dg.split("▸ Decisions in force")[1].split("\n▸ ")[0]


class R065(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.home = os.path.join(cls.tmp, "Exchange")
        os.makedirs(os.path.join(cls.home, "projects", "pp"))
        h = H.Harness(cls.home)
        h.role_define("operator", "builder", "pp")
        cls.aid = h.register(project="pp", model=MODEL)["id"]
        h.role_assign("operator", "builder", cls.aid)
        rec = lambda t, tags: h.record(cls.aid, "decision", t, "body " + t, tags=tags, project="pp")["id"]
        cls.std = rec("oldest standing rule", ["pin", "standing-rule"])          # oldest of all, ranked first
        cls.pins = [rec("ordinary pin %02d" % i, ["pin"]) for i in range(29)]   # 30 pins in total
        cls.cited = rec("cited by the foundation doc", [])                      # pinned by citation, no tag
        cls.newer = [rec("newer unpinned %02d" % i, []) for i in range(70)]     # pushes every pin out of the newest 60
        with open(os.path.join(cls.home, "projects", "pp", "FOUNDATIONS.md"), "w") as f:
            f.write("---\ndoc: foundations\n---\n# Foundations\n- %s\n" % cls.cited)
        cls.h = H.Harness(cls.home)

    def digest(self):
        st = self.h.state()
        return self.h.restore_digest(st, self.aid, "builder", [])

    def test_pins_outside_the_newest_60_are_shown_ranked_and_capped(self):
        sec = decisions_section(self.digest())
        self.assertIn("pinned 15 of 31", sec)                       # 30 tagged + 1 cited; default cap 15 (0.17.0 stage 2)
        ids = re.findall(r"\b[A-Z]-[0-9a-f]{5}\b", sec)
        self.assertIn(self.std, ids)
        self.assertIn(self.cited, ids)
        first_pin = [i for i in ids if i in set(self.pins) | {self.std, self.cited}][0]
        self.assertIn(first_pin, (self.std, self.cited))               # rank 0 (standing rule / cited) before ordinary pins
        self.assertIn("newest unpinned: " + self.newer[-1], sec)        # the newest unpinned decision is still there
        self.assertIn("+16 more pinned → harness_recall kind=decision tags=[pin] project=pp", sec)   # pointer to the rest (cap 15)

    def test_pin_cap_config(self):
        cfgp = os.path.join(self.home, "_harness", "config.json")
        cfg = json.load(open(cfgp))
        try:
            json.dump(dict(cfg, restore_pin_cap=3), open(cfgp, "w"))
            sec = decisions_section(self.digest())
            self.assertIn("pinned 3 of 31", sec)
            self.assertEqual(len([i for i in re.findall(r"\b[A-Z]-[0-9a-f]{5}\b", sec) if i not in self.newer]), 3)
        finally:
            json.dump(cfg, open(cfgp, "w"))

    def test_digest_head_stays_inside_the_budget(self):
        dg = self.digest()
        self.assertNotIn("digest cut at restore_budget", dg)

    def test_search_pages_past_the_clamp(self):
        c = self.h.corpus
        everything = c.search_all(None, kind="decision", project="pp")
        self.assertEqual(len(everything), 101)
        self.assertEqual(len({r["id"] for r in everything}), 101)       # no duplicates across pages
        p1 = c.search(None, limit=100, kind="decision", project="pp")
        p2 = c.search(None, limit=100, offset=100, kind="decision", project="pp")
        self.assertEqual((len(p1), len(p2)), (100, 1))
        self.assertFalse({r["id"] for r in p1} & {r["id"] for r in p2})

    def test_recall_offset_and_more_hint(self):
        r1 = self.h.recall(kind="decision", project="pp", tags=["pin"], limit=25)["text"]
        self.assertIn("more: offset=25", r1)
        r2 = self.h.recall(kind="decision", project="pp", tags=["pin"], limit=25, offset=25)["text"]
        self.assertIn("from 26", r2)
        self.assertNotIn("more: offset=", r2)
        ids1 = set(re.findall(r"^([A-Z]-[0-9a-f]{5}) ", r1, re.M))
        ids2 = set(re.findall(r"^([A-Z]-[0-9a-f]{5}) ", r2, re.M))
        self.assertEqual((len(ids1), len(ids2)), (25, 5))
        self.assertFalse(ids1 & ids2)

    def test_mcp_recall_schema_has_project_and_offset(self):
        import mcp_server as M
        props = [t for t in M.TOOLS if t[0] == "harness_recall"][0][2]
        self.assertIn("offset", props)
        self.assertIn("project", props)


if __name__ == "__main__":
    unittest.main()
