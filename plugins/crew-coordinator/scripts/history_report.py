#!/usr/bin/env python3
"""Read-only history report for crew-coordinator 0.14.6 (Wave 1: #2, #3, #11, #12, #13).

The append-only log is never rewritten. This script only reads it and prints counts and seq-id lists, so a
data fix goes on the write path (alias map, refs list, host normalisation) and history stays as logged.

    python3 scripts/history_report.py [--log <events.jsonl> | --home <Exchange>] [--json]
"""
import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness as H  # noqa: E402


def load(path):
    out = []
    with open(path, "r", encoding="utf-8") as f:     # read-only
        for line in f:
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except ValueError:
                    pass
    return out


def missing_via(events):
    """#12: events that carry no `via` provenance."""
    return [e["seq"] for e in events if not e.get("via")]


def actors_vs_registrations(events):
    """#13: distinct actor values against distinct agent.registered ids. The difference names the writers that are
    not registered agents (`human`, `system`, ...), with how many events and which types each wrote."""
    regs = {e["data"]["id"] for e in events if e.get("type") == "agent.registered"}
    actors = {}
    for e in events:
        a = actors.setdefault(e.get("actor"), {"events": 0, "types": {}, "first_seq": e["seq"]})
        a["events"] += 1
        a["types"][e["type"]] = a["types"].get(e["type"], 0) + 1
    extra = {k: v for k, v in actors.items() if k not in regs}
    return {"actors": len(actors), "registrations": len(regs),
            "unregistered_writers": {k: {"events": v["events"], "first_seq": v["first_seq"],
                                         "types": dict(sorted(v["types"].items(), key=lambda x: -x[1])[:6])}
                                     for k, v in extra.items()},
            "registered_never_acted": len(regs - set(actors))}


def string_refs(events):
    """#3 (events whose `refs` is a string, not a list)."""
    return [{"seq": e["seq"], "type": e["type"], "refs": (e.get("data") or {}).get("refs")}
            for e in events if isinstance((e.get("data") or {}).get("refs"), str)]


def project_offenders(events, aliases=None):
    """#2: corpus.recorded events whose project is null/empty, is not already in canonical (norm_project) form,
    or names a project that no registered agent or role ever had (unknown)."""
    aliases = aliases if aliases is not None else H.load_project_aliases()
    seen, out = set(), {"null": [], "not_canonical": [], "aliased": [], "unknown": []}
    for e in events:
        t, d = e.get("type"), e.get("data") or {}
        if t in ("agent.registered", "agent.updated", "role.defined") and d.get("project"):
            seen.add(H.norm_project(d["project"]))
        if t != "corpus.recorded":
            continue
        raw = d.get("project")
        if raw in (None, ""):
            out["null"].append(e["seq"])
            continue
        n = H.norm_project(raw)
        if n != raw:
            out["not_canonical"].append(e["seq"])
        if aliases.get(n, n) != n:
            out["aliased"].append(e["seq"])
        if aliases.get(n, n) not in {aliases.get(x, x) for x in seen}:
            out["unknown"].append(e["seq"])
    return out


def project_table(events, aliases=None):
    """Distinct project strings in the log (registrations, role definitions, corpus entries) with counts and the
    canonical project the alias map gives them; used to confirm data/project-aliases.json."""
    aliases = aliases if aliases is not None else H.load_project_aliases()
    rows = {}
    for e in events:
        d = e.get("data") or {}
        if e.get("type") in ("agent.registered", "corpus.recorded", "role.defined") and "project" in d:
            raw = d.get("project")
            r = rows.setdefault(raw, {"registered": 0, "recorded": 0, "role_defs": 0})
            r["recorded" if e["type"] == "corpus.recorded" else ("role_defs" if e["type"] == "role.defined" else "registered")] += 1
    return [{"project": k, "norm": H.norm_project(k) or None, "canonical": (aliases.get(H.norm_project(k), H.norm_project(k)) or None), **v}
            for k, v in sorted(rows.items(), key=lambda kv: str(kv[0]))]


def hosts(events):
    """#11: distinct host strings (registrations and via) and what norm_host maps them to."""
    seen = {}
    for e in events:
        for h_, src in (((e.get("data") or {}).get("host") if e.get("type") == "agent.registered" else None, "registered"),
                        ((e.get("via") or {}).get("host"), "via")):
            if h_ is not None:
                seen.setdefault(h_, {"registered": 0, "via": 0})[src] += 1
    return [{"host": k, "normalised": H.norm_host(k), **v} for k, v in sorted(seen.items())]


def wordlists(events):
    """H-016: existing names that use a word now in both lists, and the rule outcome for the shared words."""
    taken = {H.norm_name(e["data"]["sobriquet"]) for e in events if e.get("type") == "agent.registered"}
    dropped, kept = H.cross_list_dupes(taken)
    users = {w: sorted(t for t in taken if t.endswith(" " + w.lower())) for w in kept | dropped}
    return {"adjectives": len(H.ADJ), "nouns": len(H.NOUN), "cross_list_words": sorted(kept | dropped),
            "dropped_from_nouns_for_new_picks": sorted(dropped), "kept_flagged": sorted(kept),
            "existing_names_using_shared_noun": users, "rejected_adjectives": H._ADJ_REJECTED,
            "rejected_nouns": H._NOUN_REJECTED, "stored_names": len(taken)}


def build(events):
    return {"events": len(events), "missing_via": missing_via(events), "actors": actors_vs_registrations(events),
            "string_refs": string_refs(events), "project_offenders": project_offenders(events),
            "projects": project_table(events), "hosts": hosts(events), "wordlists": wordlists(events)}


def main(argv=None):
    ap = argparse.ArgumentParser(description="read-only history report")
    ap.add_argument("--log"); ap.add_argument("--home"); ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    path = a.log or os.path.join(a.home or H.resolve_home(), "_harness", "events.jsonl")
    r = build(load(path))
    if a.json:
        print(json.dumps(r, indent=1, ensure_ascii=False))
        return 0
    print(f"log: {path} · {r['events']} events")
    print(f"#12 events without via: {len(r['missing_via'])}  seqs={r['missing_via']}")
    ac = r["actors"]
    print(f"#13 distinct actors {ac['actors']} vs registrations {ac['registrations']}; unregistered writers:")
    for k, v in ac["unregistered_writers"].items():
        print(f"    {k!r}: {v['events']} events from seq {v['first_seq']} {v['types']}")
    print(f"#3 string refs: {len(r['string_refs'])}  seqs={[x['seq'] for x in r['string_refs']]}")
    po = r["project_offenders"]
    print("#2 corpus.recorded project offenders: " + "; ".join(f"{k}={len(v)}" for k, v in po.items()))
    for k, v in po.items():
        print(f"    {k}: {v}")
    print("projects (raw -> norm -> canonical):")
    for p in r["projects"]:
        print(f"    {p['project']!r} -> {p['norm']!r} -> {p['canonical']!r}  reg={p['registered']} rec={p['recorded']} roles={p['role_defs']}")
    print("#11 hosts:")
    for x in r["hosts"]:
        print(f"    {x['host']!r} -> {x['normalised']!r}  registered={x['registered']} via={x['via']}")
    w = r["wordlists"]
    print(f"H-016 lists: {w['adjectives']} adjectives, {w['nouns']} nouns, shared={w['cross_list_words']} "
          f"kept+flagged={w['kept_flagged']} dropped={w['dropped_from_nouns_for_new_picks']} users={w['existing_names_using_shared_noun']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
