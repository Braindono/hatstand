"""0.27.2 matrix rows for I1 (attach hook wired LOG-ONLY). Each ROWS entry is one row of the I1 table in the invariant map: fn(testcase). Depends on: scripts/attach_hook.py,
scripts/attach_state.py, hooks/hooks.json, harness.package_files. Text inputs marked FRAGMENT are fragments of real transcripts (success text and a refusal), never invented wording."""
import fcntl, io, json, os, re, shutil, stat, subprocess, sys, tempfile
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import attach_hook as AH, attach_state as AS

# FRAGMENT of a real Hub publish result (success) and of a real refusal; the tool's other wording is not asserted.
OK_FRAGMENT = "Published ... artifact/Bh95vCZDid4tqAZog6EYP8 (Version 88, version id 1795369775-10d9) Stored"
REFUSED_FRAGMENT = "Publish refused — nothing was merged or published"
ADD = {"files": {"attach-noop.txt": "x"}}
REMOVE = {"files": {"attach-noop.txt": None}}
OLD_LIST = {"files": [{"path": "attach-noop.txt", "content": "x"}], "remove": []}


def mkhome(tc, config=None):
    d = tempfile.mkdtemp(prefix="i1-")
    tc.addCleanup(shutil.rmtree, d, True)
    os.makedirs(os.path.join(d, "_harness"))
    if config is not None:
        with open(os.path.join(d, "_harness", "config.json"), "w") as f:
            json.dump(config, f)
    return d


def run_main(tc, home, payload, env=None):
    """-> (exit code, stdout) of attach_hook.main on one payload with HARNESS_HOME = home."""
    raw = payload if isinstance(payload, str) else json.dumps(payload)
    out, old = io.StringIO(), sys.stdout
    sys.stdout = out
    try:
        with mock.patch.dict(os.environ, dict({"HARNESS_HOME": home}, **(env or {}))):
            rc = AH.main(io.StringIO(raw))
    finally:
        sys.stdout = old
    return rc, out.getvalue()


def log_lines(home):
    p = os.path.join(home, "_harness", "attach_shapes.jsonl")
    return open(p).read().splitlines() if os.path.exists(p) else []


def post(tool, ti, resp, **kw):
    return dict({"hook_event_name": "PostToolUse", "tool_name": tool, "tool_input": ti, "tool_response": resp}, **kw)


def r_marker_logged(tc):
    shapes = [(OK_FRAGMENT, "str", "success"), ([{"type": "text", "text": OK_FRAGMENT}], "list", "success"), ({"content": [{"type": "text", "text": OK_FRAGMENT}]}, "dict", "success"),
              ({"structured": {"version": "88"}, "isError": False}, "dict", "success"), (json.dumps({"version": "88", "url": "x"}), "str", "success"), (None, "NoneType", "unknown"),
              (REFUSED_FRAGMENT, "str", "unknown")]
    for resp, typ, verdict in shapes:
        home = mkhome(tc)
        with mock.patch.object(AS, "STATE", os.path.join(home, "_harness", "attach_state.json")):
            rc, out = run_main(tc, home, post("Artifact", ADD, resp))
        lines = log_lines(home)
        tc.assertEqual((rc, out, len(lines)), (0, "", 1), resp)
        row = json.loads(lines[0])
        tc.assertEqual((row["event"], row["tool"], row["type"], row["verdict"]), ("PostToolUse", "Artifact", typ, verdict))
        tc.assertFalse(os.path.exists(os.path.join(home, "_harness", "attach_state.json")), "attach_state must not be written")
        tc.assertFalse(os.path.exists(os.path.join(home, "_harness", "attach_failures.jsonl")))
        tc.assertNotIn("artifact/", lines[0])                                    # no response text
        tc.assertNotIn("refused", lines[0])
    home = mkhome(tc)
    run_main(tc, home, post("mcp__hub__publish_files", OLD_LIST, {"content": [{"type": "text", "text": "x"}], "isError": False}))
    tc.assertEqual(json.loads(log_lines(home)[0])["keys"], ["content", "isError"])


def r_other_publishes_write_nothing(tc):
    cases = [{"action": "list"}, {"action": "read", "url": "https://claude.ai/artifact/Bh95vCZDid4tqAZog6EYP8"}, {"action": "delete", "url": "x"},
             {"files": {"index.html": "x"}}, {"files": [{"path": "other.txt"}], "remove": []}, dict(ADD, url="https://claude.ai/artifact/SomeOtherArtifact123456")]
    for ti in cases:
        home = mkhome(tc)
        rc, out = run_main(tc, home, post("Artifact", ti, OK_FRAGMENT))
        tc.assertEqual((rc, out, log_lines(home)), (0, "", []), ti)


def r_comments_and_data_write_nothing(tc):
    for tool, ti in (("ArtifactComments", {"url": "https://claude.ai/artifact/Bh95vCZDid4tqAZog6EYP8", "action": "list"}),
                     ("ArtifactData", {"url": "https://claude.ai/artifact/Bh95vCZDid4tqAZog6EYP8", "action": "set", "collection": "c", "doc_id": "d", "data": {"a": 1}})):
        home = mkhome(tc)
        rc, out = run_main(tc, home, post(tool, ti, "ok"))
        tc.assertEqual((rc, out, log_lines(home)), (0, "", []), tool)


def r_never_raises_prints_nothing(tc):
    home = mkhome(tc)
    for raw in ("", "not json", "[]", "5", json.dumps({"tool_input": 5}), json.dumps(post("Artifact", ADD, {"a": {"b": [1] * 100}})), json.dumps({"tool_input": ADD, "tool_response": "x" * 3_000_000})):
        tc.assertEqual(run_main(tc, home, raw), (0, ""), raw[:30])
    p = subprocess.run([sys.executable, "-B", os.path.join(ROOT, "scripts", "attach_hook.py")], input="not json", capture_output=True, text=True, env={"HARNESS_HOME": home, "PATH": "/usr/bin"})
    tc.assertEqual((p.returncode, p.stdout, p.stderr), (0, "", ""))


def _messages(tc, resp, want, op=None, tool_input=None):
    """attach_messages true (the 0.27.3 switch): the original messages and state."""
    home = mkhome(tc, {"attach_messages": True})
    st = os.path.join(home, "_harness", "attach_state.json")
    with mock.patch.object(AS, "STATE", st):
        rc, out = run_main(tc, home, post("Artifact", tool_input or ADD, resp, session_id="s1"))
    tc.assertEqual(rc, 0)
    if want == "op":
        tc.assertEqual(out, "")
        tc.assertEqual(json.load(open(st))["present"], op == "add")
        tc.assertEqual(log_lines(home), [])
    else:
        tc.assertIn(want, json.loads(out)["hookSpecificOutput"]["additionalContext"])
        tc.assertFalse(os.path.exists(st))


def r_messages_success(tc): _messages(tc, OK_FRAGMENT, "op", "add")
def r_messages_refused(tc): _messages(tc, REFUSED_FRAGMENT, "NOT CONFIRMED")
def r_messages_unchanged(tc): _messages(tc, {"unchanged": True}, "FAILED")
def r_messages_conflict(tc): _messages(tc, "Conflict: a newer version ... Published earlier", "NOT CONFIRMED")      # FRAGMENT wording of a conflict text
def r_messages_none(tc): _messages(tc, None, "NOT CONFIRMED")
def r_messages_error(tc): _messages(tc, {"error": "forbidden"}, "NOT CONFIRMED")


def r_messages_default_off(tc):
    tc.assertFalse(AH.messages_on(mkhome(tc)))
    tc.assertFalse(AH.messages_on(mkhome(tc, {"attach_messages": "true"})))
    tc.assertFalse(AH.messages_on(mkhome(tc, {"attach_messages": False})))
    tc.assertTrue(AH.messages_on(mkhome(tc, {"attach_messages": True})))
    tc.assertFalse(AH.messages_on(tempfile.mkdtemp(prefix="nohome-")))


def r_home_absent(tc):
    d = tempfile.mkdtemp(prefix="i1-")
    tc.addCleanup(shutil.rmtree, d, True)
    for home in (os.path.join(d, "nothing"), d):                                  # missing folder; folder without _harness
        tc.assertEqual(run_main(tc, home, post("Artifact", ADD, OK_FRAGMENT)), (0, ""))
    tc.assertEqual(os.listdir(d), [])


def r_home_read_only(tc):
    home = mkhome(tc)
    os.chmod(os.path.join(home, "_harness"), stat.S_IRUSR | stat.S_IXUSR)
    tc.addCleanup(os.chmod, os.path.join(home, "_harness"), stat.S_IRWXU)
    tc.assertEqual(run_main(tc, home, post("Artifact", ADD, OK_FRAGMENT)), (0, ""))
    tc.assertEqual(os.listdir(os.path.join(home, "_harness")), [])


def r_log_locked(tc):
    home = mkhome(tc)
    p = os.path.join(home, "_harness", "attach_shapes.jsonl")
    with open(p, "w") as f:
        f.write("keep\n")
    with open(p) as held:
        fcntl.flock(held, fcntl.LOCK_EX)
        tc.assertEqual(run_main(tc, home, post("Artifact", ADD, OK_FRAGMENT)), (0, ""))
    tc.assertEqual(open(p).read(), "keep\n")


def r_log_cap_500(tc):
    home = mkhome(tc)
    p = os.path.join(home, "_harness", "attach_shapes.jsonl")
    with open(p, "w") as f:
        f.write("".join("old %d\n" % i for i in range(505)))
    run_main(tc, home, post("Artifact", ADD, OK_FRAGMENT))
    lines = open(p).read().splitlines()
    tc.assertEqual(len(lines), 500)
    tc.assertEqual(lines[0], "old 6")                                              # the oldest were dropped
    tc.assertEqual(json.loads(lines[-1])["verdict"], "success")


def r_wiring(tc):
    d = json.load(open(os.path.join(ROOT, "hooks", "hooks.json")))["hooks"]
    tc.assertNotIn("PostToolUseFailure", d)                                       # F1: no event the host might not know
    hits = [(g, h) for g in d["PostToolUse"] for h in g["hooks"] if "attach_hook.py" in h["command"]]
    tc.assertEqual(len(hits), 1)
    g, h = hits[0]
    tc.assertEqual(h["command"], 'python3 "${CLAUDE_PLUGIN_ROOT}/scripts/attach_hook.py"')
    tc.assertEqual(h["timeout"], 5)
    for tool in ("mcp__plugin_hub_x__publish_files", "Artifact"):
        tc.assertTrue(re.fullmatch(g["matcher"], tool), tool)
    tc.assertEqual(sum("attach_hook.py" in x["command"] for ev in d.values() for gg in ev for x in gg["hooks"]), 1)
    import harness
    pkg = harness.package_files(ROOT)
    tc.assertIn("scripts/attach_hook.py", pkg)
    tc.assertIn("scripts/attach_state.py", pkg)


ROWS = {"I1-01": r_marker_logged, "I1-02": r_other_publishes_write_nothing, "I1-03": r_comments_and_data_write_nothing, "I1-04": r_never_raises_prints_nothing,
        "I1-05a": r_messages_success, "I1-05b": r_messages_refused, "I1-05c": r_messages_unchanged, "I1-05d": r_messages_conflict, "I1-05e": r_messages_none,
        "I1-05f": r_messages_error, "I1-05g": r_messages_default_off, "I1-06": r_home_absent, "I1-07": r_home_read_only, "I1-08": r_log_locked, "I1-09": r_log_cap_500,
        "I1-10": r_wiring}
