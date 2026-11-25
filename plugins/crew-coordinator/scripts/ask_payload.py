"""ask_payload: 0.27.3 C1. The ONE parser of an AskUserQuestion tool input (moved out of ask_gate.py; ask_gate and propose_hook both call it, no second copy).
Depends on: stdlib only. Interface: questions(tool_input) -> [{question, header, multi, options:[{label, description, preview}]}] (bad entries skipped, never raises);
question_texts(tool_input) -> [str] (the question strings, in order); answers(tool_response) -> {question: answer text} (best effort, {} when the shape is unknown; walks dicts and lists for the raw strings)."""
import json, re


def _s(v):
    return v if isinstance(v, str) else ""


def questions(tool_input):
    qs = tool_input.get("questions") if isinstance(tool_input, dict) else None
    out = []
    for q in (qs if isinstance(qs, list) else []):
        if not isinstance(q, dict) or not isinstance(q.get("question"), str):
            continue
        opts = []
        for o in (q.get("options") if isinstance(q.get("options"), list) else []):
            if isinstance(o, dict) and _s(o.get("label")):
                opts.append({"label": o["label"], "description": _s(o.get("description")), "preview": _s(o.get("preview"))})
            elif isinstance(o, str) and o:
                opts.append({"label": o, "description": "", "preview": ""})
        out.append({"question": q["question"], "header": _s(q.get("header")), "multi": bool(q.get("multiSelect")), "options": opts})
    return out


def question_texts(tool_input):
    return [q["question"] for q in questions(tool_input)]


_PAIR = re.compile(r'"([^"\n]{3,300})"="([^"\n]{0,500})"')
_SKIPPED = "(answered in a message)"


def _strings(v, out, depth=0):
    """Collect every raw string in a nested dict/list (json.dumps would escape the quotes the pair regex needs)."""
    if isinstance(v, str):
        out.append(v)
    elif depth < 8 and isinstance(v, dict):
        for x in v.values():
            _strings(x, out, depth + 1)
    elif depth < 8 and isinstance(v, list):
        for x in v:
            _strings(x, out, depth + 1)
    return out


def _clean(a):
    a = str(a)
    return _SKIPPED if a.startswith("[User did not answer") else a


def answers(tool_response):
    """{question text: answer} from a PostToolUse tool_response: a dict with `answers` {q: a}, or text (bare, inside a dict, or inside a list)
    holding `"q"="a"` pairs. A skipped question ("[User did not answer ... sent a message instead ...]") maps to "(answered in a message)"."""
    r = tool_response
    if isinstance(r, dict) and isinstance(r.get("answers"), dict):
        return {str(k): _clean(v) for k, v in r["answers"].items()}
    out = {}
    for t in _strings(r, []):
        for m in _PAIR.finditer(t):
            out[m.group(1)] = _clean(m.group(2))
    return out
