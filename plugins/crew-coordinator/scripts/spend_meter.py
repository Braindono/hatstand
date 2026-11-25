"""spend_meter: 0.27.3 item 1. Counts the tokens a chat (unit) spends and writes one spend.sample event per sample into the ledger.
Depends on: stdlib only. Called from ctx_hook.main (hook side: sample) and Harness.ingest_spend_spool at sync (ledger side: ingest).
Counted tokens = input + output + cache_creation + cache_read of every distinct assistant message (a streamed message repeats its usage; the last copy wins).
The ctx gauge (ctx_hook._usage_n) is NOT changed: it still counts input and cache only; this meter adds the output tokens beside it.
quota_pct is always null: no local source for a quota percent exists, so none is invented (a value must come from the app, 0.27.3 changelog says so).
No transcript text is read into the sample: counts, a session id and a unit label only.
Interface: counts(usage) -> dict; sum_usage(path, since_line=0) -> (dict, last_line); sample(session_id, path, unit, state_file, spool_dir, now, every=600) -> line|None;
ingest(home, resolve_agent, append_fn) -> number appended. Spool: <home>/_harness/spend_spool.jsonl (claimed by atomic rename, like the mistake spool)."""
import json, os, re, time

KEYS = (("in", "input_tokens"), ("out", "output_tokens"), ("cw", "cache_creation_input_tokens"), ("cr", "cache_read_input_tokens"))
MAX_PER_SYNC = 200
_UNIT = re.compile(r"[^A-Za-z0-9 _.:-]")


def counts(usage):
    u = usage if isinstance(usage, dict) else {}
    out = {}
    for k, name in KEYS:
        try:
            out[k] = max(0, int(u.get(name) or 0))
        except (TypeError, ValueError):
            out[k] = 0
    return out


def total(c):
    return sum(c.get(k, 0) for k, _ in KEYS)


def sum_usage(path, since_line=0):
    """-> ({in,out,cw,cr}, last_line). Lines after since_line (1-based count already counted); one usage per message id (the last wins)."""
    per, anon, n = {}, [], 0
    with open(path, "rb") as f:
        for raw in f:
            n += 1
            if n <= since_line or b'"usage"' not in raw:
                continue
            try:
                j = json.loads(raw.decode("utf-8", "ignore"))
            except ValueError:
                continue
            msg = j.get("message") if isinstance(j, dict) else None
            if not isinstance(msg, dict) or not isinstance(msg.get("usage"), dict):
                continue
            c = counts(msg["usage"])
            if msg.get("id"):
                per[str(msg["id"])] = c
            else:
                anon.append(c)
    s = {k: 0 for k, _ in KEYS}
    for c in list(per.values()) + anon:
        for k in s:
            s[k] += c[k]
    return s, n


def _load(p):
    try:
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def sample(session_id, path, unit, state_file, spool_dir, now=None, every=600):
    """At most one sample per `every` seconds per chat. Writes the spool line and the new line offset; -> the line written or None. Never raises on a missing file."""
    now = time.time() if now is None else now
    st = _load(state_file)
    if now - float(st.get("t") or 0) < every or not path or "/subagents/" in str(path).replace("\\", "/"):
        return None
    try:
        c, last = sum_usage(path, int(st.get("line") or 0))
    except OSError:
        return None
    rec = None
    if total(c):
        rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(now)), "session_id": str(session_id or "")[:64],
               "unit": _UNIT.sub("", str(unit or "session"))[:60] or "session", "tokens": total(c), "in": c["in"], "out": c["out"],
               "cache_w": c["cw"], "cache_r": c["cr"], "quota_pct": None}
        os.makedirs(spool_dir, exist_ok=True)
        fd = os.open(os.path.join(spool_dir, "spend_spool.jsonl"), os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600)
        try:
            os.write(fd, (json.dumps(rec, sort_keys=True) + "\n").encode("utf-8"))
        finally:
            os.close(fd)
    tmp = state_file + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"t": now, "line": last}, f)
    os.replace(tmp, state_file)
    return rec


def ingest(home, resolve_agent, append_fn):
    """Spool lines become spend.sample events: append_fn(actor, data). resolve_agent(session_id) -> agent id or None (then actor is "system").
    The spool is claimed by rename, so a hook append during ingest lands in a fresh spool. A bad line is dropped; the rest past MAX_PER_SYNC waits."""
    base = os.path.join(home, "_harness")
    spool, claimed = os.path.join(base, "spend_spool.jsonl"), os.path.join(base, "spend_spool.claimed")
    if os.path.islink(spool) or os.path.islink(claimed):
        return 0
    if os.path.isfile(spool) and not os.path.exists(claimed):
        try:
            os.rename(spool, claimed)
        except OSError:
            return 0
    if not os.path.isfile(claimed):
        return 0
    with open(claimed, encoding="utf-8", errors="replace") as f:
        lines = f.read().splitlines()
    n, rest = 0, lines[MAX_PER_SYNC:]
    try:
        for ln in lines[:MAX_PER_SYNC]:
            try:
                r = json.loads(ln)
                data = {"session_id": str(r["session_id"])[:64], "unit": str(r["unit"])[:60], "tokens": int(r["tokens"]),
                        "in": int(r["in"]), "out": int(r["out"]), "cache_w": int(r["cache_w"]), "cache_r": int(r["cache_r"]), "quota_pct": None}
            except (ValueError, KeyError, TypeError):
                continue
            data["agent"] = resolve_agent(data["session_id"])
            append_fn(data["agent"] or "system", data)
            n += 1
    finally:
        if rest:
            fd = os.open(spool, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600)
            try:
                os.write(fd, "".join(l + "\n" for l in rest).encode("utf-8"))
            finally:
                os.close(fd)
        try:
            os.unlink(claimed)
        except OSError:
            pass
    return n
