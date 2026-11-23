"""0.25.0 item 27(a): one command per message, observed. A final message of an operator-facing role with more than one fenced shell block gets one
short line and a hook.onecmd event (blocks, tokens). Observe only: it never blocks, and it is silent otherwise. Pure functions, 0 model tokens."""
import hashlib
import re

ROLES = ("envoy", "curator", "ops-coder", "steward")
SHELL_LANGS = ("bash", "sh", "shell", "zsh", "console")
LINE = "one command at a time: show the next after his result"
UNDO_LINE = "the undo goes in the Details text, not in the copy block beside the command"
_WORD = r"(?:undo|revert|roll ?back)"
_UNDO_LINE = re.compile(r"^\s*(?:#\s*)?" + _WORD + r"\b(?!\s*=)", re.I)                    # a line that is itself an undo label
_UNDO_NOTE = re.compile(r"#.*\b" + _WORD + r"\b", re.I)                                 # an undo note in a trailing or full-line comment
_UNDO = re.compile(r"^\s*(?:#\s*)?" + _WORD + r"\b|#.*\b" + _WORD + r"\b", re.I | re.M)
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


def shell_block_texts(text, untagged=False):
    """The inside of each fenced shell block, in order (same fence rules as shell_blocks); untagged=True also takes fences with no language tag."""
    out, i, text = [], 0, str(text or "")
    while True:
        m = _FENCE.search(text, i)
        if not m:
            return out
        mark, lang = m.group(1), m.group(2).lower()
        close = re.compile(r"^[ \t]*" + re.escape(mark[0]) + "{" + str(len(mark)) + r",}[ \t\r]*$", re.M).search(text, m.end())
        if lang in SHELL_LANGS or (untagged and not lang):
            out.append(text[m.end():close.start() if close else len(text)])
        i = close.end() if close else len(text)


def undo_blocks(text):
    """0.27.1 (guru row E): the number of shell blocks that hold an undo line next to a command line, so the undo looks like the next step."""
    def mixed(b):
        lines = [l for l in b.splitlines() if l.strip()]
        cmds = [l for l in lines if not l.strip().startswith("#") and not _UNDO_LINE.match(l)]
        return bool(cmds) and any(_UNDO_LINE.match(l) or _UNDO_NOTE.search(l) for l in lines)
    return sum(1 for b in shell_block_texts(text, untagged=True) if mixed(b))


def check(role, text):
    """-> (line, blocks, tokens) for a message to warn about, else None. Tokens of the printed line (about 4 characters each)."""
    if role not in ROLES:
        return None
    u = undo_blocks(text)
    if u:
        return UNDO_LINE, u, max(1, len(UNDO_LINE) // 4)
    n = shell_blocks(text)
    if n <= 1:
        return None
    return LINE, n, max(1, len(LINE) // 4)


def digest(text):
    return hashlib.sha1(str(text or "").encode("utf-8", "ignore")).hexdigest()[:12]
