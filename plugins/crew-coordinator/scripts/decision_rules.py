#!/usr/bin/env python3
"""0.27.3 C2 (capture fix piece 5): rule-based candidates for the decision ledger. Pure, stdlib only, no model.

`candidates(blocks, kinds=KINDS)` takes indexer blocks ([{role, ts, text}], already redacted by vault.parse_indexer) and
returns one dict per hit: {kind, line, ts, role, text}. `line` is the block number (0-based) in the session's indexer
file; `text` is the verbatim quote (<= QUOTE_CAP chars, a substring of the block, so the existing quote verifier in
vault.verify can check it). Five kinds: decision, rationale, proposal (options shown), insight, ask.
Depends on: nothing. Called by: vault_decisions.distill (the Haiku tagger with a closed tag set and the verifier live there).
"""
import re

KINDS = ("decision", "rationale", "proposal", "insight", "ask")
QUOTE_CAP = 300

# Assistant: first-person decision verbs only (approve/agreed describe the operator, not a decision by the assistant).
_DECISION_ASSISTANT = re.compile(r"\b(?:(?:i|we)(?:'ve|\s+have)?\s+(?:decided|settled on)|decided:|decision:|going with|we will|"
                                 r"we'll go with|settled on)\b", re.I)
# Operator: the same verbs anywhere; the short-reply words only in a block under SHORT_OPERATOR chars.
_DECISION_OPERATOR = re.compile(r"\b(decided|decision:|we will|we'll go with|going with|settled on|ruled out|rejected)\b", re.I)
_DECISION_SHORT = re.compile(r"\b(approved?|yes|yep|go|go with|pick|agreed|ok|okay|do it|ship it)\b", re.I)
SHORT_OPERATOR = 150
# Operator blocks that are not the operator's words: a path, a shell command, a harness banner, tool output.
_NOT_SPEECH = re.compile(r"^\s*(?:[~/.]|\$\s|(?:cd|ls|cat|cp|mv|ln|python3?|git|bash|sh|curl|grep|sed|tail|head|"
                         r"export|HARNESS_\w+=)\b|(?:operator act waiting|\[?harness\]?[:\s]|\[scheduled\]|<system-reminder|"
                         r"command (?:output|failed)|traceback|error:))", re.I)
# Rationale: a reason word in the same sentence as a decision verb, or (because/so that/the reason) in the block right after
# a decision candidate. The bare word "rationale" and "the reason" inside bullet or table status lines never count.
_REASON = re.compile(r"\b(because|so that|the reason|reason:|why:)", re.I)
_BULLET_OR_TABLE = re.compile(r"^\s*(?:[-*+]\s|\d+[.)]\s|\|)")
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?;])\s+")
# Insight: verbs only; the bare nouns "lesson" and "insight" do not count.
_INSIGHT = re.compile(r"\b(reali[sz]ed|turns out|root cause|learned that|noticed that|my error)\b", re.I)
_OPTION_LINE = re.compile(r"^\s*(?:[-*]\s*)?(?:option\s+)?(?:[A-D]|[1-4])[.):]\s+\S", re.I)
_LETTER_LINE = re.compile(r"^\s*(?:[-*]\s*)?(?:option\s+)?[A-D][.):]\s+\S", re.I)
_CHOICE_MARK = re.compile(r"\b(options?\b|\(recommended\)|recommended:|which of|pick one|choose (?:one|between))", re.I)
_OPTION_TABLE = re.compile(r"^\s*\|[^\n]*\boptions?\b[^\n]*\|", re.I | re.M)
_RECOMMENDED = re.compile(r"\(recommended\)", re.I)
_ASK = re.compile(r"(\?|^\s*(please|can you|could you|i want|i need|make sure|never|always|do not|don't)\b)", re.I | re.M)


def _quote(text, start=0):
    return text[start:start + QUOTE_CAP].strip()


def _first_line(text, rx):
    """The first line of `text` that matches rx, capped; the slice is verbatim."""
    pos = 0
    for ln in text.split("\n"):
        if rx.search(ln) and ln.strip():
            return _quote(text, pos + (len(ln) - len(ln.lstrip())))
        pos += len(ln) + 1
    return ""


def _offset(text, pred):
    """Offset of the first line satisfying pred, or -1."""
    pos = 0
    for ln in text.split("\n"):
        if pred(ln):
            return pos
        pos += len(ln) + 1
    return -1


def _proposal(text):
    """Options shown: an Option-column table, a (Recommended) row, or two+ option lines with a choice marker
    (lettered lines are their own marker). Numbered how-to steps alone never count."""
    m = _OPTION_TABLE.search(text)
    if m:
        return _quote(text, m.start())
    lines = text.split("\n")
    opts = [i for i, ln in enumerate(lines) if _OPTION_LINE.match(ln)]
    letters = [i for i, ln in enumerate(lines) if _LETTER_LINE.match(ln)]
    if _RECOMMENDED.search(text):
        first = opts[0] if opts else _offset(text, lambda ln: bool(_RECOMMENDED.search(ln)))
        return _quote(text, sum(len(ln) + 1 for ln in lines[:first]) if opts else first)
    if len(letters) >= 2 or (len(opts) >= 2 and _CHOICE_MARK.search(text)):
        return _quote(text, sum(len(ln) + 1 for ln in lines[:(letters or opts)[0]]))
    return ""


def _rationale(text, decision_rx, after_decision):
    """First line holding a reason word: in a sentence that also has a decision verb, or (after a decision block) at all."""
    pos = 0
    for ln in text.split("\n"):
        if ln.strip() and _REASON.search(ln):
            listed = bool(_BULLET_OR_TABLE.match(ln))
            for sent in _SENTENCE_SPLIT.split(ln):
                hit = _REASON.search(sent)
                if not hit:
                    continue
                if decision_rx.search(sent) or (after_decision and not (listed and hit.group(1).lower() == "the reason")):
                    return _quote(text, pos + (len(ln) - len(ln.lstrip())))
        pos += len(ln) + 1
    return ""


def _for_block(b, after_decision=False):
    role, text, out = b["role"], b["text"], {}
    if not text.strip() or text.lstrip().startswith(("! ", "/")):
        return out
    if role == "operator" and _NOT_SPEECH.match(text):
        return out
    prop = _proposal(text) if role == "assistant" else ""
    if prop:
        out["proposal"] = prop            # checked before rationale: option tables quote trade-offs, they are not reasons
    if role == "assistant":
        dec, drx = _first_line(text, _DECISION_ASSISTANT), _DECISION_ASSISTANT
    elif role == "operator":
        short = len(text.strip()) < SHORT_OPERATOR
        dec = _first_line(text, _DECISION_OPERATOR) or (_first_line(text, _DECISION_SHORT) if short else "")
        drx = re.compile(_DECISION_OPERATOR.pattern + ("|" + _DECISION_SHORT.pattern if short else ""), re.I)
    else:
        dec, drx = "", _DECISION_ASSISTANT
    if dec:
        out["decision"] = dec
    if not prop:
        rat = _rationale(text, drx, after_decision)
        if rat:
            out["rationale"] = rat
    ins = _first_line(text, _INSIGHT)
    if ins:
        out["insight"] = ins
    if role == "operator" and _ASK.search(text):
        out["ask"] = _quote(text)
    return out


def candidates(blocks, kinds=KINDS):
    """-> list of {kind, line, ts, role, text}, in block order, at most one per kind per block."""
    out, prev_dec = [], False
    for i, b in enumerate(blocks):
        found = _for_block(b, prev_dec)
        prev_dec = "decision" in found
        for kind, q in found.items():
            if kind in kinds and q:
                out.append({"kind": kind, "line": i, "ts": b["ts"], "role": b["role"], "text": q})
    return out
