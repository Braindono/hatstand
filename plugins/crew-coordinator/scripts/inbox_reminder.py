"""Inbox reminder (crew-coordinator 0.26.0 item 2): the one-line "harness_inbox did not run in your last reply" reminder, its
Stop and prompt hook halves, and the unattended test (`[scheduled]` runs, Haiku workers, HARNESS_UNATTENDED=1).
Moved out of the old listening module unchanged (behaviour and tests); that module is removed in item 3.

Standard library only. Costs 0 model tokens unless it injects its one reminder line. Never blocks.
"""
import json
import os
import re
import time

REMINDER = ("Inbox: harness_inbox did not run in your last reply. Call it now and answer any mail in this reply "
            "(D-9cc1f); do not ask the operator first.")
UNATTENDED_PREFIXES = ("[scheduled]",)


def is_unattended(prompt=None, model=None, env=None):
    """(c) scheduled passes ('[scheduled] ...') and Haiku workers never listen and never get the reminder."""
    env = os.environ if env is None else env
    if str(env.get("HARNESS_UNATTENDED") or "") == "1":
        return True
    if "haiku" in str(model or "").lower():
        return True
    return str(prompt or "").lstrip().startswith(UNATTENDED_PREFIXES)


# ---- Stop hook: did harness_inbox run in this turn? -------------------------------------------

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
