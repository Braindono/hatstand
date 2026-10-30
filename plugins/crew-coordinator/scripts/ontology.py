#!/usr/bin/env python3
"""Tag ontology (crew-coordinator 0.20.0, scope A-2b70b). Stdlib only; read-side: nothing here writes a tag or changes an entry.

data/ontology.json holds the concepts (id, label, facet, broader[], aliases[]), the nine facets, the non-concept buckets, and the
legacy mapping (tag -> {"c": [[concept, role], ...], "b": bucket}); since 0.21.0 the mapping and the operator's private concepts live in <home>/_harness/data/ontology-mapping.json, which the package never carries. Links between an entry and a concept are ledger events
(concept.linked / concept.unlinked), kept beside the entry so its content hash never changes.

  load()                      -> Ontology (empty and harmless when the file is missing or broken)
  Ontology.narrower(cid)      -> the concept and every narrower concept, any depth (cycle-safe)
  Ontology.nearest(text, n)   -> up to n (concept id, label) close to a word, by edit distance and containment
  Ontology.tag_state(tag, known) -> ("literal"|"known"|"reference"|"duplicate"|"new", detail)
  validate_keys(keys)         -> canonical cue object keys, or ValueError (breadth rules for the lesson cue, item 5)
  key_regexes(keys)           -> (tool regex source, input regex source or None) that scripts/lesson_cue.py compiles
"""
import hashlib
import json
import os
import re

PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LINK_ROLES = ("about", "applies", "mentions")
ROLE_RANK = {r: i for i, r in enumerate(LINK_ROLES)}      # about first
CONCEPT_ID = re.compile(r"^[a-z]{2,6}\.[a-z0-9][a-z0-9._-]{0,60}$")
REF_TAG = re.compile(r"^(?:[a-z]-[0-9a-f]{5}|[a-z]-0[0-9]{2}[a-z]?|v?\d+\.\d+(?:\.\d+)?|cc\d{3}|[a-z]\d{1,2}|stage-\d+)$")
# tags the harness writes or reads literally; the ontology never judges them
LITERAL_EXACT = {"lesson", "ruled-out", "pin", "operator-decision", "save"}
LITERAL_PREFIX = ("role-state:", "model:", "role:", "handoff:")


def _norm(s):
    return re.sub(r"[\s_]+", "-", str(s or "").strip().lower())


def spelling_key(s):
    """Case, '_' vs '-', and a plural 's' do not make a different tag."""
    k = _norm(s)
    for suf in ("ies",):
        if k.endswith(suf) and len(k) > 4:
            return k[:-3] + "y"
    return k[:-1] if k.endswith("s") and len(k) > 3 and not k.endswith("ss") else k


def distance(a, b, cap=4):
    """Edit distance (Levenshtein with adjacent transpositions counted as one edit), stopping early once it is certain to pass `cap`."""
    if a == b:
        return 0
    if abs(len(a) - len(b)) > cap:
        return cap + 1
    prev2, prev = None, list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            v = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb))
            if prev2 is not None and i > 1 and j > 1 and ca == b[j - 2] and a[i - 2] == cb:
                v = min(v, prev2[j - 2] + 1)
            cur.append(v)
        if min(cur) > cap:
            return cap + 1
        prev2, prev = prev, cur
    return prev[-1]


class Ontology:
    def __init__(self, data=None, local=None):
        """data: the packaged file (generic concepts, facets, buckets; since 0.21.0 no legacy mapping). local: the operator's own file
        <home>/_harness/data/ontology-mapping.json, never packaged: extra concepts and the legacy tag mapping, merged in."""
        d = data if isinstance(data, dict) else {}
        loc = local if isinstance(local, dict) else {}
        self.version = d.get("v")
        self.concepts = {}
        for c in list(d.get("concepts") or []) + list(loc.get("concepts") or []):      # packaged ids win over a clashing local id
            if isinstance(c, dict) and isinstance(c.get("id"), str):
                self.concepts.setdefault(c["id"], c)
        self.local_ids = {c["id"] for c in loc.get("concepts") or [] if isinstance(c, dict) and isinstance(c.get("id"), str)} - \
            {c["id"] for c in d.get("concepts") or [] if isinstance(c, dict) and isinstance(c.get("id"), str)}
        self.facets = d.get("facets") or {}
        self.buckets = d.get("buckets") or {}
        self.mapping = {}
        for src in (d.get("mapping"), loc.get("mapping")):
            self.mapping.update({str(k): v for k, v in (src or {}).items() if isinstance(v, dict)})
        self.children = {}
        for cid, c in self.concepts.items():
            for p in c.get("broader") or []:
                self.children.setdefault(p, set()).add(cid)
        self.names = {}          # normalised word -> concept id (id tail, label, aliases)
        for cid, c in self.concepts.items():
            for w in [cid.split(".", 1)[-1], c.get("label")] + list(c.get("aliases") or []):
                if w:
                    self.names.setdefault(_norm(w), cid)
        self.spellings = {}      # spelling_key -> the tag/concept string that owns it (first wins)
        for w in list(self.names) + list(self.mapping):
            self.spellings.setdefault(spelling_key(w), w)

    def __bool__(self):
        return bool(self.concepts)

    def has(self, cid):
        return cid in self.concepts

    def narrower(self, cid):
        out, todo = set(), [cid]
        while todo:
            x = todo.pop()
            if x in out or x not in self.concepts:
                continue
            out.add(x)
            todo += list(self.children.get(x, ()))
        return out

    def legacy_tags_for(self, cids):
        """Legacy tags the mapping assigns to any concept in `cids` -> {tag: best role rank}."""
        out = {}
        for tag, e in self.mapping.items():
            for cid, role in e.get("c") or []:
                if cid in cids:
                    out[tag] = min(out.get(tag, 9), ROLE_RANK.get(role, 2))
        return out

    @staticmethod
    def _close(w, c):
        """A hint is worth giving only when the two words are really alike (critic N-094cd): both at least 5 characters, at most 2 edits and
        at most 25% of the longer word changed (a swap of neighbours is one edit); or they share a hyphen-separated word of 5+ letters. Short words ("gates", "test") get none."""
        if min(len(w), len(c)) >= 5:
            d = distance(w, c, 2)
            if d <= 2 and d / max(len(w), len(c)) <= 0.25:
                return d
            if set(t for t in w.split("-") if len(t) >= 5) & set(c.split("-")):
                return 3
        return None

    def nearest(self, text, n=3):
        w = _norm(text)
        if not w:
            return []
        best = {}
        for name, cid in self.names.items():
            d = self._close(w, name)
            if d is not None and (cid not in best or d < best[cid]):
                best[cid] = d
        for tag, e in self.mapping.items():          # a legacy tag points at its first concept
            d = self._close(w, _norm(tag))
            for cid, _ in (e.get("c") or [])[:1]:
                if d is not None and (cid not in best or d < best[cid]):
                    best[cid] = d
        rows = sorted(best.items(), key=lambda x: (x[1], x[0]))[:n]
        return [(cid, self.concepts[cid].get("label")) for cid, _ in rows if cid in self.concepts]

    def tag_state(self, tag, known=()):
        """-> (state, detail). literal: the harness's own tags. reference: an id or version, belongs in refs. known: a concept id, name,
        alias or legacy tag (silent). duplicate: spelled like a known tag or concept but not identical (refused; detail = the spelling to use).
        new: unknown (warned with the nearest concepts; detail = [(concept id, label)])."""
        t = str(tag or "").strip()
        low = t.lower()
        if low in LITERAL_EXACT or low.startswith(LITERAL_PREFIX):
            return "literal", None
        if t in self.concepts or low in self.concepts or _norm(t) in self.names or t in self.mapping or low in self.mapping:
            return "known", None
        if REF_TAG.match(low):
            return "reference", None
        key = spelling_key(t)
        for pool in (self.spellings, {spelling_key(k): k for k in known}):
            other = pool.get(key)
            if other and other != t and other != low:
                return "duplicate", other
        return "new", self.nearest(t, 3)


_CACHE = {}


def local_path(home):
    return os.path.join(home, "_harness", "data", "ontology-mapping.json") if home else None


def _mtime(p):
    try:
        return os.path.getmtime(p) if p else None
    except OSError:
        return None


def load(path=None, home=None):
    """The packaged ontology, plus the operator's local file under `home` when it exists (0.21.0, A-5a989 item 8). Without the local
    file legacy tags read as 'new' (with hints). An unreadable local file is ignored; an unreadable packaged file is an empty ontology."""
    p = path or os.path.join(PLUGIN_ROOT, "data", "ontology.json")
    lp = local_path(home)
    key = (p, lp)
    try:
        m = (os.path.getmtime(p), _mtime(lp))
        if _CACHE.get(key, (None,))[0] == m:
            return _CACHE[key][1]
        with open(p, encoding="utf-8") as f:
            pub = json.load(f)
        local = None
        if m[1] is not None:
            try:
                with open(lp, encoding="utf-8") as f:
                    local = json.load(f)
            except (OSError, ValueError):
                local = None
        o = Ontology(pub, local)
    except (OSError, ValueError):
        o = Ontology()
        m = None
    _CACHE[key] = (m, o)
    return o


# ---------------------------------------------------------------- cue object keys (item 5)
MAX_GLOBS, MAX_TOOLS, GLOB_MAX = 8, 8, 200
TOOL_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_\-:.]{0,100}$")
# 0.20.0 M2 (critic N-094cd B2): tools a tool-only key may never name, compared case-insensitively; anything starting mcp__ too
BROAD_TOOLS = ("bash", "read", "write", "edit", "multiedit", "notebookedit", "agent", "task", "sendmessage")
MIN_RUN = 3                   # a glob needs a literal run of this many letters or digits between wildcards and slashes
MODES = ("note", "deny")


def _segment_ok(seg):
    """One path segment counts when its literal part is long enough. The extension never counts: for a segment with a dot after its first
    character the part before the last dot is the stem (`main.py` -> main, `*.py` -> nothing, `test_*.py` -> test_); a segment without one
    (a directory, or a hidden name such as .github) counts as a whole. Wildcards split the literal part into runs; one run must have 3+
    letters or digits."""
    dot = seg.rfind(".")
    stem = seg[:dot] if dot > 0 else seg.lstrip(".")
    return any(len(re.findall(r"[A-Za-z0-9]", run)) >= MIN_RUN for run in re.split(r"[*?\[\]]+", stem))


def validate_keys(keys):
    """The breadth rules of the operator's approval: -> {"paths": [...], "tools": [...], "mode": "note"|"deny"} (sorted, deduped).
    Refused (ValueError, with the reason): not a mapping; no path and no tool; a path glob with no literal letter or digit (a bare *, **,
    ** /* ...); a glob with control characters, the lesson fence marks or over 200 characters; a tool that is not an exact tool name;
    a tool-only key naming Bash or an mcp__ tool (it would fire on every call); more than 8 globs or 8 tools; an unknown mode."""
    if not isinstance(keys, dict):
        raise ValueError("keys must be an object {paths: [...], tools: [...], mode}")
    extra = set(keys) - {"paths", "tools", "mode"}
    if extra:
        raise ValueError("unknown key field(s): " + ", ".join(sorted(extra)))
    paths, tools = keys.get("paths") or [], keys.get("tools") or []
    if not isinstance(paths, list) or not isinstance(tools, list):
        raise ValueError("paths and tools must be lists")
    if not paths and not tools:
        raise ValueError("a key needs at least one path glob or tool")
    if len(paths) > MAX_GLOBS or len(tools) > MAX_TOOLS:
        raise ValueError("at most %d path globs and %d tools per lesson" % (MAX_GLOBS, MAX_TOOLS))
    gp = []
    for g in paths:
        if not isinstance(g, str) or not g.strip() or len(g) > GLOB_MAX:
            raise ValueError("a path glob must be a non-empty string of at most %d characters" % GLOB_MAX)
        g = g.strip()
        if re.search(r"[\x00-\x1f\x7f\u27e6\u27e7\"'\\]", g):
            raise ValueError("path glob %r holds a control character, quote, backslash or fence mark" % g[:40])
        if not any(_segment_ok(seg) for seg in g.split("/")):
            raise ValueError("path glob %r is too broad: a directory name or a file stem needs at least %d literal letters or digits "
                             "(no bare *, **, **/*x*, *.py or **/*.md: the extension does not count)" % (g[:40], MIN_RUN))
        gp.append(g)
    gt = []
    for t in tools:
        if not isinstance(t, str) or not TOOL_NAME.match(t):
            raise ValueError("tool %r is not an exact tool name (no wildcards)" % str(t)[:40])
        gt.append(t)
    if gt and not gp and any(t.lower() in BROAD_TOOLS or t.lower().startswith("mcp__") for t in gt):
        raise ValueError("a tool-only key may not name Bash, Read, Write, Edit, MultiEdit, NotebookEdit, Agent, Task, SendMessage or an mcp__ tool "
                         "(it would fire on the first such call of every session); add a path glob")
    mode = keys.get("mode", "note")
    if mode not in MODES:
        raise ValueError("mode must be note or deny")
    if mode == "deny" and not gp:
        raise ValueError("deny mode needs a path glob (a tool-only key may only be a note)")
    seen, tools = set(), []
    for t in gt:                                   # tool names are compared without case, so bash and BASH are one tool
        if t.lower() not in seen:
            seen.add(t.lower())
            tools.append(t)
    return {"mode": mode, "paths": sorted(set(gp)), "tools": sorted(tools)}


def glob_regex(g):
    """One path glob -> a regex source for the JSON text of a tool input. * stays inside one path part, ** crosses parts, ? is one
    character; a relative glob matches the end of any path (it must start at a path part), an absolute glob the whole path."""
    out, i = [], 0
    while i < len(g):
        c = g[i]
        if g.startswith("**/", i):
            out.append(r"(?:[^\s\"'\\]*/)?")
            i += 3
        elif g.startswith("**", i):
            out.append(r"[^\s\"'\\]*")
            i += 2
        elif c == "*":
            out.append(r"[^/\s\"'\\]*")
            i += 1
        elif c == "?":
            out.append(r"[^/\s\"'\\]")
            i += 1
        else:
            out.append(re.escape(c))
            i += 1
    before = r"(?<![\w.\-/])" if g.startswith("/") else r"(?:(?<=[/\"'\s=:(])|^)"
    return before + "".join(out) + r"(?![\w.\-])"


def key_regexes(keys):
    """-> (tool regex source, input regex source or None). A paths-only key fires for any tool whose input names a matching path."""
    k = validate_keys(keys)
    tool = ("(?i)^(?:" + "|".join(re.escape(t) for t in k["tools"]) + ")$") if k["tools"] else "."
    inp = "|".join("(?:%s)" % glob_regex(g) for g in k["paths"]) if k["paths"] else None
    return tool, inp


def keys_canon(keys):
    return json.dumps(validate_keys(keys), sort_keys=True, ensure_ascii=True, separators=(",", ":"))


def cue_hash(lid, when, rule, keys):
    """What the operator approved for the cue, as one hash: the lesson id, its When and Rule text and its canonical object keys. The harness
    writes it into lesson.curated; lesson_cue.py recomputes it from lesson_cues.json and uses an entry only if the ledger holds the same
    hash for that id (critic N-094cd B1: a planted cue file must never fire, let alone deny)."""
    body = json.dumps({"id": str(lid), "when": when if when is None else str(when), "rule": str(rule),
                       "keys": json.loads(keys_canon(keys)) if keys else None}, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(body.encode("utf-8")).hexdigest()
