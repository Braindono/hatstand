#!/usr/bin/env python3
"""cc 0.22.0 (release gate, spec v3 step 3): the child side of the release simulator.

The INSTALLED release starts this file with `python3 -I -B sim_launcher.py --scratch S --candidate C --action publish|scenario
--out F`. Before it imports any candidate code it installs an audit hook (sys.addaudithook) that REFUSES every write outside the
scratch folder (I6), refuses network connections and DNS lookups, and logs each subprocess and network attempt (I7a). Then it
imports the CANDIDATE's harness from C/scripts and runs one action against the scratch home. The result goes to F (inside scratch)
as JSON. A candidate can escape the hook with ctypes; that is accepted (spec v3: candidates come from our own builders)."""
import json
import os
import sys

_LOG = {"refused": [], "subprocess": [], "net": []}
_SEEN = set()
_ROOT = None
_IN_HOOK = [False]
_WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC
# 0.22.0 (envoy m-64d4a79dac01, critic S4 rerun): DENY BY DEFAULT. An audit event the fence neither judges below nor lists here as
# read-only or harmless is refused. A future candidate that needs a new event fails I6 until this gate file names it (a gate question).
SAFE_EVENTS = frozenset((
    "import", "compile", "exec", "marshal.loads", "marshal.dumps", "builtins.id", "object.__setattr__", "object.__getattr__",
    "object.__delattr__", "os.listdir", "os.scandir", "os.walk", "os.chdir", "os.getxattr", "os.listxattr", "glob.glob", "glob.glob/2",
    "socket.gethostname", "socket.gethostbyname", "socket.__new__", "sys._getframe", "sys._getframemodulename", "sys._current_frames",
    "sys.settrace", "sys.setprofile", "sys.addaudithook", "sys.excepthook", "sys.unraisablehook", "fcntl.flock", "fcntl.fcntl",
    "fcntl.lockf", "sqlite3.connect/handle", "time.sleep", "os.putenv", "os.unsetenv", "gc.get_objects", "gc.get_referrers",
    "gc.get_referents", "_thread.start_new_thread", "array.__new__", "locale.setlocale", "code.__new__", "function.__new__",
    "cpython._PySys_ClearAuditHooks", "cpython.PyInterpreterState_Clear", "cpython.PyInterpreterState_New",
    "cpython.run_command", "cpython.run_file", "cpython.run_module", "cpython.run_startup", "cpython.run_interactivehook",
    "os.getpgid", "os.getsid", "pathlib.Path.glob", "pathlib.Path.rglob", "ctypes.dlsym",
))


def _real(p):
    try:
        if isinstance(p, bytes):
            p = os.fsdecode(p)
        if not isinstance(p, str):
            return None
        return os.path.realpath(os.path.abspath(p))
    except Exception:
        return None


def _inside(p):
    r = _real(p)
    if r is None:
        return True                      # an fd or an object, not a path: nothing to judge here
    if r in ("/dev/null", "/dev/stdout", "/dev/stderr"):
        return True
    return r == _ROOT or r.startswith(_ROOT + os.sep)


def _db_inside(db):
    """A database path is inside scratch, or in memory. URIs (file:...?mode=...) are read by their path part."""
    d = os.fsdecode(db) if isinstance(db, (bytes, os.PathLike)) else str(db or "")
    if d in ("", ":memory:") or d.startswith("file::memory:"):
        return True
    if d.startswith("file:"):
        d = d[5:].split("?", 1)[0]
    return _inside(d)


_FD_PATHS = {}           # fd -> (absolute path, st_dev, st_ino) for fds this child opened through os.open (dir_fd-relative calls)


def _full(path, dir_fd, what):
    """critic S4 rerun 2 (X5): the open/mkdir/... audit events carry no dir_fd, so a dir_fd-relative call is resolved here. A dir_fd the
    fence did not open itself is refused."""
    if isinstance(path, int):                       # an fd given as the path (fchmod-style)
        return _fd_base(path, what + " on an fd the fence did not open")
    if dir_fd is None:
        return os.fsdecode(path) if isinstance(path, bytes) else path
    return os.path.join(_fd_base(dir_fd, what + " with a dir_fd the fence did not open"),
                        os.fsdecode(path) if isinstance(path, bytes) else str(path))


def _fd_base(fd, why):
    """The path an fd names, only if the fence opened it AND it still is that file (a reused or dup'ed fd number fails the identity
    check, so a stale record never vouches for another file)."""
    rec = _FD_PATHS.get(fd)
    try:
        st = os.fstat(fd)
    except OSError:
        st = None
    if not rec or st is None or (st.st_dev, st.st_ino) != rec[1:]:
        _refuse(why, fd)
    return rec[0]


def _fence_dir_fd():
    """Wrap the os (and posix) functions that take dir_fd: judge the resolved path, keep an fd -> path map for os.open."""
    import posix
    real = {n: getattr(os, n) for n in ("open", "close", "mkdir", "rmdir", "unlink", "remove", "rename", "replace", "link", "symlink",
                                         "chmod", "chown", "utime", "mkfifo", "mknod") if hasattr(os, n)}

    def w_open(path, flags, mode=0o777, *, dir_fd=None):
        full = _full(path, dir_fd, "os.open")
        if flags & _WRITE_FLAGS and not _inside(full):
            _refuse("os.open write", full)
        fd = real["open"](path, flags, mode, dir_fd=dir_fd)
        st = os.fstat(fd)
        _FD_PATHS[fd] = (os.path.abspath(full), st.st_dev, st.st_ino)
        return fd

    def w_close(fd):
        _FD_PATHS.pop(fd, None)
        return real["close"](fd)

    def one(name):
        def f(path, *a, dir_fd=None, **k):
            full = _full(path, dir_fd, "os." + name)
            if not _inside(full):
                _refuse("os." + name, full)
            return real[name](path, *a, **({"dir_fd": dir_fd} if dir_fd is not None else {}), **k)
        return f

    def two(name):
        def f(src, dst, *a, src_dir_fd=None, dst_dir_fd=None, **k):
            for p_, fd_ in ((src, src_dir_fd), (dst, dst_dir_fd)):
                full = _full(p_, fd_, "os." + name)
                if not _inside(full):
                    _refuse("os." + name, full)
            extra = {}
            if src_dir_fd is not None:
                extra["src_dir_fd"] = src_dir_fd
            if dst_dir_fd is not None:
                extra["dst_dir_fd"] = dst_dir_fd
            return real[name](src, dst, *a, **extra, **k)
        return f

    def w_symlink(src, dst, target_is_directory=False, *, dir_fd=None):
        full = _full(dst, dir_fd, "os.symlink")
        if not _inside(full):
            _refuse("os.symlink", full)
        return real["symlink"](src, dst, target_is_directory, **({"dir_fd": dir_fd} if dir_fd is not None else {}))
    wrapped = {"open": w_open, "close": w_close, "symlink": w_symlink}
    for n in ("mkdir", "rmdir", "unlink", "remove", "chmod", "chown", "utime", "mkfifo", "mknod"):
        if n in real:
            wrapped[n] = one(n)
    for n in ("rename", "replace", "link"):
        if n in real:
            wrapped[n] = two(n)
    for n, f in wrapped.items():
        setattr(os, n, f)
        if hasattr(posix, n):
            setattr(posix, n, f)


def _fence_natives():
    """Before any candidate import: stub _posixsubprocess (fork_exec has no audit event) and wrap the sqlite3 and dbm openers so a
    database file outside scratch is refused on every Python (sqlite3.connect has an audit event only from 3.10)."""
    import types
    stub = types.ModuleType("_posixsubprocess")

    def _deny(*a, **k):
        _LOG["refused"].append("_posixsubprocess.fork_exec")
        raise PermissionError("release-sim: _posixsubprocess.fork_exec refused inside the simulator")
    stub.fork_exec = _deny
    sys.modules["_posixsubprocess"] = stub

    def wrap(mod, name, label):
        real = getattr(mod, name, None)
        if real is None or getattr(real, "_sim_wrapped", False):
            return

        def opener(db, *a, **k):
            if not _db_inside(db):
                _refuse(label, db)
            return real(db, *a, **k)
        opener._sim_wrapped = True
        setattr(mod, name, opener)
    for modname, fn in (("_sqlite3", "connect"), ("sqlite3", "connect"), ("sqlite3.dbapi2", "connect"), ("dbm", "open"),
                        ("dbm.gnu", "open"), ("dbm.ndbm", "open"), ("_gdbm", "open"), ("_dbm", "open")):
        try:
            mod = __import__(modname, fromlist=["x"])
            wrap(mod, fn, f"{modname}.{fn}")
        except Exception:
            pass


def _refuse(what, p):
    _LOG["refused"].append(f"{what} {str(p)[:200]}")
    raise PermissionError(f"release-sim: {what} outside the scratch folder refused: {p}")


def _hook(event, args):
    if _IN_HOOK[0]:
        return
    _SEEN.add(event)
    _IN_HOOK[0] = True
    try:
        if event == "open":
            path, mode, flags = (list(args) + [None, None, None])[:3]
            w = (isinstance(mode, str) and any(c in mode for c in "wax+")) or (isinstance(flags, int) and flags & _WRITE_FLAGS)
            if w and not _inside(path):
                _refuse("write", path)
        elif event in ("os.rename", "os.replace", "os.link", "os.symlink"):
            for p in args[:2]:
                if not _inside(p):
                    _refuse(event, p)
        elif event in ("os.remove", "os.rmdir", "os.mkdir", "os.chmod", "os.chown", "os.truncate", "os.utime", "shutil.rmtree",
                       "os.chflags", "os.lchflags", "os.setxattr", "os.removexattr"):
            if args and not _inside(args[0]):
                _refuse(event, args[0])
        elif event in ("os.system", "os.exec", "os.spawn", "os.fork", "os.forkpty", "pty.spawn"):
            _LOG["subprocess"].append([event] + [str(x)[:120] for x in list(args)[:3]])
            _LOG["refused"].append(f"{event} {str(args)[:160]}")      # critic S4 blocker 4: refused, not only logged
            raise PermissionError(f"release-sim: {event} refused inside the simulator")
        elif event in ("subprocess.Popen", "os.posix_spawn"):
            # critic S4 rerun blocker 1: a grandchild has no audit hook, so the child starts NO process at all (the scenario needs none)
            exe, argv = (list(args) + [None, None])[:2]
            argv = [str(x) for x in (argv if isinstance(argv, (list, tuple)) else [argv or exe])]
            _LOG["subprocess"].append(argv)
            _LOG["refused"].append(f"{event} {' '.join(argv)[:160]}")
            raise PermissionError(f"release-sim: {event} refused inside the simulator: {argv[:3]}")
        elif event in ("sqlite3.connect", "dbm.open"):    # critic S4 rerun blocker 2 (3.10+; 3.9 is covered by the wrappers below)
            if args and not _db_inside(args[0]):
                _refuse(event, args[0])
        elif event in ("os.mkfifo", "os.mknod"):
            if args and not _inside(args[0]):
                _refuse(event, args[0])
        elif event == "socket.bind":
            addr = args[1] if len(args) > 1 else None
            if isinstance(addr, (str, bytes)) and not _inside(addr):
                _refuse(event, addr)
        elif event in ("shutil.copyfile", "shutil.copystat", "shutil.copymode", "shutil.copytree", "shutil.move"):
            for p in (args[1:2] if event != "shutil.move" else args[:2]):
                if not _inside(p):
                    _refuse(event, p)
        elif event == "shutil.make_archive":
            if args and not _inside(args[0]):
                _refuse(event, args[0])
        elif event == "shutil.unpack_archive":
            if len(args) > 1 and not _inside(args[1]):
                _refuse(event, args[1])
        elif event in ("tempfile.mkstemp", "tempfile.mkdtemp"):
            if args and not _inside(args[0]):
                _refuse(event, args[0])
        elif event not in SAFE_EVENTS:                     # deny by default
            _LOG["refused"].append(f"unknown audit event {event}")
            raise PermissionError(f"release-sim: audit event {event} is not on the fence's list; refused (deny by default)")
        elif event in ("socket.connect", "socket.sendto", "socket.getaddrinfo"):
            _LOG["net"].append(f"{event} {str(args[1:] if event != 'socket.getaddrinfo' else args[:2])[:160]}")
            raise PermissionError(f"release-sim: network refused ({event})")
    finally:
        _IN_HOOK[0] = False


def _scenario(H, M, home):
    """The fixed agent scenario (spec v3 step 7). Every step reports booleans and ids only, never Do-line text."""
    out, err = {}, []
    h = H.Harness(home)

    def call(name, **kw):
        try:
            M.BOUND.update(home=None, id=None)
        except Exception:
            pass
        return M.call(h, name, kw)

    def step(name, fn):
        try:
            return fn()
        except Exception as e:
            err.append(f"{name}: {type(e).__name__}: {str(e)[:200]}")
            return None
    for r in ("sim-alpha", "sim-beta"):
        step("role_define " + r, lambda r=r: h.role_define("operator", r, "harness-ops", carry="none"))
    reg = lambda role: h.register(project="harness-ops", model="claude-haiku-5-5", task="release-sim", role=role)["id"]
    a, b, c = step("register a", lambda: reg("sim-alpha")), step("register b", lambda: reg("sim-beta")), step("register c", lambda: reg(None))
    if not (a and b and c):
        return {"errors": err}
    s1 = step("send task", lambda: call("harness_send", agent=a, to="role:sim-beta", body="release-sim task", subject="sim", kind="task")) or {}
    mid = s1.get("id")
    out["task_sent"] = bool(mid)
    out["send_has_nudge_field"] = "nudge" in s1 or "nudge_skipped" in s1
    offered = any(e.get("type") in ("nudge.offered", "nudge.sent") and (e.get("data") or {}).get("msg") == mid for e in h.store.read_all()[-50:])
    out["offered"] = offered
    if offered:
        r = step("nudge_result", lambda: call("harness_admin", agent=a, op="nudge_result",
                                             args={"msg_id": mid, "outcome": "delivered", "reason": "release-sim"})) or {}
        out["reported"] = bool(r.get("reported"))
    inbox = step("inbox b", lambda: call("harness_inbox", agent=b))
    out["task_in_inbox"] = bool(mid) and mid in json.dumps(inbox, default=str)
    s2 = step("send result", lambda: call("harness_send", agent=b, to=a, body="release-sim result", kind="result", reply_to=mid)) or {}
    out["result_sent"] = bool(s2.get("id"))
    out["sync_ok"] = step("sync a", lambda: call("harness_sync", agent=a)) is not None
    n = step("record", lambda: call("harness_record", agent=c, kind="note", title="release-sim note", body="sim body")) or {}
    nid = n.get("id")
    rc = step("recall", lambda: call("harness_recall", agent=c, ids=[nid], query="release-sim note")) if nid else None
    out["recall_ok"] = bool(nid) and nid in json.dumps(rc, default=str)
    p = step("approval request", lambda: call("harness_admin", agent=a, op="role_define", args={"role": "sim-gamma", "project": "harness-ops"})) or {}
    pid = p.get("pending")
    if pid:
        rec = h._approval_records().get(pid) or {}
        g = step("approve", lambda: h.approve(pid, code=rec.get("args_digest", "")[:4], tty=True)) or {}
        out["approval_granted"] = g.get("state") == "granted"
    else:
        out["approval_granted"] = False
    # I3b (critic S4 blocker 1): a recipient with a (fake, scratch-only) app session id; its Do-line must carry the id and no name
    step("role_define sim-delta", lambda: h.role_define("operator", "sim-delta", "harness-ops", carry="none"))
    dlt = step("register d", lambda: h.register(project="harness-ops", model="claude-haiku-5-5", task="release-sim", role="sim-delta",
                                                host_session_id="local_simdelta")["id"])
    if dlt:
        try:
            import doorbell as D_
            D_.settle(h, dlt)
        except Exception:
            pass
        n = (step("send to d", lambda: call("harness_send", agent=a, to="role:sim-delta", body="release-sim id", kind="task")) or {}).get("nudge")
        do = n.get("do") if isinstance(n, dict) else str(n or "")
        sob = (h.state().agents.get(dlt) or {}).get("sobriquet") or "\x00"
        out["doline_has_id"] = "local_simdelta" in (do or "")
        out["doline_name_free"] = bool(do) and sob not in do and "SIM-DELTA -" not in do.upper() and "LISTAGENTS" not in do.upper()
    out["hooks"] = _hook_probes(home)
    out["errors"] = err
    return out


def _hook_probes(home):
    """I9 (critic S4 blocker 2): the candidate's own H1/H2, through retire_guard's process, on fixed probes. Booleans only."""
    import io, contextlib
    res = {}
    try:
        import retire_guard as RG
    except Exception as e:
        return {"error": f"retire_guard import: {type(e).__name__}"}
    user = os.path.expanduser("~")
    pub = os.path.join(_ROOT, "tmp", "harness-hub", "crew-coordinator")
    os.makedirs(os.path.join(pub, ".claude-plugin"), exist_ok=True)
    with open(os.path.join(pub, ".claude-plugin", "plugin.json"), "w") as f:
        f.write("{}")
    probes = {
        "deny_cache": ("Bash", {"command": "cp x ~/.claude/plugins/cache/crew-coordinator/scripts/"}, True),
        "deny_rpm": ("Bash", {"command": f"rsync -a src/ '{user}/Library/Application Support/Claude/local-agent-mode-sessions/s1/rpm/cc/'"}, True),
        "deny_bin": ("Bash", {"command": f"sed -i '' s/a/b/ {home}/_harness/bin/harness.py"}, True),
        "deny_published": ("Edit", {"file_path": os.path.join(pub, "scripts", "doorbell.py")}, True),
        "allow_ls": ("Bash", {"command": "ls ~/.claude/plugins"}, False),
    }
    for name, (tool, ti, want_deny) in probes.items():
        buf, old_in = io.StringIO(), sys.stdin
        try:
            sys.stdin = io.StringIO(json.dumps({"tool_name": tool, "tool_input": ti, "cwd": _ROOT, "session_id": "sim"}))
            with contextlib.redirect_stdout(buf):
                RG.main()
        except Exception:
            pass
        finally:
            sys.stdin = old_in
        denied = '"deny"' in buf.getvalue()
        res[name] = denied == want_deny
    return res


def main(argv=None):
    global _ROOT
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--scratch", required=True)
    p.add_argument("--candidate", required=True)
    p.add_argument("--action", required=True, choices=("publish", "scenario"))
    p.add_argument("--out", required=True)
    p.add_argument("--replay", action="store_true", help="tests only: publish an old tree over a newer registry entry")
    a = p.parse_args(argv)
    _ROOT = os.path.realpath(a.scratch)
    _fence_natives()                                               # before the hook, so the wrappers' own imports are not judged
    _fence_dir_fd()
    sys.addaudithook(_hook)                                        # before any candidate import
    home = os.path.join(_ROOT, "home")
    res = {"action": a.action}
    try:
        sys.path.insert(0, os.path.join(os.path.realpath(a.candidate), "scripts"))
        import harness as H
        H._SIM_CHILD = True                                        # the candidate's own gate never recurses into a simulator
        if a.action == "publish":
            if a.replay:        # acceptance-test replays of old trees (e.g. 0.21.0): treat the candidate's version as newer
                _info = H.read_plugin(os.path.realpath(a.candidate))
                _orig, _ver = H.vtuple, (_info or (None, None))[1]
                H.vtuple = lambda v, _o=_orig, _c=_ver: (10 ** 6,) if v == _c else _o(v)
            h = H.Harness(home)
            r = h.publish_release(path=os.path.realpath(a.candidate), build=True, override="release-sim",
                                  pkg=os.path.join(_ROOT, "pkg", "candidate.plugin"))
            res["published"] = {k: r.get(k) for k in ("name", "version", "code") if isinstance(r, dict)}
        else:
            import mcp_server as M
            res["scenario"] = _scenario(H, M, home)
            res["approval_actions"] = list(getattr(H.Harness, "APPROVAL_ACTIONS", ()))
    except Exception as e:
        res["error"] = f"{type(e).__name__}: {str(e)[:300]}"
    res["log"] = dict(_LOG, events=sorted(_SEEN))
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(res, f, default=str)
    return 0


if __name__ == "__main__":
    sys.exit(main())
