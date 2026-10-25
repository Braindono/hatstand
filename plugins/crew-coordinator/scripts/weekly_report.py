#!/usr/bin/env python3
"""Weekly health report (cc 0.17.0 stage 0, R-052 phase 3). Local script, zero model tokens, read-only on its sources.

One markdown page plus a JSON twin (health-<week>_<date>.md/.json), written to <ops root>/projects/orchestration/digests/weekly/ (or --out-dir):
  1. Mail per role: unread, owed replies, restore digest size above the capsule (from live_metrics, on a temp copy)
  2. Nudges: sent, skipped, cap hits by reason
  3. Gates: approvals requested / granted / denied / expired, release gate overrides (with reason), failed tool
     calls by tool, bind mismatches; handoff-gate warnings, blocks and overrides (ledger events since 0.17.0, R-080)
  4. Transcript indexer: redaction failures, private drops, denied sessions, last run (its state file, read-only)
  5. Steward: passes in the window, findings, exit codes, live tokens first -> last, tokens saved (trend.jsonl)
  6. Releases: count, per plugin, split ratio (releases per released plugin)
  7. Handoffs and auto-restores
Each number that has a value in the previous report's JSON shows its change.

  python3 weekly_report.py [--home EXCHANGE] [--days 7] [--out-dir DIR] [--now ISO]   (prints the page path)"""
import argparse, collections, datetime as dt, glob, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import live_metrics as LM   # noqa: E402

PREFIX = "health-"   # the steward's corpus digests share digests/weekly as <week>.json; never compare with those
GATE_WORDS = ("scope", "gate", "approv", "refus", "denied", "not allowed", "operator-only")


def _ts(e):
    try:
        return dt.datetime.fromisoformat(str(e.get("ts", "")).replace("Z", "+00:00"))
    except ValueError:
        return None


def ledger_events(home, since, until):
    """Events with since <= ts < until, read straight from the ledger file (never through Harness: that writes)."""
    path = os.path.join(home, "_harness", "events.jsonl")
    out = []
    with open(path, "rb") as f:
        for line in f:
            try:
                e = json.loads(line)
            except ValueError:
                continue
            t = _ts(e) if isinstance(e, dict) else None
            if t and since <= t < until:
                out.append(e)
    return out


def ledger_stats(events):
    c = collections.Counter(e.get("type") for e in events)
    d = lambda e: e.get("data") or {}
    skipped = collections.Counter(str(d(e).get("reason") or "?").split(" ")[0] + " cap" if "cap" in str(d(e).get("reason") or "")
                                  else str(d(e).get("reason") or "?")[:40] for e in events if e.get("type") == "nudge.skipped")
    failed = [d(e) for e in events if e.get("type") == "call.failed"]
    rel = [d(e) for e in events if e.get("type") == "release.published"]
    per = collections.Counter(r.get("name") for r in rel)
    return {
        "nudges": {"sent": c["nudge.sent"], "skipped": c["nudge.skipped"],
                   "cap_hits": sum(n for k, n in skipped.items() if k.endswith("cap")), "skipped_by_reason": dict(skipped)},
        "gates": {"approvals_requested": c["approval.requested"], "granted": c["approval.granted"], "denied": c["approval.denied"],
                  "expired": c["approval.expired"], "consumed": c["approval.consumed"],
                  "release_gate_overrides": [{"name": x.get("name"), "version": x.get("version"), "reason": str(x.get("reason") or "")[:160]}
                                             for x in (d(e) for e in events if e.get("type") == "release.gate_override")],
                  "failed_calls": len(failed), "failed_by_tool": dict(collections.Counter(x.get("tool") or "?" for x in failed)),
                  "failed_gate_like": sum(1 for x in failed if any(w in str(x.get("error") or "").lower() for w in GATE_WORDS)),
                  "bind_mismatch": c["bind.mismatch"], "handoff_gate_warnings": c["handoff.gate_warn"],
                  "handoff_gate_blocked": c["handoff.gate_blocked"], "handoff_gate_overrides": c["handoff.gate_override"]},
        "releases": {"count": len(rel), "per_plugin": dict(per),
                     "versions": sorted(f"{r.get('name')} {r.get('version')}" for r in rel),
                     "split_ratio": round(len(rel) / len(per), 2) if per else 0.0,
                     "plugins_released_more_than_once": sorted(k for k, n in per.items() if n > 1)},
        "handoffs": {"handed_off": c["agent.handed_off"], "auto_restores": c["restore.auto"]},
        "events": len(events),
    }


def indexer_stats(state_path=None):
    """The transcript indexer's own counters (read-only). None values: no indexer state on this machine."""
    p = state_path or os.path.join(os.environ.get("INDEXER_CACHE") or os.path.expanduser("~/.cache/harness-indexer"), "state.json")
    try:
        with open(p, encoding="utf-8") as f:
            s = json.load(f)
        c = s.get("counters") or {}
    except FileNotFoundError:
        return {"state": "absent", "path": p}
    except (OSError, ValueError) as e:
        return {"state": "unreadable: %s" % type(e).__name__, "path": p}
    lr = c.get("last_run") or 0
    return {"state": "ok", "path": p, "files_tracked": len(s.get("files") or {}), "redaction_failures": c.get("dropped_error", 0),
            "private_dropped": c.get("dropped_private", 0),
            "denied_sessions": len(s["denied_sessions"]) if "denied_sessions" in s else None,   # None: pre-0.17.0 indexer
            "last_run": dt.datetime.fromtimestamp(lr).strftime("%Y-%m-%d %H:%M") if lr else "never"}


def steward_stats(trend_path, since, until):
    rows = []
    try:
        with open(trend_path, encoding="utf-8") as f:
            for ln in f:
                try:
                    r = json.loads(ln)
                except ValueError:
                    continue
                t = _ts(r)
                if t and since <= t < until:
                    rows.append(r)
    except OSError:
        return {"state": "absent", "path": trend_path}
    if not rows:
        return {"state": "ok", "path": trend_path, "passes": 0}
    return {"state": "ok", "path": trend_path, "passes": len(rows), "findings_last": rows[-1].get("findings"),
            "exit_codes": dict(collections.Counter(str(r.get("exit")) for r in rows)),
            "live_tokens_first": rows[0].get("live_tokens"), "live_tokens_last": rows[-1].get("live_tokens"),
            "saved": sum(int(r.get("saved") or 0) for r in rows), "last": str(rows[-1].get("ts"))[:16]}


def mail_stats(home):
    res = LM.run(home, scripts=HERE)
    roles = {r: {k: v.get(k) for k in ("holder", "unread", "owed", "digest_head_tokens", "digest_tokens", "pinned_visible",
                                         "pinned_in_project", "digest_error") if v.get(k) is not None}
             for r, v in res["roles"].items()}
    return {"roles": roles, "ledger_seq": res["ledger_seq"], "corpus_entries": res["corpus"]["entries"],
            "pinned_decisions": res["corpus"]["pinned_decisions"]}


def previous(out_dir, name):
    """The newest earlier report JSON in out_dir (not this one), or {}."""
    files = sorted(p for p in glob.glob(os.path.join(out_dir, PREFIX + "*.json")) if os.path.basename(p) != name + ".json")
    if not files:
        return {}
    try:
        with open(files[-1], encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _chg(cur, prev):
    if not isinstance(cur, (int, float)) or isinstance(cur, bool) or not isinstance(prev, (int, float)) or isinstance(prev, bool):
        return ""
    dlt = cur - prev
    return "" if dlt == 0 else (" (+%s)" % dlt if dlt > 0 else " (%s)" % dlt)


def render(r, prev):
    P = lambda *ks: _get(prev, ks)
    L = [f"# Harness weekly health report {r['week']}",
         f"Window {r['since'][:16]} to {r['until'][:16]} UTC · ledger seq {r['mail']['ledger_seq']} · generated {r['generated'][:16]}"
         + (f" · compared with {prev['name']}" if prev.get("name") else " · first report (no comparison)"),
         "Local script, zero model tokens. Counts are facts from the ledger and local state files; nothing here is advice.", "",
         "## 1. Mail per role", "| role | holder | unread | owed | digest above capsule (tokens) | pins visible |", "|---|---|---|---|---|---|"]
    for role, v in sorted(r["mail"]["roles"].items(), key=lambda kv: -(kv[1].get("owed") or 0)):
        pv = f"{v.get('pinned_visible', '-')}/{v.get('pinned_in_project', '-')}" if "pinned_visible" in v else "-"
        L.append(f"| {role} | {v.get('holder') or '-'} | {v.get('unread', '-')}{_chg(v.get('unread'), P('mail', 'roles', role, 'unread'))} "
                 f"| {v.get('owed', '-')}{_chg(v.get('owed'), P('mail', 'roles', role, 'owed'))} "
                 f"| {v.get('digest_head_tokens', '-')}{_chg(v.get('digest_head_tokens'), P('mail', 'roles', role, 'digest_head_tokens'))} | {pv} |"
                 + (f" ERR {v['digest_error']}" if v.get("digest_error") else ""))
    n, g, rl, h = r["ledger"]["nudges"], r["ledger"]["gates"], r["ledger"]["releases"], r["ledger"]["handoffs"]
    L += ["", "## 2. Nudges",
          f"- sent {n['sent']}{_chg(n['sent'], P('ledger', 'nudges', 'sent'))}, skipped {n['skipped']}{_chg(n['skipped'], P('ledger', 'nudges', 'skipped'))}, "
          f"cap hits {n['cap_hits']}{_chg(n['cap_hits'], P('ledger', 'nudges', 'cap_hits'))}",
          "- skipped by reason: " + (", ".join(f"{k} {v}" for k, v in sorted(n["skipped_by_reason"].items(), key=lambda x: -x[1])) or "none"),
          "", "## 3. Gates",
          f"- approvals: requested {g['approvals_requested']}, granted {g['granted']}, denied {g['denied']}, expired {g['expired']}, consumed {g['consumed']}",
          f"- release gate overrides: {len(g['release_gate_overrides'])}" + "".join(f"\n  - {o['name']} {o['version']}: {o['reason']}" for o in g["release_gate_overrides"]),
          f"- failed tool calls: {g['failed_calls']}{_chg(g['failed_calls'], P('ledger', 'gates', 'failed_calls'))} "
          f"(gate or scope wording: {g['failed_gate_like']}); by tool: " + (", ".join(f"{k} {v}" for k, v in sorted(g["failed_by_tool"].items())) or "none"),
          f"- bind mismatches (warn mode): {g['bind_mismatch']}{_chg(g['bind_mismatch'], P('ledger', 'gates', 'bind_mismatch'))}",
          f"- handoff gate (events since 0.17.0): warnings {g['handoff_gate_warnings']}"
          f"{_chg(g['handoff_gate_warnings'], P('ledger', 'gates', 'handoff_gate_warnings'))}, "
          f"blocked {g['handoff_gate_blocked']}, overrides {g['handoff_gate_overrides']}"]
    ix = r["indexer"]
    L += ["", "## 4. Transcript indexer"]
    if ix["state"] == "ok":
        L.append(f"- redaction failures {ix['redaction_failures']}{_chg(ix['redaction_failures'], P('indexer', 'redaction_failures'))}, "
                 f"private messages dropped {ix['private_dropped']}, files tracked {ix['files_tracked']}, "
                 f"denied sessions {ix['denied_sessions'] if ix['denied_sessions'] is not None else 'n/a (indexer older than 0.17.0)'}, last run {ix['last_run']}")
    else:
        L.append(f"- {ix['state']} ({ix['path']})")
    s = r["steward"]
    L += ["", "## 5. Steward"]
    if s["state"] != "ok":
        L.append(f"- trend file {s['state']} ({s['path']})")
    elif not s["passes"]:
        L.append("- no steward pass in this window")
    else:
        L.append(f"- passes {s['passes']}, last {s['last']}, findings at the last pass {s['findings_last']}, exit codes "
                 + ", ".join(f"{k}: {v}" for k, v in sorted(s["exit_codes"].items()))
                 + f"; live tokens {s['live_tokens_first']} -> {s['live_tokens_last']}; saved {s['saved']}")
    L += ["", "## 6. Releases",
          f"- published {rl['count']}{_chg(rl['count'], P('ledger', 'releases', 'count'))}; split ratio {rl['split_ratio']} releases per released plugin"
          + (f"; more than once: {', '.join(rl['plugins_released_more_than_once'])}" if rl["plugins_released_more_than_once"] else ""),
          "- " + ("; ".join(rl["versions"]) or "none"),
          "", "## 7. Handoffs",
          f"- handoffs {h['handed_off']}{_chg(h['handed_off'], P('ledger', 'handoffs', 'handed_off'))}, auto-restores {h['auto_restores']}", ""]
    return "\n".join(L)


def _get(d, ks):
    for k in ks:
        if not isinstance(d, dict):
            return None
        d = d.get(k)
    return d


def report(home, out_dir, days=7, now=None, trend_path=None, indexer_state=None):
    until = now or dt.datetime.now(dt.timezone.utc)
    since = until - dt.timedelta(days=days)
    iso = until.isocalendar()
    week = f"{iso[0]}-W{iso[1]:02d}"
    name = f"{PREFIX}{week}_{until.strftime('%Y-%m-%d')}"   # one file per day; a rerun the same day replaces it
    ops = os.environ.get("HARNESS_OPS_ROOT") or os.path.expanduser("~/Claude/Code/harness-ops")
    trend_path = trend_path or os.path.join(ops, "projects", "orchestration", "digests", "trend.jsonl")
    r = {"name": name, "week": week, "since": since.isoformat(), "until": until.isoformat(),
         "generated": dt.datetime.now(dt.timezone.utc).isoformat(), "days": days,
         "mail": mail_stats(home), "ledger": ledger_stats(ledger_events(home, since, until)),
         "indexer": indexer_stats(indexer_state), "steward": steward_stats(trend_path, since, until)}
    os.makedirs(out_dir, exist_ok=True)
    prev = previous(out_dir, name)
    md, js = os.path.join(out_dir, name + ".md"), os.path.join(out_dir, name + ".json")
    with open(md, "w", encoding="utf-8") as f:
        f.write(render(r, prev))
    with open(js, "w", encoding="utf-8") as f:
        json.dump(r, f, indent=1, sort_keys=True)
    return md, js, r


def main(argv=None):
    ap = argparse.ArgumentParser(description="harness weekly health report (zero model tokens)")
    ap.add_argument("--home", help="Exchange folder (default: HARNESS_HOME or the usual location); only read")
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--out-dir", help="default: <HARNESS_OPS_ROOT or ~/Claude/Code/harness-ops>/projects/orchestration/digests/weekly")
    ap.add_argument("--now", help="end of the window, ISO time (default: now)")
    a = ap.parse_args(argv)
    import harness as H
    home = a.home or H.resolve_home()
    ops = os.environ.get("HARNESS_OPS_ROOT") or os.path.expanduser("~/Claude/Code/harness-ops")
    out = a.out_dir or os.path.join(ops, "projects", "orchestration", "digests", "weekly")
    now = dt.datetime.fromisoformat(a.now.replace("Z", "+00:00")) if a.now else None
    if now and now.tzinfo is None:
        now = now.replace(tzinfo=dt.timezone.utc)
    md, js, _ = report(home, out, a.days, now)
    print(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
