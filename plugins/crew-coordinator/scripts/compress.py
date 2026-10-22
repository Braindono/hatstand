"""/compress: corpus compression, deterministic half (cc 0.15.5, WP5). Spec: 2026-10-15-compress-cc0155.md v2.

Judgment stays with agents; this module does what must not depend on judgment:
  start     inventory + chunk plan + worker spec + restore-questions pin, DRY-RUN report (default; writes only under
            <project>/compress/<run>/, plus the ledger event)
  snapshot  full copy of the project corpus to <project>/_archive/snapshots/<ts>/ with manifest + sha (required before apply)
  propose   validate a worker's proposal file (sources exist, quoted text verbatim at the cited lines) -> proof hash
  review    record accept/edit/reject per candidate by role (project lead and envoy)
  apply     pin first, then archive: needs a snapshot, a matching dry-run fingerprint, an unchanged restore-questions.md,
            both reviews, caller with the curation roles. Moves files to _archive/compressed/<run>/, never deletes.
  verify    deterministic grading of a fresh agent's answers against restore-questions.md (cites + expected text)
  restore   put the snapshot's files back and archive the records the run created
  lint      the steward checks: restore-questions.md exists, sha matches the run pin, every cited rule id resolves
Nothing here edits rules/ or pins by itself: tune() only writes a proposal file in the run folder."""
import hashlib
import json
import os
import re
import shutil
import time

EXT = (".md", ".txt", ".yaml", ".yml")
SKIP_DIRS = ("_archive", "compress", "__pycache__", ".git")
SKIP_SUFFIX = ("-build", "-stage", "-accepted")
CHUNK_TOKENS = 6000
SNAP_KEEP = 3
SNAP_CAP_MB = 200
RUN_RE = re.compile(r"^c-\d{8}-\d{6}$")
PASS_BAR = "all rule-bearing questions correct, 0 uncited answers"


def _H():
    import harness
    return harness


def _sha(b):
    return hashlib.sha256(b).hexdigest()


def _tok(n_bytes):
    return n_bytes // 4


def _atomic(path, text):
    d = os.path.dirname(path)
    os.makedirs(d, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


def _jwrite(path, obj):
    _atomic(path, json.dumps(obj, indent=2, ensure_ascii=False, sort_keys=True) + "\n")


def _jread(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _guard(path, run_dir):
    """The tuner and every writer stay inside the run folder or the explicit archive/snapshot areas."""
    p = os.path.realpath(path)
    if "/rules/" in p + "/" or os.path.basename(p) in ("pins.json", "rules.json"):
        raise _H().HarnessError("compress never writes rules or pins directly")
    return path


class Ctx:
    def __init__(self, h, project):
        H = _H()
        self.h = h
        self.H = H
        self.project = H.norm_project(project)
        if not self.project:
            raise H.HarnessError("compress: project required")
        self.root = H.project_dir(h.home, self.project)

    def run_dir(self, run):
        if not RUN_RE.match(str(run or "")):
            raise self.H.HarnessError("compress: run id must look like c-YYYYMMDD-HHMMSS")
        return os.path.join(self.root, "compress", run)

    def load(self, run):
        d = self.run_dir(run)
        if not os.path.isfile(os.path.join(d, "run.json")):
            raise self.H.HarnessError(f"compress: unknown run {run}")
        return d, _jread(os.path.join(d, "run.json"))

    def event(self, kind, actor, data):
        self.h.store.append(f"compress.{kind}", actor, dict(data, project=self.project))


def _actor(h, by):
    H = _H()
    if by in H.OPERATOR:
        return "human", "operator", None
    st = h.state()
    aid = h.writer(st, by)
    return aid, st.role_of(aid) or "", st


def inventory(root):
    """[{path, bytes, tokens, sha}] for the corpus text files (builds, archives and run folders excluded)."""
    out = []
    for dp, dn, fns in os.walk(root):
        dn[:] = sorted(d for d in dn if d not in SKIP_DIRS and not d.endswith(SKIP_SUFFIX) and not d.startswith("."))
        for fn in sorted(fns):
            if not fn.lower().endswith(EXT) or fn.startswith("."):
                continue
            p = os.path.join(dp, fn)
            if os.path.islink(p):
                continue
            with open(p, "rb") as f:
                b = f.read()
            out.append({"path": os.path.relpath(p, root), "bytes": len(b), "tokens": _tok(len(b)), "sha": _sha(b)[:16]})
    return out


def chunk_plan(files, limit=CHUNK_TOKENS):
    chunks, cur, n = [], [], 0
    for f in files:
        if cur and n + f["tokens"] > limit:
            chunks.append(cur)
            cur, n = [], 0
        cur.append(f["path"])
        n += f["tokens"]
    if cur:
        chunks.append(cur)
    return chunks


WORKER_SPEC = """# /compress worker spec (ephemeral, no retained context, cheap tier)
You get ONE chunk of files from project `{project}` (list in inventory.json, chunk index given in your prompt).
Output ONE JSON file `proposal-<chunk>.json` and nothing else:
{{"chunk": <n>, "candidates": [{{"kind": "rule|decision|fact", "title": "<=80 chars", "body": "terse", "source": "<path>", "lines": "a-b", "quote": "exact text copied from those lines", "rule_bearing": true|false}}],
  "archive": [{{"path": "<path>", "reason": "<why this file is stale or duplicated>"}}]}}
Rules: copy `quote` verbatim from the cited lines; never invent; never edit or delete files; flag every line that states a rule,
gate, name or procedure with rule_bearing=true; when unsure, do NOT propose archiving. You never write or read restore-questions.md.
"""


def start(h, project, by, apply=False, scheduled=False):
    """Stage 0/1 of the flow (dry-run): inventory, chunk plan, worker spec, pin of restore-questions.md, report."""
    c = Ctx(h, project)
    aid, role, st = _actor(h, by)
    run = "c-" + time.strftime("%Y%m%d-%H%M%S")
    d = c.run_dir(run)
    os.makedirs(d, exist_ok=True)
    files = inventory(c.root)
    chunks = chunk_plan(files)
    rq = os.path.join(c.root, "restore-questions.md")
    rq_sha = _sha(open(rq, "rb").read())[:16] if os.path.isfile(rq) else None
    fp = fingerprint(h, c)
    snaps = list_snapshots(c.root)
    rep = {"run": run, "project": project, "files": len(files), "tokens": sum(f["tokens"] for f in files), "chunks": len(chunks),
           "restore_questions": rq_sha or "MISSING (write it before the propose stage)", "fingerprint": fp,
           "snapshots": {"count": len(snaps), "mb": round(sum(s["bytes"] for s in snaps) / 1e6, 1), "keep": SNAP_KEEP,
                         "cap_mb": SNAP_CAP_MB, "prunable": [s["name"] for s in snaps[:-SNAP_KEEP]],
                         "note": "prunable snapshots are never deleted without the operator's OK"},
           "mode": "scheduled report-only dry run" if scheduled else "dry run", "pass_bar": PASS_BAR}
    try:    # a flagged-volume jump over 2x the last run raises a report flag only (envoy change 4)
        hd = h.health(project, None, as_text=False)
        pr = next((p for p in hd.get("projects", []) if p["project"] == project), None)
        if pr:
            rep["flagged_tokens"] = pr["flagged_tokens"]
    except Exception:
        pass
    run0 = {"run": run, "project": c.project, "created": time.time(), "by": aid, "stage": "started", "fingerprint": fp,
            "restore_questions_sha": rq_sha, "inventory_sha": _sha(json.dumps(files, sort_keys=True).encode())[:16],
            "dry_run": True, "chunks": chunks}
    _jwrite(os.path.join(d, "run.json"), run0)
    _jwrite(os.path.join(d, "inventory.json"), {"files": files, "chunks": chunks})
    _atomic(os.path.join(d, "WORKER-SPEC.md"), WORKER_SPEC.format(project=project))
    _jwrite(os.path.join(d, "report.json"), rep)
    prev = _prev_flagged(c, run)
    if prev and rep.get("flagged_tokens") and rep["flagged_tokens"] > 2 * prev:
        rep["flag"] = f"flagged volume {rep['flagged_tokens']} > 2x last run ({prev}); report flag only"
        _jwrite(os.path.join(d, "report.json"), rep)
    c.event("started", aid, {"run": run, "files": len(files), "tokens": rep["tokens"], "chunks": len(chunks), "fingerprint": fp,
                             "restore_questions_sha": rq_sha, "scheduled": bool(scheduled)})
    if scheduled:    # a scheduled run is a report only, filed to the envoy as a notice with the path
        try:
            h.send(aid if aid != "human" else "operator", "role:envoy", f"/compress dry-run report {run}: {os.path.join(d, 'report.json')}",
                   subject=f"compress report {project}", kind="notice")
        except Exception:
            pass
    return {"run": run, "dir": d, "report": rep}


def _prev_flagged(c, run):
    best = None
    base = os.path.join(c.root, "compress")
    try:
        for n in sorted(os.listdir(base)):
            if n < run and RUN_RE.match(n):
                try:
                    v = _jread(os.path.join(base, n, "report.json")).get("flagged_tokens")
                    best = v or best
                except Exception:
                    pass
    except OSError:
        pass
    return best


def fingerprint(h, c):
    """Changes when the compress script, the pinned corpus_index (sha + rules digest) or the set of pins changes: the
    dry-run is then forced again (spec dry-run policy)."""
    me = _sha(open(os.path.abspath(__file__), "rb").read())[:12]
    try:
        pin = h.corpus_index_pin()
        pin = f"{pin.get('sha')}:{pin.get('rules')}"
    except Exception:
        pin = "none"
    try:
        h.corpus.refresh()
        pins = sorted(r[0] for r in h.corpus.db.execute("SELECT id FROM entries WHERE source='log' AND (' '||tags||' ') LIKE '% pin %'"))
    except Exception:
        pins = []
    return _sha(f"{me}|{pin}|{','.join(pins)}".encode())[:16]


# ---------------------------------------------------------------- snapshot / restore

def list_snapshots(root):
    base = os.path.join(root, "_archive", "snapshots")
    out = []
    try:
        for n in sorted(os.listdir(base)):
            p = os.path.join(base, n)
            if os.path.isdir(p):
                try:
                    m = _jread(os.path.join(p, "manifest.json"))
                    out.append({"name": n, "bytes": sum(f["bytes"] for f in m.get("files", [])), "sha": m.get("sha")})
                except Exception:
                    out.append({"name": n, "bytes": 0, "sha": None})
    except OSError:
        pass
    return out


def snapshot(h, project, run, by):
    c = Ctx(h, project)
    aid, _role, _st = _actor(h, by)
    d, r = c.load(run)
    ts = time.strftime("%Y%m%d-%H%M%S")
    dst = os.path.join(c.root, "_archive", "snapshots", ts)
    if os.path.exists(dst):
        raise c.H.HarnessError(f"compress: snapshot {ts} already exists")
    files = inventory(c.root)
    for f in files:
        t = os.path.join(dst, f["path"])
        os.makedirs(os.path.dirname(t), exist_ok=True)
        shutil.copy2(os.path.join(c.root, f["path"]), t)
    man = {"snapshot": ts, "project": c.project, "files": files, "created": time.time(),
           "restore": f"harness.py compress restore --project {c.project} --run {run} --agent <id>"}
    man["sha"] = _sha(json.dumps(files, sort_keys=True).encode())[:16]
    _jwrite(os.path.join(dst, "manifest.json"), man)
    r["snapshot"] = {"name": ts, "sha": man["sha"], "inventory_sha": r["inventory_sha"]}
    r["stage"] = "snapshotted"
    _jwrite(os.path.join(d, "run.json"), r)
    c.event("snapshot", aid, {"run": run, "snapshot": ts, "sha": man["sha"], "files": len(files)})
    return {"snapshot": ts, "files": len(files), "sha": man["sha"], "restore": man["restore"]}


def _snapshot_ok(c, r):
    s = r.get("snapshot")
    if not s:
        return False
    try:
        m = _jread(os.path.join(c.root, "_archive", "snapshots", s["name"], "manifest.json"))
        return m.get("sha") == s["sha"] and all(os.path.isfile(os.path.join(c.root, "_archive", "snapshots", s["name"], f["path"])) for f in m["files"])
    except Exception:
        return False


# ---------------------------------------------------------------- propose

def validate_proposal(c, proposal):
    """-> (clean candidates, clean archive items, problems). Quotes must appear verbatim in the cited lines."""
    cands, arch, probs = [], [], []
    for i, x in enumerate(proposal.get("candidates") or []):
        try:
            kind, src, lines, quote = x["kind"], x["source"], str(x["lines"]), str(x["quote"])
            if kind not in ("rule", "decision", "fact"):
                raise ValueError("kind")
            p = os.path.realpath(os.path.join(c.root, src))
            if not p.startswith(os.path.realpath(c.root) + os.sep) or not os.path.isfile(p):
                raise ValueError("source missing or outside the project")
            m = re.fullmatch(r"(\d+)-(\d+)", lines)
            if not m:
                raise ValueError("lines must be a-b")
            a, b = int(m.group(1)), int(m.group(2))
            txt = open(p, encoding="utf-8", errors="replace").read().splitlines()
            if not (1 <= a <= b <= len(txt)):
                raise ValueError("line range outside the file")
            block = "\n".join(txt[a - 1:b])
            norm = lambda s: re.sub(r"\s+", " ", s).strip()
            if not quote.strip() or norm(quote) not in norm(block):
                raise ValueError("quote is not verbatim at the cited lines")
            cands.append({"id": f"k{len(cands) + 1}", "kind": kind, "title": str(x["title"])[:80], "body": str(x.get("body") or quote)[:600],
                          "source": src, "lines": lines, "quote": quote[:600], "rule_bearing": bool(x.get("rule_bearing"))})
        except (KeyError, ValueError, TypeError) as e:
            probs.append(f"candidate {i}: {e}")
    for i, x in enumerate(proposal.get("archive") or []):
        try:
            p = os.path.realpath(os.path.join(c.root, x["path"]))
            if not p.startswith(os.path.realpath(c.root) + os.sep) or not os.path.isfile(p):
                raise ValueError("path missing or outside the project")
            if x["path"] == "restore-questions.md" or x["path"].startswith(("PROJECT", "ROLES")):
                raise ValueError("protected file")
            arch.append({"path": x["path"], "reason": str(x.get("reason") or "")[:300]})
        except (KeyError, ValueError, TypeError) as e:
            probs.append(f"archive {i}: {e}")
    return cands, arch, probs


def propose(h, project, run, by, files):
    c = Ctx(h, project)
    aid, _role, _st = _actor(h, by)
    d, r = c.load(run)
    cands, arch, probs, seen = [], [], [], set()
    for fp_ in files:
        prop = _jread(fp_)
        cs, ar, pr = validate_proposal(c, prop)
        for x in cs:
            key = (x["source"], x["lines"])
            if key in seen:
                continue
            seen.add(key)
            x["id"] = f"k{len(cands) + 1}"
            cands.append(x)
        arch += [a for a in ar if a["path"] not in {y["path"] for y in arch}]
        probs += [f"{os.path.basename(fp_)}: {p}" for p in pr]
    out = {"candidates": cands, "archive": arch, "problems": probs}
    out["proof"] = _sha(json.dumps({"candidates": cands, "archive": arch}, sort_keys=True).encode())[:16]
    _jwrite(os.path.join(d, "proposal.json"), out)
    r["proposal_proof"], r["stage"] = out["proof"], "proposed"
    _jwrite(os.path.join(d, "run.json"), r)
    c.event("proposed", aid, {"run": run, "proof": out["proof"], "candidates": len(cands), "archive": len(arch), "rejected_by_validation": len(probs)})
    return {"proof": out["proof"], "candidates": len(cands), "archive": len(arch), "problems": probs}


# ---------------------------------------------------------------- review / apply

def review(h, project, run, by, decisions):
    """decisions: {candidate id | "archive:<path>": "accept"|"reject"|{"edit": {...}}}. Recorded per reviewing role."""
    c = Ctx(h, project)
    aid, role, _st = _actor(h, by)
    d, r = c.load(run)
    if r.get("stage") not in ("proposed", "reviewed"):
        raise c.H.HarnessError("compress: review needs a validated proposal (stage propose first)")
    prop = _jread(os.path.join(d, "proposal.json"))
    valid = {x["id"] for x in prop["candidates"]} | {"archive:" + x["path"] for x in prop["archive"]}
    path = os.path.join(d, "reviews.json")
    rv = _jread(path) if os.path.isfile(path) else {}
    mine = rv.setdefault(role or "operator", {})
    n = {"accept": 0, "reject": 0, "edit": 0}
    for k, v in decisions.items():
        if k not in valid:
            raise c.H.HarnessError(f"compress: unknown candidate {k}")
        if isinstance(v, dict) and "edit" in v:
            mine[k] = {"edit": {kk: str(vv)[:600] for kk, vv in v["edit"].items() if kk in ("title", "body")}}
            n["edit"] += 1
        elif v in ("accept", "reject"):
            mine[k] = v
            n[v] += 1
        else:
            raise c.H.HarnessError(f"compress: decision for {k} must be accept, reject or {{edit:{{...}}}}")
    _jwrite(path, rv)
    r["stage"] = "reviewed"
    _jwrite(os.path.join(d, "run.json"), r)
    c.event("reviewed", aid, {"run": run, "role": role, **n})
    _feedback(d, "review", {"role": role, **n})
    return {"role": role, **n}


def _feedback(d, kind, data):
    p = os.path.join(d, "feedback.json")
    try:
        fb = _jread(p)
    except Exception:
        fb = []
    fb = (fb + [dict(data, kind=kind, t=round(time.time()))])[-50:]    # bounded
    _jwrite(p, fb)


def apply(h, project, run, by):
    """Pin first, archive second. Refuses unless every precondition holds; nothing is deleted."""
    c = Ctx(h, project)
    H = c.H
    aid, role, st = _actor(h, by)
    d, r = c.load(run)
    st = h.state()
    if aid == "human" or not (h.curation_allows(st, aid, "pin") and h.curation_allows(st, aid, "archive")):
        raise H.HarnessError("compress apply: run it as an agent whose role has the pin and archive curation grants (the envoy)")
    if r.get("stage") != "reviewed" or r.get("applied"):
        raise H.HarnessError(f"compress apply: run is {r.get('stage')}{' (already applied)' if r.get('applied') else ''}; needs a reviewed run")
    if not _snapshot_ok(c, r) or r["snapshot"]["inventory_sha"] != r["inventory_sha"]:
        raise H.HarnessError("compress apply: no valid snapshot of this inventory (run snapshot first)")
    if fingerprint(h, c) != r["fingerprint"]:
        raise H.HarnessError("compress apply: the script, corpus_index pin or the pins changed since the dry run; start a new dry run")
    rq = os.path.join(c.root, "restore-questions.md")
    if not os.path.isfile(rq) or _sha(open(rq, "rb").read())[:16] != r.get("restore_questions_sha"):
        raise H.HarnessError("compress apply: restore-questions.md is missing or changed since the dry run (it is pinned in the run)")
    rv = {H.cr(k): v for k, v in _jread(os.path.join(d, "reviews.json")).items()}   # 0.16.0: reviews filed under an old role name count
    lead_roles = [k for k in rv if k not in ("envoy", "operator")]
    if "envoy" not in rv and "operator" not in rv:
        raise H.HarnessError("compress apply: the envoy's review is missing")
    if not lead_roles and "operator" not in rv:
        raise H.HarnessError("compress apply: the project lead's review is missing")
    prop = _jread(os.path.join(d, "proposal.json"))
    gate = rv.get("envoy") or rv.get("operator")
    accepted = {k: v for k, v in gate.items() if v == "accept" or isinstance(v, dict)}
    cands = [x for x in prop["candidates"] if x["id"] in accepted]
    for x in cands:
        e = accepted[x["id"]]
        if isinstance(e, dict):
            x.update(e["edit"])
    # 1) pin first: records for accepted candidates (tagged, pinned with a reason quoting the rule line)
    made = []
    try:
        for x in cands:
            rec = h.record(aid, "decision" if x["kind"] == "decision" else "context",
                           x["title"], f"{x['body']}\n(source: {x['source']}:{x['lines']}, compress {run})",
                           ["compress", x["kind"], f"c-{run[2:10]}"], c.project, [x["source"]])
            made.append(rec["id"])
            h.pin(by, [rec["id"]], True, f'"compress {run}"')
    except Exception as e:
        raise H.HarnessError(f"compress apply: stopped before any archive ({type(e).__name__}: {e}); records made: {made}")
    pinned = {x["id"] for x in cands}
    if any(x["rule_bearing"] and x["id"] not in pinned for x in prop["candidates"] if x["id"] in accepted):
        raise H.HarnessError("compress apply: a rule-bearing candidate is not pinned; archive refused")
    # 2) archive second: only files the envoy accepted, moved (never deleted) with a manifest
    moved = []
    adir = os.path.join(c.root, "_archive", "compressed", run)
    for x in prop["archive"]:
        if gate.get("archive:" + x["path"]) != "accept":
            continue
        src = os.path.join(c.root, x["path"])
        dst = os.path.join(adir, x["path"])
        if not os.path.isfile(src):
            continue
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        os.replace(src, dst)
        moved.append({"from": x["path"], "to": os.path.relpath(dst, c.root), "reason": x["reason"]})
    _jwrite(os.path.join(adir, "MANIFEST.json"), {"run": run, "moved": moved, "records": made})
    r.update({"applied": True, "stage": "applied", "records": made, "moved": len(moved), "applied_t": time.time()})
    _jwrite(os.path.join(d, "run.json"), r)
    c.event("applied", aid, {"run": run, "proof": r["proposal_proof"], "records": made, "moved": len(moved)})
    _feedback(d, "apply", {"records": len(made), "moved": len(moved)})
    return {"records": made, "moved": len(moved), "manifest": os.path.relpath(os.path.join(adir, "MANIFEST.json"), c.root),
            "next": "verify with a fresh non-gated agent: harness.py compress verify --run " + run}


def resolve(h, project, rel):
    """An archived path -> where it lives now (archived items stay resolvable by path)."""
    c = Ctx(h, project)
    base = os.path.join(c.root, "_archive", "compressed")
    if os.path.isfile(os.path.join(c.root, rel)):
        return {"path": rel, "archived": False}
    try:
        for run in sorted(os.listdir(base), reverse=True):
            m = _jread(os.path.join(base, run, "MANIFEST.json"))
            for x in m["moved"]:
                if x["from"] == rel:
                    return {"path": x["to"], "archived": True, "run": run}
    except OSError:
        pass
    raise c.H.HarnessError(f"compress: {rel} not found or archived")


# ---------------------------------------------------------------- verify / restore / lint / tune

def parse_questions(text):
    """restore-questions.md: `## Q<n>: <question>` blocks with `cites:` (ids or paths), `expect:` (a;b;c) and optional `rule-bearing: no`."""
    qs = []
    for blk in re.split(r"(?m)^## ", text)[1:]:
        head, _, rest = blk.partition("\n")
        m = re.match(r"(Q\d+)\s*[:.-]?\s*(.*)", head.strip())
        if not m:
            continue
        cites = re.search(r"(?mi)^cites:\s*(.+)$", rest)
        exp = re.search(r"(?mi)^expect:\s*(.+)$", rest)
        rb = re.search(r"(?mi)^rule-bearing:\s*(\w+)", rest)
        qs.append({"id": m.group(1), "q": m.group(2).strip(),
                   "cites": [x.strip() for x in (cites.group(1) if cites else "").split(",") if x.strip()],
                   "expect": [x.strip().lower() for x in (exp.group(1) if exp else "").split(";") if x.strip()],
                   "rule_bearing": not (rb and rb.group(1).lower() in ("no", "false"))})
    return qs


def verify(h, project, run, by, answers):
    """answers: {"Q1": {"answer": "...", "cites": ["D-xxxxx", "path"]}}. Deterministic grading; fixed pass bar."""
    c = Ctx(h, project)
    H = c.H
    aid, role, st = _actor(h, by)
    d, r = c.load(run)
    if not r.get("applied"):
        raise H.HarnessError("compress verify: the run is not applied")
    authors = {e["actor"] for e in h.store.read_all() if str(e.get("type", "")).startswith("compress.") and (e.get("data") or {}).get("run") == run}
    if aid in authors or aid == "human" or role in ("envoy", "steward") or h.curation_allows(st, aid, "archive"):
        raise H.HarnessError("compress verify: needs a fresh, non-gated agent that took no part in this run")
    rq = os.path.join(c.root, "restore-questions.md")
    if _sha(open(rq, "rb").read())[:16] != r.get("restore_questions_sha"):
        raise H.HarnessError("compress verify: restore-questions.md changed since the run pin")
    qs = parse_questions(open(rq, encoding="utf-8").read())
    fails, uncited = [], []
    for q in qs:
        a = answers.get(q["id"]) or {}
        text, cites = str(a.get("answer") or "").lower(), [str(x) for x in (a.get("cites") or [])]
        if not cites or not (set(cites) & set(q["cites"])):
            uncited.append(q["id"])
        if not all(e in text for e in q["expect"]) and q["rule_bearing"]:
            fails.append(q["id"])
        for ct in set(cites) & set(q["cites"]):    # a cited rule id / path must still resolve
            if not _resolves(h, c, ct):
                uncited.append(q["id"])
    ok = bool(qs) and not fails and not uncited
    res = {"ok": ok, "questions": len(qs), "wrong": fails, "uncited": sorted(set(uncited)), "pass_bar": PASS_BAR}
    r["verified"] = res
    r["stage"] = "verified" if ok else "verify-failed"
    _jwrite(os.path.join(d, "run.json"), r)
    c.event("verified", aid, {"run": run, "ok": ok, "wrong": fails, "uncited": res["uncited"]})
    _feedback(d, "verify", {"ok": ok, "wrong": len(fails), "uncited": len(res["uncited"])})
    if not ok:
        res["offer"] = f"restore the snapshot: harness.py compress restore --project {project} --run {run} --agent <envoy id>"
    return res


def _resolves(h, c, ref):
    if re.fullmatch(r"[A-Z]-[0-9a-f]{5}", ref):
        return bool(h.corpus.entry_meta(ref)) or bool(h.corpus.db.execute("SELECT 1 FROM entries WHERE id=?", (ref,)).fetchone())
    try:
        resolve(h, c.project, ref)
        return True
    except _H().HarnessError:
        return False


def restore(h, project, run, by):
    c = Ctx(h, project)
    H = c.H
    aid, _role, st = _actor(h, by)
    d, r = c.load(run)
    if aid == "human" or not h.curation_allows(st, aid, "archive"):
        raise H.HarnessError("compress restore: run it as the envoy (an agent with the archive grant)")
    if not _snapshot_ok(c, r):
        raise H.HarnessError("compress restore: the snapshot is missing or does not match its manifest")
    sd = os.path.join(c.root, "_archive", "snapshots", r["snapshot"]["name"])
    m = _jread(os.path.join(sd, "manifest.json"))
    back = 0
    for f in m["files"]:
        dst = os.path.join(c.root, f["path"])
        if not os.path.exists(dst):
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(os.path.join(sd, f["path"]), dst)
            back += 1
    archived = []
    if r.get("records"):
        try:    # unpin, then archive (the records quote "compress <run>" in their body)
            h.pin(by, r["records"], False, f'"compress {run}"')
            archived = h.archive(by, r["records"], f'"compress {run}"')
        except Exception as e:
            archived = [f"records not archived: {e}"]
    r["stage"] = "restored"
    _jwrite(os.path.join(d, "run.json"), r)
    c.event("restored", aid, {"run": run, "files_back": back})
    return {"files_restored": back, "records": r.get("records") or [], "archive": archived if isinstance(archived, list) else "ok"}


def lint(h, project):
    """Steward checks (no restore tests): restore-questions.md exists, its sha matches the newest run's pin, each cited rule id resolves."""
    c = Ctx(h, project)
    probs = []
    rq = os.path.join(c.root, "restore-questions.md")
    if not os.path.isfile(rq):
        return {"ok": False, "problems": ["restore-questions.md missing"]}
    sha = _sha(open(rq, "rb").read())[:16]
    base = os.path.join(c.root, "compress")
    runs = sorted(n for n in (os.listdir(base) if os.path.isdir(base) else []) if RUN_RE.match(n))
    if runs:
        pin = _jread(os.path.join(base, runs[-1], "run.json")).get("restore_questions_sha")
        if pin and pin != sha:
            probs.append(f"restore-questions.md sha {sha} != pin {pin} of {runs[-1]}")
    for q in parse_questions(open(rq, encoding="utf-8").read()):
        if not q["cites"]:
            probs.append(f"{q['id']}: no cites")
        for ct in q["cites"]:
            if not _resolves(h, c, ct):
                probs.append(f"{q['id']}: cited {ct} does not resolve")
    return {"ok": not probs, "problems": probs, "sha": sha}


def tune(h, project, run, by):
    """Feedback log -> a PROPOSAL file in the run folder. It never edits rules, patterns or pins (S5 gate does that)."""
    c = Ctx(h, project)
    d, r = c.load(run)
    try:
        fb = _jread(os.path.join(d, "feedback.json"))
    except Exception:
        fb = []
    wrong = sum(x.get("wrong", 0) for x in fb if x["kind"] == "verify")
    rej = sum(x.get("reject", 0) for x in fb if x["kind"] == "review")
    acc = sum(x.get("accept", 0) for x in fb if x["kind"] == "review")
    out = _guard(os.path.join(d, "tuning-proposal.md"), d)
    _atomic(out, f"# Tuning proposal for {project} ({run})\nreviews: {acc} accepted, {rej} rejected; verify misses: {wrong}.\n"
                 "Changes to thresholds or patterns go through the S5 gate (new rules digest, envoy ACCEPT + pin); this file edits nothing.\n")
    return {"proposal": os.path.relpath(out, c.root)}
