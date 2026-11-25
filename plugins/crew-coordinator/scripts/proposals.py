"""proposals: 0.27.3 C1 piece 2. The proposal store: options or drafts shown to the operator are written to disk so a handoff cannot lose them.
Depends on: stdlib, dated_switches (the one clock). Used by mcp_server (`harness_propose`) and propose_hook (AskUserQuestion capture).
File: <home>/projects/<project>/proposals/<yyyy-mm-dd>_<slug>.md, first lines `id: P-xxxxx`, `kind:`, `source:`, then the items. P- ids are their OWN prefix
with their OWN lookup (`load`); corpus id parsing and harness_recall never see them. Interface:
pid(project, title, stamp) -> "P-" + 7 hex; save(home, project, kind, title, items, recommended=None, source="tool", store=None, actor="system", answer=None) -> {id, path, text};
load(home, pid) -> {id, path, text} | None; find(home, pid) -> path | None. `store` is a ledger store; when given, one proposal.saved event is appended (id, project, kind, source, n)."""
import hashlib, os, re, time

import dated_switches

KINDS = ("options", "drafts")
SLUG = re.compile(r"[^a-z0-9]+")
PID = re.compile(r"^P-[0-9a-f]{5,12}$")
MAX_ITEM = 4000


def pid(project, title, stamp):
    return "P-" + hashlib.sha1(f"{project}|{title}|{stamp}".encode("utf-8")).hexdigest()[:7]


def _dir(home, project):
    p = SLUG.sub("-", str(project or "").lower()).strip("-")
    if not p:
        raise ValueError("proposal: project required")
    return os.path.join(home, "projects", p, "proposals"), p


def _text(pid_, kind, title, items, recommended, source, answer):
    lines = [f"id: {pid_}", f"kind: {kind}", f"source: {source}", f"title: {title}", f"recommended: {recommended or ''}", ""]
    for n, it in enumerate(items, 1):
        lines += [f"## {n}. {str(it)[:MAX_ITEM].strip()}", ""]
    if answer:
        lines += ["## His answer", "", str(answer)[:MAX_ITEM], ""]
    return "\n".join(lines)


def save(home, project, kind, title, items, recommended=None, source="tool", store=None, actor="system", answer=None):
    """Write the proposal file; same project, title and day gives a new id only when the stamp differs (stamp = epoch seconds)."""
    if kind not in KINDS:
        raise ValueError(f"proposal: kind must be one of {', '.join(KINDS)}")
    title = str(title or "").strip()
    its = [x for x in (items if isinstance(items, list) else []) if str(x).strip()]
    if not title or not its:
        raise ValueError("proposal: title and at least one item required")
    d, proj = _dir(home, project)
    os.makedirs(d, exist_ok=True)
    pid_ = pid(proj, title, time.time())
    base = f"{dated_switches.today()}_{SLUG.sub('-', title.lower()).strip('-')[:40] or 'proposal'}"
    path, n = os.path.join(d, base + ".md"), 2
    while os.path.exists(path):
        path = os.path.join(d, f"{base}-{n}.md")
        n += 1
    text = _text(pid_, kind, title, its, recommended, source, answer)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    if store is not None:
        store.append("proposal.saved", actor, {"id": pid_, "project": proj, "kind": kind, "source": source, "n": len(its)})
    return {"id": pid_, "path": path, "text": text}


def find(home, pid_):
    if not PID.match(str(pid_ or "")):
        return None
    root = os.path.join(home, "projects")
    try:
        projs = os.listdir(root)
    except OSError:
        return None
    for p in sorted(projs):
        d = os.path.join(root, p, "proposals")
        try:
            names = sorted(os.listdir(d))
        except OSError:
            continue
        for n in names:
            try:
                with open(os.path.join(d, n), encoding="utf-8") as f:
                    if f.readline().strip() == f"id: {pid_}":
                        return os.path.join(d, n)
            except OSError:
                continue
    return None


def load(home, pid_):
    path = find(home, pid_)
    if not path:
        return None
    with open(path, encoding="utf-8") as f:
        return {"id": pid_, "path": path, "text": f.read()}
