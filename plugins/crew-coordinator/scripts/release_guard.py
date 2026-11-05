#!/usr/bin/env python3
"""cc 0.22.0 release-gate hooks (spec v3: H1, H2, H3). Guardrails only: the gate is G inside publish_release.

H1 (PreToolUse, Bash): deny a command that writes into an installed plugin copy (~/.claude/plugins/, the desktop app's synced
   copies under local-agent-mode-sessions/.../rpm/) or into the Exchange mirror <home>/_harness/bin, or over a package-carried file
   in <home>/_harness/data (the names in data/.mirrored.json; local files there stay editable).
H2 (PreToolUse, Edit/Write/MultiEdit/NotebookEdit): deny an edit inside a published tree, harness-hub/<plugin>/ with a
   .claude-plugin/plugin.json.
   H1 and H2 run inside retire_guard.py (one process per tool call, no new hook process) and never import harness.py.
H3 (PostToolUse, `release_guard.py post`): after a publish that wrote release.published, compare the real home with the list
   G saved just before (release_prehash.json), write release.postcheck {ok, failures}, and on failure add a Do-line.
Every path fails open: an error lets the call through. Known bypasses (python -c, other shells, unlisted MCP tools) are why G and
the drift check, not these hooks, do the guarding."""
import json
import os
import re
import shlex
import sys
import time

WRITE_DEST_LAST = ("cp", "mv", "rsync", "install", "ln", "ditto")
WRITE_ANY = ("tee", "rm", "chmod", "touch", "truncate", "unzip", "tar")
EDIT_TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit")
PUBLISH_RE = re.compile(r"harness\.py\b.*\bpublish\b")


def _norm(p, cwd=None):
    p = os.path.expandvars(os.path.expanduser(str(p)))
    if cwd and not os.path.isabs(p):
        p = os.path.join(cwd, p)
    return os.path.realpath(os.path.abspath(p))


def protected(path, home):
    """-> a short reason when `path` is an installed copy or a mirror file, else None."""
    p = _norm(path)
    hm = os.path.realpath(os.path.expanduser("~"))
    if p.startswith(os.path.join(hm, ".claude", "plugins") + os.sep):
        return "the installed plugin cache (~/.claude/plugins)"
    if "/local-agent-mode-sessions/" in p and "/rpm/" in p:
        return "a desktop chat's synced plugin copy"
    if home:
        hb = os.path.join(os.path.realpath(home), "_harness")
        if p.startswith(os.path.join(hb, "bin") + os.sep):
            return "the Exchange code mirror (_harness/bin)"
        dd = os.path.join(hb, "data")
        if os.path.dirname(p) == dd:
            try:
                with open(os.path.join(dd, ".mirrored.json"), encoding="utf-8") as f:
                    if os.path.basename(p) in (json.load(f).get("files") or []):
                        return "a package-carried data file (_harness/data)"
            except (OSError, ValueError, AttributeError):
                pass
    return None


def _segments(cmd):
    return [s for s in re.split(r"\s*(?:&&|\|\||;|\||\n)\s*", cmd or "") if s.strip()]


def bash_targets(cmd):
    """Paths a shell command may write: redirection targets, the destination of cp/mv/..., every argument of tee/rm/...,
    and the file of sed -i. Best effort, by design."""
    out = []
    for m in re.finditer(r"(?<![<0-9&])>>?\s*([^\s;&|]+)", cmd or ""):
        out.append(m.group(1))
    for seg in _segments(cmd):
        try:
            tok = shlex.split(seg)
        except ValueError:
            tok = seg.split()
        while tok and ("=" in tok[0] and not tok[0].startswith("-")) or (tok and tok[0] in ("sudo", "command", "env")):
            tok = tok[1:]
        if not tok:
            continue
        exe, args = os.path.basename(tok[0]), [t for t in tok[1:] if not t.startswith("-")]
        if exe in WRITE_DEST_LAST and args:
            out.append(args[-1])
        elif exe in WRITE_ANY:
            out += args
        elif exe in ("sed", "gsed", "perl") and any(t.startswith("-i") or t == "-pi" for t in tok[1:]):
            out += args[1:] if exe != "perl" else args
    return out


def pre_check(inp, home):
    """-> a deny reason, or None. H1 for Bash, H2 for the edit tools."""
    tool, ti = str(inp.get("tool_name") or ""), inp.get("tool_input") if isinstance(inp.get("tool_input"), dict) else {}
    cwd = inp.get("cwd") or os.getcwd()
    if tool == "Bash":
        for t in bash_targets(str(ti.get("command") or "")):
            why = protected(_norm(t, cwd), home)
            if why:
                return (f"RELEASE GATE (H1): this command writes into {why}. Installed code changes only through a release: build in a "
                        "sibling folder, then `harness.py publish` (the gate runs there). Restore local data from _archive with "
                        "the curator if a publish moved it.")
    elif tool in EDIT_TOOLS:
        fp = ti.get("file_path") or ti.get("notebook_path")
        if fp:
            p = _norm(fp, cwd)
            parts = p.split(os.sep)
            if "harness-hub" in parts:
                i = parts.index("harness-hub")
                if i + 1 < len(parts) - 1:
                    tree = os.sep.join(parts[:i + 2])
                    if os.path.isfile(os.path.join(tree, ".claude-plugin", "plugin.json")):
                        return (f"RELEASE GATE (H2): {tree} is a published tree; never edit it. Copy it to a sibling build folder "
                                "(specs/<name>-build), change that, and publish through the gate.")
            why = protected(p, home)
            if why:
                return f"RELEASE GATE (H1): this edit writes into {why}. Installed code changes only through a release."
    return None


# ---------------------------------------------------------------------------------------------------------------------- H3
def _published_after(home, t):
    p = os.path.join(home, "_harness", "events.jsonl")
    with open(p, "rb") as f:
        f.seek(max(0, os.path.getsize(p) - (1 << 20)))
        tail = f.read().decode("utf-8", "replace").splitlines()[1:]
    for line in reversed(tail):
        if '"release.published"' in line:
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if float(e.get("t") or 0) >= t:
                return e
    return None


def post_check(inp, home):
    """H3. -> additionalContext text, or None. Writes release.postcheck when a publish ran after G saved its list."""
    tool, ti = str(inp.get("tool_name") or ""), inp.get("tool_input") if isinstance(inp.get("tool_input"), dict) else {}
    if tool == "Bash":
        cmd = str(ti.get("command") or "")
        if not PUBLISH_RE.search(cmd) or "--dry-run" in cmd:
            return None
    elif tool.endswith("harness_admin"):
        a = ti.get("args") if isinstance(ti.get("args"), dict) else {}
        if ti.get("op") != "publish_release" or a.get("dry_run"):
            return None
    else:
        return None
    pre_p = os.path.join(home, "_harness", "release_prehash.json")
    try:
        with open(pre_p, encoding="utf-8") as f:
            pre = json.load(f)
    except (OSError, ValueError):
        return None
    if pre.get("checked") or time.time() - float(pre.get("t") or 0) > 7200:
        return None
    ev = _published_after(home, float(pre.get("t") or 0))
    if not ev:
        return None
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import release_sim as RS
    import harness as H
    now = RS.hash_tree(home)
    i1, i2 = RS.check_i1_i2(pre.get("hashes") or {}, now, {f"_harness/data/{n}" for n in pre.get("carried") or []})
    fails = i1 + i2
    h = H.Harness(home)
    h.store.append("release.postcheck", "system", {"ok": not fails, "failures": fails[:40], "code_sha": pre.get("code"),
                                                    "published_seq": ev.get("seq")})
    pre["checked"] = True
    tmp = pre_p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(pre, f)
    os.replace(tmp, pre_p)
    if not fails:
        return "release.postcheck: ok (local data intact after the publish)."
    return ("release.postcheck FAILED: " + "; ".join(fails[:6]) + ". Do: harness_send to role:curator,role:secretary kind=notice "
            "naming these files; restore them from _archive (archive, never delete).")


def find_home():
    env = os.environ.get("HARNESS_HOME")
    if env:
        return os.path.expanduser(env)
    for c in ("~/Claude/Exchange", "~/Claude/Projects/Exchange", "~/mnt/Exchange"):
        p = os.path.expanduser(c)
        if os.path.isdir(os.path.join(p, "_harness")):
            return p
    return None


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    try:
        inp = json.load(sys.stdin)
        home = find_home()
        if not isinstance(inp, dict) or not home:
            return 0
        if argv[:1] == ["post"]:
            ctx = post_check(inp, home)
            if ctx:
                print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": ctx}}))
        else:
            why = pre_check(inp, home)
            if why:
                print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                                         "permissionDecisionReason": why}}))
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
