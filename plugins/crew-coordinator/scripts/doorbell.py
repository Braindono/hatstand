"""Doorbell nudge on send + /listen self-wake bookkeeping (cc 0.15.5, WP4, H-020).

Design: plans/2026-10-14_h020-doorbell-design-and-test-plan.md; spec 2026-10-15-doorbell-listen-cc0155.md v2.
- The push is made by the SENDING chat's Claude (the server cannot call SendMessage): a send returns a `nudge`
  object whose `line` is ids-only (no message text). Every nudge or skip is a ledger event (nudge.offered,
  legacy nudge.sent / nudge.skipped {reason}); 0.21.1: the sender reports the outcome (nudge.result).
- /listen is an opt-in self-wake. The OPERATOR enables roles in operator.json (never the agent-writable
  config.json). The harness decides from the ledger whether a task is open and whether to re-arm; the agent's own
  say-so is never an input. Arms expire (default 12 h, and when the agent hands off or is superseded).
- A wake may run harness_inbox and routine coordination only; wake_guard() refuses everything gated.
All reads scan the ledger tail (bounded by the window), so a call costs O(recent events)."""
import json, os, re, time

OFFERS = ("nudge.offered", "nudge.sent")     # 0.21.1 (A-58ff8 item 4): the server event was renamed; the old name still counts as an offer
OUTCOMES = ("delivered", "held", "skipped", "woke")      # 0.21.2 (item 1): "woke" = the sender fired the role's wake trigger
NUDGE_KINDS = ("task", "question", "review", "handoff", "result")   # notice / plain message start no wake
TERMINAL = ("completed", "failed", "canceled", "rejected")
TRIG_NOT_URGENT = "Do not skip this step because the mail is not urgent."   # 0.22.2 (A-0ce70 item 1): fixed text, never from mail
# 0.22.2 (A-0ce70 item 3): a relaying agent's report must carry evidence in its reason: an HTTP status and a run session id. Self-reported.
_EV_HTTP = re.compile(r"(?<![0-9A-Za-z])([1-5][0-9]{2})(?![0-9A-Za-z])")
_EV_SESSION = re.compile(r"(?<![0-9A-Za-z_])((?:cse|session)_[0-9A-Za-z]{6,64})(?![0-9A-Za-z_])")
WAKE_TEXT = ("/listen: run harness_inbox, answer routine coordination only (no approvals, publishes, pins or "
             "archives, corpus_index pins or other gated ops), then harness_admin op=listen args={action:rearm} "
             "and re-arm only if it says rearm=true.")
# During a wake only these may run (everything else is refused by wake_guard).
WAKE_TOOLS = ("harness_inbox", "harness_send", "harness_sync", "harness_recall", "harness_thread", "harness_task_update",
              "harness_whoami", "harness_ledger", "harness_status", "harness_record", "harness_admin")
WAKE_ADMIN = ("whoami", "ledger", "thread", "status", "roster", "task_update", "listen")
WAKE_RECORD_KINDS = ("note", "context")

# 0.17.0 (R-055): caps raised for release work (W43: 123 nudges skipped on caps vs 97 sent; 91 global, 28 pair)
DEFAULTS = {"nudge_per_agent_hour": 10, "nudge_per_pair_hour": 6, "global_per_hour": 30,
            "interval_min": 10, "max_per_hour": 6, "expire_h": 12, "wake_window_min": 15,
            # 0.22.0 (item 7): the delivery alarm, operator.json `doorbell` only
            "alarm_active_min": 30, "alarm_unread_min": 10, "alarm_per_role_hour": 1, "alarm_mail_after_days": 7}
BOUNDS = {"nudge_per_agent_hour": (1, 60), "nudge_per_pair_hour": (1, 30), "global_per_hour": (1, 120),
          "interval_min": (5, 120), "max_per_hour": (1, 12), "expire_h": (1, 48), "wake_window_min": (5, 60),
          "alarm_active_min": (5, 240), "alarm_unread_min": (2, 120), "alarm_per_role_hour": (1, 6), "alarm_mail_after_days": (0, 30)}


def _opcfg(h):
    """Operator-owned settings from operator.json: {"doorbell": {"off", "mute_roles", caps...},
    "listen": {"roles", "interval_min", "max_per_hour", "expire_h", "global_per_hour"}}. Type-checked, bounded."""
    try:
        import harness as H
        op, _ = H._operator_file()
    except Exception:
        op = {}
    out = dict(DEFAULTS)
    db, ls = op.get("doorbell"), op.get("listen")
    db = db if isinstance(db, dict) else {}
    ls = ls if isinstance(ls, dict) else {}
    for src in (db, ls):
        for k in BOUNDS:
            if k.startswith("alarm_") and src is not db:
                continue
            v = src.get(k)
            if isinstance(v, int) and not isinstance(v, bool) and BOUNDS[k][0] <= v <= BOUNDS[k][1]:
                out[k] = v
    out["off"] = db.get("off") is True
    out["mute_roles"] = [x for x in (db.get("mute_roles") or []) if isinstance(x, str)] if isinstance(db.get("mute_roles"), list) else []
    out["listen_roles"] = [H.cr(x) for x in (ls.get("roles") or []) if isinstance(x, str)] if isinstance(ls.get("roles"), list) else []
    return out


def _recent(h, since, types=None):
    """Events newer than `since` (epoch), oldest first, optionally only `types`."""
    out = []
    for e in reversed(h.store.read_all()):
        t = e.get("t")
        if t is not None and t < since:
            break
        if types is None or e.get("type") in types:
            out.append(e)
    out.reverse()
    return out


def _skip(h, frm, msg, to, reason):
    try:
        h.store.append("nudge.skipped", "system", {"msg": msg, "from": frm, "to": to, "reason": reason})
    except Exception:
        pass


# ---------------------------------------------------------------- nudge on send

ID_KINDS = ("task", "review", "question", "approval", "handoff")   # 0.22.0 (item 6): action kinds wake by id; results only a warm chat
ID_WAKE_MIN, ID_COLD_S = 30, 3600
TRIG_WAKE_MIN = 10                      # 0.21.2 (item 1): at most 1 trigger wake per role and per trigger id per 10 min, over all senders
TRIG_RE = re.compile(r"^trig_[A-Za-z0-9]{8,64}$")
TAIL_BYTES = 4 << 20                    # 0.21.2 (item 3): stale-id reads scan the last 4 MB of the ledger (~3,800 events at 1.1 KB each)


def _tail(h, nbytes=TAIL_BYTES, needle=None):
    """The ledger's last `nbytes`, parsed; a partial first line is dropped. `needle` (bytes): parse only lines that contain it, so a scan
    for a rare event type costs a byte search, not a JSON parse per line. Never follows a symlink. -> [events], oldest first."""
    st = h.store
    st._refuse_symlink(st.log)
    fd = os.open(st.log, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(fd, "rb") as f:
        size = os.fstat(f.fileno()).st_size
        start = max(0, size - int(nbytes))
        f.seek(start)
        raw = f.read()
    if start:
        cut = raw.find(b"\n")
        raw = raw[cut + 1:] if cut >= 0 else b""
    lines = [ln for ln in raw.split(b"\n") if ln and (needle is None or needle in ln)]
    return [e for e in st.parse_lines(ln.decode("utf-8", "replace") for ln in lines) if e.get("type") != "_corrupt"]


def _stale_marks(h, nbytes=TAIL_BYTES):
    """{app session id: recipient agent id} for ids a sender reported stale (nudge.stale_id) with no nudge.stale_cleared after it, replayed
    in ledger order over the bounded tail (item 3). The ledger is the only source (item 2): no state file holds a mark, so two chats writing
    at once cannot drop a clear. A mark older than the tail is forgotten; the worst case is one more failed send, which marks it again."""
    out = {}
    for e in _tail(h, nbytes, b"nudge.stale_"):
        t, d = e.get("type"), e.get("data") or {}
        hid = d.get("host_session_id")
        if t == "nudge.stale_id" and hid:
            out[hid] = d.get("to")
        elif t == "nudge.stale_cleared":
            out.pop(hid, None)
    return out


def _wake_trigger(st, role):
    """The role's wake trigger id from the latest operator-approved wake.pinned event (harness_admin op=wake_pin), or None. The wake.json
    file is never read here (critic B1: any local agent can write it); an edit counts only after the operator pins it again. The format is
    checked again on read."""
    pin = getattr(st, "wake_pin", None) or {}
    ent = pin.get("entries") if isinstance(pin, dict) else None
    v = ent.get(role) if isinstance(ent, dict) and role else None
    return v if isinstance(v, str) and TRIG_RE.match(v) else None


def _stale_ids(h):
    """App session ids still marked stale (see _stale_marks)."""
    return set(_stale_marks(h))


def _id_for(st, rid, kind):
    """The recipient's app session id, from the holder's own register, restore or sync record (H1 own-agent guard). Action kinds and
    results only; whether a result may use it is decided in _pick_id (warm recipients only)."""
    a = st.agents.get(rid) or {}
    hid = a.get("host_session_id")
    if kind in ID_KINDS + ("result",) and isinstance(hid, str) and hid.startswith("local_") and len(hid) < 80 and hid.replace("_", "").replace("-", "").isalnum():
        return hid
    return None


def _same_machine(a, st=None):
    """0.22.0 (item 6, critic m-00ea2ad60bc4): a session id only reaches a chat on the sender's machine. 0.22.1 (envoy m-ea0c30970c55):
    the machine is the stable machine id, never the hostname (it changes with the network). A-4d611: this side's id unreadable means
    mail only; a holder record with an id must match it; a record from before 0.22.1 (no id) matches only through a host name this
    machine itself registered or synced under (learned from the ledger), else mail only until the holder next registers, restores or
    syncs."""
    import harness as H
    mine, theirs = H.machine_id(), a.get("machine")
    if not mine:
        return False                                  # A-4d611: an unreadable id fails safe (mail only, no alarm)
    if theirs:
        return theirs == mine
    aliases = set((getattr(st, "machine_hosts", None) or {}).get(mine) or ()) | {H.HOSTNAME}
    return H.norm_host(a.get("host")) in aliases      # a record from before 0.22.1: only a host name this machine used counts


def _route(h, st, rid, a, kind, now):
    """0.22.0 (item 6, D-3e5e7): the ROLE is the address and the harness resolves it; the only thing a sender ever gets is the holder's
    own app session id. -> (hid or None, mail-only reason or None)."""
    if not st.role_of(rid):
        return None, "no role: mail only"
    if not (a.get("host_session_id") or "").startswith("local_"):
        return None, "no app session id: mail only"
    if not _same_machine(a, st):
        return None, "holder on another machine: mail only"
    hid = _pick_id(h, st, rid, kind, now)
    if hid:
        return hid, None
    if kind == "result":
        return None, "result to a cold holder: mail only"
    return None, "id route closed by a stale mark or the cold-wake cap: mail only"


def _do_one(hid, trig, line, mid):
    """0.22.0 (item 6): one exact address, no name, no title, no ListAgents row check. -> the Do-line text, or None (mail only)."""
    rep = f' harness_admin op=nudge_result args={{msg_id:"{mid}",outcome:delivered|held|skipped,reason}}.'
    parts = []
    if hid:
        parts.append(f'Do: SendMessage to {hid}: {line} (fixed fields only, no subject or body). If the send fails (stale, archived or deleted '
                     f'session) do not retry it: report skipped with reason stale_id; the mail waits. No SendMessage tool here (a Cowork or '
                     f'cloud chat): report skipped with reason no_sendmessage.'
                     + (' If it did not deliver, run the RemoteTrigger step next, then report once:' if trig else ' Then report:') + rep)
    if trig:
        parts.append(f'Do: RemoteTrigger action=run trigger_id={trig} ('
                     + ('only if the SendMessage step above did not deliver or the session holds it; ' if hid else '')
                     + 'load the tool with ToolSearch select:RemoteTrigger if it is deferred; it runs under the Claude subscription, never '
                     'with an API key; no other trigger tool). ' + TRIG_NOT_URGENT + ' Then report outcome woke'
                     + (' instead of skipped.' if hid else ':' + rep)
                     + ' No RemoteTrigger tool here: skip that step with reason no_remotetrigger.')
    return " ; ".join(parts) or None


def _pick_id(h, st, rid, kind, now):
    """Session-id route. The id comes only from the holder's own record. A COLD recipient (its last harness call over 1 h ago, or none):
    action kinds get at most 1 id wake per 30 min summed over ALL senders (nudge.idwake, counted apart from offers); a result never wakes
    a cold chat (0.22.0 item 6). A warm one costs no extra read."""
    hid = _id_for(st, rid, kind)
    if not hid or hid in _stale_ids(h):
        return None
    last = _load(_sp(h, rid)).get("last_call")
    if last and now - float(last) <= ID_COLD_S:
        return hid
    if kind == "result":
        return None
    if any(rid in (e["data"].get("to") or []) for e in _recent(h, now - ID_WAKE_MIN * 60, ("nudge.idwake",))):
        return None
    try:
        h.store.append("nudge.idwake", "system", {"to": [rid], "host_session_id": hid})
    except Exception:
        return None
    return hid


def attach_nudge(h, sender_ref, result):
    """Add `nudge` (and `skipped`) to a send result. Never raises; a failure leaves the result as it was."""
    try:
        return _attach(h, sender_ref, result)
    except Exception:
        return result


def _pick_trig(h, st, rid, mid, now):
    """0.21.2 (item 1): a role with a pinned `trig_...` wake trigger gets a RemoteTrigger Do-line, at most once per role AND once per trigger
    id per 10 min summed over all senders (critic B2: roles pointed at one routine share its slot). Event nudge.trigwake, counted apart
    from offers and written when OFFERED, since the harness cannot see whether the sender fired it; a sender reporting `delivered` (the
    SendMessage step rang, so no trigger ran) frees the slot (nudge.trigwake_released). Only reached after every existing cap passed."""
    role = st.role_of(rid)
    trig = _wake_trigger(st, role)
    if not trig:
        return None
    since = now - TRIG_WAKE_MIN * 60
    evs = _tail(h, needle=b"nudge.trigwake")
    freed = {(e.get("data") or {}).get("msg_id") for e in evs if e.get("type") == "nudge.trigwake_released"}
    for e in evs:
        d = e.get("data") or {}
        if e.get("type") == "nudge.trigwake" and (e.get("t") or 0) >= since and d.get("msg_id") not in freed \
                and (d.get("role") == role or d.get("trigger") == trig):
            return None
    try:
        h.store.append("nudge.trigwake", "system", {"role": role, "to": [rid], "msg_id": mid, "trigger": trig})
    except Exception:
        return None
    return trig


def _attach(h, sender_ref, r):
    if not isinstance(r, dict) or not r.get("id"):
        return r
    st = h.state()
    mid = r["id"]
    m = st.messages.get(mid)
    if not m:
        return r
    if m["from"] in ("human", "operator") or m["kind"] not in NUDGE_KINDS:
        return r
    sender = m["from"]
    cfg = _opcfg(h)
    now = time.time()
    hour = _recent(h, now - 3600, OFFERS + ("nudge.skipped",))
    sent = [e for e in hour if e["type"] in OFFERS]
    seen_msg = {e["data"].get("msg") or e["data"].get("msg_id") for e in _recent(h, now - 86400, OFFERS)}
    targets, skipped = [], []
    cand = list(m.get("to_resolved") or [])
    for tgt in m.get("to") or []:    # a role target resolves to its live holder now; groups and broadcasts never nudge
        if isinstance(tgt, str) and tgt.startswith("role:"):
            hid = st.role_holder(tgt[5:])
            if hid:
                cand.append(hid)
    for rid in dict.fromkeys(cand):
        a = st.agents.get(rid)
        if rid in ("human", "operator") or rid == sender or not a or a.get("status") not in ("active", "idle"):
            continue
        role = st.role_of(rid) or ""
        reason = None
        if cfg["off"]:
            reason = "doorbell off (operator.json)"
        elif role and role in cfg["mute_roles"]:
            reason = f"role {role} muted (operator.json)"
        elif mid in seen_msg:
            reason = "already nudged for this message"
        elif sum(1 for e in sent if e["data"].get("from") == sender) >= cfg["nudge_per_agent_hour"]:
            reason = f"sender cap {cfg['nudge_per_agent_hour']}/h"
        elif sum(1 for e in sent if (e["data"].get("from") == sender and rid in (e["data"].get("to") or []))
                 or (e["data"].get("from") == rid and sender in (e["data"].get("to") or []))) >= cfg["nudge_per_pair_hour"]:
            reason = f"pair cap {cfg['nudge_per_pair_hour']}/h (ping-pong guard)"
        elif len(sent) + sum(1 for e in _recent(h, now - 3600, ("listen.wake",))) >= cfg["global_per_hour"]:
            reason = f"global cap {cfg['global_per_hour']}/h"
        if reason:
            _skip(h, sender, mid, [rid], reason)
            skipped.append({"to": a.get("sobriquet"), "reason": reason})
            continue
        targets.append((rid, a))
    out = dict(r)
    if skipped:
        out["nudge_skipped"] = skipped
    if not targets:
        return out
    srole = st.role_of(sender)
    line = (f"Mail {mid} from {srole or 'agent ' + sender[:8]}, thread {m['thread']}. Run harness_inbox (CLI: harness.py inbox --agent "
            f"<your id> --peek), reply with send reply_to {mid}.")
    ring, mail_only = [], []
    for rid, a in targets:
        hid, why = _route(h, st, rid, a, m["kind"], now)
        trig = _pick_trig(h, st, rid, mid, now)
        if hid or trig:
            ring.append((rid, a, hid, trig))
        else:
            mail_only.append({"to": st.name_role(rid), "reason": why})
    if mail_only:
        out["nudge_mail_only"] = mail_only
    if not ring:
        out["nudge"] = "none (" + "; ".join(sorted({x["reason"].replace(": mail only", "") for x in mail_only})) + ": mail only)"
        return out
    ids = [rid for rid, _, _, _ in ring]
    h.store.append("nudge.offered", "system", {"msg": mid, "msg_id": mid, "from": sender, "to": ids, "thread": m["thread"],
                                               "roles": [st.role_of(rid) or None for rid in ids],
                                               "by_id": [bool(x) for _, _, x, _ in ring], "hids": [x for _, _, x, _ in ring],
                                               "by_trigger": [bool(g) for _, _, _, g in ring]})
    try:
        note_offer(h, sender, mid, now)       # the sender must report the outcome (op=nudge_result)
    except Exception:
        pass
    n_hour = sum(1 for e in sent if e["data"].get("from") == sender) + 1
    out["nudge"] = {"line": line, "to": [st.name_role(rid) for rid in ids], "msg_id": mid, "thread": m["thread"],
                    "cap_state": f"{n_hour}/{cfg['nudge_per_agent_hour']} this hour",
                    "do": " ; ".join(_do_one(x, g, line, mid) for _, _, x, g in ring)}
    return out


# ---------------------------------------------------------------- visible outcomes (0.21.1, item 4)
# The harness only OFFERS a nudge (nudge.offered); only the sender knows whether it rang. The sender reports op=nudge_result. A small per-agent
# state file (derived; the ledger is the truth) keeps the time of the agent's last harness call and its offers that still await an outcome.
# An offer becomes nudge.unreported only when it is older than the sender's PREVIOUS call and still has no result, so a result in the very next
# call (the inbox call right after the send) always counts.

def _sp(h, aid):
    return os.path.join(h.store.dir, "nudge_state", str(aid)[:64] + ".json")


def _load(p):
    try:
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(p, d):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = "%s.%d.tmp" % (p, os.getpid())
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f)
    os.replace(tmp, p)


def note_offer(h, sender, mid, t):
    p = _sp(h, sender)
    d = _load(p)
    pend = d.setdefault("pending", {})
    pend[mid] = round(float(t), 3)
    for k in sorted(pend, key=pend.get)[:-200]:         # bounded
        pend.pop(k, None)
    _save(p, d)


def settle(h, aid, now=None):
    """Called at the start of each of an agent's harness calls (except the nudge_result call itself). Writes nudge.unreported for the agent's
    offers that are older than its previous call and still have no result; then records this call's time. Never raises. -> [msg ids]."""
    out = []
    try:
        now = float(now if now is not None else time.time())
        p = _sp(h, aid)
        d = _load(p)
        prev = d.get("last_call")
        pend = d.get("pending") or {}
        if prev:
            for mid, t in list(pend.items()):
                if float(t) < float(prev):
                    h.store.append("nudge.unreported", "system", {"msg": mid, "msg_id": mid, "by": aid, "offered_t": t})
                    out.append(mid)
                    pend.pop(mid, None)
        d["pending"] = pend
        d["last_call"] = round(now, 3)
        d.pop("stale_hids", None)                   # 0.21.1 field, unused since 0.21.2 (item 2)
        _save(p, d)
        # 0.21.2 (item 2): the clear comes from the ledger only. A call from a session marked stale proves it live: clear its mark for every
        # sender. With no host session id in the env (CLI, another machine), the agent clears marks naming it (known issue, 0.21.1).
        cur = os.environ.get("CLAUDE_CODE_HOST_SESSION_ID") or ""
        for hid, to in _stale_marks(h).items():
            if (cur and cur == hid) or (not cur and to == aid):
                h.store.append("nudge.stale_cleared", "system", {"agent": aid, "host_session_id": hid})
        alarm_scan(h, now)                          # 0.22.0 (item 7): at most once a minute, inside the call the agent already makes
    except Exception:
        pass
    return out


class _Already(Exception):
    pass


def relay_evidence(reason):
    """0.22.2 (A-0ce70 item 3): the evidence a relaying (non-sender) reporter must give in its reason: a run session id (cse_... or
    session_...) and a 3-digit HTTP status. Self-reported: the harness checks the shape, not the run. -> {"http", "session"} or None."""
    s = str(reason or "")
    m = _EV_SESSION.search(s)
    if not m:
        return None
    rest = s[:m.start()] + " " + s[m.end():]      # a status is never read from inside the session id
    st = _EV_HTTP.search(rest)
    if not st:
        return None
    return {"http": st.group(1), "session": m.group(1)}


def record_result(h, caller, msg_id, outcome, reason=None):
    """harness_admin op=nudge_result {msg_id, outcome: delivered|held|skipped (woke accepted), reason}. A skipped result whose reason starts
    stale_id marks the offer's app session ids stale (nudge.stale_id) until the recipient next calls the harness from that session. The sender
    of the offered mail may report; 0.22.2 (A-0ce70 item 3): so may a relaying agent whose reason carries evidence (relay_evidence), recorded
    with `by` (reporter) and `for` (the offer's sender) and `evidence` marked self-reported. One result per message (a second call answers
    already_reported). A result counts even after the offer was flagged unreported."""
    import harness as H
    msg_id = str(msg_id or "").strip()
    if outcome not in OUTCOMES:
        raise H.HarnessError("outcome must be one of " + ", ".join(OUTCOMES))
    st = h.state()
    offer = None
    for e in reversed(h.store.read_all()[-6000:]):
        if e.get("type") in OFFERS and (e.get("data") or {}).get("msg") == msg_id or (e.get("type") in OFFERS and (e.get("data") or {}).get("msg_id") == msg_id):
            offer = e["data"]
            break
    if not offer:
        raise H.HarnessError("no nudge was offered for %s" % msg_id)
    mine = set(st.lineage(caller)) | {caller}
    why = " ".join(str(reason or "").replace("\x00", " ").split())[:80]
    ev = None
    if offer.get("from") not in mine:
        ev = relay_evidence(why)      # 0.22.2 (A-0ce70 item 3): a relaying agent may report, only with evidence
        if not ev:
            raise H.HarnessError("only the sender of %s can report its nudge" % msg_id)
    data = {"msg": msg_id, "msg_id": msg_id, "by": caller, "for": offer.get("from"), "outcome": outcome, "reason": why}
    if ev:
        data["evidence"] = dict(ev, self_reported=True)

    def _fresh(store):
        for e in store.read_all()[-3000:]:
            if e.get("type") == "nudge.result" and ((e.get("data") or {}).get("msg_id") == msg_id):
                raise _Already()
    try:
        h.store.append("nudge.result", caller, data, precheck=_fresh)
    except _Already:
        return {"msg_id": msg_id, "already_reported": True}
    if outcome == "delivered" and any(offer.get("by_trigger") or []):
        try:    # 0.21.2 (item 1): the SendMessage step rang, so no trigger ran: free the wake slot (no extra round trip, this is the report)
            h.store.append("nudge.trigwake_released", "system", {"msg_id": msg_id})
        except Exception:
            pass
    if outcome == "skipped" and why.lower().startswith("stale_id"):
        for to, hid in zip(offer.get("to") or [], offer.get("hids") or []):
            if hid:
                try:
                    h.store.append("nudge.stale_id", caller, {"msg_id": msg_id, "to": to, "host_session_id": hid})   # settle clears it
                except Exception:
                    pass
    try:
        p = _sp(h, offer.get("from"))
        d = _load(p)
        if msg_id in (d.get("pending") or {}):
            d["pending"].pop(msg_id, None)
            _save(p, d)
    except Exception:
        pass
    return {"msg_id": msg_id, "reported": True, "outcome": outcome}


def outcomes(events):
    """Counts for the weekly report and R5 from a list of ledger events: offers, the sender's reported outcomes, and offers with NO result,
    split in two (critic): PENDING = the sender has made no later call yet, UNREPORTED = a later call came and still no result. A result
    always wins over an unreported flag. -> dict"""
    offers, results, unrep = {}, {}, set()
    for e in events:
        t, d = e.get("type"), e.get("data") or {}
        k = d.get("msg_id") or d.get("msg")
        if t in OFFERS and k:
            offers[k] = d
        elif t == "nudge.result" and k:
            results[k] = d.get("outcome")
        elif t == "nudge.unreported" and k:
            unrep.add(k)
    by = {o: sum(1 for k, v in results.items() if v == o and k in offers) for o in OUTCOMES}
    no_result = [k for k in offers if k not in results]
    flagged = [k for k in no_result if k in unrep]
    return {"offered": len(offers), "delivered": by["delivered"], "woke": by["woke"], "held": by["held"], "skipped_by_sender": by["skipped"],
            "pending": len(no_result) - len(flagged), "unreported": len(flagged)}


# ---------------------------------------------------------------- /listen

def _lineage(st, aid):
    return set(st.lineage(aid))


def owed_replies(st, aid):
    """Ids of task/question/review mail (or mail marked expects_reply) to this agent that it has not answered yet."""
    mine = _lineage(st, aid)
    role = st.role_of(aid)
    out = []
    for mid in st.order:
        m = st.messages[mid]
        if m["from"] in mine:
            continue
        if not (mine & set(m.get("to_resolved", [])) or (role and f"role:{role}" in m["to"])):
            continue
        if not (m["kind"] in ("task", "question", "review") or m.get("expects_reply")):
            continue
        if (st.tasks.get(mid) or {}).get("state") in TERMINAL:
            continue
        if any(st.messages[x]["from"] in mine and st.messages[x]["seq"] > m["seq"] for x in st.threads[m["thread"]]["messages"]):
            continue
        out.append(mid)
    return out[-8:]


def open_task(st, aid):
    """Computed from the ledger (never from the agent): non-terminal tasks assigned to this agent's lineage, plus
    task/question/review mail to it that it has not answered. -> (count, [message ids])."""
    mine = _lineage(st, aid)
    ids = [k for k, tk in st.tasks.items() if mine & set(tk["to"]) and tk.get("state") not in TERMINAL]
    role = st.role_of(aid)
    for mid in st.order:
        m = st.messages[mid]
        if m["from"] in mine or mid in ids:
            continue
        if not (mine & set(m.get("to_resolved", [])) or (role and f"role:{role}" in m["to"])):
            continue
        if not (m["kind"] in ("question", "review") or m.get("expects_reply")):
            continue
        if any(st.messages[x]["from"] in mine and st.messages[x]["seq"] > m["seq"] for x in st.threads[m["thread"]]["messages"]):
            continue
        ids.append(mid)
    return len(ids), ids[-5:]


def _listen_events(h, now, cfg):
    return _recent(h, now - cfg["expire_h"] * 3600 - 60, ("listen.armed", "listen.wake", "listen.rearmed", "listen.ended"))


def listen_state(h, now=None, cfg=None):
    """-> {aid: {role, armed_t, expires, next_t, wake_t, in_wake}} for live arms, plus the wake count of this hour."""
    now = now or time.time()
    cfg = cfg or _opcfg(h)
    st = h.state()
    arms = {}
    for e in _listen_events(h, now, cfg):
        d, aid = e["data"], e["data"].get("agent")
        if not aid:
            continue
        if e["type"] == "listen.armed":
            arms[aid] = {"role": d.get("role"), "armed_t": e["t"], "expires": d.get("expires"), "next_t": d.get("next_t"), "wake_t": None}
        elif aid in arms and e["type"] == "listen.wake":
            arms[aid]["wake_t"] = e["t"]
        elif aid in arms and e["type"] == "listen.rearmed":
            arms[aid]["next_t"], arms[aid]["wake_t"] = d.get("next_t"), None
        elif e["type"] == "listen.ended":
            arms.pop(aid, None)
    live = {}
    for aid, a in arms.items():
        ag = st.agents.get(aid) or {}
        if ag.get("status") not in ("active", "idle") or ag.get("handed_off") or (a["expires"] or 0) <= now:
            continue    # session end (handoff, supersede, retire) and expiry both end the arm
        a["in_wake"] = bool(a["wake_t"] and now - a["wake_t"] < cfg["wake_window_min"] * 60)
        live[aid] = a
    wakes = len(_recent(h, now - 3600, ("listen.wake",)))
    return live, wakes


def listen_status(h):
    """Armed roles, next wake and wakes used this hour, for harness status. None when nothing to show."""
    cfg = _opcfg(h)
    live, wakes = listen_state(h, cfg=cfg)
    if not live and not wakes:
        return None
    now = time.time()
    return {"armed": [{"role": a["role"], "agent": aid[:8], "next_in_min": max(0, int(((a["next_t"] or now) - now) / 60)),
                       "expires_in_h": round(max(0.0, ((a["expires"] or now) - now) / 3600), 1)} for aid, a in live.items()],
            "wakes_this_hour": wakes, "global_cap": cfg["global_per_hour"], "enabled_roles": cfg["listen_roles"]}


def listen(h, agent, action="status"):
    """harness_admin op=listen. actions: status | arm | wake | rearm | end. The server decides; arguments carry no claims."""
    st = h.state()
    aid = h.writer(st, agent)
    role = st.role_of(aid)
    cfg = _opcfg(h)
    now = time.time()
    HE = __import__("harness").HarnessError
    action = str(action or "status").strip().lower()
    if action not in ("status", "arm", "wake", "rearm", "end"):
        raise HE("listen: action must be status|arm|wake|rearm|end")
    live, wakes = listen_state(h, now, cfg)
    mine = live.get(aid)
    if action == "status":
        return {"role": role, "enabled": bool(role and role in cfg["listen_roles"]), "armed": bool(mine),
                "next_in_min": max(0, int(((mine or {}).get("next_t") or now) - now) // 60) if mine else None,
                "wakes_this_hour": wakes, "interval_min": cfg["interval_min"]}
    if action == "end":
        if mine:
            h.store.append("listen.ended", aid, {"agent": aid, "role": role, "reason": "ended by the agent"})
        return {"armed": False}
    if not role or role not in cfg["listen_roles"]:      # cond 1: operator-owned enable, default off
        _skip(h, aid, None, [aid], f"listen not enabled for role {role or '(none)'} in operator.json")
        raise HE(f"listen: not enabled for role {role or '(none)'}; only the operator enables it (operator.json listen.roles)")
    n_open, ids = open_task(st, aid)
    role_wakes = sum(1 for e in _recent(h, now - 3600, ("listen.wake",)) if e["data"].get("role") == role)
    glob = len(_recent(h, now - 3600, OFFERS + ("listen.wake",)))
    if action == "wake":
        if not mine:
            _skip(h, aid, None, [aid], "wake without a live arm")
            return {"ok": False, "reason": "not armed or expired; stop"}
        if role_wakes >= cfg["max_per_hour"] or glob >= cfg["global_per_hour"]:
            _skip(h, aid, None, [aid], f"wake cap (role {role_wakes}/{cfg['max_per_hour']}, global {glob}/{cfg['global_per_hour']})")
            return {"ok": False, "reason": "hourly wake cap reached; stop"}
        h.store.append("listen.wake", aid, {"agent": aid, "role": role})
        return {"ok": True, "allowed": "harness_inbox and routine coordination only; no approvals, publishes, pins, archives or gated ops",
                "open": n_open, "open_ids": ids}
    # arm / rearm
    why = None
    if not n_open:
        why = "no open task or owed reply (computed from the ledger)"
    elif action == "rearm" and not mine:
        why = "not armed or expired"
    elif role_wakes >= cfg["max_per_hour"]:
        why = f"role wake cap {cfg['max_per_hour']}/h"
    elif glob >= cfg["global_per_hour"]:
        why = f"global cap {cfg['global_per_hour']}/h"
    if why:
        _skip(h, aid, None, [aid], f"{action} refused: {why}")
        if mine:
            h.store.append("listen.ended", aid, {"agent": aid, "role": role, "reason": why})
        key = "arm" if action == "arm" else "rearm"
        return {key: False, "reason": why}
    nxt = now + cfg["interval_min"] * 60
    exp = (mine or {}).get("expires") or now + cfg["expire_h"] * 3600
    if action == "arm" and not mine:
        h.store.append("listen.armed", aid, {"agent": aid, "role": role, "expires": exp, "next_t": nxt})
    else:
        h.store.append("listen.rearmed", aid, {"agent": aid, "role": role, "next_t": nxt})
    return {("arm" if action == "arm" else "rearm"): True, "delay_min": cfg["interval_min"], "message": WAKE_TEXT,
            "open": n_open, "expires_in_h": round((exp - now) / 3600, 1),
            "how": f"schedule your own wake: delay_minutes={cfg['interval_min']}, message=\"/listen\" "
                   "(send_later on Cowork; the Code scheduler on Code). It wakes only this chat."}


def wake_guard(h, tool, args):
    """Refuse gated tools while the calling agent is inside a /listen wake (condition 5). Never raises except the
    refusal itself; a ledger/lookup failure leaves the call allowed (the skill text still restricts the wake)."""
    agent = (args or {}).get("agent")
    if not agent or not isinstance(agent, str):
        return
    try:
        st = h.state()
        aid = h.resolve(st, agent, follow=False)
        # cheap exit: only a wake in the last wake_window can matter
        cfg = _opcfg(h)
        now = time.time()
        recent = _recent(h, now - cfg["wake_window_min"] * 60, ("listen.wake", "listen.rearmed", "listen.ended", "listen.armed"))
        wake_t = None
        for e in recent:
            if (e["data"] or {}).get("agent") != aid:
                continue
            wake_t = e["t"] if e["type"] == "listen.wake" else None
        if wake_t is None:
            return
    except Exception:
        return
    ok = tool in WAKE_TOOLS
    if tool == "harness_admin":
        ok = (args or {}).get("op") in WAKE_ADMIN
    elif tool == "harness_record":
        ok = str((args or {}).get("kind") or "note") in WAKE_RECORD_KINDS and str((args or {}).get("tier") or "") != "foundation"
    if not ok:
        import harness as H
        raise H.HarnessError(f"{tool}: refused during a /listen wake (inbox and routine coordination only); "
                             "the operator or a normal session runs gated and file-changing work")


# ---------------------------------------------------------------- delivery alarm (0.22.0, item 7; addendum v2.1, D-3e5e7)
# A nudge that could ring (its offer carried an id Do-line for that recipient) to an ACTIVE holder either goes unread past
# alarm_unread_min (A1) or comes back skipped for a reason that is not a cap, or unreported (A2): write nudge.alarm. Deterministic, 0 tokens.

ALARM_SCAN_EVERY_S = 60


def _is_cap(reason):
    r = str(reason or "").lower()
    return "cap" in r or r.startswith(("doorbell off", "already nudged")) or "muted" in r


def _last_activity(h, st, rid):
    """The holder's last harness call (settle's record); its ledger last_seen only when no call is on record yet."""
    lc = _load(_sp(h, rid)).get("last_call")
    if lc:
        return float(lc)
    ls = (st.agents.get(rid) or {}).get("last_seen")
    return float(ls) if ls else None


def alarm_scan(h, now=None, force=False):
    """Scan the ledger tail (last 24 h of offers) and write nudge.alarm per the rules above. At most once a minute unless force=True.
    Never raises. -> [alarm data dicts written]"""
    out = []
    try:
        now = float(now if now is not None else time.time())
        sp = os.path.join(h.store.dir, "nudge_state", "_alarm_scan.json")
        stamp = _load(sp)
        if not force and now - float(stamp.get("last") or 0) < ALARM_SCAN_EVERY_S:
            return out
        stamp["last"] = round(now, 3)
        _save(sp, stamp)
        cfg = _opcfg(h)
        st = h.state()
        evs = [e for e in _tail(h, needle=b'"nudge.') if e.get("type") in ("nudge.offered", "nudge.result", "nudge.unreported", "nudge.alarm", "nudge.alarm_armed")]
        if not any(e["type"] == "nudge.offered" and any((e.get("data") or {}).get("by_id") or []) and float(e.get("t") or 0) >= now - 86400
                   for e in evs):
            return out                               # nothing could alarm: write nothing (a read-only call stays read-only)
        armed = next((e for e in evs if e["type"] == "nudge.alarm_armed"), None) or stamp.get("armed")
        if not armed:
            ev = h.store.append("nudge.alarm_armed", "system", {"t": round(now, 3)})
            stamp["armed"] = {"t": ev.get("t", now)}
            armed = stamp["armed"]
        armed_t = float((armed.get("data") or {}).get("t") or armed.get("t") or now) if isinstance(armed, dict) else now
        alarmed = {(e.get("data") or {}).get("msg_id") for e in evs if e["type"] == "nudge.alarm"}
        results = {(e.get("data") or {}).get("msg_id"): e.get("data") or {} for e in evs if e["type"] == "nudge.result"}
        unrep = {(e.get("data") or {}).get("msg_id") for e in evs if e["type"] == "nudge.unreported"}
        role_hour = {}
        for e in evs:
            if e["type"] == "nudge.alarm" and float(e.get("t") or 0) >= now - 3600:
                r_ = (e.get("data") or {}).get("role")
                role_hour[r_] = role_hour.get(r_, 0) + 1
        sup = stamp.setdefault("suppressed", {})
        sup_seen = set(stamp.setdefault("suppressed_mids", []))
        act, unread_s = cfg["alarm_active_min"] * 60, cfg["alarm_unread_min"] * 60
        for e in evs:
            if e["type"] != "nudge.offered" or float(e.get("t") or 0) < now - 86400:
                continue
            d = e.get("data") or {}
            mid, sent_t = d.get("msg_id") or d.get("msg"), float(e.get("t") or 0)
            if not mid or mid in alarmed:
                continue
            m = st.messages.get(mid) or {}
            for i, rid in enumerate(d.get("to") or []):
                if not (d.get("by_id") or [])[i:i + 1] or not d["by_id"][i]:
                    continue                                 # A1 and A2 apply only when an id Do-line was offered (critic m-fcb579e7e932)
                a = st.agents.get(rid) or {}
                if not (a.get("host_session_id") or "").startswith("local_"):
                    continue
                last = _last_activity(h, st, rid)
                if last is None or not (now - last <= act or abs(last - sent_t) <= act):
                    continue                                 # not active at send time or at scan time
                role = (d.get("roles") or [None] * (i + 1))[i] or st.role_of(rid)
                res = results.get(mid) or {}
                cond = reason = None
                if res.get("outcome") == "skipped" and not _is_cap(res.get("reason")):
                    cond, reason = "skipped", res.get("reason") or ""
                elif mid in unrep and not res:
                    cond, reason = "unreported", "the sender made a later call and never reported"
                elif rid not in (m.get("read_by") or []) and now - sent_t >= unread_s:   # A1: whatever the sender reported
                    cond, reason = "unread", f"unread after {int((now - sent_t) // 60)} min"
                if not cond:
                    continue
                if role_hour.get(role, 0) >= cfg["alarm_per_role_hour"]:
                    if mid not in sup_seen:
                        sup[role] = sup.get(role, 0) + 1
                        sup_seen.add(mid)
                    continue
                data = {"msg_id": mid, "role": role, "to": rid, "from": d.get("from"), "cond": cond, "reason": str(reason)[:120],
                        "age_min": int((now - sent_t) // 60), "suppressed": sup.pop(role, 0)}
                h.store.append("nudge.alarm", "system", data)
                alarmed.add(mid)
                role_hour[role] = role_hour.get(role, 0) + 1
                out.append(data)
                if now - armed_t >= cfg["alarm_mail_after_days"] * 86400:
                    try:    # ids only, never subject or body text of the message
                        h.send("operator", ["role:envoy"], f"nudge.alarm {mid} role {role} cond {cond} age {data['age_min']} min",
                               subject="nudge alarm", kind="notice")
                    except Exception:
                        pass
                break
        stamp["suppressed_mids"] = sorted(sup_seen)[-500:]
        _save(sp, stamp)
    except Exception:
        pass
    return out


def alarm_lines(h, st, aid):
    """Sync 'Changed' lines: alarms in the last 24 h for this agent whose message it still has not read."""
    out = []
    try:
        for e in _tail(h, needle=b"nudge.alarm"):
            d = e.get("data") or {}
            if e.get("type") == "nudge.alarm" and d.get("to") == aid and float(e.get("t") or 0) >= time.time() - 86400:
                m = st.messages.get(d.get("msg_id")) or {}
                if aid not in (m.get("read_by") or []):
                    out.append(f"⚠ nudge alarm: {d.get('msg_id')} ({d.get('cond')}) is waiting: harness_inbox")
    except Exception:
        pass
    return out[:5]


def alarm_summary(h, days=7):
    """For the health report: alarm counts per role over `days`, and the suppressed hits summed per role."""
    since = time.time() - days * 86400
    by, sup = {}, {}
    try:
        for e in _tail(h, needle=b"nudge.alarm"):
            d = e.get("data") or {}
            if e.get("type") == "nudge.alarm" and float(e.get("t") or 0) >= since:
                by[d.get("role")] = by.get(d.get("role"), 0) + 1
                sup[d.get("role")] = sup.get(d.get("role"), 0) + int(d.get("suppressed") or 0)
    except Exception:
        pass
    return {"days": days, "alarms": sum(by.values()), "by_role": by, "suppressed": sum(sup.values()), "suppressed_by_role": sup}
