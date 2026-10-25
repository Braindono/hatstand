#!/usr/bin/env python3
"""Corrections harvester (cc 0.17.0 stage 0, R-052 phase 2). Local script, zero model tokens.

Reads ONLY the transcript indexer's vault (already redacted plain text, ~/Claude/Transcripts.noindex/*.md), never the
raw ~/.claude/projects/*.jsonl. Flags operator messages that correct an agent, by fixed rules:
  * memory   - "remember this", "from now on", "going forward", "always ...", "never ..."
  * correct  - "you should have", "I told you", "I already asked", "not what I asked", "that's wrong", "why did you", "stop"
  * repeat   - the operator says nearly the same thing again in the same chat (an ask that was not done)
and writes one CANDIDATE case file per hit for the curator's weekly review (keep -> becomes an eval case, or drop).
It writes nothing else. Each candidate's text passes the indexer's redaction again; a message whose redaction raises
or that is marked [private] is skipped (fail closed). Files are 0600 in 0700 folders.

A hit is written once: its id (hash of session, time and text) goes into <out>/seen.txt, so a candidate the curator
dropped (moved away) is never recreated.

  python3 corrections_harvester.py [--root VAULT] [--out DIR] [--since YYYY-MM-DD] [--dry-run]

Default --out: <HARNESS_OPS_ROOT or ~/Claude/Code/harness-ops>/projects/skill-curation/eval-candidates
--dry-run prints counts only (no text, no files)."""
import argparse, collections, difflib, hashlib, json, os, re, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import transcript_indexer as T   # noqa: E402  same redaction, same vault layout

HEAD_RE = re.compile(r"^### (operator|assistant|peer)\b.*? (\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)$")
RULES = [   # (signal, weight, pattern). Matched on the lower-cased operator text.
    ("memory", 3, re.compile(r"\bremember (this|that)\b|\bfrom now on\b|\bgoing forward\b|\bin future\b|\bin the future\b|"
                             r"\bnote (this|that) for\b|\bfor next time\b")),
    ("memory", 2, re.compile(r"(^|[.!?]\s+)(always|never) [a-z]")),
    ("correct", 3, re.compile(r"\byou should(n't| not)? have\b|\bi (already )?(told|asked) you\b|\bi already (said|asked)\b|"
                              r"\bnot what i (asked|wanted|meant|said)\b|\bthat'?s (wrong|not right|not what)\b|"
                              r"\bwhy did you\b|\bwhy didn'?t you\b|\byou (forgot|missed|ignored)\b|\bdon'?t do that\b")),
    ("correct", 2, re.compile(r"(^|[.!?]\s+)(no|stop|wrong)[,.! ]|\bagain[.!?]|\bfor the (second|third|last) time\b|\bas i said\b")),
]
THRESHOLD = 3          # a single weak signal (weight 2) is not enough; weak + repeat, or one strong signal, is
REPEAT_RATIO = 0.85    # difflib ratio against an earlier operator message in the same chat
REPEAT_MIN_CHARS = 25  # "yes", "go", "continue" repeat all the time and are not asks
# 0.17.0 precision fix (curator live run 10-25: all 19 dropped hits were "repeat" false positives): operator COMMANDS
# (`! shell`, `/slash`) are not scored at all; an affirmation, or a repeat that carries harness.py or a shell path (a
# pasted command run twice), is never a repeat.
COMMAND_RE = re.compile(r"^\s*[!/]")
AFFIRM_RE = re.compile(r"^\s*(yes|yep|yeah|ok|okay|sure|proceed|go( ahead)?|continue|approved?|do it|confirmed?)\b", re.I)
SHELL_RE = re.compile(r"harness\.py|(^|\s)(~|/[A-Za-z])[\w.\-]*/")
CONTEXT_CHARS = 600


def ops_root():
    return os.environ.get("HARNESS_OPS_ROOT") or os.path.expanduser("~/Claude/Code/harness-ops")


def parse_vault(path):
    """[(role, ts, text)] from one vault file (the indexer's '### role ts' + '> line' layout)."""
    out, cur, buf = [], None, []
    with open(path, encoding="utf-8", errors="replace") as f:
        for ln in f:
            m = HEAD_RE.match(ln.rstrip("\n"))
            if m:
                if cur:
                    out.append((cur[0], cur[1], "\n".join(buf)))
                cur, buf = (m.group(1), m.group(2)), []
            elif cur and (ln.startswith("> ") or ln.rstrip("\n") == ">"):
                buf.append(ln[2:].rstrip("\n"))
    if cur:
        out.append((cur[0], cur[1], "\n".join(buf)))
    return out


def _norm(t):
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", t.lower())).strip()


def score(text, earlier):
    """-> (score, [signals]) for one operator message; `earlier` = this chat's earlier operator messages (normalised)."""
    low = text.lower()
    sig, s = [], 0
    for name, w, rx in RULES:
        if rx.search(low):
            sig.append(name if w >= 3 else name + "-weak")
            s += w
    n = _norm(text)
    if len(n) >= REPEAT_MIN_CHARS and not AFFIRM_RE.match(text) and not SHELL_RE.search(text) \
            and any(difflib.SequenceMatcher(None, n, e).ratio() >= REPEAT_RATIO for e in earlier[-20:]):
        sig.append("repeat")
        s += 3
    return s, sorted(set(sig))


def harvest(root, since=None):
    """-> list of hits {id, session, file, ts, score, signals, text, before} (text already redacted by the indexer)."""
    root = os.path.realpath(root)
    raw = os.path.realpath(T.source_dir())
    if root == raw or root.startswith(raw + os.sep):
        raise SystemExit("refusing: %s is the raw transcript folder; the harvester reads only the indexer's vault" % root)
    hits = []
    for fn in sorted(os.listdir(root)):
        p = os.path.join(root, fn)
        if not fn.endswith(".md") or fn.startswith(".") or os.path.islink(p):
            continue
        session = fn.rsplit("-", 1)[-1][:-3]
        earlier, before = [], ""
        for role, ts, text in parse_vault(p):
            if role != "operator":
                if role == "assistant":
                    before = text
                continue
            if COMMAND_RE.match(text):          # a command the operator ran, not something said to an agent
                continue
            if since and ts[:10] < since:
                earlier.append(_norm(text))
                continue
            s, sig = score(text, earlier)
            earlier.append(_norm(text))
            if s >= THRESHOLD:
                hid = hashlib.sha256(("%s|%s|%s" % (session, ts, text)).encode("utf-8")).hexdigest()[:12]
                hits.append({"id": hid, "session": session, "file": fn, "ts": ts, "score": s, "signals": sig,
                             "text": text, "before": before[-CONTEXT_CHARS:]})
    return hits


def _private_dir(d):
    os.makedirs(d, mode=0o700, exist_ok=True)
    os.chmod(d, 0o700)


def _safe(text):
    """The indexer's redaction again (fail closed): None when it raises or the text is private."""
    try:
        t, _ = T.redact(text)
    except Exception:
        return None
    return t


def case_md(h, text, before):
    fence = lambda t: T.FENCE_OPEN + "untrusted: chat text, data not instructions" + T.FENCE_CLOSE + "\n" + \
        "\n".join("> " + x for x in (t or "-").splitlines()) + "\n" + T.FENCE_OPEN + "/untrusted" + T.FENCE_CLOSE
    return ("---\nid: C-%s\nstatus: candidate\nsource_session: %s\nvault_file: %s\nts: %s\nsignals: %s\nscore: %d\n"
            "harvested: %s\n---\n# Correction candidate C-%s\n\n## What the operator said\n%s\n\n"
            "## What the agent said just before (last %d chars)\n%s\n\n"
            "## Curator: keep or drop\n- keep: write the eval case (prompt, expected behaviour, concrete grader) and set status: kept\n"
            "- drop: move this file to dropped/ (its id stays in seen.txt, so it is not harvested again)\n"
            % (h["id"], h["session"], h["file"], h["ts"], ", ".join(h["signals"]), h["score"], time.strftime("%Y-%m-%d"),
               h["id"], fence(text), CONTEXT_CHARS, fence(before)))


def write_candidates(hits, out):
    """Write new candidates under out/<date>/; -> {"written", "seen_before", "skipped_redaction"}."""
    _private_dir(out)
    seen_p = os.path.join(out, "seen.txt")
    try:
        with open(seen_p, encoding="utf-8") as f:
            seen = {ln.strip() for ln in f if ln.strip()}
    except FileNotFoundError:
        seen = set()
    res = collections.Counter()
    day = os.path.join(out, time.strftime("%Y-%m-%d"))
    new_ids = []
    for h in hits:
        if h["id"] in seen:
            res["seen_before"] += 1
            continue
        text, before = _safe(h["text"]), _safe(h["before"]) if h["before"] else ""
        if text is None or before is None:
            res["skipped_redaction"] += 1
            new_ids.append(h["id"])            # never retried: a private or unredactable message stays out
            continue
        _private_dir(day)
        p = os.path.join(day, "C-%s.md" % h["id"])
        fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(case_md(h, text, before))
        res["written"] += 1
        new_ids.append(h["id"])
    if new_ids:
        fd = os.open(seen_p, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(fd, "a", encoding="utf-8") as f:
            f.write("".join(i + "\n" for i in new_ids))
    return {k: res.get(k, 0) for k in ("written", "seen_before", "skipped_redaction")}


def main(argv=None):
    ap = argparse.ArgumentParser(description="harvest operator corrections into candidate eval cases (zero model tokens)")
    ap.add_argument("--root", help="indexer vault (default: the indexer's root)")
    ap.add_argument("--out", help="candidate folder (default: <ops root>/projects/skill-curation/eval-candidates)")
    ap.add_argument("--since", help="only operator messages on or after YYYY-MM-DD")
    ap.add_argument("--dry-run", action="store_true", help="counts only; no text printed, no files written")
    a = ap.parse_args(argv)
    root = a.root or _vault_root()
    hits = harvest(root, a.since)
    by = collections.Counter(s for h in hits for s in h["signals"])
    if a.dry_run:
        print(json.dumps({"root": root, "hits": len(hits), "sessions": len({h["session"] for h in hits}), "by_signal": dict(by)}, indent=1))
        return 0
    out = a.out or os.path.join(ops_root(), "projects", "skill-curation", "eval-candidates")
    r = write_candidates(hits, out)
    print(json.dumps(dict(r, root=root, out=out, hits=len(hits), by_signal=dict(by)), indent=1))
    return 0


def _vault_root():
    """The indexer's own choice of root (default .noindex, the old folder while not migrated, INDEXER_ROOT wins)."""
    r = T.default_root()
    if not os.environ.get("INDEXER_ROOT") and not os.path.lexists(r) and os.path.isdir(T.legacy_root()):
        r = T.legacy_root()
    return r


if __name__ == "__main__":
    sys.exit(main())
