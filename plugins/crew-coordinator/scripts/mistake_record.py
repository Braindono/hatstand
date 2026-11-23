"""mistake_record: the field check and the harness-filled pointer for records tagged `mistake` (0.27.1 items 3 and 2).

What it does: refuses a mistake record that lacks its fields, and appends the session path and transcript line that a hook saved,
so an agent can neither omit nor invent the pointer. Pure functions; no harness import.
Interface: is_mistake(tags) -> bool; problems(tags, body) -> [str]; pointer_lines(home, agent, now) -> [str]; save_pointer(home, agent, path, now).
Depends on: json, os, re, time. Called by: harness.py _record (one call site), scripts/mistake_pointer_hook.py.
Why: the guru's plan (plans/2026-11-22_mistake-capture-enforcement.md): the harness decides when a mistake record exists and where it points.
"""
import json
import os
import re
import secrets
import time
import unicodedata

TAG_CHOICES = ("visible", "hindsight")
FOUND_BY = ("self", "evaluator", "peer", "operator", "script")
KINDS = ("claim", "code")
RESERVED = ("session file", "transcript line", "session", "line", "pointer")   # written by the harness only (checked after normalising)
FIELD = re.compile(r"^([a-z ]{2,20}?)\s*:\s*(.*)$")
FOUND_RE = re.compile(r"^(self|evaluator|operator|script|peer(\s*\([^)]{1,40}\))?)\s*$")
AGENT_RE = re.compile(r"^[0-9a-f]{8,64}$")
MAX_AGE_S = 60
DIR = os.path.join("_harness", "mistake-pointers")


def _tags(tags):
    if isinstance(tags, str):
        tags = re.split(r"[,\s]+", tags)
    return [str(t).strip().lower() for t in (tags or []) if str(t).strip()]


def is_mistake(tags):
    return "mistake" in _tags(tags)


# look-alike letters (Cyrillic, Greek) folded to ASCII, so "Ѕession file" cannot pass as another key
CONFUSABLES = str.maketrans({"а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "х": "x", "у": "y", "і": "i", "ѕ": "s", "ј": "j", "һ": "h", "ԁ": "d", "ӏ": "l",
                             "ո": "n", "ս": "u", "ν": "v", "ο": "o", "ρ": "p", "τ": "t", "ι": "i", "κ": "k", "ɡ": "g", "ⅼ": "l"})


QUOTES = {ord(c): None for c in '"\'`\u201c\u201d\u2018\u2019\u00ab\u00bb'}


def norm(line):
    """One body line as the checks see it: NFKC, no format or control characters (zero-width, BOM, bidi), spaces collapsed,
    list bullets, asterisks, hashes and quote marks stripped from the front, lower case."""
    t = unicodedata.normalize("NFKC", str(line))
    t = "".join(" " if c in "\t\r\x0b\x0c" else c for c in t if unicodedata.category(c) not in ("Cf", "Cc") or c in "\t\r\x0b\x0c")
    t = re.sub(r"\s+", " ", t).strip().lower()
    t = t.translate(CONFUSABLES)
    return re.sub(r"^[\s*_#>\-+\u2022\"'`\u201c\u2018]+", "", t).replace("*", "").translate(QUOTES).strip()


def _fields(body):
    out = {}
    for ln in (body or "").splitlines():
        m = FIELD.match(norm(ln))
        if m:
            out.setdefault(m.group(1).strip(), []).append(m.group(2).strip())
    return out


def problems(tags, body, candidate=False):
    """-> list of plain-language problems; empty when the record may be filed. A candidate (filed by the harness itself from the
    correction hook) carries its own pointer lines; every other record may not."""
    t, f, p = _tags(tags), _fields(body), []
    n = [c for c in TAG_CHOICES if c in t]
    if len(n) != 1:
        p.append("tag exactly one of visible or hindsight (visible: the rule or fact was in front of the agent)")
    what = f.get("what") or f.get("act") or []
    if not what or len(what[0]) < 8:
        p.append("a line 'What: <the act, one sentence, quoting it>' is missing")
    elif len(what) > 1 or len(what[0]) > 400:
        p.append("'What:' (or 'Act:') is one line of at most 400 characters")
    fb = f.get("found by") or []
    if not fb or not FOUND_RE.match(fb[0]) or not fb[0].isascii():
        p.append("'Found by:' must be one of " + ", ".join(FOUND_BY) + " (peer may add (role))")
    if not (f.get("model") or [""])[0]:
        p.append("'Model:' (the model the agent ran on) is missing")
    k = (f.get("kind") or [""])[0]
    if k not in KINDS:
        p.append("'Kind:' must be claim or code")
    if not candidate and any(r in f for r in RESERVED):
        p.append("the pointer lines (Session file, Transcript line, Session, Line) are written by the harness; remove yours")
    return p


def _safe_dir(home):
    d = os.path.join(home, DIR)
    if os.path.islink(d):
        raise OSError("pointer folder is a symlink")
    os.makedirs(d, exist_ok=True)
    return d


def save_pointer(home, agent, path, now=None):
    """Called by the PreToolUse hook: remember the transcript file and its current last line under the agent's 8-hex id.
    The agent value is the hook's tool_input, typed by the agent: only 8 or more lowercase hex characters are accepted."""
    if not isinstance(agent, str) or not AGENT_RE.match(agent):
        return False
    try:
        with open(path, "rb") as fh:
            line = sum(1 for _ in fh)
        d = _safe_dir(home)
        tmp = os.path.join(d, f".{agent[:8]}.{os.getpid()}.{secrets.token_hex(4)}.tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump({"path": path, "line": line, "ts": now if now is not None else time.time()}, fh)
        os.replace(tmp, os.path.join(d, f"{agent[:8]}.json"))
        return True
    except OSError:
        return False


def find_line(path, text, tail=4 << 20):
    """1-based line of the last transcript line containing the first 40 characters of `text`, else None (reads the last 4 MB)."""
    needle = " ".join(str(text or "").split())[:40]
    if len(needle) < 12:
        return None
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as fh:
            total = sum(chunk.count(b"\n") for chunk in iter(lambda: fh.read(1 << 20), b""))
            fh.seek(max(0, size - tail))
            lines = fh.read().decode("utf-8", "ignore").split("\n")
    except OSError:
        return None
    if lines and lines[-1] == "":
        lines.pop()
    first = total - len(lines) + 1
    for i in range(len(lines) - 1, -1, -1):
        if "harness_record" in lines[i]:
            continue                                  # the record call itself repeats the act text; the act is earlier
        if needle in " ".join(lines[i].replace("\\n", " ").split()):
            return first + i
    return None


def pointer_lines(home, agent, now=None, act=None):
    """The two harness-filled lines. They are the recorder's own transcript: the line is where the act text is found there, else the
    line of the record call (said so). If the hook did not run they say so; the record is still filed (a missed report is worse)."""
    now = now if now is not None else time.time()
    try:
        with open(os.path.join(home, DIR, f"{str(agent)[:8]}.json"), encoding="utf-8") as fh:
            d = json.load(fh)
        if now - float(d["ts"]) <= MAX_AGE_S and isinstance(d.get("path"), str):
            hit = find_line(d["path"], act)
            note = "act text found there" if hit else "the line of this record call; the act text was not found in this transcript"
            return [f"Session file: {d['path']}", f"Transcript line: {hit or int(d['line'])} ({note})"]
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return ["Session file: unavailable (the pointer hook did not run for this call)", "Transcript line: unavailable"]
