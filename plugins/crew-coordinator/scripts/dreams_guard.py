#!/usr/bin/env python3
"""dreams_guard: 0.27.3 D (lucid-dreaming build spec, module M2). PreToolUse hook (matcher Write|Edit|MultiEdit|NotebookEdit|Bash).
Refuses any write under the 99_dreams folder from a session whose cwd is not the lucid project folder (or a folder inside it). Reads stay allowed for everyone.
A write is: Write, Edit, MultiEdit or NotebookEdit on a path under the folder, or a Bash command that redirects (> >> >|), pipes to tee, or runs
mv, cp, rsync, install, ln, rm, rmdir, touch, mkdir, truncate, chmod, chown, dd of=, sed -i or perl -i with a path under the folder (cp, rsync and install: only the
destination counts; mv: source and destination). Also (0.27.3 F): curl -o/--output/--output-dir, wget -O/-P, tar -C/--directory (extracting) and tar -f (creating),
git clone <src> <dest>, find ... -delete, and a wrapper chain such as `env VAR=1 tee path`. A `(cd DIR && ...)` group keeps its cd inside the group; `{ cd DIR; ...; }` keeps it.
A redirect target `&1`, `&2`, `&-` (as in `2>&1`, `>&2`) is a stream, not a file, and is skipped.
Paths are resolved before comparing: ~, $HOME, relative to the session cwd (with a leading `cd`), ../ and symlinks.
Limits (a guard against a stray write by an agent, not a sandbox). NOT seen: `xargs rm` and other xargs/`-exec` writers (find -exec rm), a quoted `bash -c '...'` or `sh -c`,
an interpreter one-liner (python -c, node -e, perl -e without -i), a path built by a variable other than $HOME, a glob that only expands to the folder (a wildcard in the folder name itself),
command substitution $(...), here-documents and process substitution, an `env -C DIR` or `sudo -u` option argument, and a symlink created after the check.
Fail-open: any error logs one line to <state dir>/dreams-guard.log and lets the call through, so no unrelated tool is ever blocked.
A refusal writes the ledger event dreams.write_refused (agent, session_id, tool, path, cwd; never file content) when the ledger is reachable, and denies with the reason.
Depends on: stdlib; harness.py only lazily, on a refusal. Input (stdin JSON): {session_id, cwd, tool_name, tool_input}."""
import json
import os
import re
import shlex
import sys
import time

WRITER_TOOLS = ("Write", "Edit", "MultiEdit", "NotebookEdit")
ALL_ARGS = {"tee", "touch", "mkdir", "rm", "rmdir", "truncate", "chmod", "chown", "ln", "mv", "unlink", "shred"}
DEST_LAST = {"cp", "rsync", "install"}
REDIRECT = re.compile(r"^(?:\d*|&)>>?\|?(.*)$")
WRAPPERS = ("sudo", "command", "env", "nohup", "time")
SPLIT = re.compile(r"\|\||&&|[;|\n]")


def _home():
    return os.path.expanduser("~")


def dreams_root():
    return os.path.realpath(os.path.join(_home(), "Claude", "99_dreams"))


def lucid_root():
    return os.path.realpath(os.path.join(_home(), "Claude", "Code", "lucid"))


def log(msg):
    try:
        d = os.environ.get("HARNESS_STATE_DIR") or os.path.expanduser("~/.claude/crew-coordinator/state")
        os.makedirs(d, mode=0o700, exist_ok=True)
        with open(os.path.join(d, "dreams-guard.log"), "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {msg[:200]}\n")
    except Exception:
        pass


def inside(path, root):
    return path == root or path.startswith(root.rstrip(os.sep) + os.sep)


def resolve(p, cwd):
    """~, $HOME, relative to cwd, ../ and symlinks (realpath also resolves a not-yet-existing tail)."""
    p = p.replace("${HOME}", _home()).replace("$HOME", _home())
    p = os.path.expanduser(p)
    if not os.path.isabs(p):
        p = os.path.join(cwd or os.getcwd(), p)
    return os.path.realpath(p)


def from_lucid(cwd):
    return bool(cwd) and inside(os.path.realpath(os.path.expanduser(cwd)), lucid_root())


def bash_targets(cmd, cwd):
    """-> the resolved paths under the dreams folder that the command writes (empty list when none)."""
    root, hits = dreams_root(), []

    def check(p, c):
        if p and not p.startswith("-") and not re.match(r"^&[\d-]", p):      # `&1`, `&2`, `&-`: a stream, not a file
            r = resolve(p, c)
            if inside(r, root):
                hits.append(r)

    cur, scopes = cwd, []
    for seg in SPLIT.split(cmd):
        seg = seg.strip()
        if seg.lstrip().startswith("("):
            scopes.append(cur)                               # `(cd d && ...)`: the cd ends with the group
        seg = seg.lstrip("({ \t")
        closed = seg.rstrip().endswith(")") and bool(scopes)
        seg = seg.rstrip(") }\t")
        seg = re.sub(r"(\d*&?>>?\|?)", r" \1 ", seg)      # `echo x>f` -> `echo x > f`
        try:
            toks = shlex.split(seg, posix=True)
        except ValueError:
            toks = seg.split()
        if toks:
            cur = _segment(toks, cur, check)
        if closed:
            cur = scopes.pop()
    return hits


def _segment(toks, cur, check):
    """One simple command: its redirects, then its verb. -> the cwd after it (only `cd` changes it)."""
    for i, t in enumerate(toks):                       # redirects: `> p`, `>p`, `2>> p`
        m = REDIRECT.match(t)
        if m:
            check(m.group(1) or (toks[i + 1] if i + 1 < len(toks) else ""), cur)
    words = [t for t in toks if not REDIRECT.match(t)]
    while words and (re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", words[0]) or words[0] in WRAPPERS):
        w = words.pop(0)
        while w in WRAPPERS and words and words[0].startswith("-") and len(words[0]) > 1:
            words.pop(0)                               # `env -i`, `sudo -E`
    if not words:
        return cur
    verb, args = os.path.basename(words[0]), words[1:]
    if verb == "cd" and args:
        return resolve(args[0], cur)
    if verb in ALL_ARGS:
        for a in args:
            check(a, cur)
    elif verb in DEST_LAST:
        pos = [a for a in args if not a.startswith("-")]
        tdir = next((args[j + 1] for j, a in enumerate(args[:-1]) if a in ("-t", "--target-directory")), None)
        check(tdir or (pos[-1] if pos else ""), cur)
    elif verb == "dd":
        for a in args:
            if a.startswith("of="):
                check(a[3:], cur)
    elif verb in ("sed", "perl") and any(a == "-i" or (a.startswith("-i") and len(a) > 2 and a[2] != "-") or a.startswith("--in-place") or
                                          (a.startswith("-") and not a.startswith("--") and "i" in a[1:] and verb == "perl") for a in args):
        for a in args:
            check(a, cur)
    else:
        _tools(verb, args, cur, check)
    return cur


def _opt(args, short, long_):
    """Values of an option given as `-o v`, `-ov`, `--output v` or `--output=v`."""
    out = []
    for j, a in enumerate(args):
        if a in short or a == long_:
            if j + 1 < len(args):
                out.append(args[j + 1])
        elif long_ and a.startswith(long_ + "="):
            out.append(a.split("=", 1)[1])
        elif len(a) > 2 and a[:2] in short and not a.startswith("--"):
            out.append(a[2:])
    return out


def _tools(verb, args, cur, check):
    """curl, wget, tar, git clone, find -delete: the destination forms (0.27.3 F N1)."""
    if verb == "curl":
        for v in _opt(args, ("-o",), "--output") + _opt(args, (), "--output-dir"):
            check(v, cur)
    elif verb == "wget":
        for v in _opt(args, ("-O",), "--output-document") + _opt(args, ("-P",), "--directory-prefix"):
            check(v, cur)
    elif verb == "tar":
        first = args[0] if args and not args[0].startswith("--") else ""
        flags = first.lstrip("-") if re.match(r"^-?[A-Za-z]+$", first) else ""
        extract, create = "x" in flags or "--extract" in args, "c" in flags or "--create" in args
        if extract:
            for v in _opt(args, ("-C",), "--directory"):
                check(v, cur)
        if create:
            vals = _opt(args, ("-f",), "--file")
            if "f" in flags and len(args) > 1 and not vals:
                vals = [args[1]]                             # `tar czf out.tgz src`
            for v in vals:
                check(v, cur)
    elif verb == "git":
        a = list(args)
        while a and a[0] == "-C" and len(a) > 1:
            cur = resolve(a[1], cur)
            a = a[2:]
        if a and a[0] == "clone":
            pos, skip = [], False
            for x in a[1:]:
                if skip:
                    skip = False
                elif x in ("-b", "--branch", "--depth", "-o", "--origin", "-c", "--config", "--reference", "--template", "-j", "--jobs"):
                    skip = True
                elif not x.startswith("-"):
                    pos.append(x)
            if len(pos) >= 2:
                check(pos[1], cur)
            elif pos:
                check(os.path.basename(pos[0].rstrip("/")).removesuffix(".git") or "", cur)
    elif verb == "find" and "-delete" in args:
        for x in args:
            if x.startswith("-") or x in ("(", "!"):
                break
            check(x, cur)


def targets(d):
    """-> [path] under the dreams folder that this tool call writes."""
    tool, ti, cwd = d.get("tool_name"), d.get("tool_input") or {}, d.get("cwd") or os.getcwd()
    if tool in WRITER_TOOLS:
        p = ti.get("file_path") or ti.get("notebook_path") or ""
        r = resolve(p, cwd) if p else ""
        return [r] if r and inside(r, dreams_root()) else []
    if tool == "Bash":
        return bash_targets(str(ti.get("command") or ""), cwd)
    return []


def record(d, path):
    """The ledger event; best effort, never raises."""
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import harness as H
        h = H.Harness()
        st = h.state()
        aid = st.sessions.get(d.get("session_id") or "") or "system"
        h.store.append("dreams.write_refused", aid, {"agent": aid, "session_id": d.get("session_id") or "", "tool": d.get("tool_name"),
                                                    "path": path, "cwd": d.get("cwd") or ""})
    except Exception as e:
        log(f"event not written: {type(e).__name__}: {e}")


def main():
    try:
        d = json.load(sys.stdin)
        if not isinstance(d, dict) or from_lucid(d.get("cwd")):
            return 0
        hit = targets(d)
        if not hit:
            return 0
        record(d, hit[0])
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason":
                          f"DREAMS GUARD: {hit[0]} is under the 99_dreams folder, which only a session started in the lucid project folder may write. "
                          "Reading it is allowed. Ask the lucid project (role:thinker) if a change is needed."}}))
    except Exception as e:   # fail open
        log(f"dreams_guard error: {type(e).__name__}: {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
