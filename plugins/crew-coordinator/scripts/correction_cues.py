"""correction_cues: item 1 of the 0.27.1 hotfix. Decides whether the operator's message corrects the agent. Pure, no model. Depends on: stdlib.
Interface: match(text) -> {"cue": name, "quote": <the sentence of the first cue, at most 300 characters>, "cues": [all names]} or None.
The 16 cues come from the guru's measurement on his own messages (Tests/monitor-pilot/cues/cues.py, 11/22): all 15 known corrections caught, 1.9% flagged falsely.
Only his own words count: quoted blocks (lines starting with >), pasted content, system reminders and relayed messages are removed first; injected summaries,
slash commands and messages over 4000 characters never match; praise drops a match unless a strong cue (why, not as asked, supposed to) is present.
Not a judgement: a hit only files a CANDIDATE that the weekly verifier then checks."""
import re

CUES = {
 'why_agent_did': r"\bwhy (did|didn'?t|did not|was|wasn'?t|were|weren'?t|is|isn'?t|does|doesn'?t) (you|it|the|this|that|they|only|my|a|an)\b",
 'did_you_ask':   r"\bdid you (ask|check|verify|test|read)\b",
 'not_as_asked':  r"\bnot (updated |done |built |set up )?(as how|as|how|what) I (had )?(asked|requested|instructed|said|wanted)",
 'i_instructed':  r"\bI (instructed|told|asked) you\b|\bI said\b",
 'supposed_to':   r"\b(were|was|is|are) supposed to\b",
 'should_not':    r"\bshould(n'?t| not) (be|have)\b",
 'still_wrong':   r"\bstill (does ?n[o']t|is ?n[o']t|not|showing|see|feels|has|looks|above|below)\b",
 'i_dont_see':    r"\bI (don'?t|do not|can'?t|cannot) see\b",
 'looks_bad':     r"\b(looks|is|seems|feels) (a little |quite |still )?(stale|off|wrong|broken|messy|cluttered)\b",
 'wrong':         r"(?<!if I'm )(?<!if I am )\bwrong\b",
 'unnecessary':   r"\b(unnecessary|redundant|meaningless|unacceptable|abnormally)\b",
 'removed_broke': r"\byou(?: have|'ve)? (?:completely )?(removed|broke|broken|deleted|purged|overwrote)\b|\bpurged?\b",
 'roll_back':     r"\broll ?back\b|\brevert\b",
 'dont_understand': r"\bI (don'?t|do not) understand (the|why|how)\b",
 'generic':       r"\b(that'?s|this is|that is) not (it|what I (wanted|meant|asked))\b|\bthis isn'?t what I\b|\bI (didn'?t|never|did not) ask (for|you)\b|\bdon'?t do that again\b|\bhow did you miss\b|\bundo (that|this|it)\b|\bthat wasn'?t what I\b|^\s*nope\b|\byou forgot\b|\byou missed\b(?! nothing)",
 'unchanged':     r"\b(is|was|are) unchanged\b|\bdoes ?n[o']t appear\b|\bdid ?n[o']t (work|change|update)\b",
}
PRAISE = re.compile(r"\b(congratulations|congrats|great job|well done|thank(s| you))\b", re.I)   # drop a match when the message is praise
RX = {k: re.compile(v, re.I) for k, v in CUES.items()}
STRONG = ('why_agent_did', 'not_as_asked', 'supposed_to')      # these survive praise in the same message
SKIP = re.compile(r'^(This session is being continued|Background \(from|<|\[)', re.I)
TAGS = ("pasted_content", "system-reminder", "cross-session-message")
EVENT_TAG = re.compile(r"<([a-z-]+-event)\b")        # any <x-event> block (side-sessions, ci-monitor)
MAX_LEN = 4000


def _cut(t, tag):
    """Remove every <tag ...> ... </tag ...> block; an unclosed block is dropped to the end. Linear in the text length. The tags are found
    with a case-insensitive search on the text itself (never on a lower-cased copy: some letters change length when lower-cased)."""
    start, end = re.compile("<" + re.escape(tag), re.I), re.compile("</" + re.escape(tag), re.I)
    out, i = [], 0
    while True:
        m = start.search(t, i)
        if not m:
            out.append(t[i:])
            return "".join(out)
        out.append(t[i:m.start()] + " ")
        k = end.search(t, m.end())
        if not k:
            return "".join(out)
        e = t.find(">", k.end())
        i = (e + 1) if e >= 0 else len(t)


def own_words(text):
    t = str(text or "")
    for tag in TAGS + tuple(sorted(set(EVENT_TAG.findall(t.lower())))):
        t = _cut(t, tag)
    return "\n".join(ln for ln in t.splitlines() if not ln.lstrip().startswith(">"))


def match(text):
    if len(str(text or "")) > 20000:      # 0.27.1 (critic 6): decide before any regex work on a huge paste
        return None
    t = own_words(text).strip()
    if not t or len(t) > MAX_LEN or t.startswith("/") or "<cross-session-message" in str(text or "") or SKIP.match(t):
        return None
    t = t.replace("\u2019", "'")
    hits = [k for k, r in RX.items() if r.search(t)]
    if not hits or (PRAISE.search(t) and not any(k in STRONG for k in hits)):
        return None
    for sent in re.split(r"(?<=[.!?])\s+|\n+", t):
        if RX[hits[0]].search(sent):
            return {"cue": hits[0], "quote": sent.strip()[:300], "cues": hits}
    return {"cue": hits[0], "quote": t[:300], "cues": hits}
