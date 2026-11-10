#!/usr/bin/env python3
"""cc 0.22.0 release simulator (release-gate spec v3, scope A-4f925 successor A-76243). Standard library only, 0 model tokens.

Run it from the INSTALLED release; the candidate's code runs only as a child (sim_launcher.py) fenced inside a scratch folder:
  python3 -I -B <installed>/scripts/release_sim.py --candidate <tree> [--home <Exchange>] [--report-dir D] [--json]
Steps: sweep leftovers, copy <home>/_harness and _harness_anchors to a 0700 scratch folder, hash it, run the candidate's publish,
hash again (I1, I2), run a fixed agent scenario, check I3 to I8 plus the critic's I7 (tests/sim_invariants_critic.py of the
INSTALLED release), list one structured question per change, and delete the scratch folder. Exit 0 pass, 1 fail, 2 error.
The report never carries Do-line text (it holds real session and trigger ids)."""
import argparse
import ast
import difflib
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
INSTALLED = os.path.dirname(HERE)
PREFIX = "hsim-"
COPY_DIRS = ("_harness", "_harness_anchors")
SKIP_NAMES = ("__pycache__",)
# Paths a publish owns (relative to the home). I1 never reports them; events.jsonl has its own check (I8).
OWNED_RE = [re.compile(p) for p in (
    r"^_harness/events\.jsonl$", r"^_harness/registry\.json(\..*)?$", r"^_harness/[^/]+\.lock$", r"^_harness/corpus\.stamp$",
    r"^_harness/marketplace/", r"^_harness/bin/[^/]+\.py$", r"^_harness/(bin|data)/\.mirrored\.json$",
    r"^_harness_anchors/anchors\.jsonl$", r"^_harness/release_prehash\.json$", r"\.tmp$")]
# Deletions that need no archive copy (derived trees and temp files).
NO_ARCHIVE_RE = [re.compile(p) for p in (r"^_harness/marketplace/", r"\.tmp$", r"\.lock$", r"^_harness/registry\.json\.")]
SIM_PROVOKED_EVENTS = ("release.gate_override",)   # the simulator publishes with an override; the normal path does not write it
GATE_FILES = ("scripts/release_sim.py", "scripts/sim_launcher.py", "tests/sim_invariants_critic.py", "hooks/hooks.json",
              "scripts/release_guard.py", "scripts/retire_guard.py")   # critic S4 blocker 2: the hooks are gate files
GATE_FUNCS = (("scripts/harness.py", "publish_release"), ("scripts/harness.py", "_release_gate"))
WRITE_RE = re.compile(r"open\([^)]*['\"][wax]|os\.(replace|rename|remove|unlink|rmdir|makedirs|mkdir)\(|shutil\.(move|copy\w*|rmtree)\(|"
                      r"_atomic_write\(|\.write_text\(|\b_save\(")
EVENT_RE = re.compile(r"\.append\(\s*[\"']([a-z0-9_]+\.[a-z0-9_.]+)[\"']")
QFILE = "release-questions.md"
Q_RE = re.compile(r"^##\s+(Q-[0-9a-f]{8})\b.*?$\n(?:.*\n)*?^Answer:[ \t]*(.*)$", re.M)


def _sha_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 16), b""):
            h.update(b)
    return h.hexdigest()


def hash_tree(home):
    """{home-relative path: sha256} over COPY_DIRS, never following a symlink."""
    out = {}
    for top in COPY_DIRS:
        base = os.path.join(home, top)
        for dp, dns, fns in os.walk(base):
            dns[:] = [d for d in dns if d not in SKIP_NAMES and not os.path.islink(os.path.join(dp, d))]
            for fn in fns:
                fp = os.path.join(dp, fn)
                if os.path.islink(fp) or not os.path.isfile(fp):
                    continue
                out[os.path.relpath(fp, home).replace(os.sep, "/")] = _sha_file(fp)
    return out


def _owned(rel, carried):
    return any(r.search(rel) for r in OWNED_RE) or rel in carried


def check_i1_i2(before, after, carried):
    """I1 local data survives; I2 archive never delete. `carried`: home paths the candidate package itself provides."""
    i1, i2 = [], []
    archived = {}
    for rel, sha in after.items():
        if "/_archive/" in "/" + rel:
            archived.setdefault(sha, []).append(rel)
    for rel, sha in sorted(before.items()):
        gone = rel not in after
        if gone and not any(r.search(rel) for r in NO_ARCHIVE_RE) and sha not in archived:
            i2.append(f"I2 deleted without an archive copy: {rel}")
        if _owned(rel, carried):
            continue
        if gone:
            i1.append(f"I1 local file {'archived' if sha in archived else 'removed'}: {rel}")
        elif after[rel] != sha:
            i1.append(f"I1 local file changed: {rel}")
    return i1, i2


def ledger_events(raw):
    out = []
    for line in raw.decode("utf-8", "replace").splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except ValueError:
                out.append({"type": "_corrupt"})
    return out


def _event_hash(ev):
    body = {k: v for k, v in ev.items() if k != "hash"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()


def check_i8(before, after):
    """I8 the ledger is append-only and the appended events extend the hash chain."""
    if not after.startswith(before):
        return ["I8 ledger rewritten: the old bytes are not a prefix of the new bytes"]
    prev = None
    for line in reversed(before.decode("utf-8", "replace").splitlines()):
        if line.strip():
            prev = json.loads(line).get("hash")
            break
    prev = prev or "0" * 64
    out = []
    for ev in ledger_events(after[len(before):]):
        if ev.get("prev") != prev or _event_hash(ev) != ev.get("hash"):
            out.append(f"I8 chain broken at appended seq {ev.get('seq')}")
            break
        prev = ev.get("hash")
    return out


def approval_actions(root):
    try:
        with open(os.path.join(root, "scripts", "harness.py"), encoding="utf-8") as f:
            tree = ast.parse(f.read())
    except (OSError, SyntaxError):
        return None
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == "APPROVAL_ACTIONS" for t in node.targets):
            try:
                return list(ast.literal_eval(node.value))
            except ValueError:
                return None
    return None


def check_i5(installed, candidate, allowed):
    a, b = approval_actions(installed), approval_actions(candidate)
    if a is None or b is None:
        return ["I5 approval actions unreadable"]
    out = []
    for n in sorted(set(a) ^ set(b)):
        if n not in allowed:
            out.append(f"I5 approval action {'added' if n in b else 'removed'} without scope: {n}")
    return out


def documented_events(root):
    """Every backticked event name in the first cell of an EVENTS.md table row (a row may list several: `a.b` / `a.c`)."""
    try:
        with open(os.path.join(root, "docs", "EVENTS.md"), encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return set()
    out = set()
    for line in text.splitlines():
        if line.startswith("|"):
            cell = line.split("|")[1] if line.count("|") >= 2 else ""
            out |= set(re.findall(r"`([a-z0-9_]+\.[a-z0-9_.]+)`", cell))
    return out


# ------------------------------------------------------------------------------------------------ structured questions (Q)
def _py_files(root):
    d = os.path.join(root, "scripts")
    return sorted(f for f in os.listdir(d) if f.endswith(".py")) if os.path.isdir(d) else []


def _read(p):
    try:
        with open(p, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""


def _func_at(src):
    """line number -> enclosing top-level or method function name."""
    m = {}
    try:
        for node in ast.walk(ast.parse(src)):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for ln in range(node.lineno, (getattr(node, "end_lineno", node.lineno) or node.lineno) + 1):
                    m.setdefault(ln, node.name)
    except SyntaxError:
        pass
    return m


def _func_src(path, name):
    src = _read(path)
    try:
        for node in ast.walk(ast.parse(src)):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
                return ast.get_source_segment(src, node)
    except SyntaxError:
        return None
    return None


def _seg(lines, node):
    """Source text of a node's whole lines. ast.get_source_segment re-splits the entire file on every call (6852 calls over harness.py's
    8000 lines made questions() take minutes: D-b23ac), so slice the split lines once instead."""
    return "\n".join(lines[node.lineno - 1:(getattr(node, "end_lineno", node.lineno) or node.lineno)])


def _do_funcs(src):
    """Names of functions whose body contains the text "Do:" (cc 0.22.4: continuation lines of a Do-line string)."""
    out, lines = set(), src.split("\n")
    try:
        for node in ast.walk(ast.parse(src)):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and "Do:" in _seg(lines, node):
                out.add(node.name)
    except SyntaxError:
        pass
    return out


def _do_names(src):
    """Names read inside a function that holds "Do:" (cc 0.22.4b: a module constant that feeds a Do-line)."""
    out, lines = set(), src.split("\n")
    try:
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and "Do:" in _seg(lines, node):
                out |= {n.id for n in ast.walk(node) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}
    except SyntaxError:
        pass
    return out


def _module_assign(src):
    """line number -> name, for every line of a module-level assignment."""
    m = {}
    try:
        for node in ast.parse(src).body:
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                tg = node.targets if isinstance(node, ast.Assign) else [node.target]
                nm = [t.id for t in tg if isinstance(t, ast.Name)]
                for ln in range(node.lineno, (getattr(node, "end_lineno", node.lineno) or node.lineno) + 1):
                    for n in nm:
                        m.setdefault(ln, n)
    except SyntaxError:
        pass
    return m


def _append_funcs(src):
    """Names of functions whose body holds a store.append( call (cc 0.22.4b: a payload built before the call)."""
    out, lines = set(), src.split("\n")
    try:
        for node in ast.walk(ast.parse(src)):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and "store.append(" in _seg(lines, node):
                out.add(node.name)
    except SyntaxError:
        pass
    return out


def _ends_with_store(lines, v):
    """True when the text of the expression `v` (the object of `.append`) ends with `store` (self.store, h.store, store)."""
    try:
        ln = lines[(getattr(v, "end_lineno", v.lineno) or v.lineno) - 1]
        return ln.encode("utf-8")[:v.end_col_offset].decode("utf-8", "ignore").endswith("store")
    except (IndexError, AttributeError):
        return False


def _append_lines(src):
    """line number -> start line of the enclosing `store.append(` call (cc 0.22.4: new field on an existing event type)."""
    m, lines = {}, src.split("\n")
    try:
        for node in ast.walk(ast.parse(src)):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "append" \
                    and _ends_with_store(lines, node.func.value):
                for ln in range(node.lineno, (getattr(node, "end_lineno", node.lineno) or node.lineno) + 1):
                    m.setdefault(ln, node.lineno)
    except SyntaxError:
        pass
    return m


def _qid(cls, key):
    return "Q-" + hashlib.sha256(f"{cls}|{key}".encode()).hexdigest()[:8]


def questions(installed, candidate):
    """One question per change in six classes, against the installed release. -> [{id, cls, key, text}]"""
    qs = {}

    def add(cls, key, text):
        qs.setdefault(_qid(cls, key), {"id": _qid(cls, key), "cls": cls, "key": key, "text": text})
    for fn in sorted(set(_py_files(candidate)) | set(_py_files(installed))):
        new, old = _read(os.path.join(candidate, "scripts", fn)), _read(os.path.join(installed, "scripts", fn))
        nl, ol = new.splitlines(), old.splitlines()
        fmap, omap = _func_at(new), _func_at(old)
        dnew, dold = _do_funcs(new), _do_funcs(old)
        nnew, nold = _do_names(new), _do_names(old)
        massign_new, massign_old = _module_assign(new), _module_assign(old)
        fnew, fold = _append_funcs(new), _append_funcs(old)
        anew, aold = _append_lines(new), _append_lines(old)
        groups = {}                   # (cls, where) -> changed lines; added AND deleted lines count (critic S4 blocker 2)
        for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, ol, nl, autojunk=False).get_opcodes():
            if tag == "equal":
                continue
            changed = [(nl[j], fmap.get(j + 1, "<module>"), "+", dnew, anew.get(j + 1), nnew, massign_new.get(j + 1), fnew) for j in range(j1, j2)] + \
                      [(ol[i], omap.get(i + 1, "<module>"), "-", dold, aold.get(i + 1), nold, massign_old.get(i + 1), fold) for i in range(i1, i2)]
            for line, fnn, sign, dset, acall, nset, massign, aset in changed:
                where = f"scripts/{fn}::{fnn}"
                if WRITE_RE.search(line):
                    groups.setdefault(("write", where), []).append(sign + line.strip())
                if "Do:" in line or fnn in dset or (massign and massign in nset):   # 0.22.4: any changed line in a function that holds a Do: string; 0.22.4b: or a module constant such a function reads
                    groups.setdefault(("doline", where), []).append(sign + line.strip())
                if acall is not None or "store.append(" in line or fnn in aset:     # 0.22.4: any changed line of a store.append( call; 0.22.4b: or of a function that holds one
                    groups.setdefault(("event_call", where), []).append(sign + line.strip())
        for (cls, where), lines in sorted(groups.items()):
            # critic S4 blocker 1: the id carries a hash of the changed lines, so last release's answer never covers a new change
            key = f"{where}#{hashlib.sha256(chr(10).join(lines).encode()).hexdigest()[:8]}"
            if cls == "write":
                add(cls, key, f"File write changed in {where} ({len(lines)} line(s)). Which path does it write, and what if that path "
                              "already holds local data the package does not own?")
            elif cls == "event_call":
                add("event", key, f"store.append( call, or a function that holds one, changed in {where} ({len(lines)} line(s)): a new field or "
                                  "changed payload on an event type. Who reads it, and is docs/EVENTS.md current?")
            else:
                add(cls, key, f"Do-line text changed in {where} ({len(lines)} line(s)). Which sender acts on it, and what if that sender "
                              "lacks the tool it names?")
        for ev in sorted(set(EVENT_RE.findall(new)) ^ set(EVENT_RE.findall(old))):
            add("event", ev, f"Event type {ev} {'added' if ev in EVENT_RE.findall(new) else 'no longer written'}. Who reads it, and is "
                             "docs/EVENTS.md current?")
    a, b = approval_actions(installed) or [], approval_actions(candidate) or []
    for n in sorted(set(a) ^ set(b)):
        add("approval", n, f"Approval action {n} {'added' if n in b else 'removed'}. What does the operator see on the card, and what breaks for a caller?")
    def hk(r):
        d = json.loads(_read(os.path.join(r, "hooks", "hooks.json")) or "{}").get("hooks") or {}
        return {(ev, x.get("matcher"), h.get("command")) for ev, v in d.items() for x in v for h in x.get("hooks") or []}
    try:
        for ev, mt, cmd in sorted(hk(installed) ^ hk(candidate), key=str):
            add("hook", f"{ev}::{mt}::{cmd}", f"Hook changed: {ev} matcher {mt!r}. Which tool calls does it now see, and what if it fails?")
    except ValueError:
        add("hook", "hooks.json", "hooks.json does not parse in one of the trees.")
    for rel in GATE_FILES:
        if _read(os.path.join(installed, rel)) != _read(os.path.join(candidate, rel)):
            add("gate", rel, f"Gate file changed: {rel}. How does the installed simulator still catch a bad tree with this change?")
    for rel, fn in GATE_FUNCS:
        if _func_src(os.path.join(installed, rel), fn) != _func_src(os.path.join(candidate, rel), fn):
            add("gate", f"{rel}::{fn}", f"Gate function changed: {rel}::{fn}. How does the installed simulator still catch a bad tree?")
    return sorted(qs.values(), key=lambda q: (q["cls"], q["key"]))


def answers(candidate):
    return {m.group(1): m.group(2).strip() for m in Q_RE.finditer(_read(os.path.join(candidate, QFILE)))}


def questions_md(qs, ans):
    lines = ["# Release questions", "", "One question per change against the installed release. Answer every one; the gate fails on a blank answer.", ""]
    for q in qs:
        lines += [f"## {q['id']} {q['cls']}: {q['key']}", q["text"], f"Answer: {ans.get(q['id'], '')}", ""]
    return "\n".join(lines)


# ------------------------------------------------------------------------------------------------ the run
def sweep(base):
    """Archive (never delete) simulator folders a killed run left behind."""
    arch = os.path.join(base, PREFIX + "archive")
    for n in os.listdir(base):
        p_ = os.path.join(base, n)
        if n.startswith(PREFIX) and n != PREFIX + "archive" and os.path.isdir(p_) and time.time() - os.path.getmtime(p_) > 7200:   # never a live concurrent run
            os.makedirs(arch, mode=0o700, exist_ok=True)
            try:
                os.replace(os.path.join(base, n), os.path.join(arch, n))
            except OSError:
                pass


def _child_env(scratch):
    user = os.path.join(scratch, "user")
    env = {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "HOME": user, "HARNESS_HOME": os.path.join(scratch, "home"),
           "HARNESS_STATE_DIR": os.path.join(user, ".claude", "crew-coordinator", "state"),
           "HARNESS_INSTALLED_PLUGINS": os.path.join(user, ".claude", "plugins", "installed_plugins.json"),
           "XDG_CACHE_HOME": os.path.join(user, ".cache"), "TMPDIR": os.path.join(scratch, "tmp"), "HARNESS_STATE_CACHE": "0",
           "LANG": "en_US.UTF-8"}
    return env


def _run_child(scratch, candidate, action, timeout, replay=False):
    out = os.path.join(scratch, "log", action + ".json")
    cmd = [sys.executable, "-I", "-B", os.path.join(HERE, "sim_launcher.py"), "--scratch", scratch, "--candidate", candidate,
           "--action", action, "--out", out] + (["--replay"] if replay else [])
    p = subprocess.run(cmd, env=_child_env(scratch), cwd=scratch, capture_output=True, text=True, timeout=timeout)
    try:
        with open(out, encoding="utf-8") as f:
            res = json.load(f)
    except (OSError, ValueError):
        res = {"error": f"child wrote no result (exit {p.returncode}): {(p.stderr or '')[-300:]}"}
    return res


def _ctx_obj(**kw):
    return kw


def run(candidate, home, allow_actions=(), plant=(), timeout=300, keep=False, base=None, replay=False, gate_files=()):
    """-> report dict. Never raises for a candidate failure; raises only for a broken setup (exit 2)."""
    t0 = time.time()
    candidate = os.path.realpath(candidate)
    home = os.path.realpath(home)
    base = base or tempfile.gettempdir()
    sweep(base)
    scratch = tempfile.mkdtemp(prefix=PREFIX, dir=base)
    os.chmod(scratch, 0o700)
    rep = {"candidate": candidate, "installed": INSTALLED, "checks": {}, "failed": []}
    try:
        sh = os.path.join(scratch, "home")
        for d in ("home", "user/.config/crew-coordinator", "user/.claude/crew-coordinator/state", "user/.claude/plugins", "user/.cache",
                  "tmp", "log", "pkg"):
            os.makedirs(os.path.join(scratch, d), mode=0o700, exist_ok=True)
        for top in COPY_DIRS:
            src = os.path.join(home, top)
            if os.path.isdir(src):
                shutil.copytree(src, os.path.join(sh, top), symlinks=True, ignore=shutil.ignore_patterns(*SKIP_NAMES))
        op = os.path.expanduser("~/.config/crew-coordinator/operator.json")
        if os.path.isfile(op):
            dst = os.path.join(scratch, "user/.config/crew-coordinator/operator.json")
            shutil.copyfile(op, dst)
            os.chmod(dst, 0o600)
        for rel in plant:                                    # acceptance test 1: a local file the package does not own
            fp = os.path.join(sh, rel)
            os.makedirs(os.path.dirname(fp), exist_ok=True)
            with open(fp, "w", encoding="utf-8") as f:
                f.write('{"release_sim": "planted local file"}\n')
        led = os.path.join(sh, "_harness", "events.jsonl")
        with open(led, "rb") as f:
            led0 = f.read()
        before = hash_tree(sh)
        pub = _run_child(scratch, candidate, "publish", timeout, replay)
        after = hash_tree(sh)
        scen = _run_child(scratch, candidate, "scenario", timeout)
        with open(led, "rb") as f:
            led1 = f.read()
        carried = {f"_harness/data/{n}" for n in (os.listdir(os.path.join(candidate, "data")) if os.path.isdir(os.path.join(candidate, "data")) else [])}
        c = rep["checks"]
        c["setup"] = [f"publish child: {pub['error']}"] if pub.get("error") else []
        c["I1"], c["I2"] = check_i1_i2(before, after, carried)
        s = scen.get("scenario") or {}
        i3 = [f"scenario child: {scen['error']}"] if scen.get("error") else []
        i3 += [f"I3 scenario step failed: {e}" for e in s.get("errors") or []]
        for k in ("task_sent", "send_has_nudge_field", "task_in_inbox", "result_sent", "sync_ok", "recall_ok", "approval_granted"):
            if not s.get(k):
                i3.append(f"I3 {k} is false")
        if s.get("offered") and not s.get("reported"):
            i3.append("I3 the nudge was offered but the sender's report was not accepted")
        for k, msg in (("doline_has_id", "I3b the Do-line to a holder with an app session id does not carry that id"),
                       ("doline_name_free", "I3b the Do-line carries a name, a ROLE row or a ListAgents check (role-only addressing, D-3e5e7)")):
            if not s.get(k):
                i3.append(msg)
        c["I3"] = i3
        hk = s.get("hooks") or {}
        c["I9"] = [f"I9 hook probes: {hk['error']}"] if hk.get("error") else \
                  [f"I9 hook probe failed: {k}" for k in ("deny_cache", "deny_rpm", "deny_bin", "deny_published", "allow_ls") if not hk.get(k)]
        new_events = ledger_events(led1[len(led0):]) if led1.startswith(led0) else []
        docs = documented_events(candidate)
        c["I4"] = [f"I4 event type written but not in docs/EVENTS.md: {t}" for t in
                   sorted({e.get("type") for e in new_events} - docs - set(SIM_PROVOKED_EVENTS) - {"_corrupt", None})]
        c["I5"] = check_i5(INSTALLED, candidate, set(allow_actions))
        c["I6"] = [f"I6 write outside scratch refused ({who}): {r}" for who, res in (("publish", pub), ("scenario", scen))
                   for r in (res.get("log") or {}).get("refused") or []]
        c["I8"] = check_i8(led0, led1)
        critic = os.path.join(INSTALLED, "tests", "sim_invariants_critic.py")
        if os.path.isfile(critic):
            try:
                spec = importlib.util.spec_from_file_location("sim_invariants_critic", critic)
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                logs = [(r.get("log") or {}) for r in (pub, scen)]
                c["I7"] = list(mod.check(_ctx_obj(
                    scratch_home=sh, before=before, after_publish=after, ledger_before_bytes=led0, ledger_after_bytes=led1,
                    events_written=[e.get("type") for e in new_events], subprocess_log=[x for l in logs for x in l.get("subprocess") or []],
                    net_log=[x for l in logs for x in l.get("net") or []], installed_root=INSTALLED, candidate_root=candidate,
                    gate_files_allowed=list(gate_files))))
            except Exception as e:
                c["I7"] = [f"I7 critic module crashed: {e!r}"]
        else:
            c["I7"] = ["I7 tests/sim_invariants_critic.py missing from the installed release"]
        qs = questions(INSTALLED, candidate)
        ans = answers(candidate)
        open_q = [q["id"] for q in qs if not ans.get(q["id"])]
        c["Q"] = [f"Q unanswered: {i}" for i in open_q]
        rep["questions"], rep["open_questions"] = len(qs), len(open_q)
        rep["questions_md"] = questions_md(qs, ans)
        # Operator ruling D-5f5c9 (11-04): the FENCE is log-only in 0.22.0. Its findings (I6 and the critic's I7a) are reported under
        # fence_log and never fail the gate. The refusals themselves still happen, so no write lands outside scratch. Every other check
        # still blocks (setup, I1-I5, I7b/c, I8, I9, questions, drift in G): a publish or scenario that crashed, even on a fence refusal,
        # left the release unverified, so it blocks.
        fence = lambda x: x.startswith(("I6 ", "I7a "))
        allc = [x for k in ("setup", "I1", "I2", "I3", "I4", "I5", "I6", "I7", "I8", "I9", "Q") for x in c.get(k) or []]
        rep["fence_log"] = [x for x in allc if fence(x)]
        rep["failed"] = [x for x in allc if not fence(x)]
        rep["ok"] = not rep["failed"]
    finally:
        if keep:
            rep["scratch"] = scratch
        else:
            shutil.rmtree(scratch, ignore_errors=True)
    rep["seconds"] = round(time.time() - t0, 1)
    return rep


def write_report(rep, report_dir, candidate):
    base = os.path.join(report_dir, os.path.basename(os.path.realpath(candidate)))
    md = rep.pop("questions_md", "")
    with open(base + ".release-sim.json", "w", encoding="utf-8") as f:
        json.dump(rep, f, indent=1)
    with open(base + ".release-questions.template.md", "w", encoding="utf-8") as f:
        f.write(md)
    lines = [f"# Release simulator: {'PASS' if rep.get('ok') else 'FAIL'}", "", f"Candidate: {rep['candidate']}", f"Installed: {rep['installed']}",
             f"Seconds: {rep.get('seconds')}", f"Questions: {rep.get('questions')} ({rep.get('open_questions')} unanswered)", ""]
    for k, v in (rep.get("checks") or {}).items():
        lines.append(f"- {k}: {'ok' if not v else str(len(v)) + (' logged (fence, log-only)' if k == 'I6' else ' failing')}")
        lines += [f"  - {x}" for x in v[:20]]
    if rep.get("fence_log"):
        lines += ["", f"Fence (log-only, operator ruling D-5f5c9): {len(rep['fence_log'])} finding(s); they do not fail the gate."]
    with open(base + ".release-sim.md", "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return base


def main(argv=None):
    p = argparse.ArgumentParser(prog="release_sim", description=__doc__.splitlines()[0])
    p.add_argument("--candidate", required=True, help="the candidate plugin tree")
    p.add_argument("--home", default=os.environ.get("HARNESS_HOME") or os.path.expanduser("~/Claude/Projects/Exchange"))
    p.add_argument("--allow-actions", default="", help="approval action names the release scope adds or removes, comma separated")
    p.add_argument("--gate-files", default="", help="gate files the release scope names as changed, comma separated (path or path::function)")
    p.add_argument("--plant", action="append", default=[], help="home-relative local file to plant in the scratch copy (tests)")
    p.add_argument("--report-dir", help="write <tree>.release-sim.json/.md and the questions template here")
    p.add_argument("--json", action="store_true", help="print the report as one JSON line")
    p.add_argument("--keep", action="store_true", help="keep the scratch folder (debug)")
    p.add_argument("--replay", action="store_true", help="tests only: replay an old tree whose version is not newer than the registry")
    a = p.parse_args(argv)
    try:
        rep = run(a.candidate, a.home, [x.strip() for x in a.allow_actions.split(",") if x.strip()], a.plant, keep=a.keep, replay=a.replay,
                  gate_files=[x.strip() for x in a.gate_files.split(",") if x.strip()])
    except Exception as e:
        print(json.dumps({"ok": False, "error": f"{type(e).__name__}: {e}"}))
        return 2
    if a.report_dir:
        write_report(dict(rep), a.report_dir, a.candidate)
    rep.pop("questions_md", None)
    print(json.dumps(rep) if a.json else json.dumps({k: rep.get(k) for k in ("ok", "failed", "fence_log", "questions", "open_questions", "seconds")}, indent=1))
    return 0 if rep.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
