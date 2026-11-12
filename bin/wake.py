#!/usr/bin/env python3
"""Role wake registry for pass-the-ball (agent-delegation roles skill). 0.22.5: the plugin ships this file; the live copy is <home>/_harness/wake.py.
wake.py set <role> <trig_id> --kind recurring|run_once --prompt-file FILE | get <role> | clear <role> | clear --stale
  role without the 'role:' prefix. The entry is {trigger, kind, prompt}: the file must hold exactly the wake template with the role filled in
  (anything else is refused). 0.23.0: a plain trig_ string (the legacy form) is refused.
  clear --stale removes every entry that is not a trig_ id (no approval needed). 0.24.0 (A-b2950 item 13, D-8ef51): nothing pins from this
  file any more and no operator step exists; a role's holder registers its own routine (harness_admin op=wake_register) and a Code relay
  holder verifies it. Pins approved before 0.24 stay readable until stale."""
import json, os, re, sys
try: import fcntl
except ImportError: fcntl = None      # Windows: no lock, same as before
HERE = os.path.dirname(os.path.abspath(__file__))
TRIG = re.compile(r"^trig_[A-Za-z0-9]{8,64}\Z")
ROLE = re.compile(r"^[a-z][a-z0-9-]{0,39}\Z")


def wake_json():
    """The live file is <home>/_harness/wake.json. Run from the live copy (<home>/_harness/wake.py) it is the file beside the script; run from the
    plugin it is the home's file found the way the harness finds it (HARNESS_HOME or autodetect), never a file inside the plugin folder (that
    would change the plugin's code sha)."""
    if os.path.basename(HERE) == "_harness":
        return os.path.join(HERE, "wake.json")
    sys.path.insert(0, HERE)
    try:
        import harness
        home = harness.resolve_home()
    except ImportError:      # 0.23.0 (gap 5): a copy with no harness.py beside it (the hatstand mirror bin/wake.py) uses HARNESS_HOME directly
        home = os.environ.get("HARNESS_HOME")
        if not home:
            sys.exit("cannot find the harness home: set HARNESS_HOME or run <home>/_harness/wake.py")
    except Exception as e:
        sys.exit("cannot find the harness home (%s): set HARNESS_HOME or run <home>/_harness/wake.py" % e)
    d = os.path.join(home, "_harness")
    if not os.path.isdir(d):  # 0.23.0 (gap 5): one clear line, no traceback
        sys.exit("no _harness folder in the harness home %s: set HARNESS_HOME to the home that holds _harness" % home)
    return os.path.join(d, "wake.json")


P = None
# Keep identical to doorbell.WAKE_PROMPT (a test compares them).
PROMPT = ("Ball wake for role:{role}. Peek at the role's mail (as a role-less helper, never register the role), leave one line in the "
          "role's mail saying a wake arrived, and stop.")


def prompt_ok(role, text):
    return bool(ROLE.match(role)) and text.strip() == PROMPT.format(role=role)


def main(argv):
    if len(argv) < 2: sys.exit(__doc__)
    op = argv[0]
    rest = list(argv[1:])
    stale = op == "clear" and rest == ["--stale"]
    role = "" if stale else rest.pop(0)
    if role.startswith("role:"): role = role[5:]      # 3.8-safe (no str.removeprefix)
    global P
    P = wake_json()
    lock = open(P + ".lock", "w")
    if fcntl: fcntl.flock(lock, fcntl.LOCK_EX)         # one writer at a time: read-modify-write was racy
    try: d = json.load(open(P))
    except Exception: d = {}
    if not isinstance(d, dict): d = {}
    if op == "set":
        if not rest: sys.exit(__doc__)
        trig, opts = rest[0], rest[1:]
        kind, pf = None, None
        while opts:
            k = opts.pop(0)
            if k == "--kind" and opts: kind = opts.pop(0)
            elif k == "--prompt-file" and opts: pf = opts.pop(0)
            else: sys.exit(__doc__)
        if pf is None and kind is None:      # 0.23.0 (gap 6): the plain trig_ string is no longer a pin form
            sys.exit("refused: a plain trig_ pin is no longer accepted; use set %s %s --kind recurring|run_once --prompt-file FILE" % (role, trig))
        else:
            if pf is None or kind not in ("recurring", "run_once"): sys.exit("set with --kind needs --prompt-file, and kind recurring or run_once")
            if not TRIG.match(trig): sys.exit("not a trig_ id")
            try: text = open(pf, encoding="utf-8").read()
            except OSError as e: sys.exit("cannot read the prompt file: %s" % e)
            if not prompt_ok(role, text): sys.exit("refused: the prompt must equal the wake template for role:%s (no extra word, name or id)" % role)
            d[role] = {"trigger": trig, "kind": kind, "prompt": text.strip()}
    elif op == "get": print(json.dumps(d.get(role, "")) if isinstance(d.get(role), dict) else d.get(role, "")); return
    elif op == "clear":
        if stale:
            for k in [k for k, v in d.items() if not ((isinstance(v, str) and TRIG.match(v)) or (isinstance(v, dict) and TRIG.match(str(v.get("trigger", "")))))]:
                d.pop(k)
        else:
            d.pop(role, None)
    else: sys.exit(__doc__)
    tmp = "%s.%d.tmp" % (P, os.getpid())
    with open(tmp, "w") as f: json.dump(d, f, indent=0)
    os.replace(tmp, P); print("ok")


if __name__ == "__main__":
    main(sys.argv[1:])
