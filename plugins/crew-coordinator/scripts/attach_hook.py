#!/usr/bin/env python3
"""attach_hook: PostToolUse hook script (matcher: the Hub publish tool and `Artifact`). Depends on: attach_state. Standalone, stdlib only, never fails the tool call.
0.27.2 (I1) LOG-ONLY by default: a publish that touches the attach marker on the Hub writes ONE line to <home>/_harness/attach_shapes.jsonl (event name, tool name,
python type of the response, its key names, classify() verdict; never response text; at most 500 lines) and nothing else: no message to the agent, attach_state not
written, nothing printed. Absent, read-only or locked home: exit 0, silent. The messages below switch on with config attach_messages true (the 0.27.3 switch).
When the publish was the attach toggle (it adds or removes attach-noop.txt, in list or map form, on the Hub artifact):
  - result says unchanged:true  -> tells the agent the step FAILED, to run `python3 attach_state.py next`, publish exactly that, and never write "attached" until a result
    without unchanged:true; appends a line to <home>/_harness/attach_failures.jsonl (a mistake-candidate source for the harness);
  - a result with a version or url and no error -> records the operation in attach_state.json (the next restore toggles the other way);
  - anything else (error, empty, unclassifiable) -> records nothing and says the attach is NOT CONFIRMED.
Other publishes are ignored. Input (stdin JSON from the host): {tool_name, tool_input, tool_response}. Output: {"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": ...}} or nothing."""
import fcntl, json, os, re, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import attach_state as A

UNCHANGED_RE = re.compile(r'unchanged[\\"\']*\s*[:=]\s*[\\"\']*(true|1)\b', re.I)
ERROR_RE = re.compile(r'(^|\W)(error|forbidden|denied|failed|failure|refused|refusal)(\W|$)', re.I)
POSITIVE_RE = re.compile(r'[\\"\']*(version|url)[\\"\']*\s*[:=]\s*[\\"\']*[A-Za-z0-9]|^\s*Published\b.{0,600}?artifact/[A-Za-z0-9]+.{0,200}?version id\s+[0-9A-Za-z-]+', re.I | re.S)       # also the Artifact tool\'s real success text
HUB_ID = "Bh95vCZDid4tqAZog6EYP8"
MAX_TEXT, MAX_NODES = 2_000_000, 20000


def _walk(v, found, n=[0], depth=0):
    """Collect (has_error, unchanged_truthy, has_positive) over every dict in the response, however deep (bounded)."""
    n[0] += 1
    if n[0] > MAX_NODES or depth > 40:
        found["truncated"] = True
        return
    if isinstance(v, dict):
        if v.get("error") not in (None, "", False):
            found["error"] = True
        if v.get("unchanged") in (True, 1, "true", "True"):
            found["unchanged"] = True
        if v.get("version") not in (None, "", False) or v.get("url") not in (None, "", False):
            found["positive"] = True
        for x in v.values():
            _walk(x, found, n, depth + 1)
    elif isinstance(v, list):
        for x in v:
            _walk(x, found, n, depth + 1)
    elif isinstance(v, str) and len(v) < MAX_TEXT:
        t = v.strip()
        if t[:1] in "{[":
            try:
                _walk(json.loads(t), found, n, depth + 1)
                return
            except ValueError:
                pass
        if UNCHANGED_RE.search(t):
            found["unchanged"] = True
        if ERROR_RE.search(t[:300]):
            found["error"] = True
        if POSITIVE_RE.search(t):
            found["positive"] = True


def classify(resp):
    """'unchanged' | 'success' | 'unknown': success only on positive evidence (a version or url) and no error; anything unclassifiable is unknown."""
    if resp is None:
        return "unknown"
    found = {}
    _walk(resp, found, [0])
    if found.get("unchanged"):
        return "unchanged"
    if found.get("positive") and not found.get("error") and not found.get("truncated"):
        return "success"
    return "unknown"


def _strings(v, out, n=0):
    if n > 6:
        return
    if isinstance(v, str):
        out.append(v)
    elif isinstance(v, dict):
        for x in v.values():
            _strings(x, out, n + 1)
    elif isinstance(v, list):
        for x in v:
            _strings(x, out, n + 1)


def targets_hub(tool_input):
    """False only when the publish names another artifact (a url or id that does not contain the Hub's id); no url or id given counts as the Hub."""
    seen = []
    if isinstance(tool_input, dict):
        for k in ("url", "artifact", "artifact_url", "artifact_id", "id", "path"):
            if isinstance(tool_input.get(k), str):
                seen.append(tool_input[k])
    refs = [x for x in seen if "artifact/" in x or re.fullmatch(r"[A-Za-z0-9]{16,30}", x)]
    return not refs or any(HUB_ID in x for x in refs)


def marker_op(tool_input):
    """'add' or 'remove' when the publish touches the attach marker (list or map form), else None."""
    if not isinstance(tool_input, dict):
        return None
    files, rem = tool_input.get("files") or [], tool_input.get("remove") or []
    if isinstance(rem, list) and A.MARKER in [str(x.get("path") if isinstance(x, dict) else x) for x in rem]:
        return "remove"
    if isinstance(files, dict) and A.MARKER in files:
        return "remove" if files[A.MARKER] is None else "add"                       # the Artifact tool removes with a null value
    if isinstance(files, list) and any((f.get("path") if isinstance(f, dict) else f) == A.MARKER for f in files):
        return "add"
    return None


def _log(d, entry):
    os.makedirs(d, exist_ok=True)
    fd = os.open(os.path.join(d, "attach_failures.jsonl"), os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600)
    try:
        os.write(fd, (json.dumps(entry) + "\n").encode())
    finally:
        os.close(fd)


SHAPES_MAX = 500


def _home():
    h = os.environ.get("HARNESS_HOME") or os.path.join(os.path.expanduser("~"), "Claude", "Projects", "Exchange")
    return h if os.path.isdir(os.path.join(h, "_harness")) else None


def messages_on(home):
    """config attach_messages (default false): the 0.27.3 switch."""
    try:
        with open(os.path.join(home, "_harness", "config.json"), encoding="utf-8") as f:
            return json.load(f).get("attach_messages") is True
    except Exception:
        return False


def _keys(resp):
    if isinstance(resp, dict):
        return sorted(str(k) for k in resp)[:30]
    if isinstance(resp, list):
        return sorted({str(k) for x in resp[:50] if isinstance(x, dict) for k in x})[:30]
    return []


def log_shape(payload, home):
    """One line per marker publish: what the host really sends. No response text. Keeps the last SHAPES_MAX lines. Silent on any failure."""
    resp = payload.get("tool_response")
    row = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "event": str(payload.get("hook_event_name") or "unknown")[:40],
           "tool": str(payload.get("tool_name") or "")[:80], "type": type(resp).__name__, "keys": _keys(resp), "verdict": classify(resp)}
    path = os.path.join(home, "_harness", "attach_shapes.jsonl")
    try:
        fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600)
    except OSError:
        return
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        os.write(fd, (json.dumps(row) + "\n").encode())
        with open(path, encoding="utf-8") as f:
            lines = f.read().splitlines()
        if len(lines) > SHAPES_MAX:
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                f.write("\n".join(lines[-SHAPES_MAX:]) + "\n")
            os.replace(tmp, path)
    except OSError:
        pass
    finally:
        os.close(fd)


def run(payload, state_path=None, out_dir=None):
    ti = payload.get("tool_input")
    op = marker_op(ti)
    if not op or not targets_hub(ti):
        return None
    state_path = state_path or A.STATE
    verdict = classify(payload.get("tool_response"))
    nxt = os.path.abspath(os.path.join(os.path.dirname(__file__), "attach_state.py"))
    if verdict == "success":
        A.record(state_path, op)
        return None
    _log(out_dir or os.path.dirname(state_path), {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "op": op, "verdict": verdict, "session_id": payload.get("session_id")})
    if verdict == "unchanged":
        return ("Hub attach FAILED: the publish returned unchanged:true, so nothing was attached. Run `python3 %s next` for the operation that changes the artifact, "
                "publish exactly that, and do not write 'attached' in any note until a result carries a version or url without unchanged:true." % nxt)
    return ("Hub attach NOT CONFIRMED: the publish result has no version or url (or reports an error). Do not write 'attached'. Check the result, run `python3 %s next`, and publish again." % nxt)


def main(stdin=None):
    try:
        payload = json.loads((stdin or sys.stdin).read() or "{}")
        home = _home()
        if not isinstance(payload, dict) or not home:
            return 0                                                  # no harness home: nothing to log, nothing to say
        if not messages_on(home):
            if marker_op(payload.get("tool_input")) and targets_hub(payload.get("tool_input")):
                log_shape(payload, home)
            return 0
        ctx = run(payload)
        if ctx:
            print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": ctx}}))
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
