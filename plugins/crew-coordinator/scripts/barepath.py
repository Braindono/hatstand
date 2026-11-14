"""Bare-path hook (crew-coordinator 0.26.0 item 21, D-55bd0): the Stop hook logs hook.barepath when a role's final reply names a local .md, .pdf
or .docx path and no SendUserFile or artifact publish ran in that turn. Observe only: it never blocks and prints nothing; the event carries
counts and a hash, never the path or the text. Standard library only."""
import hashlib
import json
import re

EXTS = ("md", "pdf", "docx")
# a local path: it has a directory part (a "/" or a leading "~"), ends in one of EXTS, and is not part of a URL
PATH_RE = re.compile(r"(?<![\w:/.-])(?:~/|\.{1,2}/|/)?(?:[\w.@+~-]+/)+[\w.@+~ -]*?[\w@+~-]\.(?:%s)\b" % "|".join(EXTS), re.I)
SENDERS = ("SendUserFile",)
ARTIFACT = "Artifact"


COMPUTER_RE = re.compile(r"computer://+/[^\s)\]>\"']+?\.(?:%s)\b" % "|".join(EXTS), re.I)    # the old computer:// link form is a local path too


def paths(reply):
    """The local file paths a reply names, including computer:// links. URLs (http, https, file) and a bare file name with no directory part are not."""
    text = str(reply or "")
    return [m.group(0).strip() for m in PATH_RE.finditer(text)] + [m.group(0) for m in COMPUTER_RE.finditer(text)]


def turn_tools(lines):
    """[(tool name, input)] of the newest turn of a transcript (read_tail lines): the tool_use blocks after the last real user message."""
    out = []
    for ln in reversed(lines):
        try:
            j = json.loads(ln)
        except ValueError:
            continue
        msg = j.get("message") or {}
        content = msg.get("content")
        if j.get("type") == "assistant" and isinstance(content, list):
            for b in content:
                if isinstance(b, dict) and b.get("type") == "tool_use":
                    out.append((str(b.get("name") or ""), b.get("input") or {}))
        elif j.get("type") == "user":
            txt = content if isinstance(content, str) else "\n".join(
                b.get("text", "") for b in (content or []) if isinstance(b, dict) and b.get("type") == "text")
            if str(txt).strip():
                break
    return out


def delivered(tools):
    """True when a file was sent or an artifact published in the turn."""
    for name, inp in tools:
        base = name.rsplit("__", 1)[-1]
        if base in SENDERS:
            return True
        if base == ARTIFACT and (inp.get("action") in (None, "", "publish")):
            return True
    return False


def check(reply, lines):
    """-> (n paths, sorted extensions, sha12 of the reply) when the reply names a local path and nothing was sent or published; else None."""
    ps = paths(reply)
    if not ps or delivered(turn_tools(lines)):
        return None
    exts = sorted({p.rsplit(".", 1)[-1].lower() for p in ps})
    return len(ps), exts, hashlib.sha256(str(reply).encode("utf-8", "ignore")).hexdigest()[:12]
