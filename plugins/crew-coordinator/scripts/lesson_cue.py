#!/usr/bin/env python3
"""0.19.0 (R-113): lesson cue at the moment of action. Standalone hook script: stdlib only, never imports harness.py.

Ships OFF. Runs only when config `lesson_cue` is "on" (<home>/_harness/config.json) or HARNESS_LESSON_CUE=on (the
replay pilot's arm 3). Otherwise it exits at once and prints nothing.

PreToolUse: an entry fires when its `tool` regex matches the tool name AND (if given) its `input` regex matches
json.dumps(tool_input)[:4000]. UserPromptSubmit (the prompt-time variant for text-only situations, sub-arm 3b,
D-c8590): an entry with "on": "prompt" fires when its `input` regex matches the prompt text.
Each lesson fires at most once per session, and at most `max_per_session` cues per session (default 3).
A note adds non-blocking additionalContext "Lesson <id>: <cue>"; mode "deny" (per entry, default note) blocks the
tool call with the cue as the reason (PreToolUse only).

Files (interface agreed with the curator, m-4b5bcb59d88e and m-fb883a335780; <home> = HARNESS_HOME, else
~/Claude/Exchange, else ~/Claude/Projects/Exchange):
  trigger file  <home>/_harness/data/lesson_triggers.json
                {"v": 1, "max_per_session": 3, "entries": [{"id": "N-xxxxx", "tool": "^(Bash)$", "input": "(?i)ctx",
                 "cue": "<=40 tokens", "mode": "note|deny", "on": "tool|prompt"}]}   at most 30 entries
  session state <home>/_harness/cue_state/<session_id>.json  {"shown": [ids]}
  spool         <home>/_harness/cue_spool.jsonl, one line per firing:
                {"ts", "session_id", "host_session_id", "tool", "lesson", "mode", "matched": "tool|input|prompt",
                 "input_sha"}  (input_sha: sha256 of the matched text, first 12)
  curated lessons <home>/_harness/data/lesson_cues.json  {"v": 1, "lessons": {"N-xxxxx": {"when": "...", "rule": "..."}}}
                written by the harness for every lesson the operator approved whose content still matches (M6, critic N-9d725).
0.20.0 M2 (critic N-094cd B1 and addendum 2): lesson_cues.json is NOT trusted. An entry is used only if the ledger (<home>/_harness/events.jsonl,
read-only) holds a lesson.curated event whose cue_hash equals the hash recomputed from the entry's id, When, Rule and object keys AND that
event names a lesson_curate approval that was requested with the same When, Rule and keys and granted earlier in the ledger. A planted or
edited entry, a lesson curated before 0.20.0, or an unreadable ledger gives no cue and never a deny. Residual limit: a forged, correctly
chained ledger line; `harness.py verify` flags a broken chain.
0.20.0 (A-2b70b item 5): a curated lesson may carry approved cue object keys {"paths": [globs], "tools": [names], "mode": "note|deny"} in
that file ("keys" beside when/rule; the operator approved them with the lesson and the curation hash binds them). They are the ONLY source
of deny mode and of path triggers: the tool regex and the input regex are derived from the keys (scripts/ontology.py, which re-checks the
breadth rules on load). Entries of lesson_triggers.json still work for curated lessons but are always note mode. A concept link never
reaches this file, so a link added later cannot change where a rule fires.
A trigger fires only if its `id` is in that file; the cue text is that lesson's Rule (with its When), never free text from the trigger
file, and it is injected inside the lesson fence. An uncurated or unknown id gets no cue.
The harness ingests the spool as lesson.cued events on sync; this script never takes the ledger lock.
Never fails the tool call: any error exits 0 with no output."""
import hashlib, json, os, re, sys, time

MAX_ENTRIES, CUE_TOKENS, INPUT_CHARS, DEFAULT_MAX = 30, 40, 4000, 3


def home():
    e = (os.environ.get("HARNESS_HOME") or "").strip()
    if e:
        return os.path.abspath(os.path.expanduser(e))
    for c in ("~/Claude/Exchange", "~/Claude/Projects/Exchange"):
        p = os.path.expanduser(c)
        if os.path.isdir(p):
            return p
    return None


def enabled(h):
    if (os.environ.get("HARNESS_LESSON_CUE") or "").strip().lower() == "on":
        return True
    try:
        with open(os.path.join(h, "_harness", "config.json"), encoding="utf-8") as f:
            return str(json.load(f).get("lesson_cue", "off")).lower() == "on"
    except (OSError, ValueError, AttributeError):
        return False


_LEDGER = {}      # per process: <home> -> (stat key of the ledger and the cue file, verified entries)
_MARKS = (b'"lesson.curated"', b'"approval.requested"', b'"approval.granted"')
_STOPS = (b'"corpus.archived"', b'"corpus.retagged"', b'"corpus.recorded"')


def _stop(ln, out):
    """Drop from `out` the lessons an archive, retag or superseding record in this ledger line retires."""
    try:
        ev = json.loads(ln)
        t, d = ev.get("type"), ev.get("data")
        if not isinstance(d, dict):
            return
        if t == "corpus.archived":
            gone = d.get("ids") or []
        elif t == "corpus.retagged":
            gone = [d.get("id")]
        elif t == "corpus.recorded":
            gone = re.split(r"[,\s]+", d["supersedes"]) if isinstance(d.get("supersedes"), str) else []
        else:
            return
        for i in gone:
            if isinstance(i, str):
                out.pop(i, None)
    except (ValueError, AttributeError, TypeError):
        pass


def ledger_cue_hashes(h, ON):
    """-> {lesson id: cue_hash} from the ledger, read-only: for each lesson the LATEST lesson.curated event that is vouched for by an operator
    grant. An event is vouched for when it names an approval (`approval`) such that, earlier in the ledger, (1) an `approval.requested` for
    action lesson_curate carries an item for that lesson whose When, Rule and keys hash (ON.cue_hash) to the event's `cue_hash`, and (2) an
    `approval.granted` with state granted for that approval id exists before the curated event. Unvouched curated events are ignored; an
    unreadable ledger gives None. 0.20.0 M3 (critic N-99a7f probe 4): a lesson is dropped when a corpus.archived (id in ids), a
    corpus.retagged (id) or a superseding corpus.recorded (supersedes names it) comes AFTER its latest vouched curated event, so a re-planted
    pre-archive cue file does not re-arm it. A later vouched re-curation re-arms it; an unarchive alone does not."""
    p = os.path.join(h, "_harness", "events.jsonl")
    requested, granted, out = {}, set(), {}
    try:
        with open(p, "rb") as f:
            for ln in f:
                if not any(m in ln for m in _MARKS):
                    if out and any(m in ln for m in _STOPS) and any(i.encode() in ln for i in out):
                        _stop(ln, out)
                    continue
                try:
                    ev = json.loads(ln)
                except ValueError:
                    continue
                d = ev.get("data") if isinstance(ev, dict) else None
                if not isinstance(d, dict):
                    continue
                t = ev.get("type")
                if t == "approval.requested" and d.get("action") == "lesson_curate" and isinstance(d.get("id"), str):
                    items = {}
                    for it in (d.get("args") or {}).get("lessons") or []:
                        try:
                            if isinstance(it, dict) and isinstance(it.get("id"), str):
                                keys = ON.validate_keys(it["keys"]) if it.get("keys") else None
                                items[it["id"]] = ON.cue_hash(it["id"], it.get("when"), it["rule"], keys)
                        except Exception:
                            continue
                    requested[d["id"]] = items
                elif t == "approval.granted" and d.get("state") == "granted" and isinstance(d.get("id"), str):
                    granted.add(d["id"])
                elif t == "lesson.curated" and isinstance(d.get("id"), str) and isinstance(d.get("cue_hash"), str):
                    ap = d.get("approval")
                    if isinstance(ap, str) and ap in granted and requested.get(ap, {}).get(d["id"]) == d["cue_hash"]:
                        out[d["id"]] = d["cue_hash"]
    except OSError:
        return None
    return out


def _stat(path):
    try:
        st = os.stat(path)
        return (st.st_size, st.st_mtime_ns)
    except OSError:
        return None


def load_verified(h):
    """-> {lesson id: entry from lesson_cues.json} for entries the ledger vouches for (critic N-094cd B1 and addendum 2). An entry is used only if
    the hash recomputed from its id, When, Rule and object keys equals the cue_hash of the latest curated event vouched for by a granted
    lesson_curate approval (see ledger_cue_hashes). Anything else (a planted id, a changed text or key, a lesson curated before 0.20.0, an
    unreadable ledger or ontology.py) is dropped: no cue and never a deny. Cached in the process by the size and mtime of the ledger AND of
    the cue file, so editing the cue file alone re-verifies."""
    cue_path = os.path.join(h, "_harness", "data", "lesson_cues.json")
    key = (_stat(os.path.join(h, "_harness", "events.jsonl")), _stat(cue_path))
    if None in key:
        return {}
    if _LEDGER.get(h, (None,))[0] == key:
        return _LEDGER[h][1]
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import ontology as ON
        with open(cue_path, encoding="utf-8") as f:
            d = json.load(f)
        led = ledger_cue_hashes(h, ON)
    except Exception:
        return {}
    if not led or not isinstance(d, dict) or d.get("v") != 1 or not isinstance(d.get("lessons"), dict):
        return {}
    out = {}
    for lid, v in d["lessons"].items():
        try:
            if not isinstance(lid, str) or not isinstance(v, dict) or not isinstance(v.get("rule"), str) or not v["rule"].strip():
                continue
            keys = v.get("keys")
            if keys is not None:
                keys = ON.validate_keys(keys)        # a key outside the breadth rules never verifies
            if led.get(lid) and led[lid] == ON.cue_hash(lid, v.get("when"), v["rule"], keys):
                out[lid] = dict(v, keys=keys)
        except Exception:
            continue
    _LEDGER[h] = (key, out)
    return out


def load_curated(h):
    """-> {lesson id: cue text} for the verified, operator-approved lessons (Rule, with When); {} if none."""
    out = {}
    for lid, v in load_verified(h).items():
        txt = ("When %s: " % " ".join(str(v["when"]).split()) if v.get("when") else "") + " ".join(v["rule"].split())
        out[lid] = txt.replace("\u27e6", "").replace("\u27e7", "")[:CUE_TOKENS * 4]
    return out


def load_key_entries(h, curated):
    """0.20.0: trigger entries derived from the approved object keys of verified curated lessons. A key that fails the breadth rules is skipped."""
    try:
        import ontology as ON
    except Exception:
        return []
    out = []
    for lid, v in sorted(load_verified(h).items()):
        if lid not in curated or not isinstance(v.get("keys"), dict):
            continue
        try:
            k = ON.validate_keys(v["keys"])
            tool_src, inp_src = ON.key_regexes(k)
            out.append({"id": lid, "tool": re.compile(tool_src), "input": re.compile(inp_src) if inp_src else None, "cue": curated[lid],
                        "on": "tool", "mode": k["mode"]})
        except (ValueError, re.error, TypeError):
            continue
    return out


def load_triggers(h):
    """-> (entries, max_per_session). Bad entries (no id, a bad regex, an id that is not a curated lesson) are skipped."""
    curated = load_curated(h)
    keyed = load_key_entries(h, curated)
    try:
        with open(os.path.join(h, "_harness", "data", "lesson_triggers.json"), encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        return keyed, DEFAULT_MAX
    if not isinstance(d, dict) or d.get("v") != 1:
        return keyed, DEFAULT_MAX
    mx = d.get("max_per_session", DEFAULT_MAX)
    mx = mx if isinstance(mx, int) and 0 < mx <= 10 else DEFAULT_MAX
    out = list(keyed)
    for e in (d.get("entries") or [])[:MAX_ENTRIES]:
        if not isinstance(e, dict) or not isinstance(e.get("id"), str) or e["id"] not in curated:
            continue
        cue = curated[e["id"]]
        try:
            tool = re.compile(e["tool"]) if e.get("tool") else None
            inp = re.compile(e["input"]) if e.get("input") else None
        except (re.error, TypeError):
            continue
        on = "prompt" if e.get("on") == "prompt" else "tool"
        if on == "tool" and tool is None or on == "prompt" and inp is None:
            continue
        out.append({"id": e["id"], "tool": tool, "input": inp, "cue": cue, "on": on,
                    "mode": "note"})          # 0.20.0: deny mode comes only from approved keys
    return out, mx


def _state_path(h, sid):
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", sid or "nosession")[:80]
    return os.path.join(h, "_harness", "cue_state", safe + ".json")


def _read_state(p):
    try:
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) and isinstance(d.get("shown"), list) else {"shown": []}
    except (OSError, ValueError):
        return {"shown": []}


def _write(p, text, mode="w"):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, mode, encoding="utf-8") as f:
        f.write(text)


def decide(inp, h, now=None):
    """The hook's decision for one input. -> (output dict or None, spool line or None)."""
    ev = inp.get("hook_event_name") or "PreToolUse"
    sid = str(inp.get("session_id") or "")
    entries, mx = load_triggers(h)
    if not entries:
        return None, None
    sp = _state_path(h, sid)
    st = _read_state(sp)
    if len(st["shown"]) >= mx:
        return None, None
    if ev == "UserPromptSubmit":
        text = str(inp.get("prompt") or "")[:INPUT_CHARS]
        cands = [(e, "prompt", text) for e in entries if e["on"] == "prompt" and e["input"].search(text)]
        tool = ""
    else:
        tool = str(inp.get("tool_name") or "")
        text = json.dumps(inp.get("tool_input") or {}, sort_keys=True)[:INPUT_CHARS]
        cands = []
        for e in entries:
            if e["on"] != "tool" or not e["tool"].search(tool):
                continue
            if e["input"] is not None:
                if e["input"].search(text):
                    cands.append((e, "input", text))
            else:
                cands.append((e, "tool", text))
    for e, matched, txt in cands:
        if e["id"] in st["shown"]:
            continue
        st["shown"].append(e["id"])
        _write(sp, json.dumps(st))
        line = {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now or time.time())), "session_id": sid,
                "host_session_id": os.environ.get("CLAUDE_CODE_HOST_SESSION_ID") or "", "tool": tool,
                "lesson": e["id"], "mode": e["mode"] if ev == "PreToolUse" else "note", "matched": matched,
                "input_sha": hashlib.sha256(txt.encode("utf-8", "replace")).hexdigest()[:12]}
        msg = "\u27e6lesson approved by the operator: apply unless the operator says otherwise\u27e7 Lesson %s: %s \u27e6/lesson\u27e7" % (e["id"], e["cue"])
        if ev == "PreToolUse" and e["mode"] == "deny":
            out = {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                          "permissionDecisionReason": msg}}
        else:
            out = {"hookSpecificOutput": {"hookEventName": ev, "additionalContext": msg}}
        return out, line
    return None, None


def main(stdin=None):
    try:
        h = home()
        if not h or not enabled(h):
            return 0
        inp = json.loads((stdin if stdin is not None else sys.stdin).read() or "{}")
        if not isinstance(inp, dict):
            return 0
        out, line = decide(inp, h)
        if line:
            _write(os.path.join(h, "_harness", "cue_spool.jsonl"), json.dumps(line) + "\n", "a")
        if out:
            sys.stdout.write(json.dumps(out))
    except Exception:
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
