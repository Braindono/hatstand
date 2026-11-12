#!/usr/bin/env python3
"""Update the harness-local plugins installed in the Claude Code CLI (cc 0.24.0, scope A-b2950 item 2; operator ruling D-bbb12).

  python3 plugin_update.py [--apply] [--marketplace harness-local] [--plugin NAME ...]

Default is a dry run: it prints the `claude` binary found, a table (plugin, installed, available, action) and the exact commands, and
runs nothing. --apply runs `claude plugin marketplace update <marketplace>`, then `claude plugin update <plugin>@<marketplace>` for each
plugin with an update, and checks the installed version after each.
Exit codes: 0 nothing to do (or all updated), 10 updates are pending (dry run; not an error), 1 a plugin is blocked, failed or was not
updated, 2 the marketplace folder or the `claude` binary is wrong or missing. Precedence 2 > 1 > 10 > 0.
Run it only from the operator's terminal or the secretary's Hub queue, as one copyable command, dry run first. No role starts it from a
chat, and no chat launches a nested `claude` (operator rule 11-10).
This command updates Claude Code CLI installs only. Cowork and the desktop Code tab load the account's cloud copy: click save plugin in
claude.ai once for each plugin file (the secretary's queue)."""
import argparse, json, os, re, shutil, subprocess, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*\Z")
CUT = 300
CLI_ONLY = "this command updates Claude Code CLI installs only"
COWORK = ("Cowork and the desktop Code tab are not updated by this command: click save plugin in claude.ai once for each plugin file "
          "(the secretary's queue).")
RELOAD = "reload: running chats keep the old version until reloaded"
NO_CLI_INSTALL = ("crew-coordinator",)   # never hinted for a CLI install: the double-load risk is unproven (envoy advice 11-10)


class Unreadable(Exception):
    pass


def _plugins_dir():
    return os.path.join(os.path.expanduser("~"), ".claude", "plugins")


def _load(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def _ver(v):
    """A version as a tuple of ints for ordering; anything unreadable sorts lowest."""
    try:
        return tuple(int(x) for x in str(v).split("."))
    except ValueError:
        return ()


def installed(marketplace):
    """{plugin: [install dict, ...]} for keys ending @<marketplace>. One install per key or a list of installs per key (user and
    project scope) are read the same (critic round 2 nb 4). Keys whose plugin name fails NAME_RE are returned under `refused`."""
    p = os.path.join(_plugins_dir(), "installed_plugins.json")
    if not os.path.exists(p):
        return {}, []                     # a CLI with no plugin installed yet has no file
    try:
        d = _load(p)
    except (OSError, ValueError) as e:    # fix round 1 (critic): a broken file is not "nothing installed"
        raise Unreadable("cannot read %s (%s)" % (p, type(e).__name__))
    raw = d.get("plugins") if isinstance(d, dict) and isinstance(d.get("plugins"), dict) else d if isinstance(d, dict) else {}
    out, refused = {}, []
    for key, v in raw.items():
        if not isinstance(key, str) or not key.endswith("@" + marketplace):
            continue
        name = key[: -len(marketplace) - 1]
        if not NAME_RE.match(name):
            refused.append(name)
            continue
        ins = v if isinstance(v, list) else [v]
        out[name] = [x for x in ins if isinstance(x, dict)]
    return out, refused


def marketplace_dir(marketplace):
    """The folder known_marketplaces.json gives for <marketplace>, and whether its source is a directory. -> (folder or None, is_dir)."""
    try:
        d = _load(os.path.join(_plugins_dir(), "known_marketplaces.json"))
    except (OSError, ValueError):
        return None, False
    e = d.get(marketplace) if isinstance(d, dict) else None
    if not isinstance(e, dict):
        return None, False
    src = e.get("source") if isinstance(e.get("source"), dict) else {}
    folder = e.get("installLocation") or src.get("path")
    return (folder if isinstance(folder, str) else None), src.get("source") == "directory"


def available(mk_dir):
    """{plugin: (marketplace.json version, plugin.json version)} read by file, no network."""
    out = {}
    try:
        m = _load(os.path.join(mk_dir, ".claude-plugin", "marketplace.json"))
    except (OSError, ValueError):
        return out
    for p in m.get("plugins") or []:
        if not isinstance(p, dict) or not isinstance(p.get("name"), str):
            continue
        pj = None
        src = p.get("source") if isinstance(p.get("source"), str) else "./plugins/" + p["name"]
        try:
            pj = _load(os.path.join(mk_dir, src, ".claude-plugin", "plugin.json")).get("version")
        except (OSError, ValueError, AttributeError):
            pass
        out[p["name"]] = (p.get("version"), pj)
    return out


def _versions(ins):
    return sorted({str(x.get("version")) for x in ins if x.get("version") is not None}, key=_ver)


def _ships_runtime(ins):
    for x in ins:
        path = x.get("installPath")
        if isinstance(path, str) and (os.path.isdir(os.path.join(path, "hooks")) or os.path.isfile(os.path.join(path, ".mcp.json"))):
            return True
    return False


def _log(home, plugin, frm, to, result):
    d = os.path.join(home, "_logs")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "plugin_update.log"), "a", encoding="utf-8") as f:
        f.write("%s\t%s\t%s\t%s\t%s\n" % (time.strftime("%Y-%m-%dT%H:%M:%S"), plugin, frm, to, result))


def _run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    return r.returncode, (r.stderr or "").strip()[:CUT]


def main(argv=None):
    ap = argparse.ArgumentParser(prog="plugin_update.py", description=__doc__.split("\n\n")[0],
                                 epilog="Run from the operator's terminal or the secretary's Hub queue only; dry run first.")
    ap.add_argument("--apply", action="store_true", help="run the updates (default: dry run)")
    ap.add_argument("--marketplace", default="harness-local")
    ap.add_argument("--plugin", action="append", default=[], help="limit to these plugins (repeatable)")
    a = ap.parse_args(argv)
    try:
        code = _main(a)
    except Unreadable as e:
        print("stop: " + str(e) + "; nothing run")
        code = 2
    print(CLI_ONLY)
    print(COWORK)
    return code


def _main(a):
    mk = a.marketplace
    if not NAME_RE.match(mk):
        print("refused: marketplace name %r does not match [a-z0-9][a-z0-9-]*" % mk)
        return 2
    bad = [p for p in a.plugin if not NAME_RE.match(p)]
    if bad:
        print("refused: plugin name(s) " + ", ".join(repr(p) for p in bad) + " do not match [a-z0-9][a-z0-9-]*; nothing run")
        return 1
    claude = shutil.which("claude")
    print("claude binary: " + (claude or "not found"))
    ins, refused = installed(mk)
    if a.plugin:
        ins = {k: v for k, v in ins.items() if k in a.plugin}
    for name in refused:
        print("refused: installed plugin name %r does not match [a-z0-9][a-z0-9-]*" % name)
    if not ins and not refused:
        print("no %s plugin installed in Claude Code" % mk)
        return 0
    # 1b: the folder the CLI updates from must be the one this run reads (the home moved at the cutover)
    folder, is_dir = marketplace_dir(mk)
    try:
        import harness as H
        want = os.path.join(H.resolve_home(), "_harness", "marketplace")
        home = H.resolve_home()
    except Exception as e:
        print("stop: harness home not found (%s)" % str(e)[:200])
        return 2
    if not folder or os.path.realpath(os.path.expanduser(folder)) != os.path.realpath(want):
        print("stop: known_marketplaces.json gives %s for %s, but the harness marketplace is %s; nothing run"
              % (folder or "no folder", mk, want))
        return 2
    avail = available(want)
    rows, todo, blocked = [], [], bool(refused)
    for name in sorted(ins):
        iv = _versions(ins[name])
        mv, pv = avail.get(name, (None, None))
        cur = ", ".join(iv) or "?"
        if mv is None:
            act = "current (not in the marketplace)"
        elif mv != pv:
            act, blocked = "blocked: version disagrees: marketplace %s, plugin %s" % (mv, pv), True
        elif iv and all(_ver(v) >= _ver(mv) for v in iv):
            act = "current"
        else:
            act = "update"
            todo.append((name, cur, mv))
        rows.append((name, cur, mv or "-", act))
    for name in sorted(set(avail) - set(ins) - set(NO_CLI_INSTALL)):
        print("hint: %s is in the marketplace but not installed; install it once with: claude plugin install %s@%s" % (name, name, mk))
    print("%-24s %-12s %-12s %s" % ("plugin", "installed", "available", "action"))
    for r in rows:
        print("%-24s %-12s %-12s %s" % r)
    cmds = [["claude", "plugin", "marketplace", "update", mk]] + [["claude", "plugin", "update", "%s@%s" % (n, mk)] for n, _, _ in todo]
    if not a.apply:
        if todo:
            print("would run:")
            for c in cmds:
                print("  " + " ".join(c))
            print("exit 10 means updates are pending, not an error")
        return 1 if blocked else 10 if todo else 0
    if not claude:
        print("stop: the claude binary is not on PATH; nothing run")
        return 2
    if not todo:
        return 1 if blocked else 0
    rc, err = _run([claude, "plugin", "marketplace", "update", mk])
    if rc != 0:
        print("marketplace update exited %d: %s" % (rc, err))
        if not is_dir:
            print("stop: not a directory source, so no plugin update runs on a possibly stale copy")
            return 1
        print("directory source: going on; each plugin's installed version is checked after its update")
    failed = False
    for name, frm, to in todo:
        rc, err = _run([claude, "plugin", "update", "%s@%s" % (name, mk)])
        after, _ = installed(mk)
        now = _versions(after.get(name, []))
        ok = bool(now) and all(_ver(v) >= _ver(to) for v in now)   # fix round 1 (critic): no copy below `to` (a newer dev copy in another scope is fine)
        if ok:
            print("updated %s: %s -> %s" % (name, frm, to) + (" (command exited %d: %s)" % (rc, err) if rc else ""))
            if _ships_runtime(after.get(name, [])):
                print("%s: %s" % (name, RELOAD))
        else:
            failed = True
            print("not updated %s: installed %s, expected %s" % (name, ", ".join(now) or "?", to) + (" (exit %d: %s)" % (rc, err) if rc or err else ""))
        _log(home, name, frm, to, "updated" if ok else "not updated")
    return 1 if failed or blocked else 0


if __name__ == "__main__":
    sys.exit(main())
