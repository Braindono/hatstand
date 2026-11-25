#!/usr/bin/env python3
"""0.27.3 C2 (capture fix piece 6): distil sessions into the decision ledger before Claude Code expires them. Plain
script, no agent; the only model is vault.py's Haiku tagger (closed tag set), and only when --model is given.

`due(sessions, now, period)` -> sessions whose transcript is at least period-5 days old (25 of the default 30) and not yet
distilled. `run(...)` indexes (transcript_indexer, default-deny), distils each due REGISTERED session (vault.distill) into
Exchange/ledger/decisions/<yyyy-mm>.jsonl and records the last block line distilled per indexer file in
<exchange>/_harness/expiry_sweep.json; a later run on a session whose file changed distils only the new tail (the ledger also dedupes). Unregistered
sessions (not in the ledger's session.bound/agent.registered, not in <indexer root>/.allow) are counted and listed by id;
their content is never opened (only stat). `--dry-run` lists what is due and reads no transcript. The period is read live
each run from `cleanupPeriodDays` in the Claude settings file (default 30 when unset or bad). Not installed or loaded by
this release: docs/com.harness.expiry_sweep.plist is shipped as a file only. Compaction of distilled copies is not built.
Depends on: transcript_indexer, vault, vault_decisions, decision_rules. Usage: expiry_sweep.py [--dry-run] [--model haiku] [--exchange DIR]
"""
import argparse
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import transcript_indexer as TI  # noqa: E402
import vault as V                # noqa: E402
import vault_decisions as VD     # noqa: E402

DEFAULT_PERIOD = 30
MARGIN_DAYS = 5                  # day 25 of 30
DAY = 86400


def settings_path():
    return os.path.join(TI.home(), ".claude", "settings.json")


def read_period(path=None):
    """cleanupPeriodDays from the settings file, read now (never cached); 30 when unset, unreadable or not a positive int."""
    try:
        with open(path or settings_path(), "r", encoding="utf-8") as f:
            v = json.load(f).get("cleanupPeriodDays")
    except (OSError, ValueError, AttributeError):
        return DEFAULT_PERIOD
    return v if isinstance(v, int) and not isinstance(v, bool) and v > 0 else DEFAULT_PERIOD


def list_sessions(source):
    """{session_id: (path, mtime)} of *.jsonl under source. stat only; nothing is opened."""
    out = {}
    for dp, _d, files in os.walk(source):
        for fn in files:
            p = os.path.join(dp, fn)
            if fn.endswith(".jsonl") and not os.path.islink(p):
                try:
                    out[fn[:-6]] = (p, os.stat(p).st_mtime)
                except OSError:
                    pass
    return out


def due(sessions, now, period, done=()):
    """Session ids whose file is >= period-MARGIN_DAYS days old and not in `done`, oldest first."""
    cutoff = now - max(period - MARGIN_DAYS, 0) * DAY
    return [s for s, (_p, m) in sorted(sessions.items(), key=lambda kv: kv[1][1]) if m <= cutoff and s not in done]


def state_path(exchange):
    return os.path.join(exchange, "_harness", "expiry_sweep.json")


def load_state(exchange):
    try:
        with open(state_path(exchange), "r", encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def save_state(exchange, st):
    p = state_path(exchange)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(st, f, sort_keys=True)
    os.replace(tmp, p)


def run(exchange, source=None, root=None, cache=None, ledger=None, settings=None, now=None, dry_run=False,
        model_fn=None, model="haiku"):
    """-> {period, due, unregistered, distilled, entries, ...}. `ledger` is the exchange log path (or False: allow-list
    only). Registered = indexer's allowed(); everything else is listed, never read."""
    now = time.time() if now is None else now
    period = read_period(settings)
    sessions = list_sessions(source or TI.source_dir())
    st = load_state(exchange)
    unchanged = {k for k, v in st.items() if k in sessions and isinstance(v, dict) and v.get("mtime") == sessions[k][1]}
    due_ids = due(sessions, now, period, done=unchanged)
    root = root or TI.default_root()
    known = (set() if ledger is False else TI.ledger_sessions(ledger)) | TI.allow_list(root)   # no Indexer yet: a dry run creates nothing
    reg = [s for s in due_ids if s in known]
    unreg = [s for s in due_ids if s not in known]
    res = {"period": period, "dry_run": bool(dry_run), "due": reg, "unregistered": unreg, "unregistered_count": len(unreg),
           "distilled": [], "entries": 0, "dropped_quote": 0}
    if dry_run or not reg:
        return res
    ix = TI.Indexer(root=root, cache=cache, source=source, ledger=TI.exchange_log() if ledger is None else ledger)
    ix.once()                                   # default-deny stays: only allowed sessions are written
    files = V.session_files(ix.root, reg)
    for sid in reg:
        entries, got = [], False
        prev = st.get(sid, {}).get("lines") if isinstance(st.get(sid), dict) else None
        lines = dict(prev) if isinstance(prev, dict) else {}
        for p in files.get(sid, []):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    blocks, _priv = V.parse_indexer(f.read())
            except (V.RedactionError, OSError, UnicodeDecodeError):
                continue                        # fail closed: this file is skipped, the session stays due
            got = True
            key = os.path.basename(p)
            start = lines.get(key, 0) if isinstance(lines.get(key), int) else 0
            lines[key] = len(blocks)
            if start >= len(blocks):
                continue                        # nothing new since the last run
            es, info = VD.distill(blocks[start:], sid, model_fn=model_fn, model=model)
            for e in es:
                e["line"] += start              # block number in the whole file, so the ledger dedupe key is stable
            entries += es
            res["dropped_quote"] += info["quote"]
        if not got:
            continue
        res["entries"] += VD.write_ledger(exchange, entries)
        st[sid] = {"done": int(now), "mtime": sessions[sid][1], "lines": lines, "entries": len(entries)}
        res["distilled"].append(sid)
    save_state(exchange, st)
    return res


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--model", default="")
    ap.add_argument("--exchange", default=os.environ.get("HARNESS_HOME") or "")
    a = ap.parse_args(argv)
    if not a.exchange:
        print("expiry_sweep: set HARNESS_HOME or pass --exchange", file=sys.stderr)
        return 2
    fn = (lambda prompt, model: V.claude_cli(prompt, model)) if a.model else None
    print(json.dumps(run(a.exchange, dry_run=a.dry_run, model_fn=fn, model=a.model or "haiku"), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
