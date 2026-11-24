"""0.25.0 item 18: id check hook, observe mode. After harness_send or harness_record, a cited corpus id (D-, N-, C-, K- plus 5 hex digits) is looked
up: unknown (or superseded) and "title does not match how it is cited" each print one line under 40 tokens; a match prints nothing. Every checked
id logs hook.idcheck (id, verdict, tokens). Never blocks. Pure functions: the hook in harness.py supplies the corpus rows."""
import re

import dated_switches

ID_RE = re.compile(r"(?<![A-Za-z0-9_-])([DNCK]-[0-9a-f]{5})(?![0-9A-Za-z_])")
EXEMPT = re.compile(r"```.*?```|`[^`\n]*`", re.S)
TOOL_RE = re.compile(r"harness_(send|record)$")           # any MCP prefix: mcp__plugin_crew-coordinator_crew-coordinator__ or mcp__crew-coordinator__
STOP = frozenset("that this with from have been were will would should could about their there which when what into only also than then them they your "
                 "were does done more most some such very just like over under after before because while where whose these those each both "
                 "the and for are not you was but can has its".split())
OBSERVE_UNTIL = ""      # item 38 / 0.27.2: empty = observe period ended; config idcheck_observe_until holds his renewal date; after it the hook is silent
LINE_UNKNOWN = "id check: %s not found (or superseded): copy ids from a tool result"
LINE_MISMATCH = "id check: %s title does not match how you cite it"


def words(s):
    return {w for w in re.findall(r"[a-z0-9]{3,}", str(s or "").lower()) if w not in STOP}


def cited(texts):
    """-> [(id, sentence, parenthetical)] for each corpus id cited in `texts` (code spans skipped). parenthetical: the id sits in parentheses or
    brackets, the way an agent gives a reference after plain words ("Ids only in parentheses afterwards (D-5c037).")."""
    out, seen = [], set()
    for tx in texts:
        s = EXEMPT.sub(" ", str(tx or ""))
        for m in ID_RE.finditer(s):
            i = m.group(1)
            if i in seen:
                continue
            seen.add(i)
            a = max(s.rfind(".", 0, m.start()), s.rfind("\n", 0, m.start())) + 1
            b_ = [x for x in (s.find(".", m.end()), s.find("\n", m.end())) if x >= 0]
            before = s[:m.start()].rstrip()[-1:]
            after = s[m.end():m.end() + 2].lstrip()[:1]
            out.append((i, s[a:(min(b_) if b_ else len(s))], before in ("(", "[") or after in (")", "]")))     # an empty string (an id at the very start or end) is not a bracket
    return out


def verdicts(texts, titles):
    """`titles` maps live corpus id -> title. -> [(id, verdict)] verdict match | unknown | mismatch. Existence is always checked. A reference in
    parentheses is a match once the id exists (it was the false-warn source). A bare citation needs one shared word of three letters or more
    between the title and the whole message, not only its own sentence."""
    res, whole = [], " ".join(str(t or "") for t in texts)
    for i, sentence, paren in cited(texts):
        t = titles.get(i)
        if t is None:
            res.append((i, "unknown"))
        elif paren or words(t) & words(whole):
            res.append((i, "match"))
        else:
            res.append((i, "mismatch"))
    return res


def line_for(res):
    """One line for the first non-match verdict, else None (silent on success)."""
    for i, v in res:
        if v == "unknown":
            return LINE_UNKNOWN % i
        if v == "mismatch":
            return LINE_MISMATCH % i
    return None


def tokens(line):
    return max(1, len(line) // 4) if line else 0


def expired(until=None, today=None):
    return not dated_switches.is_on(until or OBSERVE_UNTIL, today or dated_switches.today(), "idcheck_observe_until")


def ended_once(h, hook, aid, until, today=None):
    """Item 38: after the observe date a hook writes ONE hook.observe_ended event per day {hook, until} and nothing else. True when it wrote one."""
    import os
    day = today or dated_switches.today()
    mark = os.path.join(h.store.dir, "observe_ended_" + hook)
    try:
        with open(mark, encoding="utf-8") as f:
            if f.read().strip() == day:
                return False
    except OSError:
        pass
    try:                                    # the marker first: an event is written only when the marker write went through (no event storm)
        os.makedirs(os.path.dirname(mark), exist_ok=True)
        with open(mark, "w", encoding="utf-8") as f:
            f.write(day)
    except OSError:
        return False
    h.store.append("hook.observe_ended", aid, {"hook": hook, "until": until})
    return True
