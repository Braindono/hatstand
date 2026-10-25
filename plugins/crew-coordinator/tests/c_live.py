#!/usr/bin/env python3
"""C-live (cc 0.17.0 stage 0): live-ledger regression check. Read-only on the live Exchange.
The measuring core is scripts/live_metrics.py (shared with the weekly report); this file is the check's command line.

  python3 c_live.py [--home EXCHANGE] [--out FILE.json]       record a snapshot (prints a short table)
  python3 c_live.py --diff BASE.json NEW.json                  compare two snapshots (exit 1 if any metric moved)
  python3 c_live.py --ab OLD_SCRIPTS NEW_SCRIPTS [--out F]     ONE snapshot measured by two code trees: the stage check

Exit codes: 0 no change, 1 metrics moved (information), 2 a role's restore digest is over its ceiling or was cut: the
stage FAILS. P-2.9 rule A: with --ab the ceiling is the old tree's figure on the same snapshot x digest_growth_max (1.2),
capped by digest_caps (envoy, curator 1794) and restore_budget; digest_ceiling_tokens is the operator's override.

A plain before/after diff also moves with live mail traffic. --ab copies the home once and measures two identical
copies, one with each tree's scripts/ (separate processes), so any difference comes from the code alone. The old tree
needs no live_metrics.py of its own (0.16.3 has none): this tree's copy measures with the old tree's harness.

Run --ab against the last published tree before each stage ACCEPT and attach the result."""
import argparse, importlib.util, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(os.path.dirname(HERE), "scripts")
_spec = importlib.util.spec_from_file_location("c_live_metrics", os.path.join(SCRIPTS, "live_metrics.py"))
LM = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(LM)
QUERIES, snapshot_home, diff, table = LM.QUERIES, LM.snapshot_home, LM.diff, LM.table


def measure(home):
    return LM.measure(home, SCRIPTS)


def run(live_home, out=None, keep=False):
    return LM.run(live_home, out, keep, SCRIPTS)


def ab(live_home, old_scripts, new_scripts, out=None):
    return LM.ab(live_home, old_scripts, new_scripts, out)


def main(argv=None):
    ap = argparse.ArgumentParser(description="C-live: read-only live-ledger regression check")
    ap.add_argument("--home", help="live Exchange folder (default: HARNESS_HOME or the usual location)")
    ap.add_argument("--out", help="write the snapshot JSON here")
    ap.add_argument("--diff", nargs=2, metavar=("BASE", "NEW"), help="compare two snapshot files")
    ap.add_argument("--ab", nargs=2, metavar=("OLD_SCRIPTS", "NEW_SCRIPTS"), help="one snapshot, two code trees")
    a = ap.parse_args(argv)
    if a.diff:
        with open(a.diff[0]) as f1, open(a.diff[1]) as f2:
            d = diff(json.load(f1), json.load(f2))
        print("\n".join(f"{k}: {o} -> {n}" for k, o, n in d) or "no change")
        return 1 if d else 0
    sys.path.insert(0, SCRIPTS)
    import harness as H
    live = a.home or H.resolve_home()
    cfg = H.load_config(live)        # the live config over THIS tree's defaults: the ceiling the stage is held to
    if a.ab:
        r = ab(live, a.ab[0], a.ab[1], a.out)
        print(table(r["new"]))
        print("A/B (same snapshot, old -> new code): " + ("; ".join(f"{k}: {o} -> {n}" for k, o, n in r["diff"]) or "no change"))
        cc = LM.ceiling_check(r["new"], cfg, old=r["old"])
        if a.out:
            r["ceiling"] = cc
            with open(a.out, "w", encoding="utf-8") as f:
                json.dump(r, f, indent=1, sort_keys=True)
            print(f"written: {a.out}")
        return _ceiling_report(cc) or (1 if r["diff"] else 0)
    res = run(live, a.out)
    print(table(res))
    if a.out:
        print(f"written: {a.out}")
    return _ceiling_report(LM.ceiling_check(res, cfg)) or 0


def _ceiling_report(cc):
    """Print the P-2.9 line; -> 2 on a breach, else 0."""
    if cc["breaches"]:
        print("CEILING BREACH (stage fails): " + "; ".join(
            f"{r} {cc['roles'][r]['tokens']}" + (" cut at restore_budget" if cc["roles"][r]["cut"] else f" > {cc['roles'][r]['ceiling']}")
            for r in cc["breaches"]))
        return 2
    top = max(cc["roles"].items(), key=lambda kv: kv[1]["tokens"] - (kv[1]["ceiling"] or 10 ** 9), default=None)
    print(f"ceiling: ok ({len(cc['roles'])} roles)" + (f"; least headroom {top[0]} {top[1]['tokens']}/{top[1]['ceiling']}"
                                                        if top and top[1]["ceiling"] else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
