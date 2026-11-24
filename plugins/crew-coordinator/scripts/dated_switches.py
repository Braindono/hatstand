"""dated_switches (0.27.2 I3): the one clock and the one on/off rule for dated switches (observe periods, the role-alias overlap).
Depends on: stdlib; ask_gate only inside scan() (lazy, to find gates.json).
Shipped code carries no switch date: an empty date means the switch has ended. A date lives only in the operator's config (config.json
`*_until`, gates.json sections), where it renews. Callers read the clock as `dated_switches.today()` through the module (never from-import),
so a test patch reaches them.
Interface: today(), is_on(date_str, today_str=None, name="", home=None), scan(home, gates_path=None), warnings(home, gates_path=None, today_str=None,
days=14), do_lines(home, gates_path=None, today_str=None, days=14), scan_literals(root). CLI: dated_switches.py check [--home DIR]
(prints one warning per switch within 14 days or past; always exits 0). A malformed date warns once to <home>/_harness/dated_switches.log, never stdout."""
import datetime
import json
import os
import re
import sys

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
LITERAL_RE = re.compile(r"""(?i)(\w*_until|until)["']?\s*[:=]\s*["'](\d{4}-\d{2}-\d{2})["']""")   # a constant or key named *_UNTIL / until holding a date
KEY_RE = re.compile(r"(?i)(^|_)until$")


def today():
    """The local date, YYYY-MM-DD (the operator's day, not UTC)."""
    return datetime.date.today().isoformat()


def parse(s):
    """-> datetime.date, or None when s is not a valid YYYY-MM-DD."""
    if not isinstance(s, str) or not DATE_RE.match(s.strip()):
        return None
    try:
        return datetime.date.fromisoformat(s.strip())
    except ValueError:
        return None


def _home(home=None):
    h = home or os.environ.get("HARNESS_HOME")
    if h:
        return h
    d = os.path.join(os.path.expanduser("~"), "Claude", "Projects", "Exchange")
    return d if os.path.isdir(os.path.join(d, "_harness")) else None


def warn_once(name, value, home=None):
    """One line per (name, value) in <home>/_harness/dated_switches.log; any failure is silent; nothing goes to stdout."""
    h = _home(home)
    if not h:
        return
    path = os.path.join(h, "_harness", "dated_switches.log")
    line = "malformed date for %s: %r (switch treated as ended)" % (name or "?", str(value)[:40])
    try:
        try:
            with open(path, encoding="utf-8") as f:
                if line in f.read().splitlines():
                    return
        except OSError:
            pass
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def is_on(date_str, today_str=None, name="", home=None):
    """True while the switch runs: today <= date. Empty or missing: off. Malformed: off, with one warning in the log."""
    if date_str is None or not str(date_str).strip():
        return False
    d = parse(str(date_str))
    if d is None:
        warn_once(name, date_str, home)
        return False
    t = parse(today_str if today_str is not None else today())
    return bool(t) and t <= d


def _gates_sections(path):
    try:
        with open(path, encoding="utf-8") as f:
            j = json.load(f)
    except Exception:
        return {}
    return {k: v for k, v in j.items() if isinstance(v, dict)} if isinstance(j, dict) else {}


def scan(home, gates_path=None):
    """-> [(name, date_str)] for every config date: <home>/_harness/config.json top-level *_until keys, and each gates.json section's *_until keys."""
    out = []
    try:
        with open(os.path.join(home, "_harness", "config.json"), encoding="utf-8") as f:
            cfg = json.load(f)
        out += [(k, v) for k, v in cfg.items() if KEY_RE.search(k) and isinstance(v, str) and v.strip()]
    except Exception:
        pass
    if gates_path is None:
        try:
            import ask_gate
            gates_path = ask_gate.config_path()
        except Exception:
            gates_path = None
    if gates_path:
        for sec, d in _gates_sections(gates_path).items():
            out += [("gates.%s.%s" % (sec, k), v) for k, v in d.items() if KEY_RE.search(k) and isinstance(v, str) and v.strip()]
    return out


def _days_left(date_str, today_str=None):
    d, t = parse(date_str), parse(today_str if today_str is not None else today())
    return (d - t).days if d and t else None


def warnings(home, gates_path=None, today_str=None, days=14):
    """One line per config date 14 days or fewer away, or past."""
    out = []
    for name, v in scan(home, gates_path):
        n = _days_left(v, today_str)
        if n is None:
            warn_once(name, v, home)
            out.append("dated switch %s has a malformed date %r: it counts as ended" % (name, str(v)[:40]))
        elif n <= days:
            out.append("dated switch %s %s: renew it in the config or let it end" % (name, ("ended %s (%d days ago)" % (v, -n)) if n < 0 else "ends %s (in %d days)" % (v, n)))
    return out


def do_lines(home, gates_path=None, today_str=None, days=14):
    """Sync Do-lines: a config date that has not lapsed yet and is 14 days or fewer away (no job to schedule)."""
    out = []
    for name, v in scan(home, gates_path):
        n = _days_left(v, today_str)
        if n is not None and 0 <= n <= days:
            out.append("⏳ dated switch %s ends %s (in %d days): renew it in the config or let it end" % (name, v, n))
    return out


def scan_literals(root):
    """-> [(path, line_no, name, date)] for every date literal held by a *_UNTIL / until constant or key in root/scripts/*.py and root/data/**.
    The caller filters (the shipped rule is no such date at all, so the test fails on a date later than today and lists file and line)."""
    hits = []
    paths = []
    for sub in ("scripts", "data"):
        for dp, _dn, fns in os.walk(os.path.join(root, sub)):
            if "__pycache__" in dp:
                continue
            paths += [os.path.join(dp, fn) for fn in fns if fn.endswith((".py", ".json")) and (sub == "data" or dp == os.path.join(root, "scripts"))]
    for p in sorted(paths):
        try:
            with open(p, encoding="utf-8") as f:
                for n, line in enumerate(f, 1):
                    for m in LITERAL_RE.finditer(line):
                        hits.append((p, n, m.group(1), m.group(2)))
        except OSError:
            continue
    return hits


def main(argv):
    if argv[:1] == ["check"]:
        home = _home(argv[argv.index("--home") + 1] if "--home" in argv[1:] and argv.index("--home") + 1 < len(argv) else None)
        for line in (warnings(home) if home else []):
            print(line)
        return 0
    print("usage: dated_switches.py check [--home DIR]")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except Exception:
        sys.exit(0)
