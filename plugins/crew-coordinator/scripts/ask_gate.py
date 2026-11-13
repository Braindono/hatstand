#!/usr/bin/env python3
"""ask_gate (crew-coordinator 0.25.0 item 32; ported from Secretary/bin/gates/ask_gate.py, not cv_gate): flag operator questions that the records
already answer (stdlib only).

Usage: python3 ask_gate.py pre | stop | session   (hook JSON on stdin)
Env:   ASK_GATE_ROOTS  colon-separated extra roots, tried before the defaults.
       GATES_CONFIG    path to gates.json (else <root>/Projects/Exchange/projects/secretary/gates.json).
All behaviour comes from gates.json at run time, so a change needs no release: sources, fact words, stopwords, hit threshold, bypass marker, and
`mode`. Two sections: "ask_gate" (CV fact rules, for the secretary and career roles listed in its `career_roles`) and "harness" (harness sources, no
CV fact words, for every other role). OBSERVE MODE FIRST: `mode` "observe" (the default) never denies or blocks: every evaluated question logs
hook.askgate (verdict, tokens, role) and the hook prints nothing; the operator's later switch to "enforce" is a gates.json value. `enabled`
false allows everything. A deny reason names labels and paths only, never an excerpt of a facts file. The SessionStart index is injected only for
career roles, never into harness chats. Stop mode reads at most the last 400 kB of the transcript.
"""
import copy
import glob
import json
import os
import re
import sys
import time

PREFIX_RE = re.compile(r"^(?:/Users/[^/]+|/home/[^/]+|/root|\$\{?HOME\}?|~)/Claude(?:/|$)")    # an absolute path under any home's Claude folder maps onto the roots
CONFIG_REL = "Projects/Exchange/projects/secretary/gates.json"
HARNESS_DEFAULTS = {
    "enabled": True,
    "mode": "observe",
    "observe_until": "2026-11-20",      # item 38: observe mode switches itself off after this date (gates.json renews it); enforce mode is never auto-off
    "sources": [
        {"label": "operator rules", "path": "Projects/Exchange/OPERATOR.md"},
        {"label": "harness operator preferences", "path": "Code/harness-ops/projects/orchestration/OPERATOR-PREFERENCES.md"},
    ],
    "fact_words": [],
    "min_terms": 2,                    # a question with fewer than two key terms is never matched (one common word flagged a harness question)
    "skip_initial_caps": True,         # a capitalised sentence opener ("Run", "Approve", "Should") is not a name: it was the false-positive source
    "stopwords_extra": ["hub"],
    "min_term_hits": 2,
    "bypass_marker": "[searched:",
    "answers_ledger": "Projects/Exchange/projects/secretary/ANSWERS.md",
}
DEFAULTS = {
    "enabled": True,
    "mode": "observe",
    "observe_until": "2026-11-20",
    "career_roles": ["secretary", "letters-manager", "resume-manager", "listings-manager", "cv-management", "career-compass"],
    "sources": [
        {"label": "operator facts (single source)", "path": "Projects/CV_Management/*skills_repository.json"},
        {"label": "intake (unmerged)", "path": "Projects/CV_Management/*skills_repository.INTAKE.md"},
        {"label": "answers ledger", "path": "Projects/Exchange/projects/secretary/ANSWERS.md"},
        {"label": "operator rules (cv)", "path": "Projects/Exchange/projects/cv-management/OPERATOR_RULES.md"},
        {"label": "operator rules", "path": "Projects/Exchange/OPERATOR.md"},
        {"label": "secretary rules", "path": "Projects/Secretary/rules/*.md"},
    ],
    "fact_words": ["degree", "major", "minor", "title", "date", "start", "end", "school", "university",
                   "employer", "salary", "address", "phone", "email", "years", "demos", "certification",
                   "location", "remote", "relocation", "sponsorship", "veteran", "gender", "race",
                   "disability", "pronouns"],
    "stopwords_extra": ["hub"],
    "min_term_hits": 2,
    "bypass_marker": "[searched:",
    "answers_ledger": "Projects/Exchange/projects/secretary/ANSWERS.md",
}
EVALUATED = False        # set by check_text: True when the text held at least one question (so an allow can be logged)
CFG = None
CFG_PATH = None
SECTION = "ask_gate"
TAIL_BYTES = 400000
MONTHS = {"jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "sept", "oct", "nov", "dec",
          "january", "february", "march", "april", "june", "july", "august", "september",
          "october", "november", "december"}
STOP_BASE = set(("you your yours should which what would confirm please still want a an the and or but of to in on "
            "for with at by from as is are was were be been do does did can could will shall may might must "
            "how when where who whom whose why that this these those it its i me my we our us he his him she "
            "her they their them not no yes if then than so there here any some all each have has had just "
            "like use used need needs ask about into over under also more most other new one two").split())
HEADING_RE = re.compile(r"(?i)question|need|answer")
MARK_RE = Q_RE = None  # built from the configured bypass marker
NUM_RE = re.compile(r"^\s*(?:[-*]\s*)?\d+[.)]\s+(.*\S)")
TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z'’\-]*|\d+")
QUOTE_RE = re.compile(r"\"([^\"]{2,})\"|“([^”]{2,})”|(?<!\w)'([^']{3,})'(?!\w)")


def log_err(e):
    sys.stderr.write(f"ask_gate error (allowing): {type(e).__name__}: {e}\n")


# ---------- sources ----------
def roots():
    r = [x for x in os.environ.get("ASK_GATE_ROOTS", "").split(":") if x]
    r += [os.path.join(os.path.expanduser("~"), "Claude")]          # more roots (a Cowork mount) come from ASK_GATE_ROOTS, never from a path in the plugin
    out = []
    for x in r:
        if x not in out:
            out.append(x)
    return out


def warn(msg):
    sys.stderr.write(f"ask_gate warning: {msg}\n")


def config_path():
    env = os.environ.get("GATES_CONFIG")
    if env:
        return env
    for r in roots():
        p = os.path.join(r, CONFIG_REL)
        if os.path.isfile(p):
            return p
    return None


def load_config(section="ask_gate"):
    """Load a gates.json section ("ask_gate" or "harness") over its built-in defaults; warn and fall back if missing/invalid."""
    global CFG, CFG_PATH, MARK_RE, Q_RE, SECTION
    SECTION = section
    cfg = copy.deepcopy(DEFAULTS if section == "ask_gate" else HARNESS_DEFAULTS)
    CFG_PATH = p = config_path()
    try:
        if not p:
            raise FileNotFoundError("gates.json not found")
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
        sec = data.get(section) if isinstance(data, dict) else None
        if not isinstance(sec, dict):
            raise ValueError("no '%s' object" % section)
    except Exception as e:
        warn(f"gates.json unusable ({type(e).__name__}: {e}); using built-in defaults")
        sec = {}
    for k, v in sec.items():
        if k in cfg and type(v) is type(cfg[k]):
            cfg[k] = v
        elif k in cfg:
            warn(f"gates.json ask_gate.{k} has wrong type; using default")
    cfg["sources"] = [s for s in cfg["sources"] if isinstance(s, dict) and isinstance(s.get("path"), str)]
    if not cfg["bypass_marker"].strip():
        cfg["bypass_marker"] = DEFAULTS["bypass_marker"]
    cfg["min_term_hits"] = max(1, cfg["min_term_hits"])
    if cfg.get("mode") not in ("observe", "enforce"):
        cfg["mode"] = "observe"
    cfg["ended"] = False
    if cfg["mode"] == "observe" and time.strftime("%Y-%m-%d") > cfg["observe_until"]:
        cfg["enabled"], cfg["ended"] = False, True     # observe period over: silent until a person renews observe_until or switches to enforce
    mk = re.escape(cfg["bypass_marker"])
    MARK_RE = re.compile(mk + r"\s*([^\]]*)\]", re.I)
    Q_RE = re.compile(r"(?:[^.?!\n]|(?<=\d)\.(?=\d))*\?(?:[ \t]*" + mk + r"[^\]]*\])?")      # a decimal point ("3.14?") does not end the question
    CFG = cfg
    return cfg


def fact_words():
    return {str(w).lower() for w in CFG["fact_words"]}


def stop_words():
    return STOP_BASE | {str(w).lower() for w in CFG["stopwords_extra"]}


def load_sources():
    return CFG["sources"]


def label_of(s):
    return s.get("label") or os.path.basename(s["path"])


WARNED = set()


def resolve(path):
    """Existing files for a source path (glob ok) across all roots."""
    m = PREFIX_RE.match(path)
    if m:
        cands = [os.path.join(r, path[m.end():]) for r in roots()] + [os.path.expanduser(path)]
    elif path.startswith("/") or path.startswith("~"):
        cands = [os.path.expanduser(path)]
    else:
        cands = [os.path.join(r, path) for r in roots()]
    out, seen = [], set()
    for c in cands:
        for f in sorted(glob.glob(c)):
            rp = os.path.realpath(f)
            if os.path.isfile(rp) and rp not in seen:
                seen.add(rp)
                out.append(rp)
    if not out and not any(ch in path for ch in "*?[") and path not in WARNED:
        WARNED.add(path)
        warn("source not found, skipped: " + path)         # item 38: a missing source is one stderr line, never a crash
    return out


def read_lines(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            txt = f.read()
    except OSError:
        return []
    if path.endswith(".json"):
        try:
            txt = json.dumps(json.loads(txt), indent=1, ensure_ascii=False)
        except ValueError:
            pass
    return txt.splitlines()


def load_records():
    recs = []  # (label, line, path)
    for s in load_sources():
        try:
            lab = label_of(s)
            for f in resolve(s["path"]):
                recs += [(lab, ln, s["path"]) for ln in read_lines(f) if ln.strip()]
        except Exception as e:
            log_err(e)
    return recs


# ---------- extraction ----------
def extract_questions(text):
    qs = []
    for m in Q_RE.finditer(text):
        q = m.group(0).strip()
        if q != "?":
            qs.append(q)
    active = False
    for ln in text.splitlines():
        n = NUM_RE.match(ln)
        if n:
            if active:
                qs.append(n.group(1).strip())
        elif ln.strip():
            if HEADING_RE.search(ln) and (len(ln) < 100 or ln.lstrip().startswith("#")):
                active = True
            elif ln.lstrip().startswith("#"):
                active = False
    out = []
    for q in qs:
        if not any(q == o or q in o for o in out):
            out = [o for o in out if o not in q] + [q]
    return out


def key_terms(q):
    q = MARK_RE.sub(" ", q)
    stop, facts = stop_words(), fact_words()
    terms = []

    def add(t):
        t = t.lower()
        if t and t not in terms:
            terms.append(t)

    for m in QUOTE_RE.finditer(q):
        add(next(g for g in m.groups() if g).strip())
    initial = bool(CFG.get("skip_initial_caps"))
    for m in TOKEN_RE.finditer(q):
        w = m.group(0)
        lw = w.lower().rstrip("'’")
        at_start = m.start() == 0 or q[:m.start()].rstrip()[-1:] in ".?!:\n"
        if lw in stop or (initial and at_start and w[0].isupper() and lw not in facts and not w.isdigit()):
            continue
        if w.isdigit() or lw in MONTHS or lw in facts or (w[0].isupper() and len(w) > 1):
            add(lw)
    return terms


def term_re(t):
    return re.compile(r"(?<![\w])" + re.escape(t) + r"(?![\w])", re.I)


def trim(line, rx_list):
    line = line.strip()
    if len(line) <= 160:
        return line
    pos = 0
    for rx in rx_list:
        m = rx.search(line)
        if m:
            pos = m.start()
            break
    start = max(0, min(pos - 60, len(line) - 160))
    return line[start:start + 160]


def find_hits(q, recs):
    terms = key_terms(q)
    if not terms or len(terms) < CFG.get("min_terms", 1):
        return []
    rxs = [term_re(t) for t in terms]
    need = min(CFG["min_term_hits"], len(terms))
    hits, seen = [], set()
    for lab, ln, path in recs:
        if sum(1 for rx in rxs if rx.search(ln)) >= need:
            h = f"{lab} ({path})"                      # labels and paths only: never an excerpt of the operator's facts
            if h not in seen:
                seen.add(h)
                hits.append(h)
                if len(hits) == 3:
                    break
    return hits


def check_text(text):
    """Return deny message or None."""
    global EVALUATED
    qs = extract_questions(text)
    EVALUATED = EVALUATED or bool(qs)
    if not qs:
        return None
    recs = None
    parts = []
    for q in qs:
        if MARK_RE.search(q):
            continue
        if recs is None:
            recs = load_records()
        hits = find_hits(q, recs)
        if hits:
            parts.append(f"Q: {q[:120]} -> " + " | ".join(hits))
    if not parts:
        return None
    return ("ASK GATE: the records may already answer this. Before asking the operator, read these and use "
            "them: " + " ;; ".join(parts) + ". Ask only what they do not answer, and mark the question "
            + CFG["bypass_marker"] + " <labels>]. Record every new operator answer in "
            + CFG["answers_ledger"] + " (date | topic | his words).")


# ---------- modes ----------
def message_texts(d):
    name = d.get("tool_name") or ""
    ti = d.get("tool_input")
    if not isinstance(ti, dict):
        return []
    if name == "AskUserQuestion" or name.endswith("__AskUserQuestion"):
        qs = ti.get("questions")
        return ["\n".join(q.get("question", "") for q in qs if isinstance(q, dict)
                          and isinstance(q.get("question"), str))] if isinstance(qs, list) else []
    is_msg = name == "SendUserMessage" or name.endswith("__SendUserMessage")
    if name.endswith("harness_send") and str(ti.get("to", "")).strip().lower() == "operator":
        is_msg = True
    if not is_msg:
        return []
    return [ti[k] for k in ("message", "body", "text", "content") if isinstance(ti.get(k), str)]


def pre(d):
    name = d.get("tool_name") or ""
    if name == "AskUserQuestion" or name.endswith("__AskUserQuestion"):
        ti = d.get("tool_input") or {}
        msg = None
        for q in (ti.get("questions") or []) if isinstance(ti, dict) else []:
            t = q.get("question") if isinstance(q, dict) else None
            if isinstance(t, str):
                # AskUserQuestion texts are questions even without a trailing "?"
                m = check_text(t if "?" in t else t + "?")
                if m:
                    msg = (msg + " ;; " if msg else "") + m
        return msg
    for t in message_texts(d):
        m = check_text(t)
        if m:
            return m
    return None


def last_assistant_text(path):
    """The last assistant text in the last 400 kB of the transcript (the first, possibly cut, line of a tail read is dropped)."""
    last = ""
    with open(path, "rb") as fb:
        fb.seek(0, 2)
        size = fb.tell()
        fb.seek(max(0, size - TAIL_BYTES))
        lines = fb.read().decode("utf-8", "replace").splitlines()
    for ln in (lines[1:] if size > TAIL_BYTES else lines):
        try:
            e = json.loads(ln)
        except ValueError:
            continue
        if not isinstance(e, dict):
            continue
        msg = e.get("message") if isinstance(e.get("message"), dict) else e
        if (msg.get("role") or e.get("type")) != "assistant":
            continue
        c = msg.get("content")
        if isinstance(c, str):
            t = c
        elif isinstance(c, list):
            t = "\n".join(b.get("text", "") for b in c if isinstance(b, dict) and b.get("type") == "text")
        else:
            continue
        if t.strip():
            last = t
    return last


def session():
    srcs = load_sources()
    items = [f"{label_of(s)}={s['path']}" for s in srcs]
    items.append(f"gates config={CFG_PATH or CONFIG_REL}")
    k = 4
    size = max(1, -(-len(items) // k))
    lines = ["WHERE FACTS LIVE (records to search before asking the operator):"]
    for i in range(k):
        lines.append("; ".join(items[i * size:(i + 1) * size]) or "-")
    lines.append("Never ask the operator for a fact before searching these. "
                 "To add a source or rule, edit gates.json and append to history")
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart",
                                             "additionalContext": "\n".join(lines)}}, ensure_ascii=False))


def caller(d):
    """-> (agent id, role) of the calling chat from the harness ledger (session id -> agent), or (None, None). Never raises."""
    try:
        here = os.path.dirname(os.path.abspath(__file__))
        if here not in sys.path:
            sys.path.insert(0, here)
        import harness as H
        h = H.Harness()
        st = h.state()
        aid = st.sessions.get(d.get("session_id"))
        aid = st.current(aid) if aid else None
        return (aid, st.role_of(aid)) if aid else (None, None)
    except Exception:
        return None, None


def log_event(aid, role, verdict, tokens):
    """hook.askgate {agent, role, verdict, tokens}: counts and a verdict, never the question text. Never raises."""
    if not aid:
        return
    try:
        import harness as H
        H.Harness().store.append("hook.askgate", aid, {"agent": aid, "role": role, "verdict": verdict, "tokens": tokens, "section": SECTION})
    except Exception as e:
        log_err(e)


def section_for(role):
    """The CV rules (section "ask_gate") apply only to the secretary and career roles; every other role, and an unknown one, uses "harness"."""
    base = load_config("ask_gate")
    return "ask_gate" if role and role in {str(x).lower() for x in base.get("career_roles") or []} else "harness"


def may_hold_question(t):
    """Cheap test before any ledger read: a "?" or a numbered list under a questions/needs/answer heading (extract_questions reads both)."""
    return "?" in t or bool(HEADING_RE.search(t) and re.search(r"^\s*(?:[-*]\s*)?\d+[.)]\s", t, re.M))


def cheap_skip(mode, d):
    """True when the call cannot hold a question to check, decided before the ledger is touched (caller() opens the harness state): a pre call that
    is neither AskUserQuestion nor operator-facing text with a "?"; a harness_send to anyone but the operator."""
    if mode != "pre":
        return False
    name = d.get("tool_name") or ""
    if name == "AskUserQuestion" or name.endswith("__AskUserQuestion"):
        return False
    return not any(may_hold_question(t) for t in message_texts(d))


def main():
    global EVALUATED
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    try:
        d = json.loads(sys.stdin.read())
        if not isinstance(d, dict):
            raise ValueError("hook input is not a JSON object")
        if cheap_skip(mode, d):
            return
        text = None
        if mode == "stop":
            if d.get("stop_hook_active"):
                return
            tp = d.get("transcript_path")
            if not tp or not os.path.isfile(tp):
                return
            text = last_assistant_text(tp)
            if not may_hold_question(text):
                return                                 # no question in the final reply: nothing to check, no ledger read
        aid, role = caller(d)
        sec = section_for(role)
        load_config(sec)
        if not CFG["enabled"]:
            if CFG.get("ended") and aid:
                try:
                    import harness as H, idcheck
                    idcheck.ended_once(H.Harness(), "askgate", aid, CFG["observe_until"])      # item 38: one hook.observe_ended per day, nothing else
                except Exception as e:
                    log_err(e)
            sys.exit(0)
        if mode == "session":
            if sec == "ask_gate":                      # the facts index is never injected into harness chats in 0.25.0
                session()
            return
        EVALUATED = False
        if mode == "stop":
            msg = check_text(text)
            kind = "stop"
        elif mode == "pre":
            msg = pre(d)
            kind = "pre"
        else:
            return
        if not msg:
            if EVALUATED:
                log_event(aid, role, "allow", 0)       # evaluated and allowed: the observe week needs the rates
            return                                     # silent on allow
        enforce = CFG["mode"] == "enforce"
        log_event(aid, role, "block" if enforce else "would_block", len(msg) // 4)
        if not enforce:
            return                                     # observe mode: never denies, never blocks, prints nothing
        if kind == "stop":
            print(json.dumps({"decision": "block", "reason": msg}, ensure_ascii=False))
        else:
            print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                                     "permissionDecisionReason": msg}}, ensure_ascii=False))
    except SystemExit:
        raise
    except Exception as e:  # never crash: allow
        log_err(e)
    sys.exit(0)


if __name__ == "__main__":
    main()
