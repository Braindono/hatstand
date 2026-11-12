#!/usr/bin/env python3
"""Pre-freeze check: approval actions added or removed between two plugin trees (cc 0.24.0, A-b2950 item 7; gate I5).

Usage: python3 check_actions.py <previous-tree> <candidate-tree> <scope-json>
  <scope-json>: a file holding the scope items, as a JSON list of strings or an object with "items".
Reads APPROVAL_ACTIONS from both trees' scripts/harness.py by ast (nothing is imported from the trees) and lists actions added and
removed. Exits 1 listing each one that no scope item names verbatim, 0 when every one is named, 2 on a usage or read error.
Read-only: no ledger writes. A script the curator runs before cutting the release tree, not a gate; its output goes in the release notes.
The diff is Harness.action_diff in harness.py, the same function release_scope uses when filed with candidate_tree."""
import json, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def main(argv):
    if len(argv) != 3:
        print(__doc__.strip().splitlines()[2], file=sys.stderr)
        return 2
    import harness as H
    prev, cand, scope = argv
    try:
        with open(scope, encoding="utf-8") as f:
            s = json.load(f)
        items = s.get("items") if isinstance(s, dict) else s
        if not isinstance(items, list):
            raise ValueError("scope json must be a list of items or {\"items\": [...]}")
        diff = H.Harness.action_diff(prev, cand)
    except (OSError, ValueError, H.HarnessError) as e:
        print(f"check_actions: {e}", file=sys.stderr)
        return 2
    print("added: " + (", ".join(diff["added"]) or "none"))
    print("removed: " + (", ".join(diff["removed"]) or "none"))
    missing = H.Harness.actions_unnamed(diff, items)
    for kind, n in missing:
        print(f"NOT NAMED: approval action {n} {kind} without a scope item naming it")
    if not missing:
        print("ok: every added or removed approval action is named in the scope")
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
