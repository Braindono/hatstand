"""operator_sign: the the user-side client for signed operator acts (requests, apply, and the replay/append gate).

What it does: tells harness.py whether the signed-operator gate is installed (a cutover record in the root log),
accepts only human ledger events that root consumed, builds request files for him to sign, and applies a signed grant.
Why: this code is editable by agents, so it never decides who the operator is; root's signed log does (see root/).
It never runs sudo and never prompts for a password: the root signer applies as his uid by calling `harness.py apply-all`, then records the consume itself.
Depends on: json, os, hashlib, threading; root/harness_verify.py and root/harness_event_map.py.
Interface: gate_on(), human_ok(ev), human_ctx(), in_ctx(), request_file(home, kind, events), commands_text(...), apply(h, req_id).
"""
import contextlib
import hashlib
import json
import os
import subprocess
import sys
import threading
import time

_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "root")
for _d in ("/usr/local/libexec", _ROOT):          # the root-installed copy wins; the plugin copy serves tests and the build
    if os.path.isfile(os.path.join(_d, "harness_verify.py")):
        sys.path.insert(0, _d)
        break
try:
    import harness_event_map as MAP   # noqa: E402
    import harness_verify as V        # noqa: E402
except ImportError:                    # a bare scripts/ copy (the Exchange bin mirror): no gate, nothing enforced
    sys.stderr.write("operator_sign: root modules not found; the signed-operator gate is off in this copy\n")
    class MAP:                         # noqa: N801
        enforced = staticmethod(lambda *a, **k: False)
        canonical = staticmethod(lambda o: __import__("json").dumps(o, sort_keys=True, separators=(",", ":"), ensure_ascii=False))
    V = None
_MAP = MAP

LOG = "/usr/local/var/harness-grants.log"
PUB = "/usr/local/etc/harness-grant.pub"
FLAG = "/usr/local/var/harness-grants.disabled"
HELPER = "/usr/local/libexec/harness-grant"
_ctx = threading.local()
_cache = {"mark": None, "val": (None, set())}


def _paths():
    return LOG, PUB, FLAG       # constants only: tests assign the module attributes; no environment variable can move them


def _accepted():
    if V is None:
        return None, set()
    log, pub, _ = _paths()
    try:
        st = os.stat(log)
    except OSError:
        return None, set()
    mark = (log, st.st_mtime_ns, st.st_size)
    if _cache["mark"] != mark:
        _cache["mark"], _cache["val"] = mark, V.accepted(log, pub)
    return _cache["val"]


def log_mark():
    """(mtime, size) of the root log, so a State cached before a grant was consumed is rebuilt."""
    try:
        st = os.stat(_paths()[0])
        return (st.st_mtime_ns, st.st_size)
    except OSError:
        return None


def gate_on():
    """True once root has recorded a cutover and the break-glass flag file is absent."""
    if os.path.exists(_paths()[2]):
        return False
    return _accepted()[0] is not None


def in_ctx():
    """Lifts only the append refusal for this thread; it is NOT security: replay still needs root's consumed grant."""
    return bool(getattr(_ctx, "on", False))


@contextlib.contextmanager
def human_ctx():
    """Inside an `apply` of a signed grant: appends of actor human are allowed (root still decides at replay)."""
    _ctx.on = True
    try:
        yield
    finally:
        _ctx.on = False


def human_ok(ev):
    """Replay rule: a human event counts when the gate is off, it predates the cutover, or root consumed it."""
    if not MAP.enforced(ev.get("type"), ev.get("actor"), ev.get("data")):
        return True           # kinds not built yet keep today's behaviour (open gaps, listed in the CHANGELOG)
    cut, ok = _accepted()
    if cut is None or os.path.exists(_paths()[2]):
        return True
    return ev.get("seq", 0) <= cut or (ev.get("seq"), ev.get("hash")) in ok


def request_file(home, kind, events, requester="harness", ttl=900):
    """Write the canonical pending request; returns (request id, path, sha256). Helper re-reads these exact bytes."""
    req = {"v": 1, "kind": kind, "requester": requester, "created": int(time.time()), "expires": int(time.time()) + ttl, "events": events}
    raw = MAP.canonical(req).encode("utf-8")
    sha = hashlib.sha256(raw).hexdigest()
    d = os.path.join(home, "_harness", "operator-pending")
    os.makedirs(d, mode=0o755, exist_ok=True)
    rid = sha[:12]
    with open(os.path.join(d, rid + ".json"), "wb") as f:
        f.write(raw)
    return rid, os.path.join(d, rid + ".json"), sha


def role_assign_events(h, role, aid):
    """The exact human events `role_assign` writes: the assignment, plus the project move when the agent's project differs."""
    st = h.state()
    return [{"type": "role.assigned", "data": {"role": role, "agent": aid}}]      # the project move is not an enforced kind


def pending_dir(home):
    return os.path.join(home, "_harness", "operator-pending")


def _consumed_acts():
    recs, _ = V.load_log(_paths()[0], _paths()[1])
    return {r.get("act") for r in recs if r.get("t") == "consume"}


def _move_done(home, rid):
    d = os.path.join(pending_dir(home), "done")
    os.makedirs(d, mode=0o755, exist_ok=True)
    os.replace(os.path.join(pending_dir(home), rid + ".json"), os.path.join(d, rid + ".json"))


def apply_all(h, file_only=False):
    """Apply every pending request that has a live signed act; a request whose act root already consumed is only filed away.
    Unsigned or expired requests stay. -> list of result dicts."""
    out = []
    d = pending_dir(h.home)
    try:
        names = sorted(n[:-5] for n in os.listdir(d) if len(n) == 17 and n.endswith(".json"))
    except OSError:
        return out
    done_acts = _consumed_acts()
    for rid in names:
        sha = hashlib.sha256(open(os.path.join(d, rid + ".json"), "rb").read()).hexdigest()
        act = find_act(sha)
        if act is None:
            continue
        if act["id"] in done_acts:
            _move_done(h.home, rid)
            out.append({"request": rid, "state": "already applied; filed away"})
            continue
        if file_only:
            continue                      # second pass after root's consume: only file away, never apply
        if time.time() > act["expires"]:
            out.append({"request": rid, "state": "signature expired; sign it again"})
            continue
        try:
            r = apply(h, rid)
        except RuntimeError as e:
            out.append({"request": rid, "state": "not applied: " + str(e)})
            continue
        out.append(dict(r, request=rid))
    return out


LINE = "sudo -k; sudo /usr/local/libexec/harness-grant approve; sudo -k"


def commands_text(rid=None):
    return ("Operator act waiting. In Terminal.app (not in a Claude chat) run your one approve line; it asks for your password once,\n"
            "lists every waiting request in full, and applies what you sign after you type the code:\n"
            f"  {LINE}\n"
            "Any password prompt other than sudo's own is not ours: refuse it.")


def find_act(sha):
    recs, _ = V.load_log(_paths()[0], _paths()[1])
    acts = [r for r in recs if r.get("t") == "act" and r.get("req") == sha]
    return acts[-1] if acts else None


def apply(h, rid):
    """Run the signed request: only the `approve` kind is built (the others refuse). Appends under ctx; root records the consume."""
    p = os.path.join(h.home, "_harness", "operator-pending", rid + ".json")
    raw = open(p, "rb").read()
    sha = hashlib.sha256(raw).hexdigest()
    act = find_act(sha)
    if act is None or time.time() > act["expires"]:
        raise RuntimeError("no live signed grant for this request: run steps 1 and 2 first")
    req = json.loads(raw)
    before = h.state().last_seq
    with human_ctx():
        d0 = req["events"][0]["data"]
        if req["kind"] == "approve":
            aid = d0["id"]
            rec = h._approval_records().get(aid)
            if not rec or rec["args_digest"] != d0.get("args_digest"):
                raise RuntimeError("unknown or changed approval")
            h.approve(aid, channel="cli-tty", code=rec["args_digest"][:4], tty=True)
        elif req["kind"] == "role_assign":
            aid = d0["role"]
            h.role_assign("operator", d0["role"], d0["agent"])
        else:
            raise RuntimeError("this act kind is not built for signing yet; nothing was done")
    new = [e for e in h.store.events_after(before) if MAP.enforced(e.get("type"), e.get("actor"), e.get("data"))]
    return {"applied": aid, "events": len(new)}      # root records the consume itself, matching digests (0.26.2)
