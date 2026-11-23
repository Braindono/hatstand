"""hub_feed_op: the harness_admin op=timer wrapper over the Hub feed's timer logic.

What it does: validates the timer args, calls the vendored hub_feed_timers.set_timer on <home>/_harness/hub_feed/timers.json.
Why: the Hub's timers feed is written by one local file module (no model); this op lets agents set a timer without editing the file by hand.
Depends on: os; scripts/hub_feed_timers.py (vendored copy of the Hub feed's timer module).
Interface: run_timer(home, args, now) -> {"id", "timer"}; raises ValueError with a plain message (the caller turns it into a HarnessError).
"""
import os

import hub_feed_timers as _timers          # vendored, reviewed with the plugin (never loaded from the agent-writable ops tree)

ALLOWED = {"id", "label", "ends_at", "extend_by", "visible", "state", "style", "owner_role", "kind", "link", "note"}


def run_timer(home, args, now):
    if not isinstance(args, dict) or not str(args.get("id") or "").strip():
        raise ValueError("timer: id required")
    if len(str(args["id"])) > 80 or len(repr(args)) > 4000:
        raise ValueError("timer: id over 80 characters or args over 4000")
    bad = sorted(set(args) - ALLOWED)
    if bad:
        raise ValueError("timer: unknown args " + ", ".join(bad))
    if "ends_at" in args and "extend_by" in args:
        raise ValueError("timer: give ends_at or extend_by, not both")
    d = os.path.join(home, "_harness", "hub_feed")
    os.makedirs(d, exist_ok=True)
    doc = _timers.set_timer(os.path.join(d, "timers.json"), args, now)
    return {"id": str(args["id"]), "timer": doc}
