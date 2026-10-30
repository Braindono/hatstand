#!/usr/bin/env python3
"""cc 0.19.0 M2 (D-b751f a2/a3, D-c8590 c3; critic N-07440): standalone PreToolUse guard for a retired chat.

Reads only <home>/_harness/retired_sessions.json (about 20 ms, never imports harness.py). When the hook's session_id is
listed, every tool is denied (matcher "*") except a read-only allowlist: Read, Grep, Glob, harness_inbox / harness_recall /
harness_sync, harness_record of a capsule (D-36a07), and harness_restore carrying an `approval` id (the server verifies that
it is a granted, unused operator approval for exactly that agent and role; a bare confirmed=true is not enough).
Matching is by session_id. The desktop host id matches only an entry keyed explicitly `host:<id>` (written when no session id
was known), and a host match never denies harness_register or harness_restore (a new chat in the same window must be able to
register). Fail-open: any error lets the call through, and an unreadable marker is logged to the state dir."""
import json
import os
import re
import sys
import time

MARKER = os.path.join("_harness", "retired_sessions.json")
HOME_CANDIDATES = ("~/Claude/Exchange", "~/Claude/Projects/Exchange", "~/mnt/Exchange")
BUILTIN_READS = ("Read", "Grep", "Glob")
HARNESS_PREFIX = re.compile(r"^mcp__(?:plugin_)?crew-coordinator(?:_crew-coordinator)?__(harness_[a-z_]+)$")
HARNESS_READS = ("harness_inbox", "harness_recall", "harness_sync")


def find_home():
    env = os.environ.get("HARNESS_HOME")
    if env:
        return os.path.expanduser(env)
    for c in HOME_CANDIDATES:
        p = os.path.expanduser(c)
        if os.path.isdir(os.path.join(p, "_harness")):
            return p
    return None


def log(msg):
    try:
        d = os.environ.get("HARNESS_STATE_DIR") or os.path.expanduser("~/.claude/crew-coordinator/state")
        os.makedirs(d, mode=0o700, exist_ok=True)
        p = os.path.join(d, "retire-guard.log")
        old = ""
        if os.path.isfile(p):
            with open(p, encoding="utf-8") as f:
                old = f.read()
        with open(p, "w", encoding="utf-8") as f:
            f.write((old if len(old) < 20000 else "") + f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {msg[:200]}\n")
    except Exception:
        pass


def load(home):
    p = os.path.join(home, MARKER)
    if not os.path.exists(p):
        return {}
    try:
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError) as e:
        log(f"unreadable marker {p}: {type(e).__name__}: {e} (failing open)")
        return {}


def retired_entry(marker, sid, host_sid=None):
    """-> (entry, matched_by_host). Session id first; the host id only for an entry keyed `host:<id>`."""
    sess = marker.get("sessions") or {}
    if sid and sid in sess and not str(sid).startswith("host:"):
        return sess[sid], False
    if host_sid and f"host:{host_sid}" in sess:
        return sess[f"host:{host_sid}"], True
    return None, False


def allowed_bare(n, ti):
    """The allowlist for a harness tool by its bare name (the server side uses it too)."""
    ti = ti if isinstance(ti, dict) else {}
    if n in HARNESS_READS:
        return True
    if n == "harness_record":
        return str(ti.get("kind") or "") == "capsule"
    if n == "harness_restore":
        return str(ti.get("approval") or "").startswith("A-")
    return False


def allowed(tool, ti):
    t = str(tool or "")
    if t in BUILTIN_READS:
        return True
    m = HARNESS_PREFIX.match(t)
    return bool(m) and allowed_bare(m.group(1), ti)


def host_exempt(tool):
    m = HARNESS_PREFIX.match(str(tool or ""))
    return bool(m) and m.group(1) in ("harness_register", "harness_restore")


def reason(ent):
    return (f"RETIRED: superseded by {ent.get('successor_name') or 'a newer chat'} at {ent.get('at') or '?'}; record a capsule "
            "with harness_record kind=capsule if needed, then stop; do not write files. A retired chat revives only with an "
            "operator approval (harness_restore with approval=<id>).")


def main():
    try:
        inp = json.load(sys.stdin)
        if not isinstance(inp, dict):
            return 0
        home = find_home()
        if not home:
            return 0
        ent, by_host = retired_entry(load(home), inp.get("session_id"), os.environ.get("CLAUDE_CODE_HOST_SESSION_ID"))
        if not ent or allowed(inp.get("tool_name"), inp.get("tool_input")) or (by_host and host_exempt(inp.get("tool_name"))):
            return 0
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                                 "permissionDecisionReason": reason(ent)}}))
    except Exception as e:   # fail open
        log(f"retire_guard error: {type(e).__name__}: {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
