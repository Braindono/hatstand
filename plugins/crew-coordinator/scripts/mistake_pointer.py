"""mistake_pointer: item 2 of the 0.27.1 hotfix. The harness, not the agent, fills where a mistake happened. Depends on: stdlib.
Interface: find_transcript(session_id, projects_dir=None) -> path|None; line_count(path) -> int; stamp(body, session_id, model, projects_dir=None)
-> body with every Session:/Line:/Model: line the writer supplied removed and the harness's own lines appended
('Session: <transcript path>', 'Line: <current line number>', 'Model: <registered model>'). With no transcript found the lines say 'unknown'
(the record is still filed; the pointer is never taken from the writer). The session id comes from the hook-bound agent record, never from arguments."""
import glob, os, re

DROP = re.compile(r"^\s*(Session|Line|Model)\s*:", re.I)
SID = re.compile(r"^[0-9a-fA-F-]{8,64}$")


def projects_root():
    return os.path.expanduser("~/.claude/projects")


def find_transcript(session_id, projects_dir=None):
    if not isinstance(session_id, str) or not SID.match(session_id):
        return None
    hits = glob.glob(os.path.join(projects_dir or projects_root(), "*", session_id + ".jsonl"))
    hits = [h for h in hits if os.path.isfile(h) and not os.path.islink(h)]
    return max(hits, key=os.path.getmtime) if hits else None


def line_count(path):
    n = 0
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            n += chunk.count(b"\n")
    return n


def stamp(body, session_id, model, projects_dir=None):
    kept = [ln for ln in str(body or "").splitlines() if not DROP.match(ln)]
    path = find_transcript(session_id, projects_dir)
    try:
        line = str(line_count(path)) if path else "unknown"
    except OSError:
        line = "unknown"
    kept += ["Session: %s" % (path or "unknown"), "Line: %s" % line, "Model: %s" % (str(model or "unknown").splitlines()[0][:80])]
    return "\n".join(kept)
