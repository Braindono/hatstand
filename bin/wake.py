#!/usr/bin/env python3
"""Role wake registry for pass-the-ball (agent-delegation roles skill).
wake.py set <role> <trig_id> | get <role> | clear <role>   (role without the 'role:' prefix)"""
import json, os, sys
try: import fcntl
except ImportError: fcntl = None      # Windows: no lock, same as before
P = os.path.join(os.path.dirname(os.path.abspath(__file__)), "wake.json")
if len(sys.argv) < 3: sys.exit(__doc__)
op, role = sys.argv[1], sys.argv[2]
if role.startswith("role:"): role = role[5:]      # 3.8-safe (no str.removeprefix)
lock = open(P + ".lock", "w")
if fcntl: fcntl.flock(lock, fcntl.LOCK_EX)         # one writer at a time: read-modify-write was racy
try: d = json.load(open(P))
except Exception: d = {}
if op == "set": d[role] = sys.argv[3]
elif op == "get": print(d.get(role, "")); sys.exit(0)
elif op == "clear": d.pop(role, None)
else: sys.exit(__doc__)
tmp = "%s.%d.tmp" % (P, os.getpid())
with open(tmp, "w") as f: json.dump(d, f, indent=0)
os.replace(tmp, P); print("ok")
