"""mistake_verify: checks a spool candidate against the agent's OWN transcript before it becomes a record. Depends on: stdlib.
Interface: verify(transcript_path, line, act, quote) -> True only when line N of that transcript is an assistant line whose text (or tool name) starts with
the act, and one of his user lines AFTER line N, once relayed, system and pasted text is removed, yields exactly that quote through correction_cues.match. The path comes from mistake_pointer.find_transcript(session id), never from the spool.
Transcripts are written by the host, not by agents, so a forged spool line cannot pass."""
import json, re

import correction_cues

_WS = re.compile(r"\s+")


def _norm(s):
    return _WS.sub(" ", str(s or "")).strip().lower()


def assistant_act(rec):
    blocks = ((rec.get("message") or {}).get("content")) or []
    texts = [b.get("text", "") for b in blocks if isinstance(b, dict) and b.get("type") == "text"]
    tools = [b.get("name", "") for b in blocks if isinstance(b, dict) and b.get("type") == "tool_use"]
    return " ".join(" ".join(texts).split())[:300] or ("tool call: " + ", ".join(tools)[:200])


def user_text(rec):
    c = (rec.get("message") or {}).get("content")
    if isinstance(c, str):
        return c
    return " ".join(b.get("text", "") for b in c if isinstance(b, dict) and b.get("type") == "text") if isinstance(c, list) else ""


def verify(path, line, act, quote):
    if not path or not isinstance(line, int) or line < 1 or not _norm(act) or not _norm(quote):
        return False
    q, found_line = _norm(quote)[:120], False
    try:
        with open(path, "rb") as f:
            for n, raw in enumerate(f, 1):
                if n < line:
                    continue
                try:
                    rec = json.loads(raw)
                except ValueError:
                    if n == line:
                        return False
                    continue
                if not isinstance(rec, dict):
                    continue
                if n == line:
                    if rec.get("type") != "assistant" or not _norm(assistant_act(rec)).startswith(_norm(act)[:200]):
                        return False
                    found_line = True
                elif found_line and rec.get("type") == "user":
                    hit = correction_cues.match(user_text(rec))        # his own words only: relayed, system and pasted text is stripped first
                    if hit and _norm(hit["quote"])[:120] == q:
                        return True
    except OSError:
        return False
    return False
