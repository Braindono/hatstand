# VENDORED (0.27.0) from the harness-ops Hub feed tool hub_feed_timers.py, source sha256 13b98ae9899f09fe42615e6a05e916f1713af2ff243c09b81eab86f47f9012fb. Reviewed with the plugin release; never loaded from the ops tree. Change it only through a release.
"""hub_feed_timers: the `timers` feed and the harness_admin op=timer logic (local file, no model).
Interface: set_timer(path, args, now) -> doc; sweep(path, closed_task_ids, now) closes timers whose
`link` task closed. args: {id,label,ends_at|extend_by(seconds),visible,state,style?,owner_role,kind,link,note}.
Style: random preset only when none given AND none stored; a stored style is never overwritten by a random one.
Depends on: stdlib. The op wrapper in the plugin's mcp_server is the curator's change (patch in specs)."""
import fcntl, json, os, random
from contextlib import contextmanager

PRESETS = ["type-led", "instrument-panel", "compact"]


def _load(path):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _save(path, data):
    tmp = "%s.%d.tmp" % (path, os.getpid())
    try:
        with open(tmp, "w") as f:
            json.dump(data, f, indent=1)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


@contextmanager
def _locked(path):
    with open(path + ".lock", "w") as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lf, fcntl.LOCK_UN)


def set_timer(path, args, now, rng=random):
    with _locked(path):
        return _set_timer(path, args, now, rng)


def sweep(path, closed_task_ids, now):
    with _locked(path):
        return _sweep(path, closed_task_ids, now)


def _set_timer(path, args, now, rng):
    data = _load(path)
    tid = args["id"]
    cur = data.get(tid, {})
    doc = dict(cur)
    for k in ("label", "owner_role", "kind", "link", "note", "visible", "state"):
        if k in args:
            doc[k] = args[k]
    doc.setdefault("starts_at", now)
    if "ends_at" in args:
        doc["ends_at"] = args["ends_at"]
    elif "extend_by" in args:
        doc["ends_at"] = (cur.get("ends_at") or now) + args["extend_by"]
    if "ends_at" not in doc:
        raise ValueError("ends_at or extend_by required")
    doc.setdefault("visible", True)
    doc.setdefault("state", "running")
    doc["style"] = args.get("style") or cur.get("style") or rng.choice(PRESETS)
    data[tid] = doc
    _save(path, data)
    return doc


def _sweep(path, closed_task_ids, now):
    data = _load(path)
    n = 0
    for doc in data.values():
        if doc.get("state") == "running" and doc.get("link") in closed_task_ids:
            doc["state"], doc["closed_at"], n = "closed", now, n + 1
    if n:
        _save(path, data)
    return n
