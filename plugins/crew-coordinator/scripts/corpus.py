"""Shared context and decision corpus for Crew Coordinator. Token-economy first.

Design
  * Source of truth: `corpus.recorded` events in the hash-chained log (auditable,
    replayable). corpus.db is a DERIVED SQLite FTS5 index kept per host in
    ~/.cache/crew-coordinator/<home-hash>/ (never on the shared mount); deleting it
    is safe because it is rebuilt on the next call.
  * Markdown files dropped in Exchange/corpus/ are chunked by heading and indexed
    automatically (re-indexed when their mtime changes).
  * Retrieval is tiered: 1-line cards first (~25 tokens each), full bodies only
    on request, always capped by a token budget.
  * Superseded entries drop out of results by default, so the decision log
    stays current and small.
"""
import glob
import hashlib
import json
import os
import re
import sqlite3
import sys
import time

PREFIX = {"decision": "D", "context": "C", "capsule": "K", "note": "N", "doc": "F"}
KINDS = list(PREFIX)
TITLE_MAX = 120
TIERS = ("foundation", "role-state", "ephemeral")   # v2 (0.15.0): who owns an entry and how long it lives
IDRE = re.compile(r"\b[A-Z]-[0-9a-f]{5}\b")
EXPIRY_DAYS = 14   # default `corpus-expiry-days`


_CTRL = re.compile("[\x00-\x08\x0b-\x1f\x7f-\x9f\u200b-\u200f\u2028\u2029\u202a-\u202e\u2066-\u2069\ufeff\u27e6\u27e7]")
_CTRL_ML = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f\u200b-\u200f\u2028\u2029\u202a-\u202e\u2066-\u2069\ufeff\u27e6\u27e7]")


def clean_text(s, cap=400, multiline=False):
    """Untrusted-text hygiene (0.15.0): strip control characters (and bidi/zero-width marks), keep \\n and \\t only when
    the field is multiline (single-line fields get a space instead), and cap the length (ellipsis marks a cut)."""
    s = "" if s is None else str(s)
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    if multiline:
        s = _CTRL_ML.sub("", s)
    else:
        s = _CTRL.sub("", s.replace("\n", " ").replace("\t", " "))
    if cap and len(s) > cap:
        s = s[:max(0, cap - 1)] + "…"
    return s


def today(offset_days=0):
    """ISO date (UTC, same clock as event ts) offset_days from now."""
    return time.strftime("%Y-%m-%d", time.gmtime(time.time() + offset_days * 86400))


def est_tokens(s: str) -> int:
    return max(1, len(s or "") // 4)


def _connect(path):
    db = sqlite3.connect(path, timeout=10)
    db.execute("PRAGMA journal_mode=DELETE")  # WAL is unsafe on VM/network mounts
    return db


def fts5_available() -> bool:
    try:
        c = sqlite3.connect(":memory:")
        c.execute("CREATE VIRTUAL TABLE t USING fts5(a)")
        return True
    except sqlite3.OperationalError:
        return False


FTS5 = fts5_available()


def cache_path(home):
    base = os.environ.get("HARNESS_CACHE") or os.path.join(
        os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache"), "crew-coordinator")
    d = os.path.join(base, hashlib.sha256(os.path.realpath(home).encode()).hexdigest()[:12])
    os.makedirs(d, mode=0o700, exist_ok=True)
    return os.path.join(d, "corpus.db")


class Corpus:
    def __init__(self, harness):
        self.h = harness
        self.dir = os.path.join(harness.home, "corpus")
        os.makedirs(self.dir, mode=0o700, exist_ok=True)
        # The index is a per-host cache, never on the shared mount: SQLite locking fails on
        # VM/network mounts ("disk I/O error"), and each host can rebuild it from the log.
        self.path = cache_path(harness.home)
        try:
            self.db = _connect(self.path)
            self._schema()
        except sqlite3.OperationalError:
            self.path = ":memory:"
            self.db = _connect(self.path)
            self._schema()

    # ------------------------------------------------------------- schema
    def _schema(self):
        d = self.db
        d.execute("""CREATE TABLE IF NOT EXISTS entries(
            id TEXT PRIMARY KEY, kind TEXT, title TEXT, body TEXT, tags TEXT, project TEXT,
            agent TEXT, agent_name TEXT, refs TEXT, supersedes TEXT, superseded_by TEXT,
            offload INTEGER DEFAULT 0, seq INTEGER, ts TEXT, sha TEXT, tokens INTEGER, source TEXT)""")
        # v2 columns (0.15.0): added in place so an index built by 0.14.x keeps working; old rows read as defaults
        have = {r[1] for r in d.execute("PRAGMA table_info(entries)")}
        for col, ddl in (("role", "TEXT DEFAULT ''"), ("tier", "TEXT DEFAULT 'ephemeral'"), ("expires", "TEXT DEFAULT ''")):
            if col not in have:
                d.execute(f"ALTER TABLE entries ADD COLUMN {col} {ddl}")
        d.execute("CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT)")
        d.execute("CREATE TABLE IF NOT EXISTS files(path TEXT PRIMARY KEY, mtime REAL, ids TEXT)")
        if FTS5:
            d.execute("CREATE VIRTUAL TABLE IF NOT EXISTS fts USING fts5(id UNINDEXED, title, body, tags, "
                      "tokenize='porter unicode61')")
        d.commit()

    def _meta(self, k, v=None):
        if v is None:
            r = self.db.execute("SELECT v FROM meta WHERE k=?", (k,)).fetchone()
            return r[0] if r else None
        self.db.execute("INSERT OR REPLACE INTO meta VALUES(?,?)", (k, str(v)))

    def _put(self, row):
        cols = ",".join(row)
        self.db.execute(f"INSERT OR REPLACE INTO entries({cols}) VALUES({','.join('?' * len(row))})", list(row.values()))
        if FTS5:
            self.db.execute("DELETE FROM fts WHERE id=?", (row["id"],))
            self.db.execute("INSERT INTO fts(id,title,body,tags) VALUES(?,?,?,?)",
                            (row["id"], row["title"], row.get("body") or "", row.get("tags") or ""))

    def _drop(self, ids):
        for i in ids:
            self.db.execute("DELETE FROM entries WHERE id=?", (i,))
            if FTS5:
                self.db.execute("DELETE FROM fts WHERE id=?", (i,))

    # ------------------------------------------------------------- sync index
    def refresh(self, events=None, st=None):
        """Bring the derived index up to date with the log and corpus/ files."""
        last = int(self._meta("last_seq") or 0)
        events = events if events is not None else self.h.store.read_all()
        head = events[-1]["seq"] if events and events[-1].get("seq") else 0
        if head < last:  # log was replaced: rebuild from scratch
            self.db.execute("DELETE FROM entries WHERE source='log'")
            if FTS5:
                self.db.execute("DELETE FROM fts WHERE id NOT IN (SELECT id FROM entries)")
            last = 0
        names = {e["data"]["id"]: e["data"]["sobriquet"] for e in events if e.get("type") == "agent.registered"}
        proj = {}  # agent -> project as of this point in the log (backfills untagged entries)
        for e in events:
            t, d0 = e.get("type"), e.get("data") or {}
            if t in ("agent.registered", "agent.updated") and d0.get("project") and d0.get("id"):
                proj[d0["id"]] = d0["project"]
            if (e.get("seq") or 0) <= last:
                continue
            if t == "corpus.pinned":  # hr 0.6.3: add/remove the 'pin' tag without rewriting the log
                for pid in d0.get("ids") or []:
                    row = self.db.execute("SELECT tags FROM entries WHERE id=?", (pid,)).fetchone()
                    if row is not None:
                        tg = [x for x in (row[0] or "").split() if x != "pin"] + (["pin"] if d0.get("on", True) else [])
                        self.db.execute("UPDATE entries SET tags=? WHERE id=?", (" ".join(tg), pid))
                continue
            if t == "corpus.archived":  # D-90088: prune without rewriting the log
                for old in d0.get("ids") or []:
                    self.db.execute("UPDATE entries SET superseded_by='archived' WHERE id=?", (old,))
                continue
            if t == "corpus.unarchived":  # v2: back into search; expiry rule restored from the event
                exp = d0.get("expires") or {}
                for pid in d0.get("ids") or []:
                    nxt = [r[0] for r in self.db.execute("SELECT id, supersedes FROM entries WHERE supersedes<>''")
                           if pid in re.split(r"[,\s]+", r[1])]
                    self.db.execute("UPDATE entries SET superseded_by=?, expires=? WHERE id=? AND superseded_by='archived'",
                                    (nxt[-1] if nxt else "", exp.get(pid) or "", pid))
                continue
            if t != "corpus.recorded":
                continue
            d = e["data"]
            self._put({"id": d["id"], "kind": d["kind"], "title": d["title"], "body": d.get("body") or "",
                       "tags": " ".join(d.get("tags") or []), "project": d.get("project") or proj.get(e["actor"], ""),
                       "agent": e["actor"], "agent_name": names.get(e["actor"], e["actor"][:8]),
                       "refs": json.dumps(d.get("refs") or []), "supersedes": d.get("supersedes") or "",
                       "superseded_by": "", "offload": 1 if d.get("offload") else 0, "seq": e["seq"],
                       "ts": e["ts"], "sha": d.get("sha"), "tokens": est_tokens(d.get("body") or ""),
                       "source": "log", "role": d.get("role") or "", "tier": d.get("tier") or "ephemeral",
                       "expires": d.get("expires") or ""})   # old events lack all three: ephemeral, no expiry, no role
            if d.get("supersedes"):
                for old in re.split(r"[,\s]+", d["supersedes"]):
                    if old:
                        self.db.execute("UPDATE entries SET superseded_by=? WHERE id=?", (d["id"], old))
        self._meta("last_seq", head)
        self._index_files()
        self.db.commit()

    def _index_files(self):
        seen = set()
        for dp, _, fns in os.walk(self.dir):
            for fn in fns:
                if not fn.lower().endswith((".md", ".txt")) or sys.modules[type(self.h).__module__].is_ignored(os.path.relpath(os.path.join(dp, fn), self.dir)):
                    continue
                p = os.path.join(dp, fn)
                rel = os.path.relpath(p, self.h.home)
                seen.add(rel)
                mt = os.path.getmtime(p)
                row = self.db.execute("SELECT mtime, ids FROM files WHERE path=?", (rel,)).fetchone()
                if row and abs(row[0] - mt) < 1e-6:
                    continue
                if row:
                    self._drop(json.loads(row[1]))
                ids = []
                with open(p, encoding="utf-8", errors="replace") as f:
                    text = f.read()
                for heading, body in chunk_markdown(text, fn):
                    cid = "F-" + hashlib.sha256(f"{rel}#{heading}".encode()).hexdigest()[:5]
                    self._put({"id": cid, "kind": "doc", "title": f"{rel} § {heading}"[:TITLE_MAX], "body": body,
                               "tags": "", "project": "", "agent": "file", "agent_name": "file", "refs": json.dumps([rel]),
                               "supersedes": "", "superseded_by": "", "offload": 0, "seq": 0,
                               "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(mt)),
                               "sha": hashlib.sha256(body.encode()).hexdigest(), "tokens": est_tokens(body),
                               "source": "file"})
                    ids.append(cid)
                self.db.execute("INSERT OR REPLACE INTO files VALUES(?,?,?)", (rel, mt, json.dumps(ids)))
        for (rel, ids) in self.db.execute("SELECT path, ids FROM files").fetchall():
            if rel not in seen:
                self._drop(json.loads(ids))
                self.db.execute("DELETE FROM files WHERE path=?", (rel,))

    # ------------------------------------------------------------- write
    def _model_of(self, actor):
        """Model provenance (t-88d62a1ac0): the acting agent's self-reported model, 'operator' for the human."""
        if actor in ("operator", "human"):
            return "operator"
        try:
            return (self.h.state().agents.get(actor) or {}).get("model") or "unknown"
        except Exception:
            return "unknown"

    # D-15566 P2: an archive/pin reason quotes each entry's rule-bearing line. 0.14.6 (A2): no "none ..." bypass;
    # only the harness's own mechanical-prune auto-fill (mechanical=True) skips the quote check.
    QUOTE_RE = re.compile(r'["\u201c`]([^"\u201d`]{6,})["\u201d`]')

    @staticmethod
    def _norm(x):
        return " ".join((x or "").lower().replace("\u2019", "'").split())

    def check_reason(self, ids, reason, op, mechanical=False):
        reason = " ".join((reason or "").split())
        if mechanical and reason:
            return reason
        if not reason:
            raise ValueError(f'{op}: reason required (D-15566 P2): quote each entry\'s rule-bearing line in "…"')
        quotes = [self._norm(q) for q in self.QUOTE_RE.findall(reason)]
        rows = self.db.execute(f"SELECT id, title, body FROM entries WHERE id IN ({','.join('?'*len(ids))})", ids).fetchall()
        miss = [i for i, t, b in rows if not any(q and q in self._norm(f"{t}\n{b}") for q in quotes)]
        if miss:
            raise ValueError(f'{op}: reason must quote a line from each entry in "…"; '
                             f'no matching quote for {miss} (D-15566 P2)')
        return reason

    def _review_models(self, actor, review):
        """D-15566 P4: a /health review (D-70499) records drafter_model (the Haiku worker) and lead_model."""
        if not review:
            return {}
        d = review.get("drafter_model") or "unknown"
        l = review.get("lead_model") or self._model_of(actor)
        return {"drafter_model": d, "lead_model": l}

    def archive(self, actor, ids, reason="", review=None, mechanical=False):
        ids = [i for i in ids if i]
        if not ids:
            raise ValueError("archive: ids required")
        known = {r[0] for r in self.db.execute(f"SELECT id FROM entries WHERE id IN ({','.join('?'*len(ids))})", ids)}
        miss = [i for i in ids if i not in known]
        if miss:
            raise ValueError(f"archive: unknown ids {miss}")
        reason = self.check_reason(ids, reason, "archive", mechanical)
        self._keep_content(ids, reason)
        self.h.store.append("corpus.archived", actor, dict({"ids": ids, "reason": reason, "model": self._model_of(actor)},
                                                           **self._review_models(actor, review)))
        return {"archived": ids}

    def _keep_content(self, ids, reason):
        """v2: archive never deletes. Copy each live entry to <home>/_archive/corpus/<ISO-week>/<id>.md and add one
        manifest line (id, title, tier, reason, date) to that week's manifest.jsonl (readable by the secretary report)."""
        now = time.gmtime(time.time())
        wk = os.path.join(self.h.home, "_archive", "corpus", time.strftime("%G-W%V", now))
        q = (f"SELECT id,kind,title,body,tags,project,role,tier,agent_name,ts,superseded_by FROM entries "
             f"WHERE id IN ({','.join('?' * len(ids))})")
        rows = self.db.execute(q, ids).fetchall()
        for r in rows:   # the id becomes a file name: IDRE-shaped ids only
            if not IDRE.fullmatch(str(r[0])):
                raise ValueError(f"archive: id {clean_text(r[0], 40)!r} is not a corpus id (<letter>-<5 hex>); nothing written")
        os.makedirs(wk, mode=0o700, exist_ok=True)
        for r in rows:
            if r[10] == "archived":
                continue
            with _private_open(os.path.join(wk, r[0] + ".md"), "w") as f:
                f.write(f"---\nid: {r[0]}\nkind: {r[1]}\ntitle: {_fm(r[2])}\ntags: {_fm(r[4])}\nproject: {_fm(r[5])}\n"
                        f"role: {_fm(r[6] or '')}\ntier: {_fm(r[7] or 'ephemeral')}\nby: {_fm(r[8])}\nts: {_fm(r[9])}\n---\n{r[3] or ''}\n")
            with _private_open(os.path.join(wk, "manifest.jsonl"), "a") as f:
                f.write(json.dumps({"id": r[0], "title": clean_text(r[2], TITLE_MAX * 2), "tier": r[7] or "ephemeral",
                                    "reason": reason, "date": time.strftime("%Y-%m-%d", now)}, ensure_ascii=False) + "\n")

    def unarchive(self, actor, ids):
        """v2: bring archived entries back into search. Unknown or live ids are reported, not errors.
        Expiry rule restored: ephemeral note/context +N days, everything else none."""
        ids = [i for i in ids if i]
        if not ids:
            raise ValueError("unarchive: id required")
        self.refresh()
        st = {r[0]: r for r in self.db.execute(
            f"SELECT id,kind,tier,superseded_by FROM entries WHERE id IN ({','.join('?' * len(ids))})", ids)}
        back = [i for i in ids if i in st and st[i][3] == "archived"]
        noop = {i: ("unknown id" if i not in st else "already live") for i in ids if i not in back}
        out = {"unarchived": back, "noop": noop}
        if back:
            days = self.h.expiry_days(None)
            exp = {i: today(days) for i in back if st[i][1] in ("note", "context") and (st[i][2] or "ephemeral") == "ephemeral"}
            self.h.store.append("corpus.unarchived", actor, {"ids": back, "expires": exp, "model": self._model_of(actor)})
            self.refresh()
            out["expires"] = exp
        msg = []
        if back:
            msg.append(f"unarchived {', '.join(back)}")
        msg += [f"{i}: no-op, {why}" for i, why in noop.items()]
        out["text"] = "; ".join(msg)
        return out

    # ------------------------------------------------------------- v2: pins by citation, due
    def foundation_cited(self):
        """v2: ids cited in the BODY of a foundation doc (front matter `doc: foundations`, or a FOUNDATIONS*.md under
        projects/<p>/ or corpus/), minus ids in that doc's `replaces:` header. Treated as pinned."""
        cited, files = set(), []
        try:
            pdirs = list(self.h.project_dirs_map().values())
        except Exception:
            pdirs = glob.glob(os.path.join(self.h.home, "projects", "*"))
        for d in pdirs + [os.path.join(self.h.home, "corpus")]:
            files += glob.glob(os.path.join(d, "*.md"))
        for p in files:
            try:
                with open(p, encoding="utf-8", errors="replace") as f:
                    txt = f.read()
            except OSError:
                continue
            m = re.match(r"^---\n(.*?)\n---\n?", txt, re.S)
            fm, body = (m.group(1), txt[m.end():]) if m else ("", txt)
            if not (re.search(r"^doc:\s*foundations?\s*$", fm, re.M | re.I)
                    or os.path.basename(p).upper().startswith("FOUNDATIONS")):
                continue
            rep = set()
            for line in re.findall(r"^replaces:\s*(.*)$", fm, re.M):
                rep |= set(IDRE.findall(line))
            cited |= set(IDRE.findall(body)) - rep
        return cited

    def due(self, on=None):
        """v2: ids whose `expires` is on or before `on` (default today). Read-only: nothing is removed; pinned
        (tag `pin`), citation-pinned, archived and superseded entries are never due."""
        self.refresh()
        on = on or today()
        keep = self.foundation_cited()
        out = []
        for i, tg in self.db.execute("SELECT id, tags FROM entries WHERE expires<>'' AND expires<=? AND superseded_by=''", (on,)):
            if "pin" not in (tg or "").split() and i not in keep:
                out.append(i)
        return sorted(out)

    def pin(self, actor, ids, on=True, reason="", review=None):
        ids = [i for i in ids if i]
        if not ids:
            raise ValueError("pin: ids required")
        known = {r[0] for r in self.db.execute(f"SELECT id FROM entries WHERE id IN ({','.join('?'*len(ids))})", ids)}
        miss = [i for i in ids if i not in known]
        if miss:
            raise ValueError(f"pin: unknown ids {miss}")
        reason = self.check_reason(ids, reason, "pin" if on else "unpin")
        self.h.store.append("corpus.pinned", actor, dict({"ids": ids, "on": bool(on), "reason": reason,
                                                          "model": self._model_of(actor)}, **self._review_models(actor, review)))
        return {"pinned" if on else "unpinned": ids}

    def record(self, agent_id, kind, title, body="", tags=None, project=None, refs=None,
               supersedes=None, offload=False, model=None, role=None, tier=None):
        if kind not in PREFIX or kind == "doc":
            raise ValueError(f"kind must be one of {[k for k in KINDS if k != 'doc']}")
        title = " ".join((title or "").split())
        if not title:
            raise ValueError("title (one-line summary) is required; it is what other agents see first")
        title = title[:TITLE_MAX]
        body = (body or "").strip()
        sha = hashlib.sha256(f"{kind}|{title}|{body}".encode()).hexdigest()
        self.refresh()
        dup = self.db.execute("SELECT id FROM entries WHERE sha=? AND superseded_by=''", (sha,)).fetchone()
        if dup:
            return {"id": dup[0], "duplicate": True}
        while True:
            cid = PREFIX[kind] + "-" + os.urandom(3).hex()[:5]
            if not self.db.execute("SELECT 1 FROM entries WHERE id=?", (cid,)).fetchone():
                break
        if isinstance(refs, str):   # 0.14.6 (#10): refs is always a list at write
            refs = [refs] if refs else []
        tier = tier or "ephemeral"
        if tier not in TIERS:
            raise ValueError(f"tier must be one of {list(TIERS)}")
        expires = None   # note and context expire by default; decision, capsule, role-state and foundation do not
        if tier == "ephemeral" and kind in ("note", "context"):
            expires = today(self.h.expiry_days(project))
        data = {"id": cid, "kind": kind, "title": title, "body": body, "tags": [t.strip().lower() for t in (tags or []) if t.strip()],
                "project": project, "refs": [str(r) for r in (refs or [])], "supersedes": supersedes, "offload": bool(offload), "sha": sha,
                "model": model or "unknown",
                "role": role or "unassigned", "tier": tier, "expires": expires}
        self.h.store.append("corpus.recorded", agent_id, data)
        self.refresh()
        out = {"id": cid, "tokens": est_tokens(body)}
        if supersedes:
            out["supersedes"] = supersedes
        return out

    # ------------------------------------------------------------- read
    def _filters(self, kind=None, tags=None, project=None, since_seq=None, include_superseded=False, offload=None,
                 exclude_by=None):
        w, a = [], []
        if exclude_by:   # N-39193: an agent's /update must not count its own entries as new
            w.append(f"e.agent_name NOT IN ({','.join('?' * len(exclude_by))})")
            a += list(exclude_by)
        if not include_superseded:
            w.append("e.superseded_by=''")
        if kind:
            ks = [k.strip() for k in (kind if isinstance(kind, list) else str(kind).split(","))]
            w.append(f"e.kind IN ({','.join('?' * len(ks))})")
            a += ks
        if project:
            w.append("e.project=?")
            a.append(project)
        for t in (tags or []):
            w.append("(' '||e.tags||' ') LIKE ?")
            a.append(f"% {t.lower()} %")
        if since_seq is not None:
            w.append("e.seq>?")
            a.append(since_seq)
        if offload is not None:
            w.append("e.offload=?")
            a.append(1 if offload else 0)
        return w, a

    def search(self, query=None, limit=5, **flt):
        try:   # 0.15.3 (P7): a caller-supplied limit is clamped (negative LIMIT means "no limit" in sqlite)
            limit = max(1, min(int(limit), 100))
        except (TypeError, ValueError):
            limit = 5
        self.refresh()
        w, a = self._filters(**flt)
        where = (" AND " + " AND ".join(w)) if w else ""
        terms = [t for t in re.findall(r"[\w\-]+", (query or "").lower()) if len(t) > 1]
        if terms and FTS5:
            match = " OR ".join('"' + t.replace('"', "") + '"' for t in terms)
            sql = (f"SELECT e.id,e.kind,e.title,e.tags,e.agent_name,e.ts,e.tokens,e.offload,e.superseded_by,e.expires "
                   f"FROM fts JOIN entries e ON e.id=fts.id WHERE fts MATCH ?{where} "
                   f"ORDER BY bm25(fts, 0, 8.0, 1.0, 4.0) LIMIT ?")
            rows = self.db.execute(sql, [match] + a + [limit]).fetchall()
        elif terms:  # portable fallback: weighted term counts
            rows = self.db.execute(f"SELECT e.id,e.kind,e.title,e.tags,e.agent_name,e.ts,e.tokens,e.offload,e.superseded_by,e.expires,"
                                   f"lower(e.title||' '||e.tags), lower(e.body) FROM entries e WHERE 1=1{where}", a).fetchall()
            scored = []
            for r in rows:
                s = sum(r[10].count(t) * 4 + r[11].count(t) for t in terms)
                if s:
                    scored.append((s, r[:10]))
            rows = [r for _, r in sorted(scored, key=lambda x: -x[0])[:limit]]
        else:
            rows = self.db.execute(f"SELECT e.id,e.kind,e.title,e.tags,e.agent_name,e.ts,e.tokens,e.offload,e.superseded_by,e.expires "
                                   f"FROM entries e WHERE 1=1{where} ORDER BY e.seq DESC, e.ts DESC LIMIT ?", a + [limit]).fetchall()
        return [dict(zip(("id", "kind", "title", "tags", "by", "ts", "tokens", "offload", "superseded_by", "expires"), r)) for r in rows]

    def count(self, **flt):
        self.refresh()
        w, a = self._filters(**flt)
        where = (" WHERE " + " AND ".join(w)) if w else ""
        return self.db.execute(f"SELECT COUNT(*) FROM entries e{where}", a).fetchone()[0]

    def get(self, ids, budget=1500):
        self.refresh()
        out, used = [], 0
        for i in list(ids)[:50]:   # 0.15.3 (P7): at most 50 ids per call
            r = self.db.execute("SELECT id,kind,title,body,tags,agent_name,ts,refs,supersedes,superseded_by,expires "
                                "FROM entries WHERE id=?", (i,)).fetchone()
            if not r:
                out.append(f"{i}: not found")
                continue
            head = (f"{r[0]} {r[1]} · {clean_text(r[2], 300)}" + (f" [{clean_text(r[4], 200)}]" if r[4] else "")
                    + f" · {clean_text(r[5], 60)} {clean_text(r[6], 40)[:10]}")   # 0.15.1 (P6): titles/tags/names are file- or peer-written
            if r[8]:
                head += f" · supersedes {clean_text(r[8], 200)}"
            if r[9] == "archived":
                head += " · ARCHIVED (still readable; admin op=unarchive to search it again)"
            elif r[9]:
                head += f" · SUPERSEDED by {r[9]}"
            if r[10] and r[10] <= today() and not r[9] and "pin" not in (r[4] or "").split():
                head += f" · DUE {r[10]}"
            body = clean_text(r[3] or "", 0, True)
            room = max(0, budget - used - est_tokens(head))
            if est_tokens(body) > room:
                cut = room * 4
                body = body[:cut].rstrip() + f" …[+{est_tokens(r[3]) - room}t; raise budget or narrow]"
            used += est_tokens(head) + est_tokens(body)
            out.append(head + ("\n" + body if body else ""))
            if used >= budget:
                break
        return "\n---\n".join(out), used


def _fm(v) -> str:
    """One front-matter value: single line; quoted (JSON string) when it holds a newline, quote or backslash."""
    raw = "" if v is None else str(v)
    t = clean_text(raw, 1000)
    if any(c in raw for c in '\n\r"\\') or t != raw:
        return json.dumps(t, ensure_ascii=False)
    return t


def _private_open(path, mode="w"):
    """Create-or-open with file mode 0600 for a new file (an existing file keeps its mode)."""
    flags = {"w": os.O_WRONLY | os.O_CREAT | os.O_TRUNC, "a": os.O_WRONLY | os.O_CREAT | os.O_APPEND,
             "x": os.O_WRONLY | os.O_CREAT | os.O_EXCL}[mode]
    return os.fdopen(os.open(path, flags | getattr(os, "O_NOFOLLOW", 0), 0o600), mode if mode != "x" else "w", encoding="utf-8")


def card_line(r) -> str:
    tags = f" [{r['tags']}]" if r.get("tags") else ""
    off = " ⇣" if r.get("offload") else ""
    if r.get("expires") and r["expires"] <= today() and not r.get("superseded_by"):
        off += " due"
    return (f"{r['id']} {r['kind'][:3]} · {clean_text(r['title'], 300)}{clean_text(tags, 200)}{off} · "
            f"{clean_text(r['by'], 60)} {str(r['ts'])[5:10]} · ~{r['tokens']}t")


def chunk_markdown(text, fallback, max_chars=2400):
    """Split on #/## headings; oversize sections split on blank lines."""
    parts, head, buf = [], fallback, []
    for line in text.splitlines():
        m = re.match(r"^(#{1,3})\s+(.*)", line)
        if m:
            if "".join(buf).strip():
                parts.append((head, "\n".join(buf).strip()))
            head, buf = m.group(2).strip(), []
        else:
            buf.append(line)
    if "".join(buf).strip():
        parts.append((head, "\n".join(buf).strip()))
    out = []
    for h, b in parts:
        if len(b) <= max_chars:
            out.append((h, b))
            continue
        chunk, n = [], 1
        for para in re.split(r"\n\s*\n", b):
            if sum(len(c) for c in chunk) + len(para) > max_chars and chunk:
                out.append((f"{h} ({n})", "\n\n".join(chunk)))
                chunk, n = [], n + 1
            chunk.append(para)
        if chunk:
            out.append((f"{h} ({n})" if n > 1 else h, "\n\n".join(chunk)))
    return out
