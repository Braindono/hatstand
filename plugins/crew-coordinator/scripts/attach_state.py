"""attach_state: which operation makes the next Hub attach a REAL publish. Depends on: stdlib.
Interface: next_op(state_path) -> {"op": "add"|"remove", "marker": "attach-noop.txt", "publish": {...arguments to give publish_files...}}; record(state_path, op) stores the
operation that actually succeeded. CLI: python3 attach_state.py next   (prints the JSON). State: <home>/_harness/attach_state.json {"present": bool, "at": iso}.
The marker toggles every restore (add when absent, remove when present) so each attach changes the artifact; a publish that returns unchanged:true is a failed step (attach_hook).
The state changes only through the hook's reading of a successful publish, never through the agent's say-so."""
import datetime, json, os, sys, tempfile

MARKER = "attach-noop.txt"
STATE = os.path.join(os.environ.get("HARNESS_HOME") or os.path.join(os.path.expanduser("~"), "Claude", "Projects", "Exchange"), "_harness", "attach_state.json")   # 0.27.2: the harness home wins


def present(state_path=STATE):
    try:
        return json.load(open(state_path)).get("present") is True
    except (OSError, ValueError, AttributeError):
        return False


def next_op(state_path=STATE):
    if present(state_path):
        return {"op": "remove", "marker": MARKER, "publish": {"files": [], "remove": [MARKER]}}
    return {"op": "add", "marker": MARKER, "publish": {"files": [{"path": MARKER, "content": "attach %s\n" % datetime.datetime.now().isoformat(timespec="seconds")}], "remove": []}}


def record(state_path, op):
    if op not in ("add", "remove"):
        return
    os.makedirs(os.path.dirname(state_path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".w-", suffix=".tmp", dir=os.path.dirname(state_path))
    with os.fdopen(fd, "w") as f:
        json.dump({"present": op == "add", "at": datetime.datetime.now().isoformat(timespec="seconds")}, f)
    os.replace(tmp, state_path)


if __name__ == "__main__":
    if sys.argv[1:] == ["next"]:
        print(json.dumps(next_op()))
    else:
        print("usage: attach_state.py next")
        sys.exit(2)
