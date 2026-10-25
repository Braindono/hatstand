"""cc 0.17.0 R-051d vault backfill (operator go D-cba36): indexed transcripts -> one vault file per role-holding agent
(Haiku tags, budgeted, resumable), handoff capsules -> one file per capsule from their own tags (no model), and the
list of what stays unrecoverable. Dry run writes nothing and calls no model. Run: python3 -B tests/test_c170_r051d.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _env  # noqa: F401  isolate HOME and HARNESS_* first
import contextlib, io, json, os, sys, tempfile, time, unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
import harness as H
import vault as V

MODEL = "claude-opus-5-5"
KEY = "sk-ant-" + "P" * 30


def ts(t):
    return time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(t))


CAPSULE = """---
handoff: harness-ops/2026-10-20-old-chat
from: Old Chat #0ddc0de0 (ops-coder)
model: claude-opus-5-5
project: harness-ops
created: 2026-10-20
status: accepted
---
# Handoff
## 5b. Operator asks in this chat
- [done] restore as ops-coder from the misty capsule
- [open] write the weekly report
- [dropped] move the vault into iCloud
"""


class Backfill(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.home = os.path.join(self.tmp, "Exchange")
        os.makedirs(os.path.join(self.home, "_harness"))
        self.ix = os.path.join(self.tmp, "ix")
        os.makedirs(self.ix)
        self.ops = os.path.join(self.tmp, "ops")
        os.makedirs(self.ops)
        e = mock.patch.dict(os.environ, {"INDEXER_ROOT": self.ix, "HARNESS_STATE_CACHE": "0", "HARNESS_OPS_ROOT": self.ops,
                                         "INDEXER_CACHE": os.path.join(self.tmp, "ixcache")})
        e.start()
        self.addCleanup(e.stop)
        self.h = H.Harness(self.home)
        self.ids = {}
        for role in ("ops-coder", "envoy"):
            self.h.role_define("operator", role, "harness-ops")
            a = self.h.register(project="harness-ops", model=MODEL)["id"]
            self.h.role_assign("operator", role, a)
            self.ids[role] = a
        self.loner = self.h.register(project="harness-ops", model=MODEL)["id"]      # never had a role
        t0 = time.time() - 86400
        self.put("aaaaaaaa-1", self.ids["ops-coder"], [("operator", t0, "build the vault writer"), ("assistant", t0 + 1, "on it"),
                                                        ("operator", t0 + 2, "use key %s for the test" % KEY)])
        self.put("bbbbbbbb-2", self.ids["envoy"], [("operator", t0 + 10, "accept stage one")])
        self.put("cccccccc-3", self.loner, [("operator", t0 + 20, "no role here")])
        self.put("dddddddd-4", None, [("operator", t0 + 30, "allow-listed, not in the ledger")])
        caps = os.path.join(self.home, "projects", "harness-ops", "handoffs")
        os.makedirs(caps)
        with open(os.path.join(caps, "2026-10-20-old-chat.md"), "w") as f:
            f.write(CAPSULE)
        with open(os.path.join(caps, "2026-10-21-no-from.md"), "w") as f:
            f.write("---\ncreated: 2026-10-21\n---\n- [open] something\n")
        with open(os.path.join(caps, "2026-10-22-no-asks.md"), "w") as f:
            f.write(CAPSULE.split("## 5b")[0])
        self.prompts = []

    def put(self, sid, aid, blocks):
        if aid:
            self.h.store.append("session.bound", aid, {"session_id": sid, "agent": aid})
        with open(os.path.join(self.ix, "2026-10-24-p-%s.md" % sid[:8]), "w") as f:
            f.write("".join("### %s %s\n> %s\n\n" % (r, ts(t), x) for r, t, x in blocks))

    def model(self, prompt, model):
        self.prompts.append(prompt)
        n = prompt.count("\n   reply: ")
        return json.dumps({"tags": [{"n": k, "tag": "done", "reason": "done in chat"} for k in range(1, n + 1)]})

    def vault_files(self):
        root = V.vault_root(self.home)
        return sorted(os.path.relpath(os.path.join(d, f), root) for d, _s, fs in os.walk(root) for f in fs if f.endswith(".md")) \
            if os.path.isdir(root) else []

    def test_dry_run_counts_and_writes_nothing(self):
        r = V.backfill(self.h, dry_run=True, model_fn=self.model)
        self.assertEqual((r["agents"], r["asks"], r["agents_written"]), (3, 4, 0))   # the role-less agent is filed as unassigned
        self.assertGreater(r["prompt_tokens_est"], 0)
        self.assertEqual((r["capsules"], r["capsules_with_asks"], r["capsule_asks"]), (3, 1, 3))
        u = r["unrecoverable"]
        self.assertEqual((u["agents_filed_unassigned"], u["transcript_files_without_ledger_session"], u["capsules_without_role_line"]), (1, 1, 1))
        self.assertIn("before 2026-10-24", u["before_first_transcript"])
        self.assertEqual(self.prompts, [])
        self.assertEqual(self.vault_files(), [])

    def test_apply_writes_per_agent_and_per_capsule_without_the_key(self):
        r = V.backfill(self.h, dry_run=False, model_fn=self.model)
        self.assertEqual(r["agents_written"], 3)
        self.assertEqual(len(r["capsule_files"]), 1)
        files = self.vault_files()
        self.assertEqual(len(files), 4)
        self.assertTrue(any(f.startswith("harness-ops/ops-coder/") and "capsule" in f for f in files))
        self.assertTrue(any(f.startswith("harness-ops/unassigned/") for f in files))
        self.assertEqual(len(self.prompts), 1 + 3)                  # the preflight call, then one per agent
        for p in self.prompts:
            self.assertNotIn("P" * 30, p)
        for f in files:
            with open(os.path.join(V.vault_root(self.home), f)) as fh:
                doc = fh.read()
            self.assertNotIn("P" * 30, doc)
            self.assertIn("⟦UNTRUSTED", doc)
        cap = [f for f in files if "capsule" in f][0]
        meta = V.read_meta(os.path.join(V.vault_root(self.home), cap))
        self.assertEqual((meta["trigger"], meta["asks"], meta["open"], meta["model"]), ("backfill-capsule", 3, 1, "none"))

    def test_resume_skips_what_is_done(self):
        V.backfill(self.h, dry_run=False, model_fn=self.model)
        n = len(self.prompts)
        r = V.backfill(self.h, dry_run=False, model_fn=self.model)
        self.assertEqual((r["agents_done_before"], r["agents_written"], r["capsules_done_before"]), (3, 0, 1))
        self.assertEqual(len(self.prompts), n + 1)                  # only the preflight
        self.assertEqual(len(self.vault_files()), 4)

    def test_budget_stops_before_the_next_call_and_resumes(self):
        r = V.backfill(self.h, dry_run=False, model_fn=self.model, max_tokens=1)
        self.assertEqual(r["agents_written"], 1)
        self.assertIn("token budget 1 reached", r["stopped"])
        r2 = V.backfill(self.h, dry_run=False, model_fn=self.model, max_tokens=10 ** 6)
        self.assertEqual((r2["agents_done_before"], r2["agents_written"]), (1, 2))

    def test_capsule_files_do_not_move_the_window(self):
        V.backfill(self.h, dry_run=False, model_fn=self.model)
        vdir = os.path.join(V.vault_root(self.home), "harness-ops", "ops-coder")
        lu = V.last_until(vdir)
        self.assertTrue(lu.startswith(ts(time.time() - 86400)[:10]))   # the transcript backfill's last ask, not 2026-10-20

    def test_preflight_failure_writes_nothing(self):
        def down(prompt, model):
            raise V.ModelUnavailable("no login")
        r = V.backfill(self.h, dry_run=False, model_fn=down)
        self.assertIn("preflight model call failed", r["stopped"])
        self.assertEqual(self.vault_files(), [])

    def test_model_failure_mid_run_stops_without_an_untagged_file(self):
        calls = {"n": 0}

        def flaky(prompt, model):
            calls["n"] += 1
            if calls["n"] == 3:                                    # preflight ok, first agent ok, second fails
                raise V.ModelUnavailable("rate limited")
            return self.model(prompt, model)
        r = V.backfill(self.h, dry_run=False, model_fn=flaky)
        self.assertEqual(r["agents_written"], 1)
        self.assertIn("rate limited", r["stopped"])
        r2 = V.backfill(self.h, dry_run=False, model_fn=self.model)
        self.assertEqual((r2["agents_done_before"], r2["agents_written"]), (1, 2))
        for f in self.vault_files():
            m = V.read_meta(os.path.join(V.vault_root(self.home), f))
            self.assertEqual(m["untagged"], 0, f)

    def test_redo_untagged_archives_and_rewrites(self):
        def partial(prompt, model):                     # tags only ask 1 of each agent: the rest stay untagged
            self.prompts.append(prompt)
            return json.dumps({"tags": [{"n": 1, "tag": "done"}]})
        V.backfill(self.h, dry_run=False, model_fn=partial)
        bad = V.redo_candidates(self.home)
        self.assertEqual(len(bad), 1)                   # only the ops-coder chat has 2 asks
        dry = V.backfill(self.h, dry_run=True, model_fn=self.model, redo_untagged=True)
        self.assertEqual((dry["redo_files"], dry["asks"]), (1, 2))
        self.assertTrue(os.path.exists(bad[0]))         # the dry run moved nothing
        r = V.backfill(self.h, dry_run=False, model_fn=self.model, redo_untagged=True)
        self.assertEqual((r["redo_files"], r["agents_written"], r["agents_done_before"]), (1, 1, 2))
        self.assertEqual(V.read_meta(bad[0])["untagged"], 0)     # the rewrite takes the freed name, fully tagged
        self.assertEqual(V.redo_candidates(self.home), [])
        adir = [d for d in os.listdir(os.path.join(self.home, "_archive")) if d.endswith("vault-backfill-redo")][0]
        with open(os.path.join(self.home, "_archive", adir, "MANIFEST.sha256")) as f:
            line = f.read().split()
        self.assertEqual(line[2], os.path.relpath(bad[0], self.home))
        self.assertTrue(os.path.exists(os.path.join(self.home, line[3])))

    def test_cli_dry_run(self):
        with contextlib.redirect_stdout(io.StringIO()) as o:
            H.main(["--home", self.home, "vault-backfill"])
        out = json.loads(o.getvalue())
        self.assertTrue(out["dry_run"])
        self.assertEqual(self.vault_files(), [])


class Usage(unittest.TestCase):
    def test_json_output_counts_tokens_and_text_falls_back(self):
        def run(argv, **kw):
            if argv[:3] == ["claude", "auth", "status"]:
                return mock.Mock(returncode=0, stdout=json.dumps({"loggedIn": True, "authMethod": "claude.ai"}))
            self.assertIn("json", argv)
            return mock.Mock(returncode=0, stderr="", stdout=json.dumps(
                {"result": '{"tags":[]}', "usage": {"input_tokens": 100, "output_tokens": 20, "cache_read_input_tokens": 5}}))
        before = dict(V.USAGE)
        self.assertEqual(V.claude_cli("p", "haiku", run=run), '{"tags":[]}')
        self.assertEqual((V.USAGE["calls"] - before["calls"], V.USAGE["tokens"] - before["tokens"]), (1, 125))

        def run_text(argv, **kw):
            if argv[:3] == ["claude", "auth", "status"]:
                return mock.Mock(returncode=0, stdout=json.dumps({"loggedIn": True, "authMethod": "claude.ai"}))
            return mock.Mock(returncode=0, stderr="", stdout='{"tags":[]}')
        self.assertEqual(V.claude_cli("p", "haiku", run=run_text), '{"tags":[]}')


if __name__ == "__main__":
    unittest.main()
