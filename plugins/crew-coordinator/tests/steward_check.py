"""cc 0.17.0 R-045: steward pass quality checks on a FROZEN fixture corpus, never the live one (plan v2, critic 15-16).

What it proves about one steward pass (corpus_index.py --pass, then the steward's prune):
  - mechanical: exit bit "step_failed" clear, digest json+md written, --proof verifies
  - canary: an entry that meets the prune criteria (flagged old-decision) but sits outside the steward's S6 tier;
    it must NOT be archived (catches an over-eager prune)
  - bait: an orphan orchestration note inside the tier; it MUST be archived (a pass that does nothing fails)
  - integrity: every archived id was flagged by the pass; nothing deleted (row count kept, archive copy on disk)
  - golden recall: 30 queries with expected ids (the bait's query expects it gone)
  - unarchive round trip: the bait comes back live and findable, then is archived again
Format-independent: the digest is read through FORMATS (v4 today). The curator's v5 (named exit bits, per-project
table) is a data change there. The pass-for-nothing alarm and the drift curve wait for v5.

Usage (from the build root; the fixture is copied to a temp folder, never written in place):
  python3 -B tests/steward_check.py --check [--steward reference|none|eager] [--out FILE]
  python3 -B tests/steward_check.py --score --home H --ops O --digest D   (score a real steward's run on a staged copy)
  python3 -B tests/steward_check.py --stage DIR                           (copy the fixture for a real steward run)
  python3 -B tests/steward_check.py --build-fixture                       (rebuild; the old one is archived first)
Exit: 0 PASS, 1 FAIL, 2 setup error (fixture changed on disk, corpus_index.py not found)."""
import functools, hashlib, json, os, shutil, subprocess, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
BUILD = os.path.dirname(HERE)
FIXTURE = os.path.join(HERE, "fixtures", "steward-r045")
HARNESS_PY = os.path.join(BUILD, "scripts", "harness.py")
# cc170-build sits at <ops>/projects/skill-curation/specs/cc170-build; corpus_index.py at <ops>/projects/orchestration/scripts
CORPUS_INDEX = os.path.join(BUILD, "..", "..", "..", "orchestration", "scripts", "corpus_index.py")
MODEL = "claude-opus-5-5"
STEWARD_NAME = "Corpus Steward"

# Digest formats. Each: detect (key -> value that must match), bits (name -> exit bit), and dotted paths into the digest.
# v5 lands as one more entry here (named exit bits, per-project table); no code change.
FORMATS = {
    "v4": {"detect": {"schema": 1}, "absent": ["exit_bits"],
           "bits": {"lint": 1, "over": 2, "step_failed": 4},
           "exit": "proof.exit", "hash": "proof.hash", "flagged": "health.flagged", "projects": None},
}


def _get(d, path):
    for k in (path or "").split("."):
        if not isinstance(d, dict) or k not in d:
            return None
        d = d[k]
    return d


def read_digest(digest):
    """-> {format, exit, bits:[names], hash, flagged:[ids], projects}. Raises ValueError on an unknown format."""
    for name, f in FORMATS.items():
        if all(digest.get(k) == v for k, v in f["detect"].items()) and not any(k in digest for k in f.get("absent", [])):
            ex = _get(digest, f["exit"])
            ex = ex if isinstance(ex, int) else -1
            return {"format": name, "exit": ex, "hash": _get(digest, f["hash"]),
                    "bits": sorted(n for n, b in f["bits"].items() if ex >= 0 and ex & b),
                    "flagged": [r.get("id") for r in (_get(digest, f["flagged"]) or []) if isinstance(r, dict)],
                    "projects": _get(digest, f["projects"]) if f["projects"] else None}
    raise ValueError(f"unknown digest format (schema={digest.get('schema')!r}); add it to FORMATS")


def _no_cache(fn):
    """Run fn with the harness state cache off, then restore the caller's environment (no leak into other tests)."""
    @functools.wraps(fn)
    def w(*a, **k):
        old = os.environ.get("HARNESS_STATE_CACHE")
        os.environ["HARNESS_STATE_CACHE"] = "0"
        try:
            return fn(*a, **k)
        finally:
            if old is None:
                os.environ.pop("HARNESS_STATE_CACHE", None)
            else:
                os.environ["HARNESS_STATE_CACHE"] = old
    return w


# ----------------------------------------------------------------- fixture

def _sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(65536), b""):
            h.update(b)
    return h.hexdigest()


def _files(root):
    out = {}
    for r, ds, fs in os.walk(root):
        ds[:] = sorted(d for d in ds if d != "__pycache__")
        for x in sorted(fs):
            if x.endswith(".lock") or x == ".DS_Store":
                continue
            p = os.path.join(r, x)
            out[os.path.relpath(p, root)] = _sha(p)
    return out


def load_manifest(fixture=FIXTURE):
    with open(os.path.join(fixture, "manifest.json"), encoding="utf-8") as f:
        return json.load(f)


def verify_frozen(fixture=FIXTURE):
    """-> list of problems; [] when every fixture file matches the manifest and nothing was added."""
    try:
        man = load_manifest(fixture)
    except (OSError, ValueError) as e:
        return [f"manifest: {e}"]
    have = _files(os.path.join(fixture, "home"))
    want = man.get("files") or {}
    probs = [f"changed: {p}" for p in sorted(want) if p in have and have[p] != want[p]]
    probs += [f"missing: {p}" for p in sorted(want) if p not in have]
    probs += [f"added: {p}" for p in sorted(have) if p not in want]
    return probs


# Golden entries: (project, role, kind, title, query). Titles carry one distinctive word each; the query is that word.
GOLDEN = [
    ("secretary", "secretary", "note", "Invoice reminders batch on Thursdays", "invoice"),
    ("secretary", "secretary", "note", "Calendar holds expire after 48 hours", "calendar"),
    ("secretary", "secretary", "decision", "Mail triage labels use three colours", "triage"),
    ("secretary", "secretary", "note", "Travel bookings keep the receipt PDF", "travel"),
    ("secretary", "secretary", "decision", "Birthday cards go out a week early", "birthday"),
    ("secretary", "secretary", "note", "Pharmacy refill window is five days", "pharmacy"),
    ("secretary", "secretary", "note", "Utility meter photos stay private", "utility"),
    ("cv-management", "letters-manager", "decision", "Cover letters stay under one page", "cover"),
    ("cv-management", "letters-manager", "note", "Referees are asked before listing", "referees"),
    ("cv-management", "letters-manager", "note", "Portfolio links point at the static site", "portfolio"),
    ("cv-management", "letters-manager", "decision", "Salary bands are never stated first", "salary"),
    ("cv-management", "letters-manager", "note", "Interview prep notes live per company", "interview"),
    ("cv-management", "letters-manager", "note", "Headshot photo is not attached", "headshot"),
    ("skill-curation", "curator", "decision", "Plugin versions follow semver strictly", "semver"),
    ("skill-curation", "curator", "note", "Marketplace registry is rebuilt nightly", "marketplace"),
    ("skill-curation", "curator", "note", "Lint warnings block nothing until 0.18", "warnings"),
    ("skill-curation", "curator", "decision", "Changelog entries cite the request id", "changelog"),
    ("skill-curation", "curator", "note", "Fixture trees are regenerated on purpose only", "regenerated"),
    ("skill-curation", "curator", "note", "Canary installs go to one role first", "installs"),
    ("orchestration", "steward", "note", "Trend rows append once per pass", "trend"),
    ("orchestration", "steward", "note", "Weekly report groups by ISO week", "weekly"),
    ("orchestration", "steward", "note", "Secretary feed carries the top three findings", "feed"),
    ("orchestration", "steward", "note", "Proof hash covers the canonical digest", "proof"),
    ("orchestration", "envoy", "decision", "Envoy inspects every steward pass", "inspects"),
    ("orchestration", "envoy", "decision", "Prune trigger is per project", "trigger"),
    ("orchestration", "envoy", "note", "Spot checks take two archived ids", "spot"),
    ("orchestration", "envoy", "note", "Verdicts are PASS FAIL or ACTION", "verdicts"),
    ("orchestration", "envoy", "decision", "Archive only, never delete", "never"),
]
CANARY = ("secretary", "decision", "Canary: quarterly tax folder is kept forever", "quarterly")
BAIT = ("orchestration", "note", "Bait: scheduler retry memo from the old pass", "scheduler")


@_no_cache
def build_fixture(fixture=FIXTURE):
    """Build the synthetic corpus once and freeze it (file hashes in manifest.json). An existing fixture is archived
    to fixtures/_archive/<date>-steward-r045-<time>/ first, never deleted."""
    import harness as H
    if os.path.exists(fixture):
        dst = os.path.join(os.path.dirname(fixture), "_archive",
                           time.strftime("%Y-%m-%d") + "-steward-r045-" + time.strftime("%H%M%S"))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.move(fixture, dst)
    work = tempfile.mkdtemp(prefix="r045-build-")
    home = os.path.join(work, "Exchange")
    os.makedirs(os.path.join(home, "_harness"))
    h = H.Harness(home)
    roles = {"steward": "orchestration", "envoy": "orchestration", "secretary": "secretary",
             "letters-manager": "cv-management", "curator": "skill-curation"}
    for r, p in roles.items():
        h.role_define("operator", r, p)
        a = h.register(project=p, model=MODEL)["id"]
        h.role_assign("operator", r, a)
    hold = lambda r: h.state().role_holder(r)
    canary = h.record(hold("secretary"), "decision", CANARY[2], "Kept for the record; the owner decides its fate.")["id"]
    bait = h.record(hold("steward"), "note", BAIT[2], "Superseded by the trend file; nothing cites it.")["id"]

    def roll(role, n):
        for _ in range(n):
            h.handoff(hold(role), "---\nhandoff: x\n---\n# H\nRoutine handoff.\n")
            h.restore(role, model=MODEL, project=roles[role], confirmed=True)
    roll("secretary", 3)   # the canary's author is now 3 generations back: old-decision
    roll("steward", 1)     # the bait's author is superseded: orphan note in orchestration
    golden = []
    for p, r, k, title, q in GOLDEN:
        i = h.record(hold(r), k, title, f"{title}. Recorded for the R-045 golden recall set.")["id"]
        golden.append({"q": q, "expect": i, "present": True})
    golden.append({"q": CANARY[3], "expect": canary, "present": True})
    golden.append({"q": BAIT[3], "expect": bait, "present": False})
    import health
    pre = health.health(h)
    os.makedirs(fixture)
    shutil.copytree(home, os.path.join(fixture, "home"), ignore=shutil.ignore_patterns("*.lock", "__pycache__"))
    man = {"built": time.strftime("%Y-%m-%d"), "purpose": "R-045 steward pass checks; synthetic, no live data",
           "canary": [canary], "bait": [bait], "golden": golden, "steward": hold("steward"),
           "entries": pre["entries"], "flagged": sorted(f["id"] for f in pre["flagged"]),
           "files": _files(os.path.join(fixture, "home"))}
    with open(os.path.join(fixture, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(man, f, indent=1, sort_keys=True)
    shutil.rmtree(work, ignore_errors=True)   # our own temp build folder
    return man


def stage(dst, fixture=FIXTURE):
    """Copy the frozen fixture to dst -> (home, ops). Refuses a changed fixture."""
    probs = verify_frozen(fixture)
    if probs:
        raise RuntimeError("fixture changed on disk: " + "; ".join(probs[:5]))
    home, ops = os.path.join(dst, "home"), os.path.join(dst, "ops")
    shutil.copytree(os.path.join(fixture, "home"), home)
    # empty folders are made here, not shipped: a zip package drops empty directories
    os.makedirs(os.path.join(ops, "projects", "orchestration", "digests"))
    os.makedirs(os.path.join(home, "corpus"), exist_ok=True)
    return home, ops


# ----------------------------------------------------------------- pass, steward, score

def _env(ops):
    e = {k: v for k, v in os.environ.items() if not k.startswith("HARNESS_")}
    e.update({"HARNESS_OPS_ROOT": ops, "HARNESS_PY": HARNESS_PY, "HARNESS_STATE_CACHE": "0", "PYTHONDONTWRITEBYTECODE": "1"})
    return e


def run_pass(home, ops, corpus_index=CORPUS_INDEX):
    """corpus_index.py --pass on the staged copy -> (exit, digest json path or None, stdout)."""
    r = subprocess.run([sys.executable, "-B", corpus_index, "--home", home, "--pass", "--by", STEWARD_NAME,
                        "--trigger", "r045-check"], capture_output=True, text=True, env=_env(ops), timeout=300)
    dd = os.path.join(ops, "projects", "orchestration", "digests")
    js = sorted(f for f in os.listdir(dd) if "-pass-" in f and f.endswith(".json") and "-diff" not in f) if os.path.isdir(dd) else []
    return r.returncode, (os.path.join(dd, js[-1]) if js else None), (r.stdout + r.stderr).strip()


def _harness(home):
    import harness as H
    return H, H.Harness(home)


@_no_cache
def steward(home, flagged, mode="reference", steward_id=None):
    """Prune the flagged ids. reference: as the steward, archive what the S6 gate allows, one id at a time (the rest
    would go to the owner as kind=review). none: archive nothing. eager: the operator archives every flagged id.
    -> {archived: [...], refused: {id: reason}}"""
    H, h = _harness(home)
    out = {"archived": [], "refused": {}}
    if mode == "none":
        return out
    by = "operator" if mode == "eager" else (steward_id or h.state().role_holder("steward"))
    for i in flagged:
        try:
            why = ""
            if mode == "eager":   # the archive needs a quoted line from the entry (D-15566 P2): quote its title
                t = (h.corpus.db.execute("SELECT title FROM entries WHERE id=?", (i,)).fetchone() or [""])[0]
                why = f'r045 eager control: "{t}"'
            h.archive(by, [i], reason=why)
            out["archived"].append(i)
        except H.HarnessError as e:
            out["refused"][i] = str(e)[:160]
    return out


@_no_cache
def score(home, ops, digest_path, man, corpus_index=CORPUS_INDEX, round_trip=True):
    """-> {verdict, checks:[{name, ok, detail}]}"""
    checks = []
    add = lambda n, ok, d="": checks.append({"name": n, "ok": bool(ok), "detail": d})
    dg = None
    if digest_path and os.path.isfile(digest_path):
        with open(digest_path, encoding="utf-8") as f:
            dg = read_digest(json.load(f))
    add("digest_written", dg is not None and os.path.isfile(digest_path[:-5] + ".md"), digest_path or "none")
    if dg is None:
        return {"verdict": "FAIL", "checks": checks}
    add("step_failed_clear", "step_failed" not in dg["bits"] and dg["exit"] >= 0, f"exit={dg['exit']} bits={dg['bits']}")
    pr = subprocess.run([sys.executable, "-B", corpus_index, "--home", home, "--proof", str(dg["hash"]), "--exit", str(dg["exit"])],
                        capture_output=True, text=True, env=_env(ops), timeout=120)
    add("proof_verifies", pr.returncode == 0, (pr.stdout or pr.stderr).strip()[:160])
    flagged = set(dg["flagged"])
    can, bait = man["canary"], man["bait"]
    add("canary_flagged", set(can) <= flagged, "fixture sanity: the canary meets the prune criteria")
    add("bait_flagged", set(bait) <= flagged, "fixture sanity: the bait meets the prune criteria")
    H, h = _harness(home)
    state = lambda i: h.corpus.entry_state(i)
    add("canary_survived", all(state(i) == "live" for i in can), {i: state(i) for i in can})
    add("bait_archived", all(state(i) == "archived" for i in bait), {i: state(i) for i in bait})
    archived = sorted(r[0] for r in h.corpus.db.execute("SELECT id FROM entries WHERE superseded_by='archived'"))
    add("archived_were_flagged", set(archived) <= flagged, sorted(set(archived) - flagged))
    n = h.corpus.db.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
    copies = {os.path.splitext(f)[0] for r, _, fs in os.walk(os.path.join(home, "_archive", "corpus")) for f in fs if f.endswith(".md")}
    add("nothing_deleted", n == man["entries"] and set(archived) <= copies,
        f"rows {n}/{man['entries']}; archive copies missing {sorted(set(archived) - copies)}")
    hits, miss = 0, []
    for g in man["golden"]:
        ids = [r["id"] for r in h.corpus.search(g["q"], limit=5)]
        ok = (g["expect"] in ids) == g["present"]
        hits += ok
        if not ok:
            miss.append(g["q"])
    add("golden_recall", hits == len(man["golden"]) and len(man["golden"]) >= 30, f"{hits}/{len(man['golden'])} miss={miss}")
    if round_trip:
        b = bait[0]
        rows0 = n
        u = h.unarchive(man["steward"], [b])
        back = state(b) == "live" and b in [r["id"] for r in h.corpus.search(BAIT[3], limit=5)]
        again = False
        try:
            h.archive(man["steward"], [b], reason="")
            again = state(b) == "archived"
        except H.HarnessError as e:
            u["rearchive_error"] = str(e)[:160]
        rows1 = h.corpus.db.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
        add("unarchive_round_trip", back and again and rows1 == rows0, f"back={back} rearchived={again} rows {rows0}->{rows1}")
    return {"verdict": "PASS" if all(c["ok"] for c in checks) else "FAIL", "format": dg["format"], "checks": checks}


def check(mode="reference", fixture=FIXTURE, corpus_index=CORPUS_INDEX, keep=False):
    """Stage the fixture, run the pass, prune with `mode`, score. -> result dict."""
    if not os.path.isfile(corpus_index):
        raise FileNotFoundError(f"corpus_index.py not found at {os.path.normpath(corpus_index)}")
    man = load_manifest(fixture)
    work = tempfile.mkdtemp(prefix="r045-")
    home, ops = stage(work, fixture)
    code, dpath, log = run_pass(home, ops, corpus_index)
    flagged = []
    if dpath:
        with open(dpath, encoding="utf-8") as f:
            flagged = read_digest(json.load(f))["flagged"]
    pr = steward(home, flagged, mode, man["steward"])
    res = score(home, ops, dpath, man, corpus_index)
    res.update({"steward_mode": mode, "pass_exit": code, "pass_line": log.splitlines()[-1] if log else "",
                "archived": pr["archived"], "refused": sorted(pr["refused"]), "work": work if keep else None})
    if not keep:
        shutil.rmtree(work, ignore_errors=True)   # our own temp copy
    return res


def main(argv):
    sys.path.insert(0, HERE)
    import _env  # noqa: F401  private HOME, no HARNESS_* from the caller
    sys.path.insert(0, os.path.join(BUILD, "scripts"))
    val = lambda f, d=None: argv[argv.index(f) + 1] if f in argv and argv.index(f) + 1 < len(argv) else d
    try:
        if "--build-fixture" in argv:
            m = build_fixture()
            print(json.dumps({"built": FIXTURE, "files": len(m["files"]), "flagged": len(m["flagged"]),
                              "golden": len(m["golden"])}, indent=1))
            return 0
        if "--stage" in argv:
            home, ops = stage(val("--stage"))
            print(json.dumps({"home": home, "ops": ops}))
            return 0
        if "--score" in argv:
            res = score(val("--home"), val("--ops"), val("--digest"), load_manifest(), val("--corpus-index", CORPUS_INDEX))
        else:
            res = check(val("--steward", "reference"), corpus_index=val("--corpus-index", CORPUS_INDEX), keep="--keep" in argv)
    except (RuntimeError, FileNotFoundError) as e:
        print(f"setup error: {e}")
        return 2
    txt = json.dumps(res, indent=1, sort_keys=True, default=str)
    if val("--out"):
        with open(val("--out"), "w", encoding="utf-8") as f:
            f.write(txt + "\n")
    print(txt)
    return 0 if res["verdict"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
