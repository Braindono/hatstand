#!/usr/bin/env python3
"""hook_latency (0.27.2 I6, step 0 of the refactor): time every hook in hooks/hooks.json on a path proven to run. Depends on: tools/hook_cases.py, scripts/harness.py, stdlib.
Usage: python3 tools/hook_latency.py [--runs 20] [--messages 3000] [--json] [--day1]   (--day1 exits 1 when any hook is an early exit or a hook has no case)
A synthetic ledger (5 agents, 3000 messages through the real Harness API) is built once in a temporary home and cached under the temp folder, keyed on the code sha and the
day; before EVERY timed run the ledger is restored from that pristine copy, so each run starts alike and the live ledger is never read or written.
One row per hook command in hooks.json: median and p90 ms over the runs, the last exit code, the proof that the intended path ran (named output text, a ledger event
or a changed file) and its verdict: "measured" (the proof held on every run) or "early exit" (no proof, or it failed on some run: not a measurement).
One more row times `python3 -c "import harness"` alone."""
import argparse
import json
import math
import os
import shutil
import statistics
import subprocess
import sys
import tempfile
import time

MAX_AGE_S = 3000      # the release-guard case needs a release.published event less than 2 hours old, so a cached ledger lives 50 minutes
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import hook_cases as C


def hooks_in(path=None):
    """-> [(event, matcher, command)] for every command in hooks.json, in file order."""
    with open(path or os.path.join(ROOT, "hooks", "hooks.json"), encoding="utf-8") as f:
        d = json.load(f)["hooks"]
    return [(ev, x.get("matcher", ""), h["command"]) for ev, groups in d.items() for x in groups for h in x.get("hooks", [])]


def tail_of(command):
    """'python3 "${CLAUDE_PLUGIN_ROOT}/scripts/harness.py" hook idcheck' -> 'harness.py hook idcheck'."""
    return command.split("/scripts/", 1)[1].replace('"', "", 1).strip()


def ledger_key():
    sys.path.insert(0, os.path.join(ROOT, "scripts"))
    import harness
    import datetime
    return harness.code_sha(ROOT, "plugin")[:12] + "-" + datetime.date.today().isoformat()


def pristine(base, messages):
    """-> (dir, info). The cached pristine ledger for this code sha and day (built once)."""
    d = os.path.join(base, "ledger-%s-%d" % (ledger_key(), messages))
    try:
        with open(os.path.join(d, "ok")) as f:
            fresh = time.time() - json.load(f)["built"] < MAX_AGE_S
    except (OSError, ValueError, KeyError):
        fresh = False
    if not fresh:
        shutil.rmtree(d, ignore_errors=True)
        os.makedirs(d)
        info = C.build_ledger(d, ROOT, messages)
        with open(os.path.join(d, "ok"), "w") as f:
            json.dump(info, f)
    with open(os.path.join(d, "ok")) as f:
        return d, json.load(f)


def _events(home):
    try:
        with open(os.path.join(home, "_harness", "events.jsonl"), "rb") as f:
            return f.read()
    except OSError:
        return b""


def _abs(run, rel):
    return os.path.join(run, rel) if rel.startswith("state/") else os.path.join(run, "home", rel)


def _stamp(path):
    """(name, size, mtime) of a file, or of every file under a folder; empty when absent."""
    files = [(os.path.dirname(path), os.path.basename(path))] if os.path.isfile(path) else [(dp, fn) for dp, _d, fs in os.walk(path) for fn in fs]
    out = []
    for dp, fn in files:
        try:
            st = os.stat(os.path.join(dp, fn))
            out.append((fn, st.st_size, st.st_mtime_ns))
        except OSError:
            pass
    return sorted(out)


def relocate_cache(run):
    """The corpus index is kept per home path (sha of its real path); the restored copy lives at another path, so the one cache folder is renamed to match."""
    import hashlib
    os.makedirs(os.path.join(run, "cache"), exist_ok=True)
    try:
        src = os.path.join(run, "cache", os.listdir(os.path.join(run, "cache"))[0])
    except IndexError:
        return
    dst = os.path.join(run, "cache", hashlib.sha256(os.path.realpath(os.path.join(run, "home")).encode()).hexdigest()[:12])
    if src != dst:
        os.rename(src, dst)


def proof_held(proof, run, before, after_out):
    """True when the named evidence of the intended path is there."""
    if not proof:
        return False
    kind, needle = proof
    home = os.path.join(run, "home")
    if kind == "out":
        return needle in after_out
    if kind == "event":
        new = _events(home)[before["events"]:].decode("utf-8", "replace")
        return any(('"type": "%s"' % needle in ln or '"type":"%s"' % needle in ln) for ln in new.splitlines())
    return _stamp(_abs(run, needle)) != before["files"]


def time_hook(ev, command, extra, proof, pristine_dir, run, runs, env):
    cmd = [sys.executable, "-B", os.path.join(ROOT, "scripts", command.split("/scripts/", 1)[1].split('"')[0])] + command.split('"')[-1].split()
    ms, held, rc = [], 0, None
    base_in = {"session_id": C.SID, "cwd": os.path.join(run, "home", "proj"), "transcript_path": "", "hook_event_name": ev}
    for _ in range(runs):
        shutil.rmtree(run, ignore_errors=True)
        shutil.copytree(pristine_dir, run, ignore=shutil.ignore_patterns("ok"))
        home = os.path.join(run, "home")
        os.makedirs(os.path.join(home, "proj"), exist_ok=True)
        relocate_cache(run)
        before = {"events": len(_events(home)), "files": _stamp(_abs(run, proof[1])) if proof and proof[0] == "file" else []}
        t = time.perf_counter()
        p = subprocess.run(cmd, input=json.dumps(dict(base_in, **extra)), capture_output=True, text=True, env=env, cwd=run)
        ms.append((time.perf_counter() - t) * 1000)
        rc = p.returncode
        held += proof_held(proof, run, before, p.stdout)
    return ms, held, rc


def row(name, ev, ms, held, rc, proof, runs):
    ms = sorted(ms)
    verdict = "measured" if proof and held == runs else "early exit"
    return {"hook": name, "event": ev, "median_ms": round(statistics.median(ms), 1), "p90_ms": round(ms[max(0, math.ceil(0.9 * len(ms)) - 1)], 1), "exit": rc,
            "proof": ("%s: %s" % proof if proof else "none") + (" (%d/%d runs)" % (held, runs) if proof else ""), "verdict": verdict}


def measure(runs=20, messages=3000, base=None, only=None):
    base = base or os.path.join(tempfile.gettempdir(), "hook-latency-cache")
    os.makedirs(base, exist_ok=True)
    pdir, info = pristine(base, messages)
    run = tempfile.mkdtemp(prefix="hl-run-")
    try:
        env = C.env_for(run, ROOT)
        table = C.cases(os.path.join(run, "home"), info)
        rows = []
        for ev, _m, command in hooks_in():
            if only and tail_of(command) not in only:
                continue
            extra, proof = table.get((ev, tail_of(command)), ({}, None))
            ms, held, rc = time_hook(ev, command, extra, proof, pdir, run, runs, env)
            rows.append(row(tail_of(command), ev, ms, held, rc, proof, runs))
        t = []
        for _ in range(runs):
            s = time.perf_counter()
            subprocess.run([sys.executable, "-B", "-c", "import sys; sys.path.insert(0, %r); import harness" % os.path.join(ROOT, "scripts")], capture_output=True, env=env, cwd=run)
            t.append((time.perf_counter() - s) * 1000)
        rows.append({"hook": 'python3 -c "import harness"', "event": "import only", "median_ms": round(statistics.median(t), 1),
                     "p90_ms": round(sorted(t)[max(0, math.ceil(0.9 * len(t)) - 1)], 1), "exit": 0, "proof": "n/a (import time)", "verdict": "import"})
        return rows
    finally:
        shutil.rmtree(run, ignore_errors=True)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=20)
    ap.add_argument("--messages", type=int, default=3000)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--day1", action="store_true")
    a = ap.parse_args(argv)
    rows = measure(a.runs, a.messages)
    if a.json:
        print(json.dumps(rows, indent=1))
    else:
        for r in rows:
            print("%-8s %-44s median %7.1f p90 %7.1f exit %s  %s  [%s]" % (r["event"][:8], r["hook"][:44], r["median_ms"], r["p90_ms"], r["exit"], r["verdict"], r["proof"]))
    bad = [r for r in rows if r["verdict"] == "early exit"]
    if bad:
        sys.stderr.write("%d hook(s) without proof of the intended path: %s\n" % (len(bad), ", ".join(r["hook"] for r in bad)))
    return 1 if (a.day1 and bad) else 0


if __name__ == "__main__":
    sys.exit(main())
