"""subagent_cap: 0.27.3 item 3 (F3). The launcher of a subagent writes its written cap; the sync scan records an overrun of 1.5x as a candidate mistake.
Depends on: stdlib, mistake_pointer (finds the session transcript), spend_meter (the one token count). Called from mistake_ingest.scan_caps at sync.
Cap file: <home>/_harness/subagent_caps/<session_id>.<subagent_id>.json = {session_id, subagent, label, cap_tokens, cap_calls, t}; either cap may be 0 (not set).
Launcher side: write_cap(home, session_id, subagent, label, cap_tokens, cap_calls); CLI: python3 subagent_cap.py <home> <session_id> <subagent> <label> <cap_tokens> <cap_calls>.
Subagent transcript: <projects>/<project>/<session_id>/subagents/<subagent>.jsonl. Counted tokens = spend_meter's total (input + output + cache both); calls = tool_use blocks.
Ratio = the larger of tokens/cap_tokens and calls/cap_calls. A cap file untouched for 14 days is ignored."""
import json, os, re, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mistake_pointer, spend_meter

RATIO = 1.5
STALE_S = 14 * 86400
ID = re.compile(r"^[A-Za-z0-9_-]{4,64}$")


def caps_dir(home):
    return os.path.join(home, "_harness", "subagent_caps")


def write_cap(home, session_id, subagent, label, cap_tokens=0, cap_calls=0, now=None):
    if not (ID.match(str(session_id)) and ID.match(str(subagent))) or int(cap_tokens) < 0 or int(cap_calls) < 0 or not (int(cap_tokens) or int(cap_calls)):
        raise ValueError("session id, subagent id and at least one positive cap are required")
    d = caps_dir(home)
    os.makedirs(d, mode=0o700, exist_ok=True)
    p = os.path.join(d, "%s.%s.json" % (session_id, subagent))
    rec = {"session_id": session_id, "subagent": subagent, "label": str(label)[:60], "cap_tokens": int(cap_tokens), "cap_calls": int(cap_calls),
           "t": time.time() if now is None else now}
    fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(rec, f)
    return p


def read_caps(home, now=None):
    now = time.time() if now is None else now
    d, out = caps_dir(home), []
    if not os.path.isdir(d) or os.path.islink(d):
        return out
    for fn in sorted(os.listdir(d)):
        p = os.path.join(d, fn)
        try:
            if not fn.endswith(".json") or os.path.islink(p) or now - os.path.getmtime(p) > STALE_S:
                continue
            with open(p, encoding="utf-8") as f:
                r = json.load(f)
            if ID.match(str(r["session_id"])) and ID.match(str(r["subagent"])):
                out.append({"file": fn, "session_id": r["session_id"], "subagent": r["subagent"], "label": str(r.get("label") or "")[:60],
                            "cap_tokens": max(0, int(r.get("cap_tokens") or 0)), "cap_calls": max(0, int(r.get("cap_calls") or 0))})
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return out


def usage_of(path):
    """-> (counted tokens, tool calls) of one subagent transcript."""
    c, _ = spend_meter.sum_usage(path)
    calls = 0
    with open(path, "rb") as f:
        for raw in f:
            if b'"tool_use"' in raw:
                try:
                    m = (json.loads(raw.decode("utf-8", "ignore")).get("message") or {}).get("content")
                except ValueError:
                    continue
                calls += sum(1 for b in (m if isinstance(m, list) else []) if isinstance(b, dict) and b.get("type") == "tool_use")
    return spend_meter.total(c), calls


def overruns(home, projects_dir=None, now=None):
    """-> [{cap, tokens, calls, ratio, path}] for every cap whose subagent reached RATIO x a cap that is set."""
    hits = []
    for cap in read_caps(home, now):
        sess = mistake_pointer.find_transcript(cap["session_id"], projects_dir)
        if not sess:
            continue
        sub = os.path.join(os.path.dirname(sess), cap["session_id"], "subagents", cap["subagent"] + ".jsonl")
        if not os.path.isfile(sub) or os.path.islink(sub):
            continue
        tokens, calls = usage_of(sub)
        ratio = max(tokens / cap["cap_tokens"] if cap["cap_tokens"] else 0, calls / cap["cap_calls"] if cap["cap_calls"] else 0)
        if ratio >= RATIO:
            hits.append({"cap": cap, "tokens": tokens, "calls": calls, "ratio": ratio, "path": sub})
    return hits


if __name__ == "__main__":
    a = sys.argv[1:]
    print(write_cap(a[0], a[1], a[2], a[3], int(a[4]), int(a[5])))
