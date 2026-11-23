#!/usr/bin/env python3
"""mistake_pointer_hook: PreToolUse hook on harness_record (0.27.1 item 2).

What it does: saves this chat's transcript path and current last line under the calling agent's short id, so the harness can
fill the pointer of a mistake record itself. Fail-open and silent: any error lets the call through.
Depends on: mistake_record.py (same folder). Reads: hook JSON on stdin (transcript_path, tool_input.agent). Writes: <home>/_harness/mistake-pointers/.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
HOME_CANDIDATES = (os.path.join("~", "Claude", "Exchange"), os.path.join("~", "Claude", "Projects", "Exchange"), "~/mnt/Exchange")


def find_home():
    env = os.environ.get("HARNESS_HOME")
    if env:
        return os.path.expanduser(env)
    for c in HOME_CANDIDATES:
        p = os.path.expanduser(c)
        if os.path.isdir(os.path.join(p, "_harness")):
            return p
    return None


def main():
    try:
        inp = json.load(sys.stdin)
        ti = inp.get("tool_input") or {}
        agent, path, home = ti.get("agent"), inp.get("transcript_path"), find_home()
        if agent and path and home:
            import mistake_record as M
            M.save_pointer(home, agent, path)
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
