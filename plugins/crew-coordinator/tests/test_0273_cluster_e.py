"""0.27.3 cluster E: change_feed (resource mapping, generated list, --since, role filter, digest line) and its restore/sync line.
Temp HOME only; no real ledger. Run: python3 -B -m unittest tests.test_0273_cluster_e"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _env  # noqa: F401  isolate HOME and HARNESS_* first
import io, json, os, sys, tempfile, unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
import change_feed as CF

SAMPLE = os.path.join(HERE, "..", "docs", "resources.sample.json")
EX = "Exch" + "ange"      # built by concatenation (rules 5a/5e)


def rec(path, ts, by="Wren", note="x", actor="a1"):
    return {"path": path, "ts": ts, "by": by, "actor": actor, "note": note, "version": 1}


class T(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="cf-")
        os.makedirs(os.path.join(self.home, "_harness"))
        self.res = [{"id": "core", "name": "CORE", "prefixes": [EX + "/rules/CORE.md"], "roles": []},
                    {"id": "curator", "name": "curator file", "prefixes": [EX + "/rules/roles/curator.md"], "roles": ["curator"]},
                    {"id": "rules", "name": "rules", "prefixes": [EX + "/rules"], "roles": []}]

    def put_resources(self):
        with open(CF.resources_path(self.home), "w") as f:
            json.dump({"resources": self.res}, f)

    def test_prefix_mapping_longest_wins_and_segment_boundary(self):
        self.assertEqual(CF.resource_for(EX + "/rules/CORE.md", self.res)["id"], "core")
        self.assertEqual(CF.resource_for(EX + "/rules/other.md", self.res)["id"], "rules")
        self.assertIsNone(CF.resource_for(EX + "/rulesX/a.md", self.res))
        self.assertIsNone(CF.resource_for("elsewhere/a.md", self.res))

    def test_unmapped_counted_not_dropped(self):
        recs = [rec("elsewhere/a.md", "2026-11-24T10:00:00Z"), rec("elsewhere/b.md", "2026-11-24T10:01:00Z"),
                rec(EX + "/rules/CORE.md", "2026-11-24T11:00:00Z", note="new rule")]
        txt = CF.render(recs, self.res)
        self.assertIn("other (unmapped paths): 2 edit(s)", txt)
        self.assertIn("| CORE | new rule | Wren", txt)
        self.assertLess(txt.index("other x2"), txt.index("| CORE |"))     # newest last

    def test_write_never_overwrites_hand_notes(self):
        self.put_resources()
        hand = os.path.join(self.home, "CHANGES.md")
        with open(hand, "w") as f:
            f.write("hand")
        with self.assertRaises(ValueError):
            CF.write_generated(self.home, hand)
        out = CF.write_generated(self.home)
        self.assertEqual(os.path.basename(out), "CHANGES.generated.md")
        self.assertEqual(open(hand).read(), "hand")

    def test_since_cli_limits_rows(self):
        self.put_resources()
        with open(os.path.join(self.home, "_harness", "events.jsonl"), "w") as f:
            for i in range(6):
                f.write(json.dumps({"type": "artifact.versioned", "actor": "a%d" % i, "ts": "2026-11-24T1%d:00:00.000Z" % i,
                                    "data": {"path": EX + "/rules/f%d.md" % i, "version": 1, "note": "n%d" % i}}) + "\n")
        out = io.StringIO()
        with mock.patch("sys.stdout", out):
            CF.main(["since", "2026-11-24T12:30:00Z", "--home", self.home, "--limit", "2"])
        lines = out.getvalue().strip().splitlines()
        self.assertEqual(len(lines), 2)
        self.assertIn("n5", lines[-1])
        self.assertEqual(CF.parse_since("garbage"), None)
        self.assertTrue(CF.parse_since("24h").endswith("Z"))

    def test_role_filter_and_own_edits(self):
        recs = [rec(EX + "/rules/roles/curator.md", "2026-11-24T10:00:00Z", note="cur"),
                rec(EX + "/rules/CORE.md", "2026-11-24T11:00:00Z", note="core", actor="me")]
        since = "2026-11-24T09:00:00Z"
        self.assertIn("curator file", CF.digest_line(recs, self.res, "curator", since))
        self.assertNotIn("curator file", CF.digest_line(recs, self.res, "envoy", since))
        self.assertNotIn("CORE", CF.digest_line(recs, self.res, "envoy", since, exclude_by={"me"}))
        self.assertEqual(CF.digest_line(recs, self.res, "envoy", since, exclude_by={"me"}), "")

    def test_digest_line_caps(self):
        res = [{"id": "r%d" % i, "name": "Resource number %d" % i, "prefixes": ["p%d" % i], "roles": []} for i in range(9)]
        recs = [rec("p%d/f" % i, "2026-11-24T10:%02d:00Z" % i, note="a fairly long summary text for " + "z" * 80) for i in range(9)]
        ln = CF.digest_line(recs, res, "x", "2026-11-24T09:00:00Z")
        self.assertLessEqual(len(ln), CF.CAP_CHARS)
        self.assertIn("more", ln)
        self.assertLessEqual(ln.count("Resource number"), CF.CAP_ROWS)
        self.assertEqual(CF.digest_line(recs, res, "x", None), "")

    def test_absent_resources_adds_nothing(self):
        self.assertIsNone(CF.load_resources(self.home))
        self.assertEqual(CF.digest_line([rec("p/f", "2026-11-24T10:00:00Z")], None, "x", "2026-01-01"), "")
        self.assertIsNone(CF.write_generated(self.home))

    def test_sample_ships_clean_and_loads(self):
        raw = open(SAMPLE).read()
        for bad in ("/" + "Users", "b" + "tf", "~/"):
            self.assertNotIn(bad, raw)
        rows = CF.load_resources(path=SAMPLE)
        self.assertGreaterEqual(len(rows), 25)
        self.assertEqual(CF.resource_for(EX + "/rules/CORE.md", rows)["id"], "core")


class Wired(unittest.TestCase):
    """The real restore digest and sync carry the line; absent resources.json changes nothing."""
    def setUp(self):
        import harness as H
        self.home = tempfile.mkdtemp(prefix="cfw-")
        self.h = H.Harness(self.home)
        self.h.role_define("operator", "coder", "harness-ops")
        self.a = self.h.register(project="harness-ops", role="coder", model="claude-sonnet-5-5")["id"]
        self.h.role_define("operator", "writer", "harness-ops")
        self.b = self.h.register(project="harness-ops", role="writer", model="claude-sonnet-5-5")["id"]
        self.h.sync(self.a)                                  # the reader's last sync

    def commit_other(self):
        path = os.path.join(self.home, "rules", "CORE.md")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        open(path, "w").write("v1")
        self.h.commit(self.b, "rules/CORE.md", note="new change-notes rule")

    def digest(self):
        return self.h.restore_digest(self.h.state(), self.a, "coder", [])

    def test_absent_resources_no_line_in_digest_or_sync(self):
        self.commit_other()
        self.assertNotIn("Changed since you last looked", self.digest())
        self.assertNotIn("Changed since you last looked", self.h.sync(self.a, mark=False)["text"])

    def test_line_in_digest_and_sync_with_resources(self):
        base = os.path.basename(self.home)
        with open(CF.resources_path(self.home), "w") as f:
            json.dump({"resources": [{"id": "core", "name": "CORE", "prefixes": [base + "/rules/CORE.md"], "roles": ["coder"]},
                                      {"id": "x", "name": "Other", "prefixes": [base + "/rules/Other.md"], "roles": ["envoy"]}]}, f)
        self.commit_other()
        d = self.digest()
        self.assertIn("Changed since you last looked: CORE (new change-notes rule)", d)
        self.assertEqual(d.count("Changed since you last looked"), 1)
        sy = self.h.sync(self.a, mark=False)["text"]
        self.assertIn("Changed since you last looked: CORE", sy)
        self.assertNotIn("Other", sy)


if __name__ == "__main__":
    unittest.main()
