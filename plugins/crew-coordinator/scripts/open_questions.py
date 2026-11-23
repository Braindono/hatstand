"""open_questions: one open question per topic across chats (0.27.1, guru row H: the same layout question was asked in two chats).

What it does: remembers the key terms of every question put to him (who, when) and says when another chat asked a question on the same topic recently.
Interface: seen(home, agent, role, terms, now) -> None | "ASK GATE ..." message; the caller (ask_gate.py pre mode) adds it to its verdict, so the
gate's observe or enforce mode applies. Depends on: json, os, time. Data: <home>/_harness/open_questions.jsonl (terms only, never the question text).
Terms are the question's content words (topic_terms: words of 3 or more letters that are not common words; a version such as 0.27.1 is one term).
A topic matches when at least 3 terms and 60% of the shorter list are shared. A question counts as open for 4 hours (no answer signal exists; the short window is the close).
"""
import fcntl
import json
import math
import os
import re
import time

WINDOW_S = 4 * 3600
KEEP = 200


def _path(home):
    return os.path.join(home, "_harness", "open_questions.jsonl")


STOP = frozenset("a an the and or but if then than that this these those what which who whom whose when where why how should would could can may might must will shall do does did "
                 "is are was were be been being to of in on at by for with from as it its we you your our they them their there here not no yes use used using "
                 "please also about into over under after before more most some any all each one two".split())
TOKEN = re.compile(r"\d+(?:\.\d+)+|[a-z][a-z0-9_-]{2,}")


def topic_terms(question):
    """-> content words of a question, lower case, deduplicated, in order."""
    out = []
    for t in TOKEN.findall(str(question or "").lower()):
        if t not in STOP and t not in out:
            out.append(t)
    return out


def _load(path, now):
    try:
        if os.path.islink(path):
            return []
        rows = [json.loads(l) for l in open(path, encoding="utf-8").read().splitlines() if l.strip()]
    except (OSError, ValueError):
        return []
    keep = []
    for r in rows:
        try:
            if isinstance(r, dict) and now - float(r.get("t") or 0) < WINDOW_S:
                keep.append(r)
        except (TypeError, ValueError):
            continue                                        # a row with a bad time is ignored, never fatal
    return keep[-KEEP:]


def seen(home, agent, role, terms, now=None):
    now = now if now is not None else time.time()
    terms = sorted({str(t).lower() for t in terms or []})
    if len(terms) < 3 or not home or not agent:
        return None
    path = _path(home)
    try:
        lock = os.open(path + ".lock", os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        fcntl.flock(lock, fcntl.LOCK_EX)
    except OSError:
        lock = None
    try:
        return _seen_locked(path, agent, role, terms, now)
    finally:
        if lock is not None:
            os.close(lock)


def _seen_locked(path, agent, role, terms, now):
    rows = _load(path, now)
    dup = None
    for r in reversed(rows):
        other = r.get("terms") if isinstance(r.get("terms"), list) else []
        need = max(3, math.ceil(0.6 * min(len(terms), len(other) or 99)))
        if r.get("agent") != agent and len(set(terms) & set(other)) >= need:
            dup = r
            break
    rows.append({"t": now, "agent": agent, "role": role or "?", "terms": terms})
    try:
        tmp = path + ".%d.tmp" % os.getpid()
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write("".join(json.dumps(r) + "\n" for r in rows[-KEEP:]))
        os.replace(tmp, path)
    except OSError:
        pass
    if dup:
        return ("ASK GATE (one open question per topic): the %s chat asked him about this %d minutes ago. Do not ask again; wait for his answer, "
                "or read it in the records and point to it." % (dup.get("role") or "other", int((now - float(dup["t"])) // 60)))
    return None
