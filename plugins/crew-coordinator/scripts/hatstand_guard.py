"""0.18.0 (R-097, D-c92cb): the corpus and the ledger never reach the Hatstand repo.

Standing rule (operator 2026-10-26): no corpus entry, ledger event, vault file, handoff, digest or archive is ever
published to github.com/Braindono/hatstand. hatstand-sync.sh runs this guard on the staged files before any push:
    git -c core.quotepath=false diff --cached --name-only -z --diff-filter=ACMR | python3 hatstand_guard.py <clone root>
Names are NUL-separated (newline-separated input is accepted too). Exit 0 = clean; exit 1 = a STOP line per hit on
stderr; nothing is pushed. The guard fails CLOSED: a staged name it cannot open, a file it cannot decode, or a changed
fixture manifest is a STOP, never a skip (critic N-b5617, B1 and N1).

Checks, on every staged file except the one exemption below:
1. Path (case-insensitive): a folder named corpus, vault, handoffs, digests, _archive or projects anywhere in the path;
   a top-level ledger/ folder inside a plugin; any *.jsonl; runtime files (events.jsonl, registry.json, config.json,
   corpus.db, *.lock).
2. Content: text is read as UTF-8, UTF-16 (BOM or NUL pattern) or gunzipped; anything else is refused unless its
   extension is a known asset type AND the file starts with that type's magic bytes; decoded text that still holds
   NUL bytes (UTF-32) is refused. Keys match in double or single quotes, escaped or not. In every file, a line with the ledger event shape ("seq", "prev" and "hash" keys)
   or the three keys within one 600-character window (pretty-printed events) is refused. The only files allowed to
   carry that shape are SHAPE_PINNED below, each by path AND sha256: a changed pinned file stops the push until its
   pin is updated in a reviewed release (curator m-cb0764d65780).
3. Content, when HARNESS_HOME is set: a verbatim live corpus title of 40 or more characters.
4. 0.21.0 (A-5a989 item 9, D-6385f), three more rules, all fail-closed:
   a. Structural, in every JSON, YAML, fixture and CHANGELOG file (parsed keys and values, never code or prose): a "mapping" or
      "omitted_legacy_tags" key, or any role-state:<name> value, is refused.
   b. Private terms: a whole-word, case-insensitive match, in ANY text file (prose and code included), against the local list
      <home>/_harness/data/hatstand-private-terms.txt (one term per line, # comments; kept by the curator, never packaged).
      A hyphenated or multi-word term also matches its spaced, underscored and joined spellings. Limit, by design: a job-search target that
      is a common word (a search engine, a given name) cannot be guarded by a whole-word match and is not on the list.
      The refusal names the file and the term's line number in the list, never the term.
   c. Fail closed: HARNESS_HOME unset, the corpus ledger unreadable, or the terms file missing, unreadable or empty is a STOP
      with nothing pushed. There is no environment override.
Exemption (narrow, listed in the CHANGELOG): the synthetic steward fixture tests/fixtures/steward-r045 of
crew-coordinator. Its manifest.json must have exactly the sha256 pinned below (a manifest staged with new entries
cannot certify itself, critic B2), and only files whose sha256 that manifest lists are exempt. The manifest itself is
content-checked like any file. Changing the fixture means changing the pin here, in a reviewed release."""
import gzip
import hashlib
import json
import os
import re
import sys

FIXTURE = "plugins/crew-coordinator/tests/fixtures/steward-r045/"
FIXTURE_MANIFEST_SHA256 = "0351bcc609bf1ea7cb10d23ea2da43afd290ca22d5082993a135bb2e76946ac2"
_CC = "plugins/crew-coordinator/"
# Files that legitimately describe the event shape: the synthetic hash vectors, the event docs, the vector generator and
# one state-cache test. Path plus sha256; anything else with the shape stops the push.
SHAPE_PINNED = {
    _CC + "data/hash-vectors.json": "26b000602ec96ab36a4c005e00d269936ddbe3e15aeee213c7e75341cd64c3fb",
    _CC + "docs/EVENTS.md": "e8bbea4d000f1dbaf71aba6e6f75ca16ca6da3812afe82bae2cb1336d328c94a",
    _CC + "scripts/hash_vectors.py": "b4349bca19d6e83a934345cbb9f62de9bfab32bb3149adc5ac470a4e59f3b416",
    _CC + "tests/test_cc161_state_cache.py": "889d98a22dd8c21bdb082e571ea708a973d252ca9691db027204cc9fa50eef45",
}
DENY_DIRS = {"corpus", "vault", "handoffs", "digests", "_archive", "projects"}
RUNTIME = {"events.jsonl", "registry.json", "config.json", "corpus.db"}
# A key in double or single quotes, each quote optionally escaped: "seq":, \"seq\":, 'seq': (Python repr). Envoy m-1953412e1e3f (a, b).
LEDGER_KEYS = [re.compile(r"""\\?["']%s\\?["']\s*:""" % k) for k in ("seq", "prev", "hash")]
# An asset extension is trusted only when the file starts with that type's magic bytes (envoy m-1953412e1e3f, d).
ASSET_MAGIC = {".png": (b"\x89PNG\r\n\x1a\n",), ".jpg": (b"\xff\xd8\xff",), ".jpeg": (b"\xff\xd8\xff",),
               ".gif": (b"GIF87a", b"GIF89a"), ".ico": (b"\x00\x00\x01\x00",), ".webp": (b"RIFF",),
               ".woff": (b"wOFF",), ".woff2": (b"wOF2",), ".ttf": (b"\x00\x01\x00\x00", b"true"), ".otf": (b"OTTO",),
               ".pdf": (b"%PDF-",)}
ASSET_EXT = set(ASSET_MAGIC)
TITLE_MIN = 40
TERMS_FILE = "hatstand-private-terms.txt"
STRUCT_KEYS = ("mapping", "omitted_legacy_tags")
ROLE_STATE = re.compile(r"role-state:[A-Za-z0-9_]")
STRUCT_KEY_TEXT = re.compile(r"""\\?["']?(?:%s)\\?["']?\s*:""" % "|".join(STRUCT_KEYS))
DATA_EXT = {".json", ".yml", ".yaml"}
WINDOW = 600
GZ_MAX = 50 * 1024 * 1024


def _sha(p):
    with open(p, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def _manifest(root):
    """-> (files dict, problem or None). The manifest counts only when its sha is the pinned one."""
    p = os.path.join(root, FIXTURE, "manifest.json")
    if not os.path.isfile(p):
        return {}, None
    if _sha(p) != FIXTURE_MANIFEST_SHA256:
        return {}, "fixture manifest.json differs from the pinned sha (hatstand_guard.FIXTURE_MANIFEST_SHA256)"
    try:
        with open(p, encoding="utf-8") as f:
            files = json.load(f).get("files") or {}
        return (files if isinstance(files, dict) else {}), None
    except (OSError, ValueError):
        return {}, "fixture manifest.json unreadable"


def exempt(root, name, man):
    pre = FIXTURE + "home/"
    if name.startswith(pre):
        want = man.get(name[len(pre):])
        return bool(want) and want == _sha(os.path.join(root, name))
    return False


def path_hit(name):
    parts = name.split("/")
    low = [p.lower() for p in parts]
    inner = low[2:] if low[0] == "plugins" and len(low) > 2 else low
    base = low[-1]
    if DENY_DIRS.intersection(low[:-1]):
        return "folder " + "/".join(p for p, l in zip(parts[:-1], low[:-1]) if l in DENY_DIRS)
    if inner and inner[0] == "ledger" and len(inner) > 1:
        return "ledger/ folder"
    if base in RUNTIME or base.endswith(".lock"):
        return "runtime file " + parts[-1]
    if base.endswith(".jsonl"):
        return "*.jsonl file"
    return None


def decode(name, data):
    """-> (text, "") or (None, reason). gzip and UTF-16 are decoded; other binary needs an asset extension whose magic
    bytes match; decoded text that still holds NUL bytes (UTF-32, binary) is refused (envoy m-1953412e1e3f, c)."""
    ext = os.path.splitext(name.lower())[1]
    if ext in ASSET_MAGIC:
        if not any(data.startswith(m) for m in ASSET_MAGIC[ext]) or (ext == ".webp" and data[8:12] != b"WEBP"):
            return None, "file named %s does not start with that type's magic bytes" % ext
        return "", ""
    if data[:2] == b"\x1f\x8b":
        try:
            with gzip.GzipFile(fileobj=__import__("io").BytesIO(data)) as g:
                data = g.read(GZ_MAX + 1)
        except (OSError, EOFError):
            return None, "gzip file that cannot be read"
        if len(data) > GZ_MAX:
            return None, "gzip file too large to check"
        ext = ""
    if data[:2] in (b"\xff\xfe", b"\xfe\xff") or (len(data) >= 4 and data[1:4:2] == b"\x00\x00" and data[0:1] != b"\x00") \
            or (len(data) >= 4 and data[0:4:2] == b"\x00\x00" and data[1:2] != b"\x00"):
        enc = "utf-16" if data[:2] in (b"\xff\xfe", b"\xfe\xff") else ("utf-16-le" if data[1:2] == b"\x00" else "utf-16-be")
        try:
            text = data.decode(enc)
        except UnicodeDecodeError:
            return None, "UTF-16 file that cannot be decoded"
    else:
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            return None, "binary file of an unchecked type"
    if "\x00" in text:
        return None, "NUL bytes remain after decoding (UTF-32 or binary)"
    return text, ""


def ledger_hit(text):
    for n, line in enumerate(text.splitlines(), 1):
        if all(rx.search(line) for rx in LEDGER_KEYS):
            return f"line {n} has the ledger event shape (seq, prev, hash)"
    for m in LEDGER_KEYS[0].finditer(text):
        w = text[max(0, m.start() - WINDOW):m.end() + WINDOW]
        if LEDGER_KEYS[1].search(w) and LEDGER_KEYS[2].search(w):
            return "a multi-line object has the ledger event shape (seq, prev, hash)"
    return None


def live_titles(home):
    """Titles of 40+ characters from the live ledger's corpus entries (read-only)."""
    out = set()
    log = os.path.join(home, "_harness", "events.jsonl")
    try:
        with open(log, encoding="utf-8") as f:
            for line in f:
                if '"corpus.recorded"' not in line:
                    continue
                try:
                    t = (json.loads(line).get("data") or {}).get("title")
                except ValueError:
                    continue
                if isinstance(t, str) and len(t.strip()) >= TITLE_MIN:
                    out.add(t.strip())
    except OSError:
        pass
    return out


def is_data(name):
    """JSON, YAML, fixture files and the CHANGELOG: the files whose parsed keys and values the structural rule reads."""
    low = name.lower()
    base = low.rsplit("/", 1)[-1]
    return os.path.splitext(low)[1] in DATA_EXT or "/fixtures/" in "/" + low or base.startswith("changelog")


def structural_hit(name, text):
    """-> reason or None. JSON is parsed (keys at any depth, string values); other data files are read as text."""
    if os.path.splitext(name.lower())[1] == ".json":
        try:
            found = []

            def walk(o):
                if isinstance(o, dict):
                    for k, v in o.items():
                        if k in STRUCT_KEYS:
                            found.append("a '%s' key" % k)
                        if isinstance(k, str) and ROLE_STATE.search(k):
                            found.append("a role-state:* key")
                        walk(v)
                elif isinstance(o, list):
                    for v in o:
                        walk(v)
                elif isinstance(o, str) and ROLE_STATE.search(o):
                    found.append("a role-state:* value")
            walk(json.loads(text))
            if found:
                return "carries " + found[0] + " (never pushed: structural rule)"
            return None
        except ValueError:
            pass                                    # not valid JSON: read it as text below
    m = STRUCT_KEY_TEXT.search(text)
    if m:
        return "carries a '%s' key (never pushed: structural rule)" % m.group(0).strip("\\\"': ")
    if ROLE_STATE.search(text):
        return "carries a role-state:* value (never pushed: structural rule)"
    return None


def read_terms(home):
    """-> (compiled regex, count, problem). The terms file is the curator's local list; never packaged."""
    p = os.path.join(home, "_harness", "data", TERMS_FILE)
    try:
        with open(p, encoding="utf-8") as f:
            lines = f.read().splitlines()
    except (OSError, UnicodeDecodeError):
        return None, 0, "the private-terms list (%s) cannot be read" % TERMS_FILE
    terms = [(n, t.strip()) for n, t in enumerate(lines, 1) if t.strip() and not t.lstrip().startswith("#")]
    if not terms:
        return None, 0, "the private-terms list (%s) is empty" % TERMS_FILE
    # A multi-word or hyphenated term also matches its spaced, underscored and joined spellings (critic, thread t-682b61f20f):
    # a term such as "two-words" also catches "Two Words", "two_words" and "twowords".
    rx = "|".join("(?P<t%d>%s)" % (n, r"[\s\-_]*".join(re.escape(w) for w in re.split(r"[\s\-_]+", t) if w)) for n, t in terms)
    return re.compile(r"(?<![A-Za-z0-9])(?:%s)(?![A-Za-z0-9])" % rx, re.I), len(terms), None


def read_corpus(home):
    """-> (titles of 40+ chars, live tag set, problem). The tag list is only a read check: if the ledger cannot be read, nothing is pushed."""
    out, tags = set(), set()
    log = os.path.join(home, "_harness", "events.jsonl")
    try:
        with open(log, encoding="utf-8") as f:
            for line in f:
                if '"corpus.recorded"' not in line:
                    continue
                try:
                    d = json.loads(line).get("data") or {}
                except ValueError:
                    continue
                t = d.get("title")
                if isinstance(t, str) and len(t.strip()) >= TITLE_MIN:
                    out.add(t.strip())
                for x in d.get("tags") or []:
                    if isinstance(x, str):
                        tags.add(x)
    except (OSError, UnicodeDecodeError):
        return set(), set(), "the corpus ledger cannot be read"
    return out, tags, None


def check(root, names, home=None):
    """-> list of (path, reason)."""
    man, problem = _manifest(root)
    hits = []
    titles, terms_rx, fatal = set(), None, None
    if not home:
        fatal = "HARNESS_HOME is not set, so the corpus and the private terms cannot be read (fail closed, no override)"
    else:
        titles, _tags, fatal = read_corpus(home)
        if not fatal:
            terms_rx, _n, fatal = read_terms(home)
    if fatal:
        return [("(guard)", fatal + "; nothing pushed")]
    if problem and any(n.startswith(FIXTURE) for n in names):
        hits.append((FIXTURE + "manifest.json", problem))
    for name in names:
        p = os.path.join(root, name)
        if os.path.islink(p) or not os.path.isfile(p):
            hits.append((name, "staged name the guard cannot open as a regular file"))
            continue
        if exempt(root, name, man):
            continue
        why = path_hit(name)
        if why:
            hits.append((name, why))
            continue
        try:
            with open(p, "rb") as f:
                data = f.read()
        except OSError:
            hits.append((name, "staged file the guard cannot read"))
            continue
        text, info = decode(name, data)
        if text is None:
            hits.append((name, info))
            continue
        why = ledger_hit(text)
        if why and name in SHAPE_PINNED:
            if hashlib.sha256(data).hexdigest() == SHAPE_PINNED[name]:
                why = None
            else:
                why += "; it is a pinned file whose sha256 changed (update SHAPE_PINNED in a reviewed release)"
        if why:
            hits.append((name, why))
            continue
        if is_data(name):
            why = structural_hit(name, text)
            if why:
                hits.append((name, why))
                continue
        m = terms_rx.search(text)
        if m:
            n = int(m.lastgroup[1:])
            hits.append((name, "contains a private term (line %d of the local %s)" % (n, TERMS_FILE)))
            continue
        for t in titles:
            if t in text:
                hits.append((name, f"contains a live corpus title ({len(t)} chars)"))
                break
    return hits


def read_names(raw):
    sep = "\0" if "\0" in raw else "\n"
    return [n for n in (x.strip("\n") for x in raw.split(sep)) if n.strip()]


def main(argv):
    root = argv[1] if len(argv) > 1 else "."
    names = read_names(sys.stdin.buffer.read().decode("utf-8", "surrogateescape"))
    hits = check(root, names, os.environ.get("HARNESS_HOME") or None)
    for name, why in hits:
        print(f"hatstand: STOP, corpus/ledger guard: {name}: {why}", file=sys.stderr)
    return 1 if hits else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
