"""0.25.0 item 27(a): one command per message, observed. A final message of an operator-facing role with more than one fenced shell block gets one
short line and a hook.onecmd event (blocks, tokens). Observe only: it never blocks, and it is silent otherwise. Pure functions, 0 model tokens."""
import hashlib
import re

ROLES = ("envoy", "curator", "ops-coder", "steward")
SHELL_LANGS = ("bash", "sh", "shell", "zsh", "console")
LINE = "one command at a time: show the next after his result"
_FENCE = re.compile(r"^[ \t]*(`{3,}|~{3,})[ \t]*([A-Za-z0-9_+-]*)[^\n]*$", re.M)


def shell_blocks(text):
    """The number of fenced shell blocks (bash, sh, shell, zsh, console) in `text`. A fence of another language, or none, never counts; an
    unclosed fence runs to the end."""
    n, i, text = 0, 0, str(text or "")
    while True:
        m = _FENCE.search(text, i)
        if not m:
            return n
        mark, lang = m.group(1), m.group(2).lower()
        close = re.compile(r"^[ \t]*" + re.escape(mark[0]) + "{" + str(len(mark)) + r",}[ \t\r]*$", re.M).search(text, m.end())
        if lang in SHELL_LANGS:
            n += 1
        i = close.end() if close else len(text)


def check(role, text):
    """-> (line, blocks, tokens) for a message to warn about, else None. Tokens of the printed line (about 4 characters each)."""
    if role not in ROLES:
        return None
    n = shell_blocks(text)
    if n <= 1:
        return None
    return LINE, n, max(1, len(LINE) // 4)


def digest(text):
    return hashlib.sha1(str(text or "").encode("utf-8", "ignore")).hexdigest()[:12]
