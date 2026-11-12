"""Push on completion (cc 0.21.0, scope A-ae352 item 1; curator spec v2 section 4a; critic N-53375 B1-B3).

The harness decides when the operator needs to know; the agent that caused the event delivers it. The server cannot call tools, so a trigger
returns a `notify` object in the acting agent's own tool result, carrying one `Do: PushNotification "<text>" status=proactive (then report:
harness_admin op=notify_sent id=<n-id>)` line, exactly like the doorbell nudge. Triggers:
  (a) harness_send kind=result whose reply_to is a kind=task message
  (b) any mail to the operator (kind=question included)
  (c) approval.requested, whose text gives the minutes left before expiry
Events: notify.queued {id, kind, thread, ref, actor, text, due, at, state, batch, dropped, approval, expires}; notify.sent {id, by}.
state: issue (the Do-line was handed out now), hold (quiet hours; released with the first allowed push after them), fold (daily cap reached;
released with the next allowed push, never dropped). Policy (config.json key "notify", all type-checked and bounded):
  {"quiet": "22:00-07:00", "tz": "local", "cap_per_day": 6, "dedupe_minutes": 30, "approvals_ignore_quiet": true, "digest_after_minutes": 60}
Rules (tests per rule):
  * Decided under the ledger lock with the notify.queued append, so two agents cannot both take the last slot of the day (gap 1).
  * The cap and the dedupe count ISSUED Do-lines (notify.queued state=issue), once per notify id; notify.sent only tracks delivery (gap 2).
  * Dedupe key is (thread, trigger kind). Approvals are never deduped, held by the cap or folded; they count outside the daily cap (B3).
  * Quiet hours hold pushes; approvals bypass them unless approvals_ignore_quiet is false. A held approval that has expired by release time is
    dropped from the batch, never pushed (gap 4).
  * The push text is built from fixed fields only: who (role or name from the ledger), trigger kind, ids, for approvals the action and minutes
    left. A subject comes last, cleaned, quoted, at most 60 characters, never first (B2).
  * A Do-line exists only in the harness's own result field `notify`; peer text is fenced as data and cannot create one (B1; the agent-side
    rule is one line in the protocol skill).
  * Anything issued but unsent `digest_after_minutes` after its due time, or held/folded past that, is listed by undelivered() for the
    secretary digest (cloud chats have no PushNotification). Counted once per notify id.
Standard library only. Never raises into the caller: a failure leaves the result as it was."""
import calendar, re, time, uuid

DEFAULTS = {"quiet": "22:00-07:00", "tz": "local", "cap_per_day": 6, "dedupe_minutes": 30,
            "approvals_ignore_quiet": True, "digest_after_minutes": 60}
BOUNDS = {"cap_per_day": (1, 50), "dedupe_minutes": (0, 1440), "digest_after_minutes": (5, 1440)}
TEXT_MAX, SUBJECT_MAX = 120, 60
WINDOW_DAYS = 3
_QUIET_RE = re.compile(r"^(\d{1,2}):(\d{2})-(\d{1,2}):(\d{2})$")
_BAD = re.compile(r"[\x00-\x1f\x7f⟦⟧\"\\`]")


def policy(h):
    """The effective policy: defaults overlaid with config.json "notify", every value type-checked and bounded."""
    out = dict(DEFAULTS)
    try:
        import harness as H
        raw = H.load_config(h.home).get("notify")
    except Exception:
        raw = None
    if not isinstance(raw, dict):
        return out
    q = raw.get("quiet")
    if isinstance(q, str) and (q.strip().lower() in ("", "off", "none") or _QUIET_RE.match(q.strip())):
        out["quiet"] = q.strip()
    tz = raw.get("tz")
    if isinstance(tz, str) and tz.strip().lower() in ("local", "utc"):
        out["tz"] = tz.strip().lower()
    for k, (lo, hi) in BOUNDS.items():
        v = raw.get(k)
        if isinstance(v, int) and not isinstance(v, bool) and lo <= v <= hi:
            out[k] = v
    if isinstance(raw.get("approvals_ignore_quiet"), bool):
        out["approvals_ignore_quiet"] = raw["approvals_ignore_quiet"]
    return out


def _tm(t, tz):
    return time.gmtime(t) if tz == "utc" else time.localtime(t)


def _epoch(tm_fields, tz):
    return calendar.timegm(tm_fields) if tz == "utc" else time.mktime(tm_fields + (-1,))


def _at(t, tz, hour, minute, day_offset=0):
    lt = _tm(t, tz)
    return float(_epoch((lt.tm_year, lt.tm_mon, lt.tm_mday + day_offset, hour, minute, 0, 0, 0), tz))


def quiet_state(cfg, t):
    """-> (in_quiet, epoch when quiet ends). No quiet window configured -> (False, None)."""
    m = _QUIET_RE.match(cfg["quiet"]) if isinstance(cfg.get("quiet"), str) else None
    if not m:
        return False, None
    sh, sm, eh, em = (int(x) for x in m.groups())
    if not (0 <= sh < 24 and 0 <= eh < 24 and 0 <= sm < 60 and 0 <= em < 60) or (sh, sm) == (eh, em):
        return False, None
    lt = _tm(t, cfg["tz"])
    mod, s, e = lt.tm_hour * 60 + lt.tm_min, sh * 60 + sm, eh * 60 + em
    inq = (s <= mod < e) if s < e else (mod >= s or mod < e)
    if not inq:
        return False, None
    end = _at(t, cfg["tz"], eh, em)
    if end <= t:
        end = _at(t, cfg["tz"], eh, em, 1)
    return True, end


def _day(t, tz):
    return time.strftime("%Y-%m-%d", _tm(t, tz))


def next_day_start(t, tz):
    return _at(t, tz, 0, 0, 1)


def clean(s, n):
    """Peer or agent text made safe for a phone line: no control characters, quotes, backslashes, backticks or fence marks."""
    s = _BAD.sub(" ", str(s or ""))
    s = " ".join(s.split())
    return s[:n].rstrip()


def build_text(who, kind, ids, subject=None, approval=None, extra=0):
    """B2: fixed fields first. `subject` (peer-controlled) is last, quoted, at most 60 characters; the whole line at most 120."""
    who = clean(who, 40) or "an agent"
    if kind == "approval":
        a = approval or {}
        left = a.get("minutes_left")
        head = "%s: approval %s %s, %s" % (who, clean(a.get("id"), 12), clean(a.get("action"), 30),
                                             ("%d min left" % left) if left is not None else "no expiry")
    elif kind == "result":
        head = "%s: result %s on thread %s" % (who, clean(ids.get("ref"), 16), clean(ids.get("thread"), 16))
    else:
        head = "%s: %s %s for you" % (who, "question" if ids.get("question") else "mail", clean(ids.get("ref"), 16))
    tail = (" +%d more notifications" % extra) if extra else ""      # 0.24.0 (A-b2950 item 8.1)
    subj = clean(subject, SUBJECT_MAX)
    room = TEXT_MAX - len(head) - len(tail)
    if subj and room >= 8:
        q = ' "%s"' % subj[:max(0, room - 3)].rstrip()
        head += q if len(q) > 3 else ""
    return (head + tail)[:TEXT_MAX]


def _window(h, now):
    """notify events of the last WINDOW_DAYS. Event times are the real write times, so the cut is against the real clock (a caller may pass
    a different `now`, as the tests do)."""
    out = []
    ref = min(now, time.time())
    for e in reversed(h.store.read_all()):
        t = e.get("t")
        if t is not None and t < ref - WINDOW_DAYS * 86400:
            break
        if e.get("type") in ("notify.queued", "notify.sent", "notify.listed"):
            out.append(e)
    out.reverse()
    return out


# 0.24.0 (A-b2950 item 8.2): a queued notification expires only when BOTH hold: the secretary's digest has listed it (notify.listed, written
# by the secretary with harness_admin op=notify_listed; sync and restore lines never write it) and it is more than a day old. A Friday-evening
# row never pushed still reaches the Monday digest. Approval rows keep their own expiry rule. Nothing is deleted (append-only).
LISTED_EXPIRE_S = 86400


def _listed(evs):
    """-> (ids listed by the secretary's digest, ids whose drop line the digest already carried)."""
    listed, carried = set(), set()
    for e in evs:
        if e.get("type") == "notify.listed":
            d = e.get("data") or {}
            listed.update(x for x in d.get("ids") or [] if isinstance(x, str))
            carried.update(x for x in d.get("dropped") or [] if isinstance(x, str))
    return listed, carried


def _expired(d, listed, now):
    return d.get("kind") != "approval" and d.get("id") in listed and now - float(d.get("at") or now) > LISTED_EXPIRE_S


def _fold(evs):
    """-> (queued by id, sent by id, carrier by released id, dropped ids). A released id rode in the batch of its carrier."""
    q, sent, carrier, dropped = {}, {}, {}, set()
    for e in evs:
        d = e.get("data") or {}
        if e["type"] == "notify.queued" and d.get("id"):
            q[d["id"]] = d
            for i in d.get("batch") or []:
                carrier[i] = d["id"]
            dropped.update(d.get("dropped") or [])
        elif e["type"] == "notify.sent" and d.get("id"):
            sent[d["id"]] = d
    return q, sent, carrier, dropped


def _who(st, aid):
    if aid not in st.agents:
        return "a new chat"                    # e.g. a restore asked for approval before the chat has an agent
    a = st.agents.get(aid) or {}
    role = st.role_of(aid) if a else None
    return (role.upper() if role else None) or a.get("sobriquet") or str(aid)[:8]


def decide(h, trig, now=None):
    """Decide and record one trigger under the ledger lock. trig: {kind: result|operator|approval, actor: agent id, thread, ref, subject,
    question: bool, approval: {id, action, expires}}. -> the notify.queued data (with state) or None when deduped."""
    now = float(now if now is not None else time.time())
    cfg = policy(h)
    store = h.store
    st = h.state()
    kind = trig["kind"]
    with store._lock():
        rep = store._repair_tail()
        if rep:
            store._append_locked("log.repaired", "system", rep)
        evs = _window(h, now)
        q, sent, carrier, dropped_ids = _fold(evs)
        released = set(carrier) | dropped_ids | {i for i, d in q.items() if _expired(d, _listed(evs)[0], now)}   # 0.24.0 item 8.2: never batched
        if kind != "approval":
            cut = now - cfg["dedupe_minutes"] * 60
            key = (trig.get("thread"), kind)
            if cfg["dedupe_minutes"] and any((d.get("thread"), d.get("kind")) == key and d.get("at", 0) >= cut
                                             for d in q.values() if d.get("kind") != "approval"):
                return None
        in_quiet, qend = quiet_state(cfg, now)
        if in_quiet and not (kind == "approval" and cfg["approvals_ignore_quiet"]):
            state, due = "hold", qend
        elif kind != "approval" and sum(1 for d in q.values() if d.get("state") == "issue" and d.get("kind") != "approval"
                                        and _day(d.get("at", 0), cfg["tz"]) == _day(now, cfg["tz"])) >= cfg["cap_per_day"]:
            state, due = "fold", next_day_start(now, cfg["tz"])
        else:
            state, due = "issue", now
        batch, dropped = [], []
        if state == "issue":
            for i, d in q.items():
                if i in released or d.get("state") not in ("hold", "fold") or (d.get("due") or 0) > now:
                    continue
                if d.get("kind") == "approval" and d.get("expires") and d["expires"] <= now:
                    dropped.append(i)
                else:
                    batch.append(i)
        ap = trig.get("approval") or None
        if ap and ap.get("expires"):
            ap = dict(ap, minutes_left=max(0, int((ap["expires"] - now + 59) // 60)))
        text = build_text(_who(st, trig.get("actor")), kind, {"ref": trig.get("ref"), "thread": trig.get("thread"),
                                                             "question": trig.get("question")}, trig.get("subject"), ap, len(batch))
        nid = "n-" + uuid.uuid4().hex[:5]
        while nid in q:
            nid = "n-" + uuid.uuid4().hex[:5]
        data = {"id": nid, "kind": kind, "thread": trig.get("thread"), "ref": trig.get("ref"), "actor": trig.get("actor"), "text": text,
                "due": round(due, 3), "at": round(now, 3), "state": state, "batch": batch, "dropped": dropped}
        if ap:
            data["approval"] = ap.get("id")
            data["expires"] = ap.get("expires")
        actor = trig.get("actor") if trig.get("actor") in st.agents else "system"
        store._append_locked("notify.queued", actor, data)
    return data


def do_line(data):
    return 'Do: PushNotification "%s" status=proactive (then report: harness_admin op=notify_sent id=%s)' % (data["text"], data["id"])


def _attach(r, data):
    if data and data.get("state") == "issue":
        r = dict(r)
        r["notify"] = {"id": data["id"], "do": do_line(data)}
    return r


# ------------------------------------------------------------------ triggers

def attach_send(h, sender_ref, r):
    """After a harness_send: trigger (a) a result replying to a task, or (b) mail to the operator. Never raises."""
    try:
        if not isinstance(r, dict) or not r.get("id"):
            return r
        st = h.state()
        m = st.messages.get(r["id"])
        if not m or m.get("from") in ("human", "operator"):
            return r
        parent = st.messages.get(m.get("parent") or "")
        to_op = any(x in ("human", "operator") for x in list(m.get("to") or []) + list(m.get("to_resolved") or []))
        if m.get("kind") == "result" and parent and parent.get("kind") == "task":
            kind = "result"
        elif to_op:
            kind = "operator"
        else:
            return r
        data = decide(h, {"kind": kind, "actor": m["from"], "thread": m.get("thread"), "ref": m["id"], "subject": m.get("subject"),
                          "question": m.get("kind") == "question"})
        return _attach(r, data)
    except Exception:
        return r


def attach_approval(h, caller, shape, rec):
    """After request_approval: trigger (c). rec: {id, action, expires}. Never raises."""
    try:
        data = decide(h, {"kind": "approval", "actor": caller, "thread": None, "ref": rec["id"],
                          "approval": {"id": rec["id"], "action": rec["action"], "expires": rec.get("expires")}})
        return _attach(shape, data)
    except Exception:
        return shape


# ------------------------------------------------------------------ report and digest

def mark_sent(h, caller, nid):
    """harness_admin op=notify_sent. Only the agent that was handed the Do-line may report it; idempotent."""
    nid = str(nid or "").strip()
    now = time.time()
    q, sent, _c, _d = _fold(_window(h, now))
    d = q.get(nid)
    if not d:
        raise _err("unknown notify id %s" % nid)
    if d.get("state") != "issue":
        raise _err("%s was not handed out as a Do-line (state %s)" % (nid, d.get("state")))
    if d.get("actor") != caller:
        raise _err("%s was handed to another agent" % nid)

    def _fresh(store):
        for e in store.read_all()[-400:]:
            if e.get("type") == "notify.sent" and (e.get("data") or {}).get("id") == nid:
                raise _AlreadySent()
    try:
        h.store.append("notify.sent", caller, {"id": nid, "by": caller}, precheck=_fresh)
    except _AlreadySent:
        return {"id": nid, "already_reported": True}
    return {"id": nid, "reported": True}


class _AlreadySent(Exception):
    pass


def _err(msg):
    import harness as H
    return H.HarnessError(msg)


def undelivered(h, now=None):
    """Notifications the secretary digest should carry: issued and unsent `digest_after_minutes` after their due time (a chat without
    PushNotification never reports), and held or folded ones that were never released, `digest_after_minutes` after they came due.
    Expired approvals are left out. Each notify id once. FIXED FIELDS ONLY (curator A-5a989, critic D2): no text, no subject, nothing a
    peer wrote. -> [{id, kind, role, age_minutes}]; `role` is the role (else the name) of the agent that was handed the Do-line; the
    digest reads the details from the ledger by id (notify.queued)."""
    now = float(now if now is not None else time.time())
    cfg = policy(h)
    evs = _window(h, now)
    q, sent, carrier, dropped = _fold(evs)
    listed = _listed(evs)[0]
    wait = cfg["digest_after_minutes"] * 60
    st = h.state()
    out = []
    for i, d in sorted(q.items(), key=lambda kv: kv[1].get("at", 0)):
        if i in sent or i in dropped or _expired(d, listed, now):      # 0.24.0 item 8.2: listed and over a day old
            continue
        c = q.get(carrier.get(i)) if i in carrier else None
        if c is not None and c["id"] in sent:
            continue                                   # delivered inside a batch that was reported
        due = (c.get("due") if c is not None else d.get("due")) or 0
        if now - due < wait:
            continue
        if d.get("kind") == "approval" and d.get("expires") and d["expires"] <= now:
            continue
        out.append({"id": i, "kind": d.get("kind"), "role": _who(st, d.get("actor")), "age_minutes": max(0, int((now - (d.get("at") or now)) // 60))})
    return out


def dropped(h, now=None):
    """0.24.0 (A-b2950 item 8.3): queued rows that expired (listed and over a day old) without delivery and whose drop the secretary's digest
    has not carried yet. Fixed fields only. -> (line or None, ids). The line is shown until the secretary's next notify_listed records it."""
    now = float(now if now is not None else time.time())
    evs = _window(h, now)
    q, sent, carrier, drop_ids = _fold(evs)
    listed, carried = _listed(evs)
    rows = []
    for i, d in sorted(q.items(), key=lambda kv: kv[1].get("at", 0)):
        if i in sent or i in drop_ids or i in carried or (i in carrier and carrier[i] in sent) or not _expired(d, listed, now):
            continue
        rows.append((i, "%s %s" % (clean(d.get("kind"), 12) or "-", clean(d.get("thread"), 16) or "-")))
    if not rows:
        return None, []
    return "dropped (listed, over a day old): " + ", ".join(r[1] for r in rows), [r[0] for r in rows]


def mark_listed(h, caller, ids, now=None):
    """harness_admin op=notify_listed args={ids}: the secretary records that its digest carried these rows (notify.listed {ids, by,
    dropped}). Only the role secretary may; any other caller is refused. Each id is written once; `dropped` records the drop line the same
    digest carried, so it is shown once. Sync and restore lines never call this."""
    import harness as H
    st = h.state()
    if st.role_of(caller) != "secretary":
        raise H.HarnessError("notify_listed: only the role secretary records that its digest listed a notification")
    ids = [str(x).strip() for x in (ids if isinstance(ids, list) else str(ids or "").replace(",", " ").split()) if str(x).strip()][:200]
    now = float(now if now is not None else time.time())
    evs = _window(h, now)
    q = _fold(evs)[0]
    listed = _listed(evs)[0]
    unknown = [i for i in ids if i not in q]
    new = [i for i in dict.fromkeys(ids) if i in q and i not in listed]
    _line, drop = dropped(h, now)
    if not new and not drop:
        return {"listed": [], "already": [i for i in ids if i in listed], "unknown": unknown}

    def _fresh(store):
        if _listed([e for e in store.read_all()[-400:]])[0] & set(new):
            raise _AlreadySent()
    try:
        h.store.append("notify.listed", caller, {"ids": new, "by": caller, "dropped": drop}, precheck=_fresh)
    except _AlreadySent:
        return {"listed": [], "already": new, "unknown": unknown}
    return {"listed": new, "dropped": drop, "unknown": unknown}
