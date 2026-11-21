"""harness_verify: reads the root grant log and the ledger; the unpatchable audit, and the replay filter's source.

What it does: verifies every signed log record against the public key, lists the human ledger events that are
signed-in (matched by a consume record) and reports human events after the cutover that are not, plus consumed events
missing from the ledger. Installed root-owned as /usr/local/libexec/harness-verify; the plugin imports the same source.
Why: only root's signature makes a human event count; a patched reader of the ledger must not widen that.
Depends on: json, subprocess (/usr/bin/openssl), tempfile, os, harness_event_map. Interface:
  load_log(log_path, pub_path) -> (records, bad), accepted(log_path, pub_path) -> (cutover_seq|None, set of (seq, hash)),
  audit(ledger_path, log_path, pub_path) -> list of problem strings, main(argv).
"""
import base64
import json
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness_event_map as MAP

DOMAIN = "harness-op-v1|"
OPENSSL = "/usr/bin/openssl"


def sign_text(rec):
    return DOMAIN + json.dumps(rec, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def verify_sig(pub_path, text, sig_b64):
    try:
        sig = base64.b64decode(sig_b64)
        with tempfile.TemporaryDirectory() as d:
            sp, mp = os.path.join(d, "s"), os.path.join(d, "m")
            open(sp, "wb").write(sig)
            open(mp, "wb").write(text.encode("utf-8"))
            r = subprocess.run([OPENSSL, "dgst", "-sha256", "-verify", pub_path, "-signature", sp, mp],
                               capture_output=True, env={})
            return r.returncode == 0
    except Exception:
        return False


def load_log(log_path, pub_path):
    recs, bad = [], []
    try:
        lines = open(log_path, encoding="utf-8").read().splitlines()
    except OSError:
        return [], []
    for n, line in enumerate(lines, 1):
        try:
            o = json.loads(line)
            rec, sig = o["rec"], o["sig"]
        except Exception:
            bad.append(f"log line {n}: unreadable")
            continue
        if verify_sig(pub_path, sign_text(rec), sig):
            recs.append(rec)
        else:
            bad.append(f"log line {n}: signature invalid")
    return recs, bad


def accepted(log_path, pub_path):
    recs, _ = load_log(log_path, pub_path)
    cut, ok = None, set()
    for r in recs:
        if r.get("t") == "cutover" and cut is None:
            cut = int(r["seq"])
        elif r.get("t") == "consume":
            for s, h in r.get("events", []):
                ok.add((int(s), h))
    return cut, ok


def _ledger(path):
    out = []
    for line in open(path, encoding="utf-8").read().splitlines():
        try:
            e = json.loads(line)
            if isinstance(e, dict):
                out.append(e)
        except ValueError:
            continue
    return out


def audit(ledger_path, log_path, pub_path):
    recs, bad = load_log(log_path, pub_path)
    problems = list(bad)
    cut, ok = accepted(log_path, pub_path)
    if cut is None:
        return problems + ["no cutover record: the gate is not installed"]
    evs = {e.get("seq"): e for e in _ledger(ledger_path)}
    for s, h in sorted(ok):
        e = evs.get(s)
        if e is None or e.get("hash") != h:
            problems.append(f"consumed event seq {s} is missing or changed in the ledger")
    for s, e in sorted(evs.items()):
        if isinstance(s, int) and s > cut and MAP.enforced(e.get("type"), e.get("actor"), e.get("data")) and (s, e.get("hash")) not in ok:
            problems.append(f"human event seq {s} ({e.get('type')}) has no signed grant: ignored (any actor)")
    return problems


def main(argv=None):
    a = argv or sys.argv[1:]
    if len(a) != 3:
        print("usage: harness-verify <ledger events.jsonl> <grants.log> <public key>")
        return 2
    p = audit(*a)
    print("\n".join(p) if p else "ok: every human event after the cutover is signed")
    return 1 if p else 0


if __name__ == "__main__":
    sys.exit(main())
