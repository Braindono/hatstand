"""change_feed.py (0.27.3 E, change awareness, interim): a no-model view of artifact.versioned events by shared resource.
What it does: maps each versioned file path to a resource (prefix match against <home>/_harness/resources.json), then
  (a) renders a generated change list (date | resource | summary | who, newest last) BESIDE the hand-written CHANGES.md
      (default <home>/CHANGES.generated.md; a target named CHANGES.md is refused, so the hand notes are never overwritten),
  (b) prints at most N one-line rows since a time (`since`), and
  (c) builds the single "Changed since you last looked" line the restore digest and sync show (`digest_line`).
Setup (one line, run once by hand, nothing runs at install): cp <plugin>/docs/resources.sample.json <home>/_harness/resources.json
Without that file every function returns nothing and costs nothing.
resources.json rows: {id, name, aliases[], owner, prefixes[], roles[]}; roles empty or ["*"] = every role. Paths are the ledger keys
("<workspace folder>/<relative path>"); a prefix matches the whole path or a path segment boundary. Longest prefix wins.
CLI: change_feed.py render [--home H] [--out FILE] | since <ISO|24h|2d|last_seen> [--home H] [--role R] [--agent ID] [--limit N]
Depends on: stdlib only. Events are read from <home>/_harness/events.jsonl (the harness passes records straight in)."""
import argparse, datetime, json, os, re, sys

CAP_ROWS = 5            # the digest line shows at most five resources
CAP_CHARS = 240         # about 60 tokens (chars / 4)
HAND_NOTES = "CHANGES.md"
GENERATED = "CHANGES.generated.md"


def resources_path(home):
    return os.path.join(home, "_harness", "resources.json")


def load_resources(home=None, path=None):
    """Rows of resources.json, or None when the file is absent or unreadable (callers then add nothing)."""
    p = path or resources_path(home)
    try:
        with open(p, "r", encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        return None
    rows = d.get("resources") if isinstance(d, dict) else d
    rows = [r for r in (rows or []) if isinstance(r, dict) and r.get("id")]
    return rows or None


def resource_for(path, rows):
    """The row whose longest prefix matches path (whole path or a segment boundary), else None."""
    best, blen = None, -1
    for r in rows or []:
        for pre in r.get("prefixes") or []:
            pre = str(pre).rstrip("/")
            if pre and (path == pre or path.startswith(pre + "/")) and len(pre) > blen:
                best, blen = r, len(pre)
    return best


def uses(row, role):
    """Does this role use the resource? Empty roles or '*' means every role; an unknown role sees only those."""
    roles = [str(x).strip().lower() for x in (row.get("roles") or [])]
    return not roles or "*" in roles or (role or "").strip().lower() in roles


def record_of(ev, name=lambda x: x):
    """A ledger artifact.versioned event as the flat record the rest of this file uses."""
    d = ev.get("data") or {}
    return {"path": d.get("path") or "", "ts": ev.get("ts") or "", "by": name(ev.get("actor")), "actor": ev.get("actor"),
            "note": d.get("note"), "version": d.get("version"), "source": d.get("source", "manual")}


def read_records(home):
    """Every artifact.versioned record in the ledger, oldest first, with agent names from agent.registered."""
    names, evs = {}, []
    try:
        with open(os.path.join(home, "_harness", "events.jsonl"), "r", encoding="utf-8") as f:
            for line in f:
                try:
                    ev = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(ev, dict):
                    continue
                if ev.get("type") == "agent.registered":
                    names[(ev.get("data") or {}).get("id")] = (ev.get("data") or {}).get("sobriquet")
                elif ev.get("type") == "artifact.versioned":
                    evs.append(ev)
    except OSError:
        return []
    return [record_of(e, lambda a: names.get(a) or (a or "")[:8]) for e in evs]


def _summary(notes):
    """The last note a person wrote; an auto-hook note ("auto: Edit") counts as no summary."""
    for n in reversed(notes):
        n = (n or "").strip()
        if n and not n.lower().startswith("auto:"):
            return n.replace("\n", " ")
    return "edited"


def rows(records, resources, since=None, role=None, exclude_by=None):
    """Grouped rows (date, resource id, who) in time order: {ts, date, id, name, by, n, summary}; unmapped paths group
    under id 'other' (counted, never dropped). since is an ISO string (kept: ts > since); role keeps mapped resources the
    role uses (and 'other' only when role is None); exclude_by is a set of agent ids to leave out."""
    groups, order = {}, []
    for r in sorted(records, key=lambda x: x["ts"]):
        if (since and r["ts"] <= since) or (exclude_by and r.get("actor") in exclude_by):
            continue
        res = resource_for(r["path"], resources)
        if role is not None and (res is None or not uses(res, role)):
            continue
        rid, rname = (res["id"], res.get("name") or res["id"]) if res else ("other", "other")
        k = (r["ts"][:10], rid, r["by"])
        if k not in groups:
            groups[k] = {"ts": r["ts"], "date": r["ts"][:10], "id": rid, "name": rname, "by": r["by"], "n": 0, "notes": []}
            order.append(k)
        g = groups[k]
        g["n"] += 1
        g["ts"] = r["ts"]
        g["notes"].append(r["note"])
    out = []
    for k in order:
        g = groups[k]
        g["summary"] = _summary(g.pop("notes"))
        out.append(g)
    return sorted(out, key=lambda g: g["ts"])


def row_line(g):
    return f"{g['date']} | {g['name']}{' x%d' % g['n'] if g['n'] > 1 else ''} | {g['summary'][:120]} | {g['by']}"


def render(records, resources):
    """The generated change list as text (newest last). Not the hand-written CHANGES.md."""
    rs = rows(records, resources)
    other = sum(g["n"] for g in rs if g["id"] == "other")
    head = ["# Generated change list (from artifact.versioned events; not the hand-written CHANGES.md)",
            "date | resource | summary | who", ""]
    return "\n".join(head + [row_line(g) for g in rs] + ["", f"other (unmapped paths): {other} edit(s)", ""])


def write_generated(home, out=None):
    """Write the generated list; refuses the hand-written file name. Returns the path, or None without resources.json."""
    res = load_resources(home)
    if res is None:
        return None
    out = out or os.path.join(home, GENERATED)
    if os.path.basename(out) == HAND_NOTES:
        raise ValueError(f"refusing to overwrite the hand-written {HAND_NOTES}; pick another file")
    with open(out, "w", encoding="utf-8") as f:
        f.write(render(read_records(home), res))
    return out


def digest_line(records, resources, role, since, exclude_by=None, max_rows=CAP_ROWS, max_chars=CAP_CHARS):
    """'Changed since you last looked: ...' or '' (no resources, no last-sync time, nothing changed). One line, resource
    names with a short summary, own edits left out, mapped resources the role uses only."""
    if not resources or not since:
        return ""
    rs = [g for g in rows(records, resources, since=since, role=role, exclude_by=exclude_by)]
    by_res = {}
    for g in rs:                       # one entry per resource, newest summary wins
        e = by_res.setdefault(g["id"], {"name": g["name"], "n": 0, "summary": ""})
        e["n"] += g["n"]
        e["summary"] = g["summary"]
    items = list(by_res.values())
    head = "Changed since you last looked: "
    parts = []
    for e in items[:max_rows]:
        s = e["summary"] if e["summary"] != "edited" else ""
        parts.append(e["name"] + (f" x{e['n']}" if e["n"] > 1 else "") + (f" ({s[:40]})" if s else ""))
    more = len(items) - len(parts)
    while parts and len(head + "; ".join(parts)) + (12 if more else 0) > max_chars:
        parts.pop()
        more += 1
    if not parts:
        return ""
    return head + "; ".join(parts) + (f"; +{more} more" if more else "")


def parse_since(text, now=None):
    """ISO time, or 30m / 24h / 2d relative to now; returns an ISO-Z string or None."""
    now = now or datetime.datetime.utcnow()
    m = re.fullmatch(r"(\d+)([mhd])", (text or "").strip())
    if m:
        delta = datetime.timedelta(**{{"m": "minutes", "h": "hours", "d": "days"}[m.group(2)]: int(m.group(1))})
        return (now - delta).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    return text if re.match(r"\d{4}-\d\d-\d\d", text or "") else None


def last_synced(home, agent_prefix):
    """ts of the newest agent.synced event whose actor starts with agent_prefix, else None."""
    ts = None
    try:
        with open(os.path.join(home, "_harness", "events.jsonl"), "r", encoding="utf-8") as f:
            for line in f:
                if '"agent.synced"' in line and agent_prefix in line:
                    try:
                        ev = json.loads(line)
                    except ValueError:
                        continue
                    if ev.get("type") == "agent.synced" and str(ev.get("actor", "")).startswith(agent_prefix):
                        ts = ev.get("ts")
    except OSError:
        return None
    return ts


def main(argv=None):
    ap = argparse.ArgumentParser(description="no-model change feed over artifact.versioned events")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("render")
    r.add_argument("--home", required=True)
    r.add_argument("--out")
    s = sub.add_parser("since")
    s.add_argument("when", help="ISO time, 24h, 2d, or last_seen (needs --agent)")
    s.add_argument("--home", required=True)
    s.add_argument("--role")
    s.add_argument("--agent", help="agent id (prefix) for last_seen")
    s.add_argument("--limit", type=int, default=10)
    a = ap.parse_args(argv)
    res = load_resources(a.home)
    if res is None:
        print("no resources.json at " + resources_path(a.home) + " (copy docs/resources.sample.json there)")
        return 0
    if a.cmd == "render":
        print(write_generated(a.home, a.out))
        return 0
    since = last_synced(a.home, a.agent) if a.when == "last_seen" and a.agent else parse_since(a.when)
    if not since:
        print("cannot read the time; use an ISO time, 24h, 2d, or last_seen with --agent")
        return 2
    for g in rows(read_records(a.home), res, since=since, role=a.role)[-a.limit:]:
        print(row_line(g))
    return 0


if __name__ == "__main__":
    sys.exit(main())
