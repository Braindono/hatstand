#!/usr/bin/env python3
"""0.27.3 C2 (capture fix piece 5): decision-ledger distiller, split out of vault.py (0.27.3 C2b).
`extract_decisions` (rules from decision_rules), `distill` (Haiku picks one tag per quote from the closed set DECISION_TAGS;
every quote must pass vault.verify; output redacted) and `write_ledger` (Exchange/ledger/decisions/<yyyy-mm>.jsonl, local,
0600, deduped by (session, line, kind), so re-running a session's tail adds only what is new).
Depends on: vault (verify, parse_tags, redact_out, RedactionError, ANY_ID, FENCE_*, PROMPT_CAP), decision_rules, corpus.
Called by: expiry_sweep.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
from corpus import clean_text  # noqa: E402
from vault import (ANY_ID, FENCE_CLOSE, FENCE_OPEN, PROMPT_CAP, RedactionError, parse_tags, redact_out, verify)  # noqa: E402

DECISION_TAGS = ("settled", "open", "superseded", "unclear")   # the closed tag set for ledger entries

def extract_decisions(blocks, session, kinds=None):
    """Rule candidates (decision_rules) for one session's indexer blocks; `kinds` narrows the five kinds."""
    import decision_rules as DR
    return [dict(c, session=session) for c in DR.candidates(blocks, tuple(kinds or DR.KINDS))]


def build_decision_prompt(cands):
    """-> (prompt, n). The model only chooses one tag per numbered quote from DECISION_TAGS."""
    head = ("Tag each numbered quote with one tag from: settled, open, superseded, unclear.\n"
            "settled = the matter was decided; open = still being discussed; superseded = later reversed; unclear = "
            "cannot tell from the quote. Give no other text.\n"
            'Return exactly: {"tags":[{"n":1,"tag":"settled"}]}\n\nQUOTES:\n')
    parts, size, n = [head], len(head), 0
    for k, c in enumerate(cands, 1):
        blk = "%d. [%s] %s%s%s\n" % (k, c["kind"], FENCE_OPEN, clean_text(c["text"], 300, multiline=True), FENCE_CLOSE)
        if size + len(blk) > PROMPT_CAP:
            break
        parts.append(blk)
        size += len(blk)
        n = k
    return "".join(parts), n


def distill(blocks, session, source_text=None, kinds=None, model_fn=None, model="haiku", id_exists=None, redact=None):
    """-> (entries, info). entries: {date, session, line, role, kind, quote, ids, tag}. No model, or a failing one: every
    tag is `unclear`. Every quote must be a substring of the redacted session text (the existing `verify`); a quote that
    fails is dropped and counted in info["quote"]. Output text goes through redact_out; a redaction error drops the entry."""
    cands = extract_decisions(blocks, session, kinds)
    src = {session: source_text if source_text is not None else "\n".join(b["text"] for b in blocks)}
    tags, note = {}, ""
    if cands and model_fn:
        prompt, n = build_decision_prompt(cands)
        try:
            tags = parse_tags(model_fn(prompt, model), n, DECISION_TAGS)
        except Exception as e:      # model off or bad output: entries stay `unclear`, the ledger still gets them
            note = "model skipped: %s" % clean_text(type(e).__name__ + ": " + str(e), 160)
    elif cands:
        note = "no model: tags unclear"
    asks = [dict(c, text=c["text"]) for c in cands]
    rows, counts = verify(asks, tags, src, id_exists or (lambda i: True))
    out = []
    for r in rows:
        try:
            q = redact_out(r["text"], redact)
        except RedactionError:
            counts["quote"] += 1
            continue
        out.append({"date": r["ts"][:10], "session": session, "line": r["line"], "role": r["role"], "kind": r["kind"],
                    "quote": q, "ids": sorted(set(ANY_ID.findall(q))), "tag": r["tag"] if r["tag"] in DECISION_TAGS else "unclear"})
    return out, dict(counts, candidates=len(cands), note=note)


def ledger_path(exchange_home, date):
    return os.path.join(exchange_home, "ledger", "decisions", "%s.jsonl" % date[:7])


def write_ledger(exchange_home, entries):
    """Append entries to Exchange/ledger/decisions/<yyyy-mm>.jsonl (local file, 0600), skipping a (session, line, kind)
    already there, so a rerun adds nothing. -> number written."""
    by_month, n = {}, 0
    for e in entries:
        by_month.setdefault(e["date"][:7], []).append(e)
    for month, es in sorted(by_month.items()):
        p = ledger_path(exchange_home, month)
        os.makedirs(os.path.dirname(p), mode=0o700, exist_ok=True)
        have = set()
        try:
            with open(p, "r", encoding="utf-8") as f:
                for ln in f:
                    try:
                        d = json.loads(ln)
                        have.add((d.get("session"), d.get("line"), d.get("kind")))
                    except ValueError:
                        pass
        except OSError:
            pass
        fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(fd, "a", encoding="utf-8") as f:
            for e in es:
                k = (e["session"], e["line"], e["kind"])
                if k not in have:
                    have.add(k)
                    f.write(json.dumps(e, sort_keys=True) + "\n")
                    n += 1
    return n
