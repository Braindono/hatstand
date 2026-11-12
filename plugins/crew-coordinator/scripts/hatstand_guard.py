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
content-checked like any file. Changing the fixture means changing the pin here, in a reviewed release.
5. 0.24.0 (A-b2950 item 17, guard spec v3, D-945c6): the rules read bytes (check_blobs), so hatstand_check.py can check
   staged blobs, every commit of a pushed range, tag objects and ref names. Five more rules, each naming file and line,
   never the value:
   a. home/user: a user name of this machine or of the identity list, as a word or in a /Users, /home or C:\\Users path;
      the synthetic x, bob and claude are allowed.
   b. host names: the identity list's hosts, `hostname -s` and, on macOS, the scutil names; whole word, any case.
   c. email: any address except the synthetic domains (example.*, *.invalid, *.test, *.example), the GitHub noreply
      identity and the co-author address; the git@ remote form of GitHub is a remote. Identity-list addresses are always refused.
   d. credentials (moved here from the sync's grep, widened): see CRED_RULES. Synthetic fixtures are exempt by path AND
      sha256 (CRED_PINNED).
   e. workspace layout: the operator's workspace folder under the home, the app-support folder and the agent session
      folder are refused; docs use the <home> and <workspace> placeholders.
   The identity list <lists>/hatstand-private-identity.txt (`user|host|email <value>` lines; kept by the curator, never
   packaged) is required: missing, empty or not understood is a STOP."""
import gzip
import hashlib
import json
import os
import re
import sys

FIXTURE = "plugins/crew-coordinator/tests/fixtures/steward-r045/"
FIXTURE_MANIFEST_SHA256 = "b2644821766cd1e524da99ced5cbcd0db9d7281377b0062ecb515cc173c597c4"
_CC = "plugins/crew-coordinator/"
# Files that legitimately describe the event shape: the synthetic hash vectors, the event docs, the vector generator and
# one state-cache test. Path plus sha256; anything else with the shape stops the push.
SHAPE_PINNED = {
    _CC + "data/hash-vectors.json": "26b000602ec96ab36a4c005e00d269936ddbe3e15aeee213c7e75341cd64c3fb",
    _CC + "docs/EVENTS.md": "109973244fe558e59aa7a75750558187873f2cc3bb9665bab34a7e1a3d837d3d",
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


def read_terms(home, lists_dir=None):
    """-> (compiled regex, count, problem). The terms file is the curator's local list; never packaged."""
    p = os.path.join(lists_dir or os.path.join(home, "_harness", "data"), TERMS_FILE)
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


# ---------------------------------------------------------------- 0.24.0 item 17 (A-b2950; guard spec v3, D-945c6, D-7e1dd)
# The rules read bytes, not files: a pre-commit hook checks the staged blobs and a pre-push hook checks every blob, commit
# message, tag message and ref name of the pushed range (hatstand_check.py). Five more rules, each naming the file and line,
# never the matched value. Patterns that would match their own source are built in pieces, so this file passes its own rules.
IDENTITY_FILE = "hatstand-private-identity.txt"
ALLOWED_USERS = {"x", "bob", "claude"}
_NOT_A_USER = ALLOWED_USERS | {"root", "user", "runner", "nobody"}
HOME_RX = re.compile(r"(?:/Users/|/home/|[Cc]:\\{1,2}Users\\{1,2})([A-Za-z0-9_.-]+)")
EMAIL_RX = re.compile(r"(?<![A-Za-z0-9._%+-])([A-Za-z0-9._%+-]+)@([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,})(?![A-Za-z0-9-])")
# Synthetic domains (RFC 2606/6761), the GitHub noreply identity, the Claude co-author address, and the git@ remote form.
EMAIL_OK_DOMAINS = ("example.com", "example.org", "example.net", "users.noreply.github.com")
EMAIL_OK_TLDS = ("invalid", "test", "example", "localhost")
EMAIL_OK_ADDRESSES = ("noreply" + "@anthropic.com", "git" + "@github.com")   # in pieces: the item 15 tree check allows neither
# Credential patterns, adapted from public rule sets (gitleaks style), copied and reviewed, not installed.
CRED_RULES = [
    ("a GitHub token", r"(?<![A-Za-z0-9])gh[pousr]_[A-Za-z0-9]{16,}"),
    ("a GitHub fine-grained token", r"github_pat_[A-Za-z0-9_]{16,}"),
    ("an Anthropic key", r"sk-ant-[A-Za-z0-9_-]{16,}"),
    ("an API key of the sk- form", r"(?<![A-Za-z0-9])sk-(?!ant-)[A-Za-z0-9_-]{16,}"),
    ("an AWS key id", r"(?<![A-Z0-9])(?:AKIA|ASIA)[0-9A-Z]{12,}"),
    ("a Slack token", r"(?<![A-Za-z0-9])xox[baprs]-[A-Za-z0-9-]{10,}"),
    ("a Google API key", r"AIza[0-9A-Za-z_-]{20,}"),
    ("a private key block", r"BEGIN[A-Z ]{0,20}PRIVATE KEY"),
    ("a JWT", r"eyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"),
    ("a bearer token", r"(?i)(?<![A-Za-z0-9])bearer\s+[A-Za-z0-9._~+/-]{20,}=*"),
    ("a URL with credentials", r"(?<![A-Za-z0-9+.-])[A-Za-z][A-Za-z0-9+.-]{1,15}://[^\s/:@'\"<>()]{1,64}:[^\s/@'\"<>()]{1,128}@[A-Za-z0-9-]+\.[A-Za-z0-9.-]+"),
    ("a password assignment", r"(?i)(?<![A-Za-z0-9_])(?:password|passwd|pwd)\s*[:=]\s*['\"][^'\"\s]{6,}['\"]"),
    ("a relay email domain", "private" + "relay"),
]
CRED_RX = [(d, re.compile(p)) for d, p in CRED_RULES]
# Files that must carry credential-shaped text (synthetic test fixtures), by path AND sha256, like SHAPE_PINNED: a changed
# pinned file stops the push until its pin is updated in a reviewed release. Computed by running these rules over the tree.
CRED_PINNED = {
    _CC + "tests/test_c170_r051a.py": "5eab27ebe0c9cc3a5973d1e03327ab228deb3499cbdc428d9d3b70bd729c45b7",
    _CC + "tests/test_cc151_w3.py": "b31a6b85aa7c61d444dd469b6845acd93f829d310e5efdda12a0828cb38f91e0",
    _CC + "tests/test_cc162_indexer.py": "6a3f0bec9c12c3e668b42cd1d6780f3ebbc017548fb7596cd8afc3ef308243ba",
    _CC + "tests/test_e4_c3.py": "603e2637f11bc37d86a072d8394f8f07cc7efea57502539eaa8abbd34b61a24e",
}
# Rule 5e (D-945c6): the operator's workspace layout is refused; docs use the <home> and <workspace> placeholders instead.
WORKSPACE_RX = re.compile("|".join([
    r"~/" + "Claude(?![A-Za-z0-9])",
    r"\$\{?HOME\}?/" + "Claude(?![A-Za-z0-9])",
    re.escape("Library/Application Support/" + "Claude"),
    re.escape("local-agent-mode" + "-sessions"),
]))
RULE = {"a": "rule 5a home/user", "b": "rule 5b host name", "c": "rule 5c email", "d": "rule 5d credential",
        "e": "rule 5e workspace path", "t": "private term", "c4": "corpus title"}


class Hit(tuple):
    """(where, name, line, rule, reason). where = (staged), a commit, a tag object or a ref; line may be None."""
    __slots__ = ()

    def __new__(cls, where, name, line, rule, reason):
        return tuple.__new__(cls, (where, name, line, rule, reason))

    where = property(lambda s: s[0])
    name = property(lambda s: s[1])
    line = property(lambda s: s[2])
    rule = property(lambda s: s[3])
    reason = property(lambda s: s[4])

    def stop_line(self):
        loc = self.name + (":%d" % self.line if self.line else "")
        return "hatstand: STOP, %s: %s: %s: %s" % (self.rule, self.where, loc, self.reason)


def _run(cmd):
    import subprocess
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=2)
        return r.stdout.strip() if r.returncode == 0 else ""
    except (OSError, ValueError, Exception):
        return ""


_MACHINE = None


def machine_identity():
    """-> (users, hosts) of this machine: the login name, the home folder's name, `hostname -s`, and on macOS the three scutil
    names. Read once per process."""
    global _MACHINE
    if _MACHINE is None:
        import getpass
        import socket
        users, hosts = set(), set()
        try:
            users.add(getpass.getuser())
        except Exception:
            pass
        h = os.path.expanduser("~")
        if HOME_RX.match(h):
            users.add(os.path.basename(h.rstrip("/")))
        hosts.add(socket.gethostname().split(".")[0])
        hosts.add(_run(["hostname", "-s"]))
        if sys.platform == "darwin":
            for k in ("ComputerName", "LocalHostName", "HostName"):
                hosts.add(_run(["scutil", "--get", k]).split(".")[0])
        _MACHINE = ({u for u in users if len(u) >= 2 and u.lower() not in _NOT_A_USER},
                    {x for x in hosts if len(x) >= 3 and x.lower() != "localhost"})
    return _MACHINE


def read_identity(lists_dir):
    """-> (users, hosts, emails, problem). The identity list is the curator's local file, one entry per line:
    `user <name>`, `host <name>` or `email <address>`; # comments. Missing, empty or not understood = a STOP (fail closed)."""
    p = os.path.join(lists_dir, IDENTITY_FILE)
    try:
        with open(p, encoding="utf-8") as f:
            lines = f.read().splitlines()
    except (OSError, UnicodeDecodeError):
        return set(), set(), set(), "the identity list (%s) cannot be read" % IDENTITY_FILE
    out = {"user": set(), "host": set(), "email": set()}
    for n, line in enumerate(lines, 1):
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        kind, _, val = s.partition(" ")
        if kind not in out or not val.strip():
            return set(), set(), set(), "line %d of the identity list (%s) is not 'user|host|email <value>'" % (n, IDENTITY_FILE)
        out[kind].add(val.strip())
    if not any(out.values()):
        return set(), set(), set(), "the identity list (%s) is empty" % IDENTITY_FILE
    return out["user"], out["host"], {e.lower() for e in out["email"]}, None


def _words_rx(words):
    words = sorted({w for w in words if w}, key=len, reverse=True)
    if not words:
        return None
    alt = "|".join(r"[\s\-_]*".join(re.escape(p) for p in re.split(r"[\s\-_]+", w) if p) for w in words)
    return re.compile(r"(?<![A-Za-z0-9])(?:%s)(?![A-Za-z0-9])" % alt, re.I)


class Rules:
    """Everything the checks need, loaded once: corpus titles, private terms, the identity list and this machine's names.
    A missing or unreadable list sets .fatal; the caller STOPs with nothing committed or pushed (no override)."""

    def __init__(self, home, lists_dir=None):
        self.fatal, self.titles, self.terms_rx = None, set(), None
        self.users_rx = self.hosts_rx = None
        self.users, self.emails = set(), set()
        self.identity_sha = None
        if not home:
            self.fatal = "HARNESS_HOME is not set, so the corpus and the private terms cannot be read (fail closed, no override)"
            return
        lists_dir = lists_dir or os.path.join(home, "_harness", "data")
        self.titles, _tags, self.fatal = read_corpus(home)
        if not self.fatal:
            self.terms_rx, _n, self.fatal = read_terms(home, lists_dir)
        if not self.fatal:
            users, hosts, self.emails, self.fatal = read_identity(lists_dir)
            try:    # critic r1 (non-blocking): the list is agent-writable; its sha is printed so a change shows up
                with open(os.path.join(lists_dir, IDENTITY_FILE), "rb") as f_:
                    self.identity_sha = hashlib.sha256(f_.read()).hexdigest()[:12]
            except OSError:
                self.identity_sha = None
            mu, mh = machine_identity()
            self.users = {u.lower() for u in users | mu} - ALLOWED_USERS
            self.users_rx = _words_rx(self.users)
            self.hosts_rx = _words_rx(hosts | mh)


def email_ok(local, domain, rules):
    addr = ("%s@%s" % (local, domain)).lower()
    d = domain.lower()
    if addr in rules.emails:
        return False
    if addr in EMAIL_OK_ADDRESSES or d in EMAIL_OK_DOMAINS or d.endswith(tuple("." + x for x in EMAIL_OK_DOMAINS)):
        return True
    return d.rsplit(".", 1)[-1] in EMAIL_OK_TLDS


def _line(text, pos):
    return text.count("\n", 0, pos) + 1


def text_hits(text, rules, creds=True):
    """-> [(rule, line, reason)]: rules 5a to 5e, the private terms and the corpus titles; the first hit of each rule."""
    out = []
    m = rules.users_rx.search(text) if rules.users_rx else None
    for hm in HOME_RX.finditer(text):
        if hm.group(1).lower() in rules.users:
            m = hm if (m is None or hm.start() < m.start()) else m
            break
    if m:
        out.append((RULE["a"], _line(text, m.start()), "a user name of this machine or of the identity list"))
    m = rules.hosts_rx.search(text) if rules.hosts_rx else None
    if m:
        out.append((RULE["b"], _line(text, m.start()), "a host name of this machine or of the identity list"))
    for em in EMAIL_RX.finditer(text):
        if not email_ok(em.group(1), em.group(2), rules):
            out.append((RULE["c"], _line(text, em.start()), "an email address outside the allowed synthetic and noreply forms"))
            break
    if creds:
        for desc, rx in CRED_RX:
            cm = rx.search(text)
            if cm:
                out.append((RULE["d"], _line(text, cm.start()), "looks like " + desc))
                break
    m = WORKSPACE_RX.search(text)
    if m:
        out.append((RULE["e"], _line(text, m.start()), "a workspace path; use the <home> or <workspace> placeholder"))
    return out


def check_text(where, label, text, rules):
    """Commit headers and messages, tag objects and ref names: the identity, email, credential, workspace, term and title rules."""
    hits = [Hit(where, label, ln, r, why) for r, ln, why in text_hits(text, rules)]
    m = rules.terms_rx.search(text) if rules.terms_rx else None
    if m:
        hits.append(Hit(where, label, _line(text, m.start()), RULE["t"],
                        "contains a private term (line %d of the local %s)" % (int(m.lastgroup[1:]), TERMS_FILE)))
    for t in rules.titles:
        if t in text:
            hits.append(Hit(where, label, None, RULE["c4"], "contains a live corpus title (%d chars)" % len(t)))
            break
    return hits


def _manifest_bytes(data):
    """The fixture manifest, from its bytes: -> (files dict, problem or None)."""
    if data is None:
        return {}, None
    if hashlib.sha256(data).hexdigest() != FIXTURE_MANIFEST_SHA256:
        return {}, "fixture manifest.json differs from the pinned sha (hatstand_guard.FIXTURE_MANIFEST_SHA256)"
    try:
        files = json.loads(data.decode("utf-8")).get("files") or {}
        return (files if isinstance(files, dict) else {}), None
    except (ValueError, UnicodeDecodeError):
        return {}, "fixture manifest.json unreadable"


UNREADABLE = "staged file the guard cannot read"
NOT_REGULAR = "staged name the guard cannot open as a regular file"


def check_blobs(items, rules, get_blob=None, where="(staged)"):
    """items: [(name, bytes | None[, reason])]. None = not a regular file (a symlink or submodule) unless a reason is given.
    get_blob(name) returns another blob of the SAME tree or commit (the fixture manifest), or None. -> [Hit]."""
    if rules.fatal:
        return [Hit(where, "(guard)", None, "guard", rules.fatal + "; nothing pushed")]
    names = [it[0] for it in items]
    hits = []
    man, problem = _manifest_bytes(get_blob(FIXTURE + "manifest.json") if get_blob else None)
    if problem and any(n.startswith(FIXTURE) for n in names):
        hits.append(Hit(where, FIXTURE + "manifest.json", None, "fixture", problem))
    for it in items:
        name, data = it[0], it[1]
        if data is None:
            hits.append(Hit(where, name, None, "path", it[2] if len(it) > 2 and it[2] else NOT_REGULAR))
            continue
        sha = hashlib.sha256(data).hexdigest()
        pre = FIXTURE + "home/"
        if name.startswith(pre) and man.get(name[len(pre):]) and man.get(name[len(pre):]) == sha:
            continue
        why = path_hit(name)
        if why:
            hits.append(Hit(where, name, None, "path", why))
            continue
        text, info = decode(name, data)
        if text is None:
            hits.append(Hit(where, name, None, "decode", info))
            continue
        old = None
        why = ledger_hit(text)
        if why and name in SHAPE_PINNED:
            if sha == SHAPE_PINNED[name]:
                why = None
            else:
                why += "; it is a pinned file whose sha256 changed (update SHAPE_PINNED in a reviewed release)"
        if why:
            old = Hit(where, name, None, "ledger shape", why)
        if not old and is_data(name):
            why = structural_hit(name, text)
            if why:
                old = Hit(where, name, None, "structural", why)
        if not old:
            m = rules.terms_rx.search(text)
            if m:
                old = Hit(where, name, _line(text, m.start()), RULE["t"],
                          "contains a private term (line %d of the local %s)" % (int(m.lastgroup[1:]), TERMS_FILE))
        if not old:
            for t in rules.titles:
                if t in text:
                    old = Hit(where, name, None, RULE["c4"], "contains a live corpus title (%d chars)" % len(t))
                    break
        if old:
            hits.append(old)
        pinned = CRED_PINNED.get(name)
        creds = pinned != sha
        for r, ln, why in text_hits(text, rules, creds=creds):
            if r == RULE["d"] and pinned:
                why += "; it is a pinned file whose sha256 changed (update CRED_PINNED in a reviewed release)"
            hits.append(Hit(where, name, ln, r, why))
    return hits


# Files the package-build check leaves to their owner until a scrub lands: the curator's CHANGELOG (as item 15's tree test did).
PACKAGE_5E_LATER = ()


def workspace_hits(items, get_blob=None, where="(package)"):
    """Rule 5e alone, which needs no local list: -> [Hit]. Run when a package is built (publish --build), so a workspace path
    is refused before a release exists, not only at the mirror push. items: [(name, bytes)] with names as the repo has them."""
    man, _p = _manifest_bytes(get_blob(FIXTURE + "manifest.json") if get_blob else None)
    hits = []
    for name, data in items:
        if name.rsplit("/", 1)[-1] in PACKAGE_5E_LATER and name.count("/") <= 2:
            continue
        pre = FIXTURE + "home/"
        if name.startswith(pre) and man.get(name[len(pre):]) == hashlib.sha256(data).hexdigest():
            continue
        text, _i = decode(name, data)
        m = WORKSPACE_RX.search(text) if text else None
        if m:
            hits.append(Hit(where, name, _line(text, m.start()), RULE["e"], "a workspace path; use the <home> or <workspace> placeholder"))
    return hits


def check(root, names, home=None, lists_dir=None):
    """Working-tree wrapper kept for older callers: -> list of (path, reason)."""
    rules = Rules(home, lists_dir)
    if rules.fatal:
        return [("(guard)", rules.fatal + "; nothing pushed")]
    items = []
    for name in names:
        p = os.path.join(root, name)
        if os.path.islink(p) or not os.path.isfile(p):
            items.append((name, None))
            continue
        try:
            with open(p, "rb") as f:
                items.append((name, f.read()))
        except OSError:
            items.append((name, None, UNREADABLE))

    def get_blob(n):
        p = os.path.join(root, n)
        if not os.path.isfile(p):
            return None
        with open(p, "rb") as f:
            return f.read()
    out = []
    for h in check_blobs(items, rules, get_blob):
        out.append((h.name, h.reason if h.rule in ("path", "decode", "ledger shape", "structural", "fixture", RULE["t"], RULE["c4"])
                    else "%s, line %s: %s" % (h.rule, h.line, h.reason)))
    return out


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
