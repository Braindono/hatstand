"""capsule_pointer: 0.27.3 C1 piece 1 (+ piece 4 function). A capsule open question that offers a choice must say where the choice is recorded.
Depends on: stdlib only. Called from Harness._handoff_gate (mode warn|block = config handoff_gate, same switch as the asks gate).
Interface: choice_items(text) -> [item text] (items under an "Open questions" heading whose words offer a choice (pick, draft, option, which of, A/B/C) AND carry a "?", "or", "default" or "between");
has_pointer(item) -> bool (a file path or bare file name with a common extension, a `P-xxxxx` proposal id, a corpus id D-/N-/A-/M- or thread id t- plus hex, a Hub question code (Q7) or "Questionnaire ... Q7", an https link, two or more option lines written out under the item, or an inline list "X, Y, or Z?" on the first line);
unpointed(text) -> [item text] (choice items with no pointer); pointer_audit(events) -> {role_or_agent: count} (handoff.pointer_warn events, per role).
An item is a top-level bullet (or numbered line) and the indented lines under it. P- ids are their own prefix: scripts/proposals.py looks them up, corpus id parsing never sees them."""
import re

HEADING = re.compile(r"^\s{0,3}#{1,6}\s*(.+?)\s*#*\s*$")
OPEN_Q = re.compile(r"open\s+questions?", re.I)
BULLET = re.compile(r"^(\s*)(?:[-*+]|\d+[.)])\s+(.*)$")
CHOICE = re.compile(r"\b(pick|picks|choose|choice|drafts?|options?|which of|which one|alternatives?)\b|\b[A-D]\s*(?:/|or)\s*[A-D]\b|\(\s*[A-D]\s*[,/]", re.I)
POINTER_PATH = re.compile(r"(?:^|[\s`(\[])(?:~|/|\.{1,2}/)?[\w.@-]+(?:/[\w.@ -]+)+\.\w{1,6}\b|(?:^|[\s`(\[])[\w-]+\.(?:py|sh|md|json|jsonl|txt|html|yaml|yml|toml|csv|tsv|plist)\b")
INLINE_LIST = re.compile(r"[^,?]+,[^,?]+,?\s+or\s+[^,?]+\?")   # "X, Y, or Z?" on the first line: the options are written out
NONE_ITEM = re.compile(r"^\W*none\b", re.I)
POINTER_ID = re.compile(r"\bP-[0-9a-f]{5,12}\b")
POINTER_REF = re.compile(r"\b[DNAMdnam]-[0-9a-f]{5,}\b|\bt-[0-9a-f]{5,}\b|\(\s*[A-Z]\d+\s*\)|\bQuestionnaire\b[^.\n]*?\b[A-Z]\d+\b")
LOST = re.compile(r"\b(lost|missing|gone|no \w+ on disk)\b", re.I)   # an id that names a LOST record points nowhere
CHOICE_MARK = re.compile(r"\?|\bor\b|\bdefault\b|\bbetween\b", re.I)   # a choice word alone is not a question
POINTER_URL = re.compile(r"https://[^\s)>\]]+")
OPTION_LINE = re.compile(r"^\s*(?:[-*+]\s+)?(?:\(?[A-Za-z0-9]{1,2}[.):]\s+|option\s+\w+\s*[:.-]\s*)\S", re.I)


def _section(text):
    """Lines under each heading that names open questions, up to the next heading."""
    lines, on, out = (text or "").splitlines(), False, []
    for ln in lines:
        h = HEADING.match(ln)
        if h:
            on = bool(OPEN_Q.search(h.group(1)))
            continue
        if on:
            out.append(ln)
    return out


def items(text):
    """Open-question items: [(first line, [continuation lines])]."""
    got, cur = [], None
    for ln in _section(text):
        m = BULLET.match(ln)
        if m and len(m.group(1)) <= 1:
            cur = (m.group(2), [])
            got.append(cur)
        elif cur is not None and ln.strip():
            cur[1].append(ln)
    return got


def _full(it):
    return "\n".join([it[0]] + it[1])


def choice_items(text):
    return [_full(i) for i in items(text) if not NONE_ITEM.match(i[0]) and CHOICE.search(_full(i)) and CHOICE_MARK.search(_full(i))]


def has_pointer(item):
    first, *rest = (item or "").splitlines() or [""]
    if POINTER_ID.search(item) or POINTER_URL.search(item) or POINTER_PATH.search(item):
        return True
    if POINTER_REF.search(item) and not LOST.search(item):
        return True
    if INLINE_LIST.search(first):
        return True
    return sum(1 for ln in rest if OPTION_LINE.match(ln)) >= 2


def unpointed(text):
    return [i for i in choice_items(text) if not has_pointer(i)]


def pointer_audit(events):
    """Count capsule open items without a pointer, per role (0.27.3 piece 4). `events` = ledger events; reads type handoff.pointer_warn and
    handoff.pointer_blocked, data {count, role?}; an event without a role counts under its actor. -> {role: items}."""
    out = {}
    for e in events or []:
        if not isinstance(e, dict) or e.get("type") not in ("handoff.pointer_warn", "handoff.pointer_blocked"):
            continue
        d = e.get("data") if isinstance(e.get("data"), dict) else {}
        who = str(d.get("role") or e.get("actor") or "unknown")
        try:
            out[who] = out.get(who, 0) + max(0, int(d.get("count") or 0))
        except (TypeError, ValueError):
            continue
    return out
