"""/health: corpus weight and prune candidates (D-90088). Token weight; checks: superseded vs live,
age of live decisions (handoff generations), orphans. Pruning appends corpus.archived; log never rewritten."""
import glob
import html as _html
import json
import os
import re

from corpus import clean_text as _ct

IDRE = re.compile(r"\b[A-Z]-[0-9a-f]{5}\b")


def norm(p, aliases):
    p = (p or "").strip()
    if not p:
        return "(none)"
    if p.startswith("("):
        return p
    s = re.sub(r"[\s_]+", "-", p).lower()
    return aliases.get(p) or aliases.get(s) or s


def _cfg(h):
    try:
        return json.load(open(os.path.join(h.store.dir, "config.json")))
    except Exception:
        return {}


def health(h, project=None, agent=None):
    st = h.state()
    c = h.corpus
    c.refresh()
    cfg = _cfg(h)
    aliases, N = cfg.get("project_aliases") or {}, int(cfg.get("health_generations", 3))
    rows = [dict(zip([d[0] for d in cur.description], r)) for cur in [c.db.execute(
        "SELECT id,kind,title,body,tags,refs,supersedes,superseded_by,project,agent,agent_name,tokens,seq,source FROM entries")]
        for r in cur.fetchall()]
    # citations: other entries + newest handoff per project
    cited = {}
    fcited = c.foundation_cited()   # v2: ids cited in a foundation body are treated as pinned
    for r in rows:
        for i in set(IDRE.findall(" ".join([r["title"] or "", r["body"] or "", r["refs"] or "", r["supersedes"] or ""]))):
            if i != r["id"]:
                cited[i] = cited.get(i, 0) + 1
    for d in [os.path.join(p_, "handoffs") for p_ in h.project_dirs_map().values()]:
        fs = sorted(glob.glob(os.path.join(d, "*.md")), key=os.path.getmtime)
        if fs:
            for i in set(IDRE.findall(open(fs[-1], encoding="utf-8", errors="ignore").read())):
                cited[i] = cited.get(i, 0) + 1

    def gen(a):
        n, seen, cur = 0, set(), a
        while cur and cur not in seen:
            seen.add(cur)
            cur = (st.agents.get(cur) or {}).get("successor")
            n += 1 if cur else 0
        return n

    def infer(a):
        # blank entry project: author's current project, else nearest in its lineage (successors, then predecessors)
        for step in ("successor", "predecessor"):
            cur, seen = a, set()
            while cur and cur not in seen:
                seen.add(cur)
                p = (st.agents.get(cur) or {}).get("project")
                if p:
                    return p
                cur = (st.agents.get(cur) or {}).get(step)
        return ""

    out = []
    for r in rows:
        if not (r["project"] or "").strip() and r["agent"]:
            r["project"] = "(shared-docs)" if r["source"] == "file" else (infer(r["agent"]) or "(pre-project)")
        r["project"] = norm(r["project"], aliases)
        if project and r["project"] != norm(project, aliases):
            continue
        if agent and not (r["agent"] or "").startswith(agent) and (r["agent_name"] or "").lower() != agent.lower():
            continue
        r["live"] = not r["superseded_by"]
        r["archived"] = r["superseded_by"] == "archived"
        r["gen"] = gen(r["agent"]) if r["source"] == "log" else 0
        r["cites"] = cited.get(r["id"], 0)
        r["flag"] = ""
        if r["live"] and r["source"] == "log" and not r["cites"] and "pin" not in (r.get("tags") or "").split() \
                and r["id"] not in fcited:
            if r["kind"] == "decision" and r["gen"] >= N:
                r["flag"] = "old-decision"
            elif r["kind"] in ("capsule", "note") and r["gen"] >= 1:
                r["flag"] = "orphan"
        out.append(r)
    tok = lambda xs: sum(x["tokens"] or 0 for x in xs)
    live = [r for r in out if r["live"]]
    flagged = sorted([r for r in out if r["flag"]], key=lambda r: -(r["tokens"] or 0))
    agg = lambda key, xs: sorted(((k, tok([x for x in xs if x[key] == k])) for k in {x[key] for x in xs}), key=lambda t: -t[1])
    lt, ft = tok(live), tok(flagged)
    thr = max(int(cfg.get("health_min_tokens", 1500)), int(lt * float(cfg.get("health_ratio", 0.2))))
    # D-d01a5: per-project status = flagged tokens >= max(500, 0.2 x project live); same formula drives the size trigger
    pmin, pratio = int(cfg.get("prune_min_tokens", 500)), float(cfg.get("prune_ratio", 0.2))
    projects = []
    for p_ in sorted({r["project"] for r in out}):
        pl, pf = tok([r for r in live if r["project"] == p_]), tok([r for r in flagged if r["project"] == p_])
        pt = max(pmin, int(pl * pratio))
        projects.append({"project": p_, "live_tokens": pl, "flagged_tokens": pf, "threshold": pt,
                         "status": "▲" if pf >= pt else "●"})
    return {"scope": {"project": project, "agent": agent}, "entries": len(out), "live": len(live),
            "tokens": tok(out), "live_tokens": lt, "superseded_tokens": tok([r for r in out if not r["live"] and not r["archived"]]),
            "archived_tokens": tok([r for r in out if r["archived"]]),
            "by_kind": agg("kind", live), "by_project": agg("project", live), "by_agent": agg("agent_name", live),
            "flags": {f: [len([r for r in flagged if r["flag"] == f]), tok([r for r in flagged if r["flag"] == f])]
                      for f in ("old-decision", "orphan")},
            "flagged": [{k: r[k] for k in ("id", "kind", "flag", "tokens", "gen", "project", "agent_name", "title")} for r in flagged],
            "flagged_tokens": ft, "threshold": thr, "status": "▲" if ft >= thr else "●", "generations": N,
            "projects": projects, "over": [p_["project"] for p_ in projects if p_["status"] == "▲"],
            "approvals": _approvals(h), "corpus_index_pin": _ci_pin(h), "warnings": _cfg_warnings(h),
            "transcripts": _transcripts(h)}


def _cfg_warnings(h):
    """0.15.1 (P5): config entries that were ignored (outside the ceiling, wrong type), cleaned, surfaced once."""
    try:
        import harness as _hz
        return [_ct(w, 200) for w in _hz.path_config(h.home)["warnings"]]
    except Exception:
        return []


def _ci_pin(h):
    try:
        ok, msg, cur, pin = h.corpus_index_status()
        if ok:
            return {"ok": True, "line": "corpus_index.py pin ok"}
        bad = "script" if cur.get("sha") != pin.get("sha") else "rules"
        return {"ok": False, "line": f"corpus_index.py pin MISMATCH ({bad})"}
    except Exception as e:
        return {"ok": False, "line": f"corpus_index.py pin MISMATCH (script): {type(e).__name__}"}


def _transcripts(h):
    """0.16.2: the transcript indexer's status from its state file (counts and times only), or None if it never ran."""
    try:
        import time as _t
        p = os.path.join(os.environ.get("INDEXER_CACHE") or os.path.expanduser("~/.cache/harness-indexer"), "state.json")
        s = json.load(open(p, encoding="utf-8"))
        c = s.get("counters") or {}
        last = float(c.get("last_run") or 0)
        return {"files": len(s.get("files") or {}), "last_run_min": int((_t.time() - last) // 60) if last else None,
                "redaction_failures": int(c.get("dropped_error") or 0), "denied": int(c.get("denied") or 0),
                "bad_lines": int(c.get("bad_lines") or 0)}
    except Exception:
        return None


def _approvals(h):
    try:
        return h.approvals_summary()
    except Exception:
        return {"pending": 0, "granted": 0, "cli_tty": 0}


def k(n):
    return f"{n/1000:.1f}k" if n >= 1000 else str(n)


def text(d, top=8):
    j = lambda xs, n=5: " · ".join(f"{_ct(a, 60)} {k(b)}" for a, b in xs[:n])
    s = d["scope"]
    sc = " ".join(f"{a}={b}" for a, b in s.items() if b) or "all"
    L = [f"{d['status']} corpus {sc}: live {k(d['live_tokens'])} ({d['live']}/{d['entries']}) · superseded {k(d['superseded_tokens'])} · archived {k(d['archived_tokens'])}",
         f"kind: {j(d['by_kind'])}", f"project: {j(d['by_project'])}", f"agent: {j(d['by_agent'])}",
         f"flags: old-decision (≥{d['generations']} gen, uncited) {d['flags']['old-decision'][0]}/{k(d['flags']['old-decision'][1])} · "
         f"orphan {d['flags']['orphan'][0]}/{k(d['flags']['orphan'][1])} · threshold {k(d['threshold'])}"]
    ov = [p_ for p_ in d.get("projects", []) if p_["status"] == "▲"]
    L.append("projects ▲: " + (" · ".join(f"{p_['project']} {k(p_['flagged_tokens'])}/{k(p_['threshold'])}" for p_ in ov)
                               if ov else "none over max(500, 20% live)"))
    for r in d["flagged"][:top]:
        L.append(f"  {r['id']} {r['flag']} {r['tokens']}t g{r['gen']} {_ct(r['title'], 60)}")
    if len(d["flagged"]) > top:
        L.append(f"  … +{len(d['flagged']) - top} more (dashboard /health)")
    ap = d.get("approvals") or {}
    L.append(f"approvals: {ap.get('pending', 0)} pending, {ap.get('granted', 0)} granted (cli-tty {ap.get('cli_tty', 0)})")
    cp = d.get("corpus_index_pin") or {}
    if cp:
        L.append(("● " if cp.get("ok") else "▲ ") + cp["line"])
    tr = d.get("transcripts")
    if tr:    # 0.16.2: indexer status line
        late = tr["last_run_min"] is None or tr["last_run_min"] > 10
        L.append(("▲ " if late or tr["redaction_failures"] else "● ") + f"transcripts: {tr['files']} files · last run "
                 + ("never" if tr["last_run_min"] is None else f"{tr['last_run_min']} min ago")
                 + f" · redaction failures {tr['redaction_failures']} · denied sessions {tr['denied']} · bad lines {tr['bad_lines']}")
    for w in d.get("warnings") or []:
        L.append("▲ " + _ct(w, 200))
    if d["status"] == "▲":
        L.append("Do: run /prune (read-only report; /prune does the review)")
    if ap.get("pending"):
        L.append(f"▲ {ap['pending']} approval request(s): harness.py pending")
    return "\n".join(L)


def page(h, project=None, agent=None):
    d = health(h, project, agent)
    e = lambda x: _html.escape(str(x))
    bars = lambda xs: "".join(
        f'<tr><td>{e(a)}</td><td class="n">{k(b)}</td><td><div class="bar" style="width:{100*b/max(1,xs[0][1]):.0f}%"></div></td></tr>'
        for a, b in xs[:8])
    rows = "".join(f'<tr><td><input type="checkbox" name="id" value="{e(r["id"])}"></td><td>{e(r["id"])}</td><td>{e(r["flag"])}</td>'
                   f'<td class="n">{r["tokens"]}</td><td>g{r["gen"]}</td><td>{e(_ct(r["project"], 60))}</td><td>{e(_ct(r["title"], 200))}</td></tr>'
                   for r in d["flagged"])
    css = ("body{font:14px/1.45 system-ui;margin:24px;background:#fff;color:#1b1b1b}@media(prefers-color-scheme:dark){body{background:#161616;color:#ececec}}"
           "table{border-collapse:collapse;margin:0 0 20px;width:100%}td,th{padding:4px 8px;border-bottom:1px solid #8883;text-align:left}"
           ".n{text-align:right;font-variant-numeric:tabular-nums}.bar{height:10px;background:#4a7bd0;border-radius:2px;min-width:2px}"
           "h2{font-size:15px;margin:18px 0 6px}section{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:16px}")
    return (f"<!doctype html><meta charset=utf-8><title>Corpus health</title><style>{css}</style>"
            f"<h1>{d['status']} Corpus health</h1><p>Live {k(d['live_tokens'])} tokens in {d['live']}/{d['entries']} entries · superseded {k(d['superseded_tokens'])} · "
            f"archived {k(d['archived_tokens'])} · flagged {k(d['flagged_tokens'])} (threshold {k(d['threshold'])})</p>"
            f"<section><div><h2>By kind</h2><table>{bars(d['by_kind'])}</table></div><div><h2>By project</h2><table>{bars(d['by_project'])}</table></div>"
            f"<div><h2>By agent</h2><table>{bars(d['by_agent'])}</table></div></section>"
            f"<h2>Prune candidates</h2><form method=post action=/api/archive><table><tr><th></th><th>id</th><th>flag</th><th>tokens</th><th>gen</th><th>project</th><th>title</th></tr>{rows}</table>"
            f"<input name=reason placeholder='reason: quote the rule line in \"…\"' style='width:40%'> <button>Archive selected</button> <button formaction=/api/pin>Pin selected</button></form>"
            "<script>document.querySelectorAll('form').forEach(f=>f.addEventListener('submit',async ev=>{ev.preventDefault();"
            "const m=document.querySelector('meta[name=csrf-token]');const u=(ev.submitter&&ev.submitter.formAction)||f.action;"
            "const r=await fetch(u,{method:'POST',headers:{'X-CSRF-Token':m?m.content:'','Content-Type':'application/x-www-form-urlencoded'},"
            "body:new URLSearchParams(new FormData(f)).toString()});if(r.ok)location.reload();else alert('refused: '+r.status);}));</script>")
