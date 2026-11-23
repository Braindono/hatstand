#!/usr/bin/env python3
"""correction_hook: item 1 of the 0.27.1 hotfix. UserPromptSubmit hook script: when his message corrects the agent, files a CANDIDATE mistake record
(spool line) pointing at the agent's previous turn, his words quoted, found_by operator, and tells the agent to add one description line.
Standalone, stdlib only, never takes the ledger lock, never fails the prompt: any error exits 0 with no output. Depends on: correction_cues.
Input (stdin JSON from the host): {session_id, transcript_path, prompt}. Spool: <home>/_harness/mistake_spool.jsonl, one JSON line per candidate:
{ts, session_id, transcript_path, line (1-based line of the agent's previous assistant turn, or null), kind (code if that turn used a tool that edits or runs, else claim),
act (the first 300 characters of that turn's text, or its tool name), quote, cue, found_by: operator}. The harness turns spool lines into records (mistake_ingest).
Output: {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": "..."}} on a hit, nothing otherwise.
One candidate per session and prompt text (hash) so a repeated hook run never files twice."""
import hashlib, json, os, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import correction_cues

EDITS = {"Bash", "Edit", "Write", "MultiEdit", "NotebookEdit"}
TAIL = 4 << 20


def home():
    e = (os.environ.get("HARNESS_HOME") or "").strip()
    if e:
        return e
    cands = (os.path.join("~", "Claude", "Projects", "Exchange"), os.path.join("~", "Claude", "Exchange"))
    for c in cands:
        if os.path.isdir(os.path.expanduser(c)):
            return os.path.expanduser(c)
    return os.path.expanduser(cands[0])


def previous_turn(path):
    """-> (1-based line number, kind, act) of the last assistant line in the transcript, or None. Reads only the last 4 MB."""
    size = os.path.getsize(path)
    with open(path, "rb") as f:
        f.seek(max(0, size - TAIL))
        data = f.read()
    total = 0
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            total += chunk.count(b"\n")
    lines = data.split(b"\n")
    if lines and lines[-1] == b"":
        lines.pop()
    if size > TAIL:
        lines = lines[1:]                                     # the first piece may be cut in half
    first_no = total - len(lines) + 1
    for i in range(len(lines) - 1, -1, -1):
        try:
            r = json.loads(lines[i])
        except ValueError:
            continue
        if not isinstance(r, dict) or r.get("type") != "assistant" or r.get("isSidechain"):
            continue
        blocks = ((r.get("message") or {}).get("content")) or []
        texts = [b.get("text", "") for b in blocks if isinstance(b, dict) and b.get("type") == "text"]
        tools = [b.get("name", "") for b in blocks if isinstance(b, dict) and b.get("type") == "tool_use"]
        kind = "code" if any(t in EDITS or t.startswith("mcp__") for t in tools) else "claim"
        act = " ".join(" ".join(texts).split())[:300] or ("tool call: " + ", ".join(tools)[:200])
        return first_no + i, kind, act, ((r.get("message") or {}).get("model") or None)
    return None


def run(payload, out_home=None):
    prompt = payload.get("prompt")
    hit = correction_cues.match(prompt)
    sid, path = payload.get("session_id"), payload.get("transcript_path")
    if not hit or not isinstance(sid, str) or not isinstance(path, str) or not os.path.isfile(path):
        return None
    prev = previous_turn(path)
    if not prev:
        return None
    ln, kind, act = prev[:3]
    key = hashlib.sha256((sid + "|" + str(prompt)).encode("utf-8", "replace")).hexdigest()[:16]
    base = os.path.join(out_home or home(), "_harness")
    seen = os.path.join(base, "mistake_seen")
    os.makedirs(seen, exist_ok=True)
    mark = os.path.join(seen, key)
    if os.path.exists(mark):
        return None
    line = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "session_id": sid, "transcript_path": path, "line": ln, "kind": kind, "act": act,
            "quote": hit["quote"], "cue": hit["cue"], "found_by": "operator", "key": key, "model": prev[3] if len(prev) > 3 else None}
    fd = os.open(os.path.join(base, "mistake_spool.jsonl"), os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600)
    try:
        os.write(fd, (json.dumps(line) + "\n").encode("utf-8"))
    finally:
        os.close(fd)
    os.close(os.open(mark, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600))
    return ("A correction candidate was filed for your previous turn (%s line %d), his words quoted: \"%s\". The harness made the record; you add one line: "
            "what you did, quoting your own words or command, then whether the rule or fact was in front of you (visible) or not (hindsight). "
            "Use harness_record kind=note tags=[mistake, visible|hindsight] with 'Act:', 'Found by: operator', 'Kind: %s'. Do not argue the candidate away." %
            (os.path.basename(path), ln, hit["quote"][:200], kind))


def main(stdin=None):
    try:
        payload = json.loads((stdin or sys.stdin).read() or "{}")
        ctx = run(payload) if isinstance(payload, dict) else None
        if ctx:
            print(json.dumps({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": ctx}}))
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
