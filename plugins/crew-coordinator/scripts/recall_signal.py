#!/usr/bin/env python3
"""0.20.0 (D-b28d7 item d, envoy plan N-3a2e5 and addendum N-fcd4d): the recall-miss loop. Stdlib only.

Every harness_recall call appends one line to <home>/_harness/recall_stats.jsonl (a derived counter file, not the ledger):
{"t": epoch, "agent": id, "ids": n id requests, "q": query given, "search": bool, "sig": hash}. The weekly report counts these lines and the
`recall.miss` ledger events. A miss is written as a ledger event, kind one of:
  suspect     an id request with query= whose requested id is NOT among the top K=5 search hits for that query (fixed before the build)
  unresolved  an id request for an id that is not in the corpus
  repeat      the same agent repeats the same search (same words, filters, offset) within 10 minutes
  reported    the agent said the lookup missed (harness_admin op=recall_miss)
No-fire set: paging (other offset), query refinement (other words), two agents asking the same thing (the state is per agent), a correct id
with a query that ranks it in the top K. The detector is blind to an id request without query=: the report shows the query share."""
import calendar, hashlib, json, os, re, time

SUSPECT_K = 5
REPEAT_SECS = 600
STATS = "recall_stats.jsonl"
TAIL = 60000
KINDS = ("suspect", "unresolved", "repeat", "reported")


def words(q):
    return sorted({t for t in re.findall(r"[\w\-]+", (q or "").lower()) if len(t) > 1})


def sig(query, offset=0, kind=None, tags=None, project=None, concept=None, limit=None):
    """Same words, offset, filters AND page size: a bigger limit is a new request (critic M4), not a repeat."""
    raw = json.dumps([words(query), int(offset or 0), kind or "", sorted(map(str, tags or [])), project or "", concept or "", int(limit or 5)], sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()[:12]


def _path(d):
    return os.path.join(d, STATS)


def read_lines(d, tail=TAIL):
    """-> list of dict lines from the end of the stats file (a torn first line is skipped); [] if absent."""
    p = _path(d)
    try:
        with open(p, "rb") as f:
            f.seek(0, 2)
            n = f.tell()
            f.seek(max(0, n - tail))
            data = f.read()
    except OSError:
        return []
    out = []
    for ln in data.split(b"\n"):
        try:
            v = json.loads(ln)
        except ValueError:
            continue
        if isinstance(v, dict):
            out.append(v)
    return out


def repeated(d, agent, s, now=None):
    """True if `agent` made the same search (signature `s`) within REPEAT_SECS before now."""
    now = now or time.time()
    for v in reversed(read_lines(d)):
        if v.get("agent") == agent and v.get("sig") == s and v.get("search") and now - float(v.get("t") or 0) <= REPEAT_SECS:
            return True
    return False


def log(d, rec):
    """Append one stats line (a single O_APPEND write, no lock). Never raises."""
    try:
        os.makedirs(d, exist_ok=True)
        with open(_path(d), "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, sort_keys=True) + "\n")
    except OSError:
        pass


def week(t):
    return time.strftime("%G-W%V", time.gmtime(t))


def data(d, miss_events, weeks=1, now=None):
    """Weekly numbers: {"weeks": [{"week", "calls", "id_requests", "with_query", "searches", "old_asked", "miss": {kind: n}}], "top_missed": [{"id" or "query", "n"}]},
    newest week first. `miss_events` are the ledger's recall.miss events (dicts with ts, data). All zeros when nothing was counted."""
    now = now or time.time()
    keep = [week(now - 7 * 86400 * i) for i in range(max(1, min(int(weeks or 1), 12)))]
    by = {w: {"week": w, "calls": 0, "id_requests": 0, "with_query": 0, "searches": 0, "old_asked": 0, "miss": {k: 0 for k in KINDS}} for w in keep}
    for v in read_lines(d, tail=50_000_000):
        b = by.get(week(float(v.get("t") or 0)))
        if not b:
            continue
        b["calls"] += 1
        b["id_requests"] += int(v.get("ids") or 0)
        b["old_asked"] += int(v.get("old_asked") or 0)
        if v.get("ids") and v.get("q"):
            b["with_query"] += int(v["ids"])
        if v.get("search"):
            b["searches"] += 1
    top = {}
    for ev in miss_events:
        dd = ev.get("data") or {}
        try:
            w = week(calendar.timegm(time.strptime(str(ev.get("ts"))[:19], "%Y-%m-%dT%H:%M:%S")))
        except (ValueError, OverflowError):
            continue
        b = by.get(w)
        if not b:
            continue
        k = dd.get("kind")
        if k in b["miss"]:
            b["miss"][k] += 1
        for i in (dd.get("ids") or [])[:5]:
            top[("id", str(i))] = top.get(("id", str(i)), 0) + 1
        q = " ".join(words(dd.get("query")))[:80]
        if q:
            top[("query", q)] = top.get(("query", q), 0) + 1
    worst = sorted(top.items(), key=lambda x: (-x[1], x[0]))[:5]
    return {"weeks": [by[w] for w in keep], "top_missed": [{k[0]: k[1], "n": n} for k, n in worst]}


def report(d, miss_events, weeks=1, now=None):
    """The same numbers as text, for harness_admin op=recall_report and `harness.py recall-report`."""
    r = data(d, miss_events, weeks, now)
    lines = []
    for b in r["weeks"]:
        if not (b["calls"] or sum(b["miss"].values())):
            continue
        share = ("%d%%" % round(100 * b["with_query"] / b["id_requests"])) if b["id_requests"] else "n/a"
        lines.append(f"{b['week']}: {b['calls']} recall calls · {b['id_requests']} id requests, {share} with query= · {b['searches']} searches · "
                     f"{sum(b['miss'].values())} misses (" + ", ".join(f"{k} {b['miss'][k]}" for k in KINDS) + ")"
                     + (f" · {b['old_asked']} ids asked for on purpose after supersession/archive (not counted as misses)" if b["old_asked"] else ""))
    if not lines:
        lines = ["no recall calls counted in this window"]
    if r["top_missed"]:
        lines.append("missed most: " + "; ".join(f"{next(k for k in x if k != 'n')} {x[next(k for k in x if k != 'n')]} ×{x['n']}" for x in r["top_missed"]))
    return "\n".join(lines)
