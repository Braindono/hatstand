"""0.24.0 item 17 (A-b2950; guard spec v3; D-945c6): the Hatstand commit and push checker.

Run with `python3 -I -B hatstand_check.py <command> ...`. It imports hatstand_guard.py from its own folder, never from a repo.

Two modes:
- Installed (the hooks): no --home. The folder holding this file also holds pre-commit, pre-push, hatstand_guard.py and
  hatstand-hooks.json {harness_home, lists_dir, installed_by, release, sha256: {file: sha}}. Every listed file's sha256 must
  match, or nothing is committed or pushed (re-run `install`). No environment variable is read for the home or the lists.
- Plugin (the sync): --home <harness home>. No manifest.

Commands:
  staged <repo>                       the staged blobs (what `git add -p` staged, not the working tree) and their paths
  pre-push <remote> <url>             stdin from git: <local ref> <local sha> <remote ref> <remote sha> per line. For each
                                      pushed ref: its name, a pushed annotated tag object, and every commit not on the
                                      remote yet (or the whole history when the clone has no remote-tracking ref for it):
                                      header, message and blobs
  scan-history <repo> [--baseline F] [--write-baseline]
                                      every commit, tag object, ref name and blob (each blob once); hits in the baseline
                                      (object, rule, line; no text) are known and not reported
  self-check <clone> [--hooks DIR]    the clone's core.hooksPath is the installed folder, no local core.hooksPath, the two
                                      hooks exist, are executable and match the manifest
  install <dest> --home H [--lists-dir L]
                                      copy the hooks, this checker and the guard to <dest>, write its gitconfig and manifest
  daily [--home H] [--git-root D] [--mirror M] [--harness-scripts S]
                                      self-check every kept clone of the remote under D, fetch the mirror, scan its history
                                      against the baseline, compare its ref tips with the sync's pushed record, and send one
                                      task to the curator and the envoy when anything is wrong
Output: one line per hit, `hatstand: STOP, <rule>: <ref|commit|(staged)>: <path>:<line>: <reason>`, then exit 1.
No flag or environment variable skips a rule."""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import hatstand_guard as G  # noqa: E402

MANIFEST = "hatstand-hooks.json"
HOOKS = ("pre-commit", "pre-push")
FILES = HOOKS + ("hatstand_check.py", "hatstand_guard.py")
BASELINE = "hatstand-scan-baseline.json"
ZERO = re.compile(r"^0+$")
# The four includeIf patterns of the spec (section 2): any URL whose last path part is hatstand or hatstand.git, either case
# of the first letter, with or without a trailing slash. hatstand-private never matches.
REMOTE_RX = re.compile(r"(?:^|[/:])[Hh]atstand(?:\.git)?/?$")
INCLUDE_PATTERNS = ("**/[Hh]atstand", "**/[Hh]atstand.git", "**/[Hh]atstand.git/", "**/[Hh]atstand/")


class Stop(Exception):
    pass


def git(repo, *args, data=None, ok=(0,)):
    r = subprocess.run(["git", "-C", repo] + list(args), input=data, capture_output=True)
    if r.returncode not in ok:
        sub = next((a for i, a in enumerate(args) if not a.startswith("-") and (i == 0 or args[i - 1] != "-c")), "?")
        raise Stop("git %s failed (exit %d): %s" % (sub, r.returncode, r.stderr.decode("utf-8", "replace").strip()[:200]))
    return r.stdout


def sha_file(p):
    with open(p, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def plugin_release():
    try:
        with open(os.path.join(HERE, "..", ".claude-plugin", "plugin.json"), encoding="utf-8") as f:
            return json.load(f).get("version") or "?"
    except (OSError, ValueError):
        return "?"


# ---------------------------------------------------------------- the installed folder
def read_manifest(folder):
    """-> manifest dict. Every file of FILES must be listed and match its sha256 (drift check, not tamper-proofing)."""
    p = os.path.join(folder, MANIFEST)
    try:
        with open(p, encoding="utf-8") as f:
            m = json.load(f)
    except (OSError, ValueError):
        raise Stop("%s is missing or unreadable in %s; re-run the installer" % (MANIFEST, folder))
    shas = m.get("sha256") or {}
    for name in FILES:
        fp = os.path.join(folder, name)
        if name not in shas:
            raise Stop("%s does not list %s; re-run the installer" % (MANIFEST, name))
        if not os.path.isfile(fp) or sha_file(fp) != shas[name]:
            raise Stop("%s differs from its sha256 in %s; re-run the installer" % (name, MANIFEST))
    if not m.get("harness_home"):
        raise Stop("%s has no harness_home; re-run the installer" % MANIFEST)
    return m


def load_rules(home=None, lists_dir=None):
    if home is None:
        m = read_manifest(HERE)
        home, lists_dir = m["harness_home"], m.get("lists_dir") or None
    return G.Rules(home, lists_dir)


# ---------------------------------------------------------------- blob reading
class Blobs:
    """git cat-file --batch over one repo."""

    def __init__(self, repo):
        self.p = subprocess.Popen(["git", "-C", repo, "cat-file", "--batch"], stdin=subprocess.PIPE, stdout=subprocess.PIPE)

    def get(self, spec):
        """-> (type, bytes) or (None, None) when the object is missing or git cat-file is gone (the caller STOPs)."""
        try:
            self.p.stdin.write(spec.encode("utf-8", "surrogateescape") + b"\n")
            self.p.stdin.flush()
        except OSError:
            return None, None
        head = self.p.stdout.readline()
        if head.endswith(b" missing\n") or not head:
            return None, None
        _oid, typ, size = head.split()
        data = self.p.stdout.read(int(size))
        self.p.stdout.read(1)
        return typ.decode(), data

    def close(self):
        try:
            self.p.stdin.close()
            self.p.wait(timeout=10)
        except Exception:
            self.p.kill()


def parse_raw(out):
    """`--raw -z` output -> [(new mode, new blob id, path)]."""
    parts = out.split(b"\0")
    res, i = [], 0
    while i < len(parts) - 1:
        meta = parts[i].decode()
        if not meta.startswith(":"):
            i += 1
            continue
        f = meta[1:].split()
        if f[4][0] in "RC":                                      # rename or copy: source, then destination
            path, i = parts[i + 2], i + 3
        else:
            path, i = parts[i + 1], i + 2
        res.append((f[1], f[3], path.decode("utf-8", "surrogateescape")))
    return res


def items_from(entries, blobs):
    items = []
    for mode, oid, path in entries:
        if not mode.startswith("100"):
            items.append((path, None))
            continue
        typ, data = blobs.get(oid)
        items.append((path, data) if typ == "blob" else (path, None, G.UNREADABLE))
    return items


# ---------------------------------------------------------------- staged
def check_staged(repo, rules):
    out = git(repo, "-c", "core.quotepath=false", "diff", "--cached", "--raw", "-z", "--no-abbrev", "--diff-filter=ACMR")
    blobs = Blobs(repo)
    try:
        items = items_from(parse_raw(out), blobs)
        return G.check_blobs(items, rules, lambda n: blobs.get(":" + n)[1])
    finally:
        blobs.close()


# ---------------------------------------------------------------- commits, tags, refs
def check_commit(repo, sha, rules, blobs, seen):
    where = "commit " + sha[:12]
    _t, raw = blobs.get(sha)
    hits = G.check_text(where, "(commit message)", (raw or b"").decode("utf-8", "replace"), rules)
    out = git(repo, "-c", "core.quotepath=false", "diff-tree", "-r", "-m", "--root", "-z", "--raw", "--no-abbrev",
              "--no-commit-id", "--diff-filter=ACMR", sha)
    entries = []
    for e in parse_raw(out):
        if (e[1], e[2]) not in seen:
            seen.add((e[1], e[2]))
            entries.append(e)
    if entries:
        hits += G.check_blobs(items_from(entries, blobs), rules, lambda n: blobs.get("%s:%s" % (sha, n))[1], where)
    return hits


def check_ref_name(ref, rules):
    return G.check_text("ref", ref, ref, rules)


def peel_tags(sha, rules, blobs, where_ref):
    """An annotated tag (or a chain of them): check each tag object's text; -> (commit sha or None, hits)."""
    hits = []
    for _ in range(10):
        typ, data = blobs.get(sha)
        if typ != "tag":
            return (sha if typ == "commit" else None), hits
        hits += G.check_text("tag " + sha[:12], where_ref, data.decode("utf-8", "replace"), rules)
        m = re.match(rb"object ([0-9a-f]+)", data)
        if not m:
            return None, hits
        sha = m.group(1).decode()
    return None, hits


def check_pre_push(repo, remote, lines, rules):
    hits = []
    blobs = Blobs(repo)
    seen = set()
    try:
        have_tracking = bool(git(repo, "for-each-ref", "--format=%(refname)", "refs/remotes/%s/" % remote).strip())
        for line in lines:
            f = line.split()
            if len(f) != 4:
                continue
            lref, lsha, rref, rsha = f
            if ZERO.match(lsha):
                continue                                         # a deletion pushes no content
            hits += check_ref_name(rref, rules)
            if lref != rref and lref != "(delete)":
                hits += check_ref_name(lref, rules)
            commit, th = peel_tags(lsha, rules, blobs, rref)
            hits += th
            if not commit:
                continue
            if have_tracking:
                args = ["rev-list", commit, "--not", "--remotes=%s" % remote]
                if not ZERO.match(rsha) and blobs.get(rsha)[0] is not None:
                    args.append(rsha)
            else:
                args = ["rev-list", commit]                      # the clone knows nothing of the remote: the whole history
            for c in git(repo, *args).decode().split():
                hits += check_commit(repo, c, rules, blobs, seen)
    finally:
        blobs.close()
    return hits


# ---------------------------------------------------------------- history and baseline
def scan_history(repo, rules):
    """-> [(obj, Hit)] over every commit, tag object, ref name and blob (each blob id once, under its first path)."""
    res = []
    blobs = Blobs(repo)
    try:
        for ref in git(repo, "for-each-ref", "--format=%(refname)").decode("utf-8", "replace").split("\n"):
            if ref:
                for h in check_ref_name(ref, rules):
                    res.append(("ref:" + hashlib.sha256(ref.encode()).hexdigest()[:16], h))
        for ln in git(repo, "for-each-ref", "--format=%(objectname) %(objecttype)", "refs/tags").decode().split("\n"):
            if ln.endswith(" tag"):
                oid = ln.split()[0]
                _c, th = peel_tags(oid, rules, blobs, "(tag)")
                res += [(oid, h) for h in th]
        commits = git(repo, "rev-list", "--all").decode().split()
        for c in commits:
            _t, raw = blobs.get(c)
            for h in G.check_text("commit " + c[:12], "(commit message)", (raw or b"").decode("utf-8", "replace"), rules):
                res.append((c, h))
        first = {}
        for ln in git(repo, "-c", "core.quotepath=false", "rev-list", "--objects", "--all").decode("utf-8", "surrogateescape").split("\n"):
            oid, _, path = ln.partition(" ")
            if path and oid not in first:
                first[oid] = path
        for oid, path in first.items():
            typ, data = blobs.get(oid)
            if typ != "blob":
                continue
            for h in G.check_blobs([(path, data)], rules, None, "blob " + oid[:12]):
                res.append((oid, h))
    finally:
        blobs.close()
    return res


def baseline_key(obj, h):
    return [obj, h.rule, h.line or 0]


def read_baseline(path):
    try:
        with open(path, encoding="utf-8") as f:
            return {tuple(e) for e in json.load(f).get("entries") or []}, None
    except OSError:
        return set(), "no baseline at %s" % path
    except ValueError:
        return set(), "the baseline %s is unreadable" % path


def new_history_hits(repo, rules, baseline_path):
    found = scan_history(repo, rules)
    base, problem = read_baseline(baseline_path)
    return [h for obj, h in found if tuple(baseline_key(obj, h)) not in base], found, problem


# ---------------------------------------------------------------- self-check
def self_check(clone, hooks=None):
    """-> list of problems (empty = the hooks run). hooks: the installed folder, default: where core.hooksPath points."""
    probs = []
    local = git(clone, "config", "--local", "--get", "core.hooksPath", ok=(0, 1)).decode().strip()
    if local:
        probs.append("the clone sets a local core.hooksPath, which overrides the installed hooks")
    eff = git(clone, "config", "--get", "core.hooksPath", ok=(0, 1)).decode().strip()
    if not eff:
        probs.append("core.hooksPath is not set for this clone (the global includeIf is missing or does not match)")
        return probs
    eff = os.path.expanduser(eff)
    if not os.path.isabs(eff):                                   # git reads a relative hooksPath from the clone's top folder
        eff = os.path.join(clone, eff)
    eff = os.path.realpath(eff)
    want = os.path.realpath(hooks) if hooks else eff
    if eff != want:
        probs.append("core.hooksPath points to %s, not the installed hooks folder" % eff)
        return probs
    if not os.path.isdir(want):
        probs.append("the hooks folder %s is missing" % want)
        return probs
    for hk in HOOKS:
        p = os.path.join(want, hk)
        if not os.path.isfile(p):
            probs.append("%s is missing from the hooks folder" % hk)
        elif not os.access(p, os.X_OK):
            probs.append("%s is not executable, so git skips it" % hk)
    try:
        read_manifest(want)
    except Stop as e:
        probs.append(str(e))
    return probs


# ---------------------------------------------------------------- install
def install(dest, home, lists_dir=None):
    os.makedirs(dest, exist_ok=True)
    src = {hk: os.path.join(HERE, "hatstand-hooks", hk) for hk in HOOKS}
    src["hatstand_check.py"] = os.path.join(HERE, "hatstand_check.py")
    src["hatstand_guard.py"] = os.path.join(HERE, "hatstand_guard.py")
    shas = {}
    for name, s in src.items():
        d = os.path.join(dest, name)
        tmp = d + ".tmp"
        shutil.copyfile(s, tmp)
        os.chmod(tmp, 0o755 if name in HOOKS else 0o644)
        os.replace(tmp, d)
        shas[name] = sha_file(d)
    with open(os.path.join(dest, "gitconfig"), "w", encoding="utf-8") as f:
        f.write("[core]\n\thooksPath = %s\n" % os.path.abspath(dest))
    man = {"harness_home": os.path.abspath(home), "lists_dir": os.path.abspath(lists_dir) if lists_dir else None,
           "installed_by": "hatstand_check.py install", "release": plugin_release(), "sha256": shas}
    with open(os.path.join(dest, MANIFEST), "w", encoding="utf-8") as f:
        json.dump(man, f, indent=1, sort_keys=True)
        f.write("\n")
    return man


def include_lines(dest):
    gc = os.path.join(os.path.abspath(dest), "gitconfig")
    return ["git config --global includeIf.hasconfig:remote.*.url:%s.path %s" % (p, gc) for p in INCLUDE_PATTERNS]


# ---------------------------------------------------------------- daily
def is_hatstand_remote(url):
    return bool(REMOTE_RX.search(url.strip()))


def kept_clones(git_root):
    out = []
    try:
        names = sorted(os.listdir(git_root))
    except OSError:
        return out
    for n in names:
        d = os.path.join(git_root, n)
        if not os.path.isdir(os.path.join(d, ".git")):
            continue
        urls = git(d, "config", "--get-regexp", r"^remote\..*\.url$", ok=(0, 1)).decode().split("\n")
        if any(is_hatstand_remote(u.split(" ", 1)[-1]) for u in urls if u):
            out.append(d)
    return out


def pushed_record(home):
    """The sync's record of pushed refs: {ref: sha}, the latest hatstand.synced event per ref."""
    rec = {}
    try:
        with open(os.path.join(home, "_harness", "events.jsonl"), encoding="utf-8") as f:
            for line in f:
                if '"hatstand.synced"' not in line:
                    continue
                try:
                    d = (json.loads(line).get("data") or {}).get("pushed") or {}
                except ValueError:
                    continue
                if isinstance(d, dict):
                    rec.update({k: v for k, v in d.items() if isinstance(k, str) and isinstance(v, str)})
    except OSError:
        pass
    return rec


def daily(home, lists_dir, git_root, mirror, hooks_dir, harness_scripts=None, send=True):
    """-> (problems, sent message id or None)."""
    problems = []
    rules = G.Rules(home, lists_dir)
    if rules.identity_sha:
        print("hatstand: daily: identity list sha256 %s" % rules.identity_sha)
    if rules.fatal:
        problems.append("the checker cannot load its lists: " + rules.fatal)
    if git_root:
        for c in kept_clones(git_root):
            for p in self_check(c, hooks_dir):
                problems.append("hooks off in %s: %s" % (os.path.basename(c), p))
    if mirror and not rules.fatal:
        try:
            git(mirror, "fetch", "--tags", "--prune", "-q")
        except Stop as e:
            problems.append("mirror fetch failed: %s" % e)
        try:
            base = os.path.join(lists_dir or os.path.join(home, "_harness", "data"), BASELINE)
            new, _all, bprob = new_history_hits(mirror, rules, base)
            if bprob:
                problems.append(bprob)
            problems += ["new hit on the remote: " + h.stop_line()[len("hatstand: STOP, "):] for h in new]
            rec = pushed_record(home)
            if rec:
                for ln in git(mirror, "for-each-ref", "--format=%(refname) %(objectname)").decode().split("\n"):
                    if not ln:
                        continue
                    ref, oid = ln.split()
                    if ref in rec and rec[ref] != oid:
                        problems.append("ref %s on the remote is not the sha the sync pushed" % ref)
                    elif ref not in rec and ref.startswith("refs/heads/"):
                        problems.append("ref %s on the remote was not pushed by the sync" % ref)
        except Stop as e:
            problems.append("history scan failed: %s" % e)
    mid = None
    if problems and send:
        mid = send_task(home, problems, harness_scripts)
    return problems, mid


def send_task(home, problems, harness_scripts=None):
    scripts = harness_scripts or os.path.join(home, "_harness", "marketplace", "plugins", "crew-coordinator", "scripts")
    os.environ["HARNESS_HOME"] = home
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    import harness as H
    h = H.Harness()
    body = ("The daily Hatstand check found %d problem(s); nothing was changed. Fix them, then confirm the next daily run is "
            "clean.\n" % len(problems)) + "\n".join("- " + p for p in problems[:40])
    r = h.send(H.SYSTEM_SENDER, ["role:curator", "role:envoy"], body, subject="Hatstand daily check: %d problem(s)" % len(problems),
               kind="task")
    return (r or {}).get("id") if isinstance(r, dict) else r


# ---------------------------------------------------------------- CLI
def _opt(args, name, default=None):
    if name in args:
        i = args.index(name)
        v = args[i + 1] if i + 1 < len(args) else None
        del args[i:i + 2]
        return v
    return default


def _flag(args, name):
    if name in args:
        args.remove(name)
        return True
    return False


def report(hits):
    for h in hits:
        print(h.stop_line(), file=sys.stderr)
    return 1 if hits else 0


def main(argv):
    args = list(argv[1:])
    if not args:
        print(__doc__, file=sys.stderr)
        return 2
    cmd = args.pop(0)
    home = _opt(args, "--home")
    lists_dir = _opt(args, "--lists-dir")
    try:
        if cmd == "install":
            if not home or not args:
                raise Stop("usage: install <dest> --home H [--lists-dir L]")
            install(args[0], home, lists_dir)
            print("hatstand: hooks installed in %s" % os.path.abspath(args[0]))
            print("hatstand: switch them on for every clone of the remote with these four lines (once per machine):")
            for ln in include_lines(args[0]):
                print("  " + ln)
            return 0
        if cmd == "self-check":
            hooks = _opt(args, "--hooks")
            probs = self_check(args[0] if args else ".", hooks or (None if home else HERE))
            for p in probs:
                print("hatstand: STOP, hooks self-check: %s" % p, file=sys.stderr)
            return 1 if probs else 0
        if cmd == "daily":
            git_root = _opt(args, "--git-root")
            mirror = _opt(args, "--mirror")
            hs = _opt(args, "--harness-scripts")
            if home is None:
                m = read_manifest(HERE)
                home, lists_dir = m["harness_home"], lists_dir or m.get("lists_dir")
            probs, mid = daily(home, lists_dir, git_root, mirror, HERE if os.path.isfile(os.path.join(HERE, MANIFEST)) else None, hs)
            for p in probs:
                print("hatstand: daily: %s" % p, file=sys.stderr)
            if mid:
                print("hatstand: daily: task sent to the curator and the envoy (%s)" % mid)
            print("hatstand: daily: done, %d problem(s)" % len(probs))     # the end line the operator step waits for
            return 1 if probs else 0
        rules = load_rules(home, lists_dir)
        if cmd == "staged":
            if home and rules.identity_sha:            # the sync (plugin mode): show which identity list it checked against
                print("hatstand: identity list sha256 %s" % rules.identity_sha)
            return report(check_staged(args[0] if args else ".", rules))
        if cmd == "pre-push":
            remote = args[0] if args else "origin"
            lines = sys.stdin.read().splitlines()
            return report(check_pre_push(".", remote, lines, rules))
        if cmd == "scan-history":
            repo = args.pop(0) if args else "."
            bpath = _opt(args, "--baseline")
            write = _flag(args, "--write-baseline")
            if rules.fatal:
                return report(G.check_blobs([], rules))
            if bpath is None:
                bpath = os.path.join(lists_dir or os.path.join(home or read_manifest(HERE)["harness_home"], "_harness", "data"), BASELINE)
            if write:
                found = scan_history(repo, rules)
                with open(bpath, "w", encoding="utf-8") as f:
                    json.dump({"version": 1, "entries": sorted(baseline_key(o, h) for o, h in found)}, f, indent=0)
                print("hatstand: baseline written: %d entries" % len(found))
                return 0
            new, _all, prob = new_history_hits(repo, rules, bpath)
            if prob:
                print("hatstand: note: %s; every hit is reported" % prob, file=sys.stderr)
            return report(new)
        raise Stop("unknown command %s" % cmd)
    except Stop as e:
        print("hatstand: STOP, checker: %s" % e, file=sys.stderr)
        return 1
    except Exception as e:                                       # fail closed: an error is a STOP, never a pass
        print("hatstand: STOP, checker error: %s: %s" % (type(e).__name__, str(e)[:200]), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
