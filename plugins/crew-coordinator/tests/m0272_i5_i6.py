"""0.27.2 matrix rows for I5 (release checklist) and I6 (hook latency baseline). Each ROWS entry is one row of the I5 / I6 tables: fn(testcase).
Depends on: docs/RELEASE-CHECKLIST.md, hooks/hooks.json, tools/hook_latency.py, tools/hook_cases.py, scripts/harness.py."""
import json, os, pwd, re, sys, tempfile
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import hook_cases as HC
import hook_latency as HL

RUNS, MESSAGES = 2, 200
_CACHE = {}


def measured():
    """One small run shared by the I6 rows: 2 runs per hook on a 200-message ledger (the real baseline uses 20 runs and 3,000 messages)."""
    if "rows" not in _CACHE:
        live = os.path.join(pwd.getpwuid(os.getuid()).pw_dir, "Claude", "Projects", "Exchange", "_harness", "events.jsonl")
        before = _head(live)
        base = tempfile.mkdtemp(prefix="i6-cache-")
        _CACHE.update(base=base, live=live, before=before, rows=HL.measure(RUNS, MESSAGES, base=base))
        _CACHE["after"] = _head(live, before)
    return _CACHE


def r_checklist(tc):
    text = open(os.path.join(ROOT, "docs", "RELEASE-CHECKLIST.md"), encoding="utf-8").read()
    for needle in ("run_gates.py run", "release_sim.py --candidate", "release-questions.md", "change the package sha", "Gate file changed:", 'STARTS with "ACCEPT sha=',
                   "Package built last", "Build the package last"):
        tc.assertIn(needle, text, needle)
    import harness
    tc.assertIn("docs/RELEASE-CHECKLIST.md", harness.package_files(ROOT))                 # named in the package manifest


def _head(path, ref=None):
    """(size, sha256) of the live ledger; with ref, the hash of its first ref-size bytes (the ledger only grows while other sessions work)."""
    import hashlib
    if not os.path.isfile(path):
        return None
    n = ref[0] if ref else os.path.getsize(path)
    h, left = hashlib.sha256(), n
    with open(path, "rb") as f:
        while left > 0:
            b = f.read(min(1 << 20, left))
            if not b:
                break
            h.update(b); left -= len(b)
    return (n, h.hexdigest())


def r_ledger_synthetic_and_live_untouched(tc):
    c = measured()
    tc.assertEqual(c["before"], c["after"])      # same size and hash for the bytes that existed before (other sessions may append meanwhile)                                               # the live ledger is byte-identical (or absent on this machine)
    if c["before"] and os.path.isfile(c["live"]):      # critic round 2: appended bytes must carry none of the tool's synthetic rows
        import re
        with open(c["live"], "rb") as f:
            f.seek(c["before"][0])
            tc.assertIsNone(re.search(rb"synthetic message \d+ about the release gate", f.read()))
    home = os.path.join(HL.pristine(c["base"], MESSAGES)[0], "home")
    tc.assertTrue(home.startswith(c["base"]))
    lines = open(os.path.join(home, "_harness", "events.jsonl")).read().splitlines()
    types = [json.loads(x)["type"] for x in lines]
    tc.assertEqual(types.count("message.sent"), MESSAGES)
    tc.assertEqual(types.count("agent.registered"), 5)


def r_one_row_per_hook(tc):
    rows = measured()["rows"]
    hooks = HL.hooks_in()
    hook_rows = [r for r in rows if r["event"] != "import only"]
    tc.assertEqual(len(hook_rows), len(hooks))
    tc.assertEqual([(r["event"], r["hook"]) for r in hook_rows], [(e, HL.tail_of(c)) for e, _m, c in hooks])
    for r in hook_rows:
        tc.assertTrue(set(r) >= {"median_ms", "p90_ms", "exit", "proof", "verdict"}, r)
        tc.assertGreaterEqual(r["p90_ms"], r["median_ms"])
    with mock.patch.object(HC, "cases", return_value={}):                                  # a hook with no case is a row too, never a missing one
        tc.assertEqual(len(HL.measure(1, MESSAGES, base=measured()["base"], only=[HL.tail_of(hooks[0][2])])), 2)


def r_proof_of_path(tc):
    rows = [r for r in measured()["rows"] if r["event"] != "import only"]
    for r in rows:
        tc.assertEqual(r["verdict"], "measured", r)                                        # every shipped hook has a proof that held on every run
        tc.assertNotEqual(r["proof"], "none", r)
    row = HL.row("h", "Stop", [1.0, 2.0], 0, 0, None, 2)
    tc.assertEqual((row["verdict"], row["proof"]), ("early exit", "none"))
    tc.assertEqual(HL.row("h", "Stop", [1.0, 2.0], 1, 0, ("out", "x"), 2)["verdict"], "early exit")    # proof held on some runs only: not a measurement


def r_cache_keyed_on_code_sha(tc):
    c = measured()
    d1 = HL.pristine(c["base"], MESSAGES)[0]
    tc.assertIn(HL.ledger_key().split("-")[0], d1)
    import harness
    tc.assertTrue(os.path.basename(d1).startswith("ledger-" + harness.code_sha(ROOT, "plugin")[:12]))
    stamp = os.path.getmtime(os.path.join(d1, "ok"))
    tc.assertEqual(HL.pristine(c["base"], MESSAGES)[0], d1)                                # built once: the second call reuses it
    tc.assertEqual(os.path.getmtime(os.path.join(d1, "ok")), stamp)
    with mock.patch.object(HL, "ledger_key", return_value="0" * 12 + "-x"):
        tc.assertNotEqual(HL.pristine(c["base"], 50)[0], d1)


def r_day1_fails_on_early_exit(tc):
    hooks = HL.hooks_in()
    one = HL.tail_of(hooks[0][2])
    real = HC.cases
    with mock.patch.object(HC, "cases", side_effect=lambda h, i: {k: v for k, v in real(h, i).items() if k[1] != one}):
        with mock.patch.object(HL.sys, "stderr"), mock.patch("builtins.print"):
            rows = HL.measure(1, MESSAGES, base=measured()["base"], only=[one])
            tc.assertEqual(rows[0]["verdict"], "early exit")
            with mock.patch.object(HL, "measure", return_value=rows):
                tc.assertEqual(HL.main(["--day1"]), 1)
                tc.assertEqual(HL.main([]), 0)


def r_import_row(tc):
    r = [x for x in measured()["rows"] if x["event"] == "import only"]
    tc.assertEqual(len(r), 1)
    tc.assertEqual(r[0]["hook"], 'python3 -c "import harness"')
    tc.assertGreater(r[0]["median_ms"], 0)


def r_nonzero_exit_reported(tc):
    tc.assertEqual(HL.row("h", "Stop", [3.0], 1, 2, ("out", "x"), 1)["exit"], 2)
    tc.assertTrue(all("exit" in r for r in measured()["rows"]))


def r_hooks_json_files_exist(tc):
    for ev, _m, cmd in HL.hooks_in():
        rel = cmd.split("${CLAUDE_PLUGIN_ROOT}/", 1)[1].split('"')[0]
        tc.assertTrue(os.path.isfile(os.path.join(ROOT, rel)), (ev, rel))


ROWS = {"I5-01": r_checklist, "I6-01": r_ledger_synthetic_and_live_untouched, "I6-02": r_one_row_per_hook, "I6-03": r_proof_of_path, "I6-04": r_cache_keyed_on_code_sha,
        "I6-05": r_day1_fails_on_early_exit, "I6-06": r_import_row, "I6-07": r_nonzero_exit_reported, "I6-08": r_hooks_json_files_exist}
