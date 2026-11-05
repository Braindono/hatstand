"""Critic invariants I7a-I7c for the crew-coordinator release simulator (release-gate spec v3, step S1).

Owner: harness-critic. The ops-coder copies this file byte for byte into tests/ and records its sha. Standard library only, no
model calls. Interface: check(ctx) -> list of failure strings (empty list = pass). `ctx` may be a dict or an object with these fields:
  scratch_home, before, after_publish (paths to sha maps), ledger_before_bytes, ledger_after_bytes, events_written,
  subprocess_log (list of argv lists), net_log (list), installed_root, candidate_root,
  gate_files_allowed (optional: paths the granted scope names as changed gate files).

I7a  no network access, and no subprocess outside the allowlist (catches a push, an upload or a model call, D-f6eaa).
I7b  the ledger is append-only and the appended events extend the hash chain (overlaps I8 on purpose).
I7c  the gate's own files are byte-equal to the installed release's, unless the scope names them.
"""
import ast
import hashlib
import json
import os

GATE_FILES = ("scripts/release_sim.py", "tests/sim_invariants_critic.py", "hooks/hooks.json")
GATE_FUNCS = (("scripts/harness.py", "publish_release"),)        # function-level compare: the rest of harness.py may change
GENESIS = "0" * 64
NO_SUBPROCESS_NAMES = ("curl", "wget", "git", "ssh", "scp", "rsync", "nc", "claude", "gh", "open", "osascript", "security")


def _get(ctx, key, default=None):
    if isinstance(ctx, dict):
        return ctx.get(key, default)
    return getattr(ctx, key, default)


def _real(p):
    return os.path.realpath(os.path.abspath(os.path.expanduser(str(p)))) if p else ""


def _under(path, root):
    path, root = _real(path), _real(root)
    return bool(root) and (path == root or path.startswith(root.rstrip(os.sep) + os.sep))


# ---------------------------------------------------------------------------------------------------------------------- I7a
def _i7a(ctx):
    out = []
    for n in _get(ctx, "net_log") or []:
        out.append(f"I7a network access during publish or scenario: {str(n)[:160]}")
    allowed_roots = [r for r in (_get(ctx, "candidate_root"), _get(ctx, "installed_root"), _get(ctx, "scratch_home")) if r]
    for argv in _get(ctx, "subprocess_log") or []:
        argv = [str(a) for a in (argv if isinstance(argv, (list, tuple)) else [argv])]
        if not argv:
            continue
        exe = os.path.basename(argv[0]).lower()
        if any(exe == b or exe.startswith(b + ".") for b in NO_SUBPROCESS_NAMES):
            out.append(f"I7a forbidden subprocess: {' '.join(argv)[:160]}")
            continue
        if not exe.startswith("python"):
            out.append(f"I7a subprocess outside the allowlist (python only): {' '.join(argv)[:160]}")
            continue
        script = next((a for a in argv[1:] if not a.startswith("-")), None)
        if "-c" in argv[1:]:
            out.append(f"I7a python -c is not allowed: {' '.join(argv)[:160]}")
        elif script and not any(_under(script, r) for r in allowed_roots):
            out.append(f"I7a python runs a script outside the candidate, installed or scratch roots: {script}")
    return out


# ---------------------------------------------------------------------------------------------------------------------- I7b
def _canon(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _event_hash(ev):
    return hashlib.sha256(_canon({k: v for k, v in ev.items() if k != "hash"}).encode("utf-8")).hexdigest()


def _last_hash(raw):
    for line in reversed(raw.splitlines()):
        line = line.strip()
        if line:
            try:
                return json.loads(line).get("hash"), json.loads(line).get("seq")
            except ValueError:
                return None, None
    return GENESIS, 0


def _i7b(ctx):
    before, after = _get(ctx, "ledger_before_bytes"), _get(ctx, "ledger_after_bytes")
    if before is None or after is None:
        return ["I7b ledger bytes missing from ctx: cannot check"]
    before, after = bytes(before), bytes(after)
    if not after.startswith(before):
        return ["I7b ledger is not append-only: the old bytes are not a prefix of the new bytes"]
    prev, seq = _last_hash(before.decode("utf-8", "replace"))
    if prev is None:
        return ["I7b the last pre-publish ledger line does not parse"]
    out = []
    tail = after[len(before):].decode("utf-8", "replace")
    if before and not before.endswith(b"\n") and tail and not tail.startswith("\n"):
        out.append("I7b an appended event was joined onto the last old line")
    for i, line in enumerate(l for l in tail.splitlines() if l.strip()):
        try:
            ev = json.loads(line)
        except ValueError:
            out.append(f"I7b appended line {i + 1} does not parse")
            break
        if ev.get("prev") != prev:
            out.append(f"I7b chain broken at appended event {i + 1} (seq {ev.get('seq')}): prev does not match")
        if _event_hash(ev) != ev.get("hash"):
            out.append(f"I7b appended event {i + 1} (seq {ev.get('seq')}) hash mismatch")
        s = ev.get("seq")
        if isinstance(s, int) and isinstance(seq, int) and s <= seq:
            out.append(f"I7b seq does not increase at appended event {i + 1} ({s} after {seq})")
        prev, seq = ev.get("hash"), s
        if len(out) >= 10:
            break
    return out


# ---------------------------------------------------------------------------------------------------------------------- I7c
def _sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 16), b""):
            h.update(b)
    return h.hexdigest()


def _func_src(path, name):
    try:
        with open(path, encoding="utf-8") as f:
            src = f.read()
        for node in ast.walk(ast.parse(src)):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
                return ast.get_source_segment(src, node)
    except (OSError, SyntaxError, ValueError):
        return None
    return None


def _i7c(ctx):
    inst, cand = _get(ctx, "installed_root"), _get(ctx, "candidate_root")
    if not inst or not cand:
        return ["I7c installed_root or candidate_root missing from ctx: cannot check"]
    allowed = {str(p).replace(os.sep, "/") for p in (_get(ctx, "gate_files_allowed") or [])}
    out = []
    for rel in GATE_FILES:
        a, b = os.path.join(inst, rel), os.path.join(cand, rel)
        if not os.path.isfile(a):
            continue                         # bootstrap: the installed release has no gate yet (the first gated release)
        if rel in allowed:
            continue
        if not os.path.isfile(b):
            out.append(f"I7c gate file removed by the candidate: {rel}")
        elif _sha(a) != _sha(b):
            out.append(f"I7c gate file changed but the scope does not name it: {rel}")
    for rel, fn in GATE_FUNCS:
        a, b = _func_src(os.path.join(inst, rel), fn), _func_src(os.path.join(cand, rel), fn)
        if a is None or f"{rel}::{fn}" in allowed:
            continue
        if not os.path.isfile(os.path.join(inst, GATE_FILES[0])):
            continue                        # bootstrap: no gate installed, so publish_release is not yet a gate
        if b is None:
            out.append(f"I7c gate function removed by the candidate: {rel}::{fn}")
        elif a != b:
            out.append(f"I7c gate function changed but the scope does not name it: {rel}::{fn}")
    return out


def check(ctx):
    out = []
    for f in (_i7a, _i7b, _i7c):
        try:
            out += f(ctx)
        except Exception as e:                # a crash in a check is a failure, never a pass
            out.append(f"{f.__name__[1:].upper()} check crashed: {e!r}")
    return out
