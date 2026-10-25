#!/usr/bin/env python3
"""Live-ledger metrics (cc 0.17.0 stage 0): the measuring core of C-live (tests/c_live.py) and the weekly report.
Read-only on the live Exchange.

It copies the ledger, config and markdown of the live home into a temp folder and measures there, because building a
Harness writes files (init_home) and restore_digest writes read marks. Caches and hook state also go to the temp folder.

Per defined role: unread mail of the holder, owed replies (uncapped, as the restore digest counts them), restore-digest
size (estimated tokens, total and above the inline capsule), pinned decisions visible in the digest of those pinned in
the role's project. Corpus: entry count, pinned decisions, and for 5 fixed recall queries the uncapped match count and
the top-5 ids.

ab() measures ONE snapshot with two code trees (each in its own process: `python3 live_metrics.py --measure-copy HOME
--scripts DIR`), so a difference comes from the code alone and not from live mail traffic."""
import argparse, json, os, re, shutil, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
ENV_KEYS = ("HARNESS_HOME", "HARNESS_CACHE", "HARNESS_STATE_DIR", "HARNESS_STATE_CACHE")

# Fixed queries: change them only together with a new baseline (the diff compares by query text).
QUERIES = ("restore digest", "context window handoff", "prune archive corpus", "release scope publish", "operator preference")
COPY_EXT = (".md", ".txt", ".json", ".jsonl")
SKIP_DIRS = {"_archive", "node_modules", ".git", "__pycache__"}
SEARCH_CAP = 100   # Corpus.search clamps limit to 100; a count of 100 means "100 or more"
DEC_ID = re.compile(r"\b[A-Z]-[0-9a-f]{5}\b")


def _keep(dirpath, names):
    """copytree ignore: skip heavy or archived folders and every file that is not text the harness reads."""
    out = []
    for n in names:
        p = os.path.join(dirpath, n)
        if os.path.islink(p):
            out.append(n)
        elif os.path.isdir(p):
            if n in SKIP_DIRS:
                out.append(n)
        elif not n.lower().endswith(COPY_EXT) and n not in ("ignore", "events.lock"):
            out.append(n)
    return out


def snapshot_home(live, dst):
    """Copy what the harness reads (ledger, config, ignore, markdown) from `live` into `dst`. Read-only on `live`."""
    live = os.path.realpath(live)
    os.makedirs(dst, exist_ok=True)
    for n in sorted(os.listdir(live)):
        src = os.path.join(live, n)
        if n in SKIP_DIRS or os.path.islink(src):
            continue
        if os.path.isdir(src):
            shutil.copytree(src, os.path.join(dst, n), ignore=_keep, symlinks=False)
        elif n.lower().endswith(COPY_EXT):
            shutil.copy2(src, os.path.join(dst, n))
    return dst


def _owed(st, aid, role):
    """The restore digest's 'Owes reply' rule, uncapped (doorbell.owed_replies keeps only the newest 8)."""
    mine = set(st.lineage(aid))
    n = 0
    for mid in st.order:
        m = st.messages[mid]
        if m["from"] in mine:
            continue
        if not (mine & set(m.get("to_resolved", [])) or f"role:{role}" in m["to"]):
            continue
        if not (m["kind"] in ("task", "question", "review") or m.get("expects_reply")):
            continue
        if (st.tasks.get(mid) or {}).get("state") in ("completed", "failed", "canceled", "rejected"):
            continue
        if any(st.messages[x]["from"] in mine and st.messages[x]["seq"] > m["seq"] for x in st.threads[m["thread"]]["messages"]):
            continue
        n += 1
    return n


def measure(home, scripts=None):
    """Metrics for the home at `home` (must already be a disposable copy: restore_digest writes read marks). `scripts`:
    the code tree to measure with; it must be the first harness imported in this process (ab() uses one process each)."""
    sys.path.insert(0, os.path.abspath(scripts or HERE))
    import harness as H
    from corpus import est_tokens
    h = H.Harness(home)
    st = h.state()
    c = h.corpus
    pinned = {r["id"] for r in c.search(None, limit=SEARCH_CAP, kind="decision", tags=["pin"])}
    roles = {}
    for role in sorted(st.roles):
        R = st.roles[role]
        aid = st.role_holder(role) or (st.current(R["holder"]) if R.get("holder") else None)
        row = {"project": H.norm_project(R.get("project")) or None, "holder": (st.agents.get(aid) or {}).get("sobriquet") if aid else None,
               "live": bool(st.role_holder(role))}
        if not aid or aid not in st.agents:
            roles[role] = row
            continue
        row["unread"] = len(h._inbox_ids(st, aid, unread_only=True))
        row["owed"] = _owed(st, aid, role)
        try:
            dg = h.restore_digest(st, aid, role, [])
        except Exception as e:   # one broken role never hides the others
            row["digest_error"] = f"{type(e).__name__}: {e}"[:200]
            roles[role] = row
            continue
        head = dg.split("▸ Latest capsule")[0]
        dec = dg.split("▸ Decisions in force")[1].split("\n▸ ")[0] if "▸ Decisions in force" in dg else ""
        row.update(digest_chars=len(dg), digest_tokens=est_tokens(dg), digest_head_tokens=est_tokens(head),
                   digest_cut="[digest cut at restore_budget]" in head,
                   pinned_visible=len(set(DEC_ID.findall(dec)) & pinned))
        roles[role] = row
    for row in roles.values():
        if "pinned_visible" in row:
            row["pinned_in_project"] = len({r["id"] for r in c.search(None, limit=SEARCH_CAP, kind="decision", tags=["pin"],
                                                                      project=row["project"])}) if row["project"] else 0
    # 0.17.0 (R-055): tokens of a standard /refresh per role: the SECOND sync with do_only (the first records this
    # process's baseline) plus an inbox call that marks nothing read. Runs after the digests (sync appends events).
    for role, row in roles.items():
        R = st.roles.get(role) or {}
        aid = st.role_holder(role) or (st.current(R["holder"]) if R.get("holder") else None)
        if not aid or aid not in st.agents or "digest_tokens" not in row:
            continue
        try:
            h.sync(aid, do_only=True)
            s2 = h.sync(aid, do_only=True)["text"]
            ib = h.inbox(aid, mark_read=False)["text"]
            row.update(refresh_sync_tokens=est_tokens(s2), refresh_tokens=est_tokens(s2) + est_tokens(ib))
        except Exception as e:
            row["refresh_error"] = f"{type(e).__name__}: {e}"[:200]
    recall = {q: {"matches": _matches(c, q), "top5": [r["id"] for r in c.search(q, limit=5)]} for q in QUERIES}
    return {"c_live": 1, "taken": time.strftime("%Y-%m-%dT%H:%M:%S"), "ledger_seq": st.last_seq,
            "agents": len(st.agents), "messages": len(st.order), "roles": roles,
            "corpus": {"entries": c.count(), "pinned_decisions": len(pinned), "pinned_capped": len(pinned) >= SEARCH_CAP,
                       "recall": recall}}


def _matches(c, q):
    """Uncapped number of live entries recall's search matches for `q` (same OR-of-terms rule as Corpus.search)."""
    from corpus import FTS5
    terms = [t for t in re.findall(r"[\w\-]+", q.lower()) if len(t) > 1]
    w, a = c._filters()
    where = (" AND " + " AND ".join(w)) if w else ""
    if FTS5:
        match = " OR ".join('"' + t.replace('"', "") + '"' for t in terms)
        return c.db.execute(f"SELECT COUNT(*) FROM fts JOIN entries e ON e.id=fts.id WHERE fts MATCH ?{where}", [match] + a).fetchone()[0]
    rows = c.db.execute(f"SELECT lower(e.title||' '||e.tags||' '||e.body) FROM entries e WHERE 1=1{where}", a).fetchall()
    return sum(1 for (txt,) in rows if any(t in txt for t in terms))


def run(live_home, out=None, keep=False, scripts=None):
    tmp = tempfile.mkdtemp(prefix="c-live-")
    saved = {k: os.environ.get(k) for k in ENV_KEYS}
    try:
        home = snapshot_home(live_home, os.path.join(tmp, "Exchange"))
        os.environ.update(HARNESS_HOME=home, HARNESS_CACHE=os.path.join(tmp, "cache"),
                          HARNESS_STATE_DIR=os.path.join(tmp, "state"), HARNESS_STATE_CACHE="0")
        res = measure(home, scripts)
        res["source"] = os.path.realpath(live_home)
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        if not keep:
            shutil.rmtree(tmp, True)
    if out:
        os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
        with open(out, "w", encoding="utf-8") as f:
            json.dump(res, f, indent=1, sort_keys=True)
    return res


def _role_int(v, role):
    if isinstance(v, dict):
        v = v.get(role, v.get("*"))
    return v if isinstance(v, int) and not isinstance(v, bool) and v > 0 else None


def ceiling_for(cfg, role, old_tokens=None):
    """0.17.0 (P-2.9, rule A): the role's digest ceiling. The operator's digest_ceiling_tokens (int, or role -> int with
    "*") when set; else old_tokens x digest_growth_max (rounded up) when an old-tree figure from the same snapshot is
    given. Then capped by digest_caps[role] and restore_budget (above the budget the digest is cut, so a higher ceiling
    could never trip). None when nothing applies."""
    import math
    c = _role_int(cfg.get("digest_ceiling_tokens"), role)
    if c is None and isinstance(old_tokens, int) and old_tokens > 0:
        try:
            g = float(cfg.get("digest_growth_max", 1.2) or 1.2)
        except (TypeError, ValueError):
            g = 1.2
        c = math.ceil(old_tokens * max(1.0, g))
    caps = [x for x in (c, _role_int(cfg.get("digest_caps"), role)) if x]
    try:
        budget = int(cfg.get("restore_budget", 2000) or 2000)
    except (TypeError, ValueError):
        budget = 2000
    return min(caps + [budget]) if caps else budget


def ceiling_check(res, cfg, old=None):
    """-> {"roles": {role: {tokens, old, ceiling, cut}}, "breaches": [role, ...]}. `old`: the old tree's result on the
    same snapshot (rule A). A breach: tokens above the ceiling, or the digest was cut at restore_budget."""
    out, br = {}, []
    for role, row in sorted((res.get("roles") or {}).items()):
        if "digest_head_tokens" not in row:
            continue
        o = ((old or {}).get("roles") or {}).get(role, {}).get("digest_head_tokens")
        c = ceiling_for(cfg, role, o)
        e = {"tokens": row["digest_head_tokens"], "old": o, "ceiling": c, "cut": bool(row.get("digest_cut"))}
        out[role] = e
        if e["cut"] or (c is not None and e["tokens"] > c):
            br.append(role)
    return {"roles": out, "breaches": br}


def ab(live_home, old_scripts, new_scripts, out=None):
    """One snapshot of `live_home`, copied twice, measured once by each code tree in its own process.
    -> {"old": res, "new": res, "diff": [[key, old, new], ...]}"""
    import subprocess
    tmp = tempfile.mkdtemp(prefix="c-live-ab-")
    try:
        snap = snapshot_home(live_home, os.path.join(tmp, "snap"))
        res = {}
        for side, scripts in (("old", old_scripts), ("new", new_scripts)):
            home = os.path.join(tmp, side, "Exchange")
            shutil.copytree(snap, home)
            env = {k: v for k, v in os.environ.items() if k not in ENV_KEYS}
            env.update(PYTHONDONTWRITEBYTECODE="1", HARNESS_HOME=home,
                       HARNESS_CACHE=os.path.join(tmp, side, "cache"), HARNESS_STATE_DIR=os.path.join(tmp, side, "state"),
                       HARNESS_STATE_CACHE="0")
            r = subprocess.run([sys.executable, "-B", os.path.abspath(__file__), "--measure-copy", home,
                                "--scripts", os.path.abspath(scripts)], env=env,
                               capture_output=True, text=True, timeout=600)
            if r.returncode != 0:
                raise RuntimeError(f"{side} tree failed: {r.stderr.strip()[-400:]}")
            res[side] = json.loads(r.stdout)
            res[side].update(source=os.path.realpath(live_home), scripts=os.path.abspath(scripts))
    finally:
        shutil.rmtree(tmp, True)
    out_d = {"old": res["old"], "new": res["new"], "diff": [list(x) for x in diff(res["old"], res["new"], ignore=("taken", "source", "scripts"))]}
    if out:
        os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
        with open(out, "w", encoding="utf-8") as f:
            json.dump(out_d, f, indent=1, sort_keys=True)
    return out_d


def _flat(d, pre=""):
    out = {}
    for k, v in d.items():
        key = f"{pre}{k}"
        if isinstance(v, dict):
            out.update(_flat(v, key + "."))
        else:
            out[key] = v
    return out


def diff(a, b, ignore=("taken", "source", "ledger_seq", "agents", "messages")):
    """[(key, old, new)] for every metric that differs; context keys in `ignore` are reported but never count."""
    fa, fb = _flat(a), _flat(b)
    return [(k, fa.get(k), fb.get(k)) for k in sorted(set(fa) | set(fb))
            if fa.get(k) != fb.get(k) and k.split(".")[0] not in ignore]


def table(res):
    lines = [f"C-live {res['taken']} seq {res['ledger_seq']} · agents {res['agents']} · messages {res['messages']}",
             f"{'role':28} {'holder':18} {'unread':>6} {'owed':>5} {'dig_t':>6} {'head_t':>6} {'pins':>7}"]
    for r, v in res["roles"].items():
        lines.append(f"{r[:28]:28} {(v.get('holder') or '-')[:18]:18} {v.get('unread', '-'):>6} {v.get('owed', '-'):>5} "
                     f"{v.get('digest_tokens', '-'):>6} {v.get('digest_head_tokens', '-'):>6} "
                     f"{str(v.get('pinned_visible', '-')) + '/' + str(v.get('pinned_in_project', '-')):>7}"
                     + (f"  ERR {v['digest_error']}" if v.get("digest_error") else ""))
    cp = res["corpus"]
    lines.append(f"corpus entries {cp['entries']} · pinned decisions {cp['pinned_decisions']}{'+' if cp['pinned_capped'] else ''}")
    lines += [f"recall '{q}': {r['matches']} matches · top5 {' '.join(r['top5'])}" for q, r in cp["recall"].items()]
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description="live-ledger metrics (internal entry point of C-live's A/B mode)")
    ap.add_argument("--measure-copy", required=True, help="an already-copied, disposable home")
    ap.add_argument("--scripts", help="code tree to measure with (default: this folder)")
    a = ap.parse_args(argv)
    print(json.dumps(measure(a.measure_copy, a.scripts)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
