"""LADDER (droppable): inbox discipline and listening ladder, crew-coordinator 0.14.6.

Spec: specs/2026-10-13-claude-code-inbox-ladder.md (envoy conditions a-e). Everything here is advisory text or a
never-blocking reminder; nothing in this module is needed by Wave 1, H-003 or H-016. To drop the ladder: delete this
file, tests/test_inbox_ladder.py, the three call sites marked `LADDER (droppable)` in harness.py (send, hook stop,
hook prompt), the "prompt" entry in hooks/hooks.json and the one-line notes in skills/protocol and skills/refresh.

Standard library only. Costs 0 model tokens unless it injects its one reminder line.
"""
import json
import math
import os
import re
import tempfile
import time

DEFAULT_RUNGS = (15, 60, 120)     # seconds, in order; `inbox-ladder: off` disables
INBOX_MAX_WAIT = 45               # the one number: no single harness_inbox call waits longer (D-ff4a4: 90 s died at 60)
EXPECTING_KINDS = ("task", "question", "review")   # (a) only these sends start a ladder
REMINDER = ("Inbox: harness_inbox did not run in your last reply. Call it now and answer any mail in this reply "
            "(D-9cc1f); do not ask the operator first.")
UNATTENDED_PREFIXES = ("[scheduled]",)


def parse_ladder(value):
    """'15,60,120' -> (15, 60, 120); 'off' -> (); missing or unparseable -> the defaults."""
    if value is None:
        return DEFAULT_RUNGS
    v = str(value).strip().strip("`").lower()
    if v in ("off", "false", "no", "0"):
        return ()
    try:
        r = tuple(int(x) for x in re.split(r"[,\s]+", v) if x)
    except ValueError:
        return DEFAULT_RUNGS
    # 0.15.3 (P7): at most 8 rungs of at most 10 minutes each
    return tuple(min(x, 600) for x in r[:8]) if r and all(x > 0 for x in r) else DEFAULT_RUNGS


def max_wait(cfg=None):
    try:
        n = int((cfg or {}).get("inbox_max_wait") or INBOX_MAX_WAIT)
    except (TypeError, ValueError):
        n = INBOX_MAX_WAIT
    return max(5, min(n, 60))        # Harness.inbox clamps a wait to 60 s anyway


def rung_chunks(rung, mw):
    """One rung as calls of at most mw seconds, equal as possible: 15 -> [15], 60 -> [30, 30], 120 -> [40, 40, 40]."""
    n = max(1, math.ceil(rung / mw))
    base, rem = divmod(rung, n)
    return [base + (1 if i < rem else 0) for i in range(n)]


def plan(rungs=DEFAULT_RUNGS, mw=INBOX_MAX_WAIT):
    return [rung_chunks(r, mw) for r in rungs]


def total_seconds(p):
    return sum(sum(c) for c in p)


def applies(kind):
    """(a) a ladder follows harness_send kind task, question or review, never notice, result or message."""
    return kind in EXPECTING_KINDS


def is_unattended(prompt=None, model=None, env=None):
    """(c) scheduled passes ('[scheduled] ...') and Haiku workers never listen and never get the reminder."""
    env = os.environ if env is None else env
    if str(env.get("HARNESS_UNATTENDED") or "") == "1":
        return True
    if "haiku" in str(model or "").lower():
        return True
    return str(prompt or "").lstrip().startswith(UNATTENDED_PREFIXES)


def ladder_hint(kind, msg_id, rungs, cfg=None, model=None, env=None):
    """The block harness_send adds to its result for a send that expects an answer. None = no ladder."""
    if not applies(kind) or not rungs or is_unattended(None, model, env):
        return None
    mw = max_wait(cfg)
    p = plan(rungs, mw)
    return {"rungs": p, "waits": [c for r in p for c in r], "max_wait": mw, "total_s": total_seconds(p),
            "stop_at_first_mail": True, "end": f"still waiting on {msg_id}",
            "how": "harness_inbox wait=<n> for each n in waits; stop at the first call that returns mail and answer it; "
                   "after the last empty call end the turn with `end`. The last empty call is your end-of-reply inbox call."}


def run(inbox, p, msg_id):
    """Drive the ladder with inbox(wait) -> {'count': n, ...}. Stops at the first mail. -> result dict."""
    calls = waited = 0
    for rung in p:
        for w in rung:
            r = inbox(w)
            calls += 1
            waited += w
            if (r or {}).get("count"):
                return {"mail": r, "calls": calls, "waited_s": waited, "end": None}
    return {"mail": None, "calls": calls, "waited_s": waited, "end": f"still waiting on {msg_id}"}


# ---- Stop hook: did harness_inbox run in this turn? (spec section 1.2) -------------------------------------------

def _text_of(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
    return ""


def turn_summary(path):
    """(inbox_called, turn_prompt) for the newest turn in a transcript JSONL: the tool_use blocks after the last
    real user message. (None, '') when the transcript cannot be read."""
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - 400000))
            lines = f.read().decode("utf-8", "ignore").splitlines()
    except Exception:
        return None, ""
    called = False
    for ln in reversed(lines):
        try:
            j = json.loads(ln)
        except ValueError:
            continue
        msg = j.get("message") or {}
        if j.get("type") == "assistant" and isinstance(msg.get("content"), list):
            for b in msg["content"]:
                if isinstance(b, dict) and b.get("type") == "tool_use" and str(b.get("name") or "").endswith("harness_inbox"):
                    called = True
        elif j.get("type") == "user":
            txt = _text_of(msg.get("content")).strip()
            if txt:
                return called, txt
    return called, ""


NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)


def state_dir():
    """0.15.1 (P5): per-user state dir (0700), never the shared /tmp. HARNESS_STATE_DIR overrides (tests)."""
    d = os.environ.get("HARNESS_STATE_DIR") or os.path.expanduser("~/.claude/crew-coordinator/state")
    try:
        os.makedirs(d, mode=0o700, exist_ok=True)
        if hasattr(os, "getuid") and os.stat(d).st_uid == os.getuid():
            os.chmod(d, 0o700)
    except OSError:
        pass
    return d


def _flag(sid):
    return os.path.join(state_dir(), f"harness-inbox-reminder-{re.sub(r'[^A-Za-z0-9_-]', '_', str(sid or 'x'))}")


def _write_flag(path, text):
    """O_CREAT|O_EXCL|O_NOFOLLOW, 0600: a planted symlink or file at the target is refused, never written through."""
    if os.path.lexists(path):
        if os.path.islink(path):
            raise OSError("reminder flag is a symlink; refused")
        os.unlink(path)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(text)


def on_stop(inp, model=None):
    """Stop hook. Notes whether harness_inbox ran this turn; if not, leaves one reminder for the next prompt.
    Never blocks. -> True when a reminder was queued."""
    called, prompt = turn_summary(inp.get("transcript_path") or "")
    if called is None or called or is_unattended(prompt, model):
        return False
    try:
        _write_flag(_flag(inp.get("session_id")), str(int(time.time())))
        return True
    except OSError:
        return False


def take_reminder(inp, prompt=None, model=None):
    """UserPromptSubmit hook: the one reminder line queued by on_stop, once. -> text or None."""
    p = _flag(inp.get("session_id"))
    if os.path.islink(p) or not os.path.exists(p):
        return None
    try:
        os.unlink(p)
    except OSError:
        pass
    return None if is_unattended(prompt if prompt is not None else inp.get("prompt"), model) else REMINDER
