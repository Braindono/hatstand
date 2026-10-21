#!/usr/bin/env python3
"""Role wake registry for pass-the-ball (agent-delegation roles skill).
wake.py set <role> <trig_id> | get <role> | clear <role>   (role without the 'role:' prefix)"""
import json, os, sys
P = os.path.join(os.path.dirname(os.path.abspath(__file__)), "wake.json")
try: d = json.load(open(P))
except Exception: d = {}
op, role = sys.argv[1], sys.argv[2].removeprefix("role:")
if op == "set": d[role] = sys.argv[3]
elif op == "get": print(d.get(role, "")); sys.exit(0)
elif op == "clear": d.pop(role, None)
else: sys.exit(__doc__)
tmp = P + ".tmp"; json.dump(d, open(tmp, "w"), indent=0); os.replace(tmp, P); print("ok")
