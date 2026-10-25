"""cc 0.17.0 stage 0, C-live: the live-ledger check reads its source home only and reports the right counts.
Run: python3 -B tests/test_c170_c_live.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _env  # noqa: F401  isolate HOME and HARNESS_* first
import hashlib, json, os, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
import harness as H
import c_live

MODEL = "claude-opus-5-5"


def tree_digest(root):
    """{relpath: (sha256, mtime_ns)} for every file under root: any write, touch or new file changes it."""
    out = {}
    for dp, dns, fns in os.walk(root):
        for fn in fns:
            p = os.path.join(dp, fn)
            with open(p, "rb") as f:
                out[os.path.relpath(p, root)] = (hashlib.sha256(f.read()).hexdigest(), os.stat(p).st_mtime_ns)
    return out


class CLive(unittest.TestCase):
    def setUp(self):
        self.home = os.path.join(tempfile.mkdtemp(prefix="c-live-src-"), "Exchange")
        os.makedirs(self.home)
        h = H.Harness(self.home)
        h.role_define("operator", "ops-coder", "orch")
        self.coder = h.register(project="orch", model=MODEL)["id"]
        h.role_assign("operator", "ops-coder", self.coder)
        self.peer = h.register(project="orch", model=MODEL)["id"]
        h.send(self.peer, "role:ops-coder", "please review", subject="r1", kind="review")
        h.send(self.peer, self.coder, "fyi", subject="n1", kind="notice")
        h.record(self.peer, "decision", "pinned rule", "body text about restore digest", tags=["pin"], project="orch")
        del h

    def test_source_home_untouched_and_counts_right(self):
        before = tree_digest(self.home)
        res = c_live.run(self.home)
        self.assertEqual(tree_digest(self.home), before, "C-live wrote to its source home")
        row = res["roles"]["ops-coder"]
        self.assertEqual((row["unread"], row["owed"]), (2, 1))
        self.assertGreater(row["digest_tokens"], 0)
        self.assertEqual((row["pinned_visible"], row["pinned_in_project"]), (1, 1))
        self.assertEqual(res["corpus"]["pinned_decisions"], 1)
        self.assertEqual(set(res["corpus"]["recall"]), set(c_live.QUERIES))
        self.assertGreaterEqual(res["corpus"]["recall"]["restore digest"]["matches"], 1)

    def test_digest_read_marks_stay_in_the_copy(self):
        c_live.run(self.home)
        again = c_live.run(self.home)   # a write-through would have marked the mail read on the first run
        self.assertEqual(again["roles"]["ops-coder"]["unread"], 2)

    def test_env_restored_after_run(self):
        os.environ["HARNESS_HOME"] = "/nonexistent-sentinel"
        try:
            c_live.run(self.home)
            self.assertEqual(os.environ["HARNESS_HOME"], "/nonexistent-sentinel")
            self.assertNotIn("HARNESS_CACHE", os.environ)
        finally:
            os.environ.pop("HARNESS_HOME", None)

    def test_diff_counts_metrics_not_context(self):
        a = c_live.run(self.home)
        b = json.loads(json.dumps(a))
        b["taken"], b["ledger_seq"] = "later", a["ledger_seq"] + 5
        self.assertEqual(c_live.diff(a, b), [])
        b["roles"]["ops-coder"]["unread"] = 40
        self.assertEqual(c_live.diff(a, b), [("roles.ops-coder.unread", 2, 40)])

    def test_ab_same_code_no_diff_and_source_untouched(self):
        before = tree_digest(self.home)
        r = c_live.ab(self.home, c_live.SCRIPTS, c_live.SCRIPTS)
        self.assertEqual(tree_digest(self.home), before)
        self.assertEqual(r["diff"], [])
        self.assertEqual(r["old"]["ledger_seq"], r["new"]["ledger_seq"])     # one snapshot for both sides
        self.assertEqual(r["new"]["roles"]["ops-coder"]["unread"], 2)          # each side got its own fresh copy

    def test_cli_diff_exit_codes(self):
        a = c_live.run(self.home)
        d = tempfile.mkdtemp()
        pa, pb = os.path.join(d, "a.json"), os.path.join(d, "b.json")
        for p, v in ((pa, a), (pb, a)):
            with open(p, "w") as f:
                json.dump(v, f)
        self.assertEqual(c_live.main(["--diff", pa, pb]), 0)
        a["roles"]["ops-coder"]["owed"] = 9
        with open(pb, "w") as f:
            json.dump(a, f)
        self.assertEqual(c_live.main(["--diff", pa, pb]), 1)


if __name__ == "__main__":
    unittest.main()
