#!/usr/bin/env python3
"""Recompute event hashes (crew-coordinator 0.14.6, #6). Read-only.

    python3 scripts/hash_vectors.py                 # data/hash-vectors.json: canonical JSON test vectors
    python3 scripts/hash_vectors.py --log events.jsonl   # every event in a log
    python3 scripts/hash_vectors.py --make > data/hash-vectors.json

Prints `<n>/<total> match`; exit 0 only when all match. The canonical form is pinned in docs/EVENTS.md.
"""
import argparse
import hashlib
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
VECTORS = os.path.join(HERE, "..", "data", "hash-vectors.json")


def canon(obj):
    """Pinned canonical JSON: keys sorted, separators (",", ":"), non-ASCII written as raw UTF-8 (ensure_ascii=False).
    Independent of harness.py on purpose: a second implementation is what makes this a test."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def event_hash(ev):
    return hashlib.sha256(canon({k: v for k, v in ev.items() if k != "hash"}).encode("utf-8")).hexdigest()


def check_events(events):
    # 0.15.3 (P7): every line must be an object whose hash matches; "_corrupt" is not an exemption, and a
    # non-object or unparseable line counts as a mismatch (reported by line number) instead of aborting the run.
    bad = []
    for i, e in enumerate(events, 1):
        if not isinstance(e, dict) or e.get("_unparseable") or event_hash(e) != e.get("hash"):
            bad.append(e.get("seq") if isinstance(e, dict) and e.get("seq") is not None else f"line {i}")
    return len(events) - len(bad), len(events), bad


def check_vectors(vectors):
    bad = []
    for i, v in enumerate(vectors):
        ok = canon(v["event"]) == v["canonical"] and hashlib.sha256(v["canonical"].encode("utf-8")).hexdigest() == v["hash"]
        if not ok:
            bad.append(i)
    return len(vectors) - len(bad), len(vectors), bad


def make():
    evs = [
        {"v": 1, "seq": 1, "ts": "2026-10-13T08:00:00.000Z", "t": 1790000000.0, "type": "t.empty", "actor": "human",
         "data": {}, "prev": "0" * 64},
        {"v": 1, "seq": 2, "ts": "2026-10-13T08:00:01.250Z", "t": 1790000001.25, "type": "t.nested", "actor": "a" * 64,
         "data": {"b": [3, 2, 1], "a": {"z": None, "y": True, "x": False}, "n": 0, "neg": -7}, "prev": "x"},
        {"v": 1, "seq": 3, "ts": "2026-10-13T08:00:02.001Z", "t": 1790000002.001, "type": "t.unicode", "actor": "system",
         "data": {"s": "café ◆ → ✓ 日本", "q": "a\"b\\c\nd\te", "emoji": "\U0001F600"}, "prev": "y"},
        {"v": 1, "seq": 4, "ts": "2026-10-13T08:00:03.100Z", "t": 1790000003.1, "type": "t.float", "actor": "human",
         "data": {"f": 0.1, "g": 1e-07, "h": 123456789.125, "i": 1.0}, "prev": "z", "via": {"t": "cli", "v": "0.14.6"}},
    ]
    return [{"event": e, "canonical": canon(e), "hash": hashlib.sha256(canon(e).encode("utf-8")).hexdigest()} for e in evs]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--log"); ap.add_argument("--vectors", default=VECTORS); ap.add_argument("--make", action="store_true")
    a = ap.parse_args(argv)
    if a.make:
        print(json.dumps(make(), indent=1, ensure_ascii=False))
        return 0
    if a.log:
        with open(a.log, "r", encoding="utf-8") as f:
            events = []
            for l in f:
                if not l.strip():
                    continue
                try:
                    events.append(json.loads(l))
                except ValueError:
                    events.append({"_unparseable": True})
        ok, n, bad = check_events(events)
        what = f"log {a.log}"
    else:
        with open(a.vectors, encoding="utf-8") as f:
            ok, n, bad = check_vectors(json.load(f))
        what = f"vectors {os.path.basename(a.vectors)}"
    print(f"{what}: {ok}/{n} match" + (f"; mismatches at {bad[:20]}" if bad else ""))
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
