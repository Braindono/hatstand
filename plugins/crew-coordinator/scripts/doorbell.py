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
from wake_batch import group_by_shape, paired_trigs, smallest_first     # 0.27.3 B (F6)

SYSTEM_SENDER = "system"     # 0.25.0 item 39 (same value as harness.SYSTEM_SENDER): alarm-scan and script notices


def is_system_sender(x):
    """0.25.0 item 39: the one test for the named system sender; a notice from it is never nudged, alarmed or owed."""
    return x == SYSTEM_SENDER

OFFERS = ("nudge.offered", "nudge.sent")     # 0.21.1 (A-58ff8 item 4): the server event was renamed; the old name still counts as an offer
OUTCOMES = ("delivered", "held", "skipped", "woke", "refused_by_app")   # 0.22.3: refused_by_app (relayer only); 0.21.2 (item 1): "woke" = the sender fired the role's wake trigger
RELAY_OUTCOMES = ("delivered", "held", "woke", "refused_by_app")   # 0.22.3 (A-8a3da item 1); 0.24.0 (item 18 point 4): + held
RELAY_ASK = ("no_sendmessage", "no_listagents", "no_response")   # 0.22.3 (item 2): a sender skip with one of these asks for a relay; 0.24.0 (A-b2950 item 3): no_response = a fire with no HTTP response
RELAY_TTL_S = 3900                                         # 0.24.0 (item 18): 65 min, past the 1-h rewake step (was 1800)
RELAY_CAP_S = 3600                                         # 0.22.3 (item 1): a relayer the app refused takes no claims for 60 min
RELAY_TURN_S = 30                                          # 0.24.0 (item 18): round-robin hold 30 s, short enough for a 60-s silent sender (was 120)
RELAY_CLAIM_S = 120                                        # 0.24.0 (item 18): the claimer sees the line at its next tool call; 2 min with no report
                                                           # means it is not acting (was 300)
RELAY_REPEAT_S = 120                                       # item 18 point 1: the hook repeats a live claim's Do-line at most once per 2 min
RELAY_NOTICE_S = 600                                       # item 18 point 5: the sender hears only of a relay unclaimed 10 min, mail unread
RELAY_HOOK_TAIL = 1 << 20                                  # item 18 point 7: the hook's cheap check reads the ledger's last 1 MB
RELAY_ROLES = ("envoy", "curator", "ops-coder", "harness-critic", "design-coder")   # 0.22.3b (blocker 1a): default claimers (operator.json doorbell.relay_roles)
RELAY_NEVER = ("steward",)                                 # 0.22.3b: the steward ignores every Do-line but register and reload (D-67610): never a claimer
RELAY_PER_SENDER_HOUR = 30                                 # 0.22.3 (item 2): relay offers per sender per hour
RELAY_NO_ALARM = ("read_before_relay",)                    # the recipient read the mail before any relay: nothing to alarm about
# 0.24.0 (A-b2950 item 5; relay-wake spec v3.2 section 1): task, question and review always ring. A sender's skip needs a reason from a fixed
# list (R1); a silent sender (R1b) and a capped send (R1c) become relay requests; no second wake while a woken mail is unread (R2), with a
# rewake at 15 min and 1 h; one ring per recipient session (R3), and none for a second mail to a session rung under 60 s ago (nb 6).
RING_KINDS = ("task", "question", "review")
SKIP_OK = ("no_sendmessage", "no_remotetrigger", "no_listagents", "no_response", "app_cap", "stale_id")
RELAY_ASK_RING = ("no_sendmessage", "no_remotetrigger", "no_listagents", "no_response", "app_cap")
RELAY_SILENT_S = 60                                        # R1b: an offer with no report after 60 s, mail unread, becomes a relay request
SAME_SESSION_S = 60                                        # nb 6: no second ring to a recipient whose earlier mail was offered under 60 s ago
REWAKE_AT_S = ((1, 900), (2, 3600))                        # R2: rewake 1 at 15 min, rewake 2 (plus the sender line) at 1 h; nothing after
WAKE_SCAN_EVERY_S = 15                                     # the R1b / rewake scan runs inside claim_relay at most this often
WOKEN_WINDOW_S = 86400                                     # R2 reads woken mail from the last 24 h of offers
_SKIP_CODE = re.compile(r"\s*([a-z_]+)")
NUDGE_KINDS = ("task", "question", "review", "handoff", "result")   # notice / plain message start no wake
TERMINAL = ("completed", "failed", "canceled", "rejected")
TRIG_NOT_URGENT = "Do not skip this step because the mail is not urgent."   # 0.22.2 (A-0ce70 item 1): fixed text, never from mail
# 0.22.2 (A-0ce70 item 3): a relaying agent's report must carry evidence in its reason: an HTTP status and a run session id. Self-reported.
_EV_HTTP = re.compile(r"(?<![0-9A-Za-z])([1-5][0-9]{2})(?![0-9A-Za-z])")   # acceptance of a relayer's evidence (unchanged); the status VALUE is fire_statuses
_EV_SESSION = re.compile(r"(?<![0-9A-Za-z_])((?:cse|session)_[0-9A-Za-z]{6,64})(?![0-9A-Za-z_])")
# 0.22.3 (A-8a3da item 4): a relayed nudge's evidence is the SendMessage result: its delivery state and the returned message UUID.
_EV_DELIVERY = re.compile(r"delivery:\s*([a-z_]{3,20})", re.I)
_EV_MSGID = re.compile(r"message_id:\s*([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})(?![0-9A-Za-z-])")
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
    rr = db.get("relay_roles")      # 0.22.3b: operator-owned (never the agent-writable config.json); the steward is never a claimer
    out["relay_roles"] = [r for r in ([H.cr(x) for x in rr if isinstance(x, str)] if isinstance(rr, list) else list(RELAY_ROLES))
                          if r not in RELAY_NEVER]
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
TRIG_RE = re.compile(r"^trig_[A-Za-z0-9]{8,64}\Z")
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


WAKE_KINDS = ("recurring", "run_once")
WAKE_PROMPT = ("Ball wake for role:{role}. Peek at the role's mail (as a role-less helper, never register the role), leave one line in the "
               "role's mail saying a wake arrived, and stop.")   # 0.22.5 (item 3): the only prompt a wake trigger may carry; the role slug is the only variable
_WAKE_ROLE_RE = re.compile(r"^[a-z][a-z0-9-]{0,39}\Z")
# 0.24.0 (A-b2950 item 13, D-8ef51): the new wake form. A one-shot routine dated at least a year out, re-fired by `run`, bound to the
# holder's chat, whose prompt is exactly this text. It replaces WAKE_PROMPT for new registrations; legacy pins keep working until stale.
WAKE_PROMPT_V2 = "Run harness_inbox."
FIRE_FIELDS = ('a fire of a registered routine reports the run result\'s fields, copied: prompt "<prompt as returned>", '
               'enabled <true|false>, session "<bound session id>"')
_BODY_RE = re.compile(r"\b(body|text)\b", re.I)
TRIGGER_DO_LINES = False                  # 0.27.1: no RemoteTrigger Do-line goes to any agent; wake changes go to role:automations or the operator (envoy, 11/22)
WAKE_CLAIM_S = 300                       # a verify or disable Do-line goes to another relay holder after 5 min with no report
# 0.23.0 (A-08480 item 3 gaps 1 and 2): what counts as the status of a fire. (a) the 3-digit number after an HTTP form (HTTP 404, HTTP <404>,
# HTTP status 404, HTTP error 500, HTTP code 403, http_status=404, HTTP-404, HTTP/2 404, HTTP/1.1 200, HTTPS 404); (b) a 4xx or 5xx number followed by a
# status phrase. Any other number (took 350 ms, woke after 120 s) is not a status.
_FIRE_HTTP = re.compile(r"\bHTTPS?(?:/[0-9](?:\.[0-9])?)?(?:[\s_:=<-]*(?:status|error|code))?[\s_:=<-]*([1-5][0-9]{2})(?![0-9])", re.I)
_FIRE_PHRASE = re.compile(r"(?<![0-9A-Za-z])([45][0-9]{2})\s*(?:not found|server error|bad request|forbidden|unauthorized|timeout|error)\b", re.I)


# 0.24.0 (A-b2950 item 3): a fire report has one format. Its reason starts with `HTTP ` and a 3-digit status (leading whitespace trimmed,
# anchored at the start); anything else is refused and the pin stays. One function, shared with the relay and wake build (relay spec v3.1,
# C12 and W8). The free-text reader below (fire_statuses / fire_spends) stays only to replay events written before 0.24.0 (no `status`).
_FIRE_FMT = re.compile(r"HTTP ([1-5][0-9]{2})(?![0-9])")
FIRE_FORMAT = "reason must start with HTTP <3 digits>"
FIRE_GONE = (401, 403, 404, 410)        # the routine is gone or no longer ours: the pin goes stale at once
FIRE_GONE_TEXT = "persistent_session_gone"   # 0.24.2 (RD-0d97a): HTTP 400 with this text in the reason: the routine's bound session is gone, stale at once
FIRE_STALE_AFTER = 3                    # any other failed status (408, 429, 5xx, ...): stale after 3 failed fires in a row for the role


def fire_status(reason):
    """The status of a fire report as an int, or None when the reason does not start with `HTTP <3 digits>`."""
    m = _FIRE_FMT.match(str(reason or "").lstrip())
    return int(m.group(1)) if m else None


def fire_effect(status):
    """-> "woken" (any 2xx: spends a run_once pin, resets the failure count), "gone" (404, 410, 401, 403: stale at once) or "failed"
    (any other status: spends nothing, counts toward FIRE_STALE_AFTER)."""
    if 200 <= int(status) <= 299:
        return "woken"
    return "gone" if int(status) in FIRE_GONE else "failed"


def fire_is_gone(status, reason):
    """0.24.2 (RD-0d97a): a fire that is gone for good: a FIRE_GONE status, or HTTP 400 whose reason names persistent_session_gone."""
    return int(status) in FIRE_GONE or (int(status) == 400 and FIRE_GONE_TEXT in str(reason or ""))


def fire_stale(st, trig, role, after_seq):
    """The status that made a pin stale through its reported fires after `after_seq`, or None. Read from the State fold (State.trig_fires):
    fires through this trigger for this role, in report order. A 2xx resets the count of failed fires in a row. 0.24.2: held and skipped
    reports count too; HTTP 400 persistent_session_gone is stale at once."""
    fails = 0
    for sq, r, status, gone in (getattr(st, "trig_fires", None) or {}).get(trig, ()):
        if sq <= after_seq or (r and role and r != role):
            continue
        eff = "gone" if gone else fire_effect(status)
        if eff == "woken":
            fails = 0
        elif eff == "gone":
            return status
        else:
            fails += 1
            if fails >= FIRE_STALE_AFTER:
                return status
    return None


def fire_statuses(reason):
    """The statuses a fire report names, in order of position; the reason is cut to 80 characters first. 0.24.0: replay of old events only."""
    s = str(reason or "")[:80]
    found = {}
    for rx in (_FIRE_HTTP, _FIRE_PHRASE):
        for m in rx.finditer(s):
            found.setdefault(m.start(1), m.group(1))
    return [found[k] for k in sorted(found)]


def fire_spends(statuses):
    """A `woke` spends a run_once pin when any status is 200 or none is named; it stays unspent only when statuses are named and none is 200."""
    return not statuses or "200" in statuses


def result_spends(d):
    """For one nudge.result `woke`: 0.24.0 its parsed `status` (any 2xx spends); an event written before 0.24.0 (no `status`): the relayer's
    evidence status if it carries one, else the sender's reason."""
    if isinstance(d.get("status"), int):
        return fire_effect(d["status"]) == "woken"
    ev = d.get("evidence") or {}
    if isinstance(ev.get("statuses"), list):          # 0.23.0 relayer evidence
        return fire_spends([str(x) for x in ev["statuses"]])
    if ev.get("http") is not None:                    # relayer evidence written before 0.23.0
        return fire_spends([str(ev["http"])])
    return fire_spends(fire_statuses(d.get("reason")))


def wake_prompt(role):
    return WAKE_PROMPT.format(role=role)


def wake_prompt_ok(role, prompt):
    """Equality with the template for this role (not a word list): any extra word, name or id is a different text. Self-reported by the
    requester; the operator's comparison in the cloud UI is the real control."""
    return isinstance(role, str) and bool(_WAKE_ROLE_RE.match(role)) and isinstance(prompt, str) and prompt.strip() == wake_prompt(role)


def pin_entry(v):
    """A wake.pinned entry as {trigger, kind, holder, prompt_sha, legacy}, or None. A plain `trig_...` string is a pin from before 0.22.5:
    recurring, bound to no holder, prompt never checked (legacy)."""
    if isinstance(v, str):
        return {"trigger": v, "kind": "recurring", "holder": None, "prompt_sha": None, "legacy": True} if TRIG_RE.match(v) else None
    if isinstance(v, dict) and isinstance(v.get("trigger"), str) and TRIG_RE.match(v["trigger"]) and v.get("kind") in WAKE_KINDS:
        return {"trigger": v["trigger"], "kind": v["kind"], "holder": v.get("holder") or None, "prompt_sha": v.get("prompt_sha"), "legacy": False}
    return None


def _spent(st, trig, after_seq):
    """True when a run_once pin's trigger has a REPORTED fire after the pin: a nudge.result outcome woke whose message was offered through this
    trigger (nudge.trigwake) and that spends by fire_spends. 0.23.0 (gap 4): read from the State fold (State.trig_spent), never from the ledger
    tail, so a spent pin stays spent however long the ledger grows. Self-reported evidence."""
    return any(sq > after_seq for sq in (getattr(st, "trig_spent", None) or {}).get(trig, ()))


def wake_pin_state(st, role, h=None):
    """-> (entry or None, state): ok | stale (the pin's holder is not the role's current holder; 0.24.0 or its fires failed, fire_stale) |
    spent (run_once, fire reported with 2xx)."""
    pin = getattr(st, "wake_pin", None) or {}
    ent = pin.get("entries") if isinstance(pin, dict) else None
    e = pin_entry(ent.get(role)) if isinstance(ent, dict) and role else None
    if not e:
        return None, "none"
    if e["holder"] and e["holder"] != st.role_holder(role):
        return e, "stale"
    try:
        if fire_stale(st, e["trigger"], role, int(pin.get("seq") or 0)) is not None:
            return e, "stale"
    except Exception:
        pass
    if e["kind"] == "run_once" and h is not None:
        try:
            if _spent(st, e["trigger"], int(pin.get("seq") or 0)):
                return e, "spent"
        except Exception:
            pass
    return e, "ok"


def reg_state(st, role):
    """0.24.0 (item 13): the role's registered routine -> (entry or None, state). state is the folded one (pending, verified, rejected,
    stale), or stale when a verified routine's fires failed (fire_stale after the verify). 0.24.1: the wake belongs to the role, so a
    holder change never stales it."""
    import harness as H
    e = (getattr(st, "wake_reg", None) or {}).get(H.cr(role or ""))
    if not e:
        return None, "none"
    if e["state"] == "verified":
        try:
            if fire_stale(st, e["trigger"], role, int(e.get("vseq") or 0)) is not None:
                return e, "stale"
        except Exception:
            pass
    return e, e["state"]


def trigger_dead(st, trig):
    """0.25.0 (item 22): True when no relay, verify or (see wake_do) disable line should be issued for this routine: it is in wake_disabled,
    its registration was rejected or went stale (reg_state: a VERIFIED routine whose reported fires after the verify failed, by any
    reporter), or, for a routine that is not the role's current one (a replaced routine, a legacy pin), fire_stale after the seq of its
    latest wake.registered or wake.verified (the pin's seq for a legacy pin). A pending routine is never dead by fires. The one dead-check:
    it reuses reg_state and fire_stale."""
    if not trig:
        return False
    if trig in (getattr(st, "wake_disabled", None) or set()):
        return True
    for role, e in (getattr(st, "wake_reg", None) or {}).items():
        if e.get("trigger") == trig:
            return reg_state(st, role)[1] in ("rejected", "stale")
    seq = (getattr(st, "wake_seq", None) or {}).get(trig)
    if seq is None:
        pin = getattr(st, "wake_pin", None) or {}
        ent = pin.get("entries") if isinstance(pin, dict) else None
        if isinstance(ent, dict) and any((pin_entry(v) or {}).get("trigger") == trig for v in ent.values()):
            seq = pin.get("seq")
    try:
        return fire_stale(st, trig, None, int(seq or 0)) is not None
    except Exception:
        return False


def last_fire_status(st, trig):
    """0.25.0 (item 22): the status of the trigger's last reported fire, or None."""
    f = (getattr(st, "trig_fires", None) or {}).get(trig) or ()
    return f[-1][2] if f else None


def registered_trigger(st, trig):
    """The role whose VERIFIED routine is `trig`, or None (a legacy pin, or a routine not verified yet)."""
    for role, e in (getattr(st, "wake_reg", None) or {}).items():
        if e.get("trigger") == trig and e.get("state") in ("verified", "stale"):
            return role
    return None


def wake_to_disable(st):
    """Triggers a relay holder should disable: a verified routine a different trigger replaced, until wake.disabled. 0.24.1: never the
    role's current verified routine, whoever holds the role. -> {trigger: role}"""
    out = dict(getattr(st, "wake_old", None) or {})
    gone = getattr(st, "wake_disabled", None) or set()
    return {t: r for t, r in out.items() if t not in gone}


def _wake_trigger(st, role, h=None):
    """The role's wake trigger id, or None. 0.24.0 (item 13): its verified routine first (registered by the holder, verified by a relay
    holder; no operator step). Otherwise a legacy wake.pinned pin until it goes stale (holder changed, fires failed) or is spent.
    Fix round 1 (critic m-5e2216478366): moving to the new form never costs a working wake. A pending or rejected registration falls
    back to the legacy pin; only a verified routine replaces it, and a verified routine that went stale keeps hiding it (a holder change
    stales the legacy pin too, and a changed routine must not be swapped for an older one silently)."""
    if not TRIGGER_DO_LINES:
        return None
    e, state = reg_state(st, role)
    if e and state == "verified":
        return None if trigger_dead(st, e["trigger"]) else e["trigger"]     # 0.25.0 (item 22): never a disabled routine
    if e and state == "stale":
        return None
    e, state = wake_pin_state(st, role, h)
    return e["trigger"] if e and state == "ok" and not trigger_dead(st, e["trigger"]) else None


def wake_repin_lines(h, st, aid):
    """Sync 'Changed' lines: which role needs a re-pin because its pin is stale or spent. Shown to the role's holder, the envoy and the curator."""
    out = []
    try:
        mine = st.role_of(aid)
        pin = getattr(st, "wake_pin", None) or {}
        for role in sorted((pin.get("entries") or {}) if isinstance(pin, dict) else {}):
            if mine not in (role, "envoy", "curator"):
                continue
            e, state = wake_pin_state(st, role, h)
            if state in ("stale", "spent"):
                why = "its holder changed" if state == "stale" else "its run-once trigger already fired"
                if state == "stale" and not (e["holder"] and e["holder"] != st.role_holder(role)):
                    why = "its trigger failed with HTTP %s" % fire_stale(st, e["trigger"], role, int(pin.get("seq") or 0))
                out.append(f"wake pin for role:{role} is {state} ({why}): left out of nudges until its holder registers a routine "
                           f"(harness_admin op=wake_register)")
    except Exception:
        pass
    return out[:4]


def wake_reg_lines(h, st, aid):
    """0.24.0 (item 13): sync 'Changed' lines for the role's holder: its routine was rejected (and why) or went stale. No operator step."""
    out = []
    try:
        role = st.role_of(aid)
        e, state = reg_state(st, role) if role else (None, "none")
        if e and state in ("rejected", "stale") and st.role_holder(role) == aid:
            why = e.get("why") or "a fire failed"
            out.append(f"wake routine for role:{role} is {state} ({why}): fix it or create a new one, then harness_admin op=wake_register")
        elif e and state == "verified" and st.role_holder(role) == aid:     # 0.24.1: a new holder sees which chat the routine wakes
            own = ((st.agents.get(aid) or {}).get("host_session_id") or "")
            if own.startswith("local_") or role in RELAY_NEVER:     # a Code holder or the steward never registers a routine: no line (as wake_register_do)
                return out
            if (own and own != e.get("session")) or (not own and e["holder"] != aid):
                out.append(f"wake routine for role:{role} is bound to session {e.get('session')}: if that is not this chat, create a routine "
                           f"for this chat and harness_admin op=wake_register (the same trigger and session keeps it)")
    except Exception:
        pass
    return out


def wake_register_do(st, aid):
    """0.24.0 (item 13): the restore/sync Do-line for a Cowork role holder (no local_ id) with no pending or verified routine of its own."""
    try:
        role = st.role_of(aid)
        a = st.agents.get(aid) or {}
        if not role or role in RELAY_NEVER or st.role_holder(role) != aid or (a.get("host_session_id") or "").startswith("local_"):
            return None
        e, state = reg_state(st, role)
        if e and (state == "verified" or (e["holder"] == aid and state == "pending")):     # 0.24.1: the role's verified routine is enough
            return None
        return (f"☎ wake routine: create one with your routine tool (prompt exactly {WAKE_PROMPT_V2!r}, a one-shot dated at least 1 year "
                "ahead, bound to this chat), then harness_admin op=wake_register args={trigger, session} with the bound session id the "
                "create result shows")
    except Exception:
        return None


def proctor_lines(h, st, aid, since=0):
    """0.23.0 (A-08480 item 2): sync 'Changed' lines. The proctor holder sees its queue; anyone sees a count of case events the replay
    rules did not apply, only when a new one appeared since its previous sync (never repeated)."""
    out = []
    try:
        cases = getattr(st, "cases", None) or {}
        if st.role_of(aid) == "proctor":
            op = [c for c in cases.values() if not c["closed"]]
            sev = lambda s_: sum(1 for c in op if c["severity"] == s_)
            now = getattr(st, "now", time.time())
            samples = sum(1 for sm in (getattr(st, "case_samples", None) or {}).values() if sm["expires_t"] > now)
            out.append(f"proctor queue: {len(op)} open (S0 {sev('S0')}, S1 {sev('S1')}); shadow {'on' if st.shadow_on() else 'off'}; "
                       f"samples open {samples}")
        rej = getattr(st, "case_rejected", None) or []
        if rej and rej[-1] > (since or 0):
            out.append(f"rejected case events: {len(rej)} (newest seq {rej[-1]})")
    except Exception:
        pass
    return out


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


def _is_ask(x):
    """A mail that asks for an answer: an answer kind (task, question, review) or any mail sent with expects_reply."""
    return bool(x) and (x.get("kind") in RING_KINDS or bool(x.get("expects_reply")))


CLOSING_KINDS = ("result", "handoff")      # round 6 (item 1): only these close an ask for the wake backstop; an acknowledgement never does


def _ask_open(st, x, m):
    """Round 4 (b), round 6 (item 1): is the ask `x` still open when mail `m` (the reply that cites it) is sent? Not when its task is finished, when
    the replier's role dismissed it (owed_close), or when the sender of `m` (its lineage) already sent a result or handoff that answers it: on x's
    thread after x, or by an answering ref. A message or notice ("on it") never closes it. The owed list keeps its older rule (any later message of
    the agent on the thread clears it for that agent), so the two differ on purpose: an ack stops the nagging of the replier, not the asker's wait."""
    try:
        xid = x.get("id")
        if (st.tasks.get(xid) or {}).get("state") in TERMINAL:
            return False
        frm = set(st.lineage(m.get("from"))) | {m.get("from")}
        if owed_closed(st, xid, frm, st.role_of(m.get("from"))):
            return False
        lo, hi = x.get("seq") or 0, m.get("seq") or 0
        for y_ in (st.threads.get(x.get("thread")) or {}).get("messages") or []:
            y = st.messages.get(y_) or {}
            if y_ != m.get("id") and lo < (y.get("seq") or 0) < hi and y.get("from") in frm and y.get("kind") in CLOSING_KINDS:
                return False
        for y_ in st.order:
            y = st.messages[y_]
            if y_ != m.get("id") and lo < (y.get("seq") or 0) < hi and y.get("from") in frm and y.get("kind") in CLOSING_KINDS \
                    and _answers(st, y, x, xid):
                return False
    except Exception:
        return True
    return True


def _reply_to_open_ask(st, m, rid=None):
    """Round 6 (item 2): is `m` a reply_to an ask that is still open and was sent by recipient `rid` (or by any recipient when rid is None)?"""
    try:
        x = st.messages.get(m.get("parent") or "")
        if not x or not _is_ask(x):
            return False
        if rid is not None:
            lin = set(st.lineage(rid)) | {rid}
        else:
            cand = list(m.get("to_resolved") or [])
            for tgt in m.get("to") or []:
                if isinstance(tgt, str) and tgt.startswith("role:") and st.role_holder(tgt[5:]):
                    cand.append(st.role_holder(tgt[5:]))
            lin = set()
            for c in cand:
                lin |= set(st.lineage(c)) | {c}
        asker_role = (st.agents.get(x.get("from")) or {}).get("role")        # round 7: the asker left and the role is vacant: still a reply to its ask
        by_role = rid is None and asker_role and f"role:{asker_role}" in (m.get("to") or [])
        return (x.get("from") in lin or bool(by_role)) and _ask_open(st, x, m)
    except Exception:
        return False


def _eff_kind(st, m, rid=None):
    """Round 6 (item 2): a plain `message` sent as a reply_to an open ask counts as a result for the doorbell (nudge, caps, backstop).
    Round 7 (gap 1): any mail of a non-answer kind sent with expects_reply is an ask: it counts as a question (same ring, relay and rewake)."""
    k = (m or {}).get("kind")
    if k in ("message", "notice", "result", "handoff") and (m or {}).get("expects_reply") and (m or {}).get("from") not in ("human", "operator"):
        return "question"
    return "result" if k == "message" and _reply_to_open_ask(st, m, rid) else k


def _waiting(st, m, rid):
    """Raw read F3 (round 3 F5): the recipient `rid` is waiting on mail `m`: its lineage sent an ask (an answer kind, or a mail with expects_reply)
    on the same thread earlier, or `m` answers an ask of its by `reply_to` or by a ref on another thread."""
    try:
        lin = set(st.lineage(rid)) | {rid}
        for x_ in (st.threads.get(m.get("thread")) or {}).get("messages") or []:
            x = st.messages.get(x_) or {}
            if x.get("from") in lin and _is_ask(x) and (x.get("seq") or 0) < (m.get("seq") or 0) and _ask_open(st, x, m):      # round 5
                return True
        # refs are stored as shared-file keys, so a message id arrives as "<home folder>/m-...": the last path part is the id
        for r_ in [m.get("parent")] + [str(r).rsplit("/", 1)[-1] for r in (m.get("refs") or [])]:
            x = st.messages.get(r_) if isinstance(r_, str) else None
            if x and x.get("from") in lin and _is_ask(x) and _ask_open(st, x, m):      # round 4 (b): an answered ask cannot ring a cold holder
                return True
    except Exception:
        return False
    return False


def _waiting_role(st, m, role):
    """Round 7 follow-up: does mail `m` answer an open ask sent by an agent that held `role` (the role may be vacant now)?"""
    try:
        cands = [m.get("parent")] + [str(r).rsplit("/", 1)[-1] for r in (m.get("refs") or [])]
        cands += list((st.threads.get(m.get("thread")) or {}).get("messages") or [])
        for r_ in cands:
            x = st.messages.get(r_) if isinstance(r_, str) else None
            if x and x.get("id") != m.get("id") and (x.get("seq") or 0) < (m.get("seq") or 0) and _is_ask(x) \
                    and (st.agents.get(x.get("from")) or {}).get("role") == role and _ask_open(st, x, m):
                return True
    except Exception:
        return False
    return False


def _covered(h, st, m, rid):
    """Raw read F3 (0.26.0): does the safety net of the three answer kinds (the cap relay, the scan's silent-sender relay and rewakes) cover this
    message for recipient `rid`? task, question and review always. A result or handoff when the recipient is waiting on that thread or its role
    has a verified wake routine: with the ladder gone a reply is otherwise heard only at the asker's next prompt."""
    k = _eff_kind(st, m, rid)
    if k in RING_KINDS:
        return True
    if k not in ("result", "handoff"):
        return False
    try:
        role = st.role_of(rid)
        if role and _wake_trigger(st, role, h):
            return True
    except Exception:
        return False
    return _waiting(st, m, rid)


def _route(h, st, rid, a, kind, now, wake_ok=True):
    """0.22.0 (item 6, D-3e5e7): the ROLE is the address and the harness resolves it; the only thing a sender ever gets is the holder's
    own app session id. -> (hid or None, mail-only reason or None). 0.24.0 (item 5): wake_ok=False (R2) closes the cold id wake."""
    if not st.role_of(rid):
        return None, "no role: mail only"
    if not (a.get("host_session_id") or "").startswith("local_"):
        return None, "no app session id: mail only"
    if not _same_machine(a, st):
        return None, "holder on another machine: mail only"
    hid = _pick_id(h, st, rid, kind, now, wake_ok)
    if hid:
        return hid, None
    if kind == "result":
        return None, "result to a cold holder: mail only"
    return None, "id route closed by a stale mark or the cold-wake cap: mail only"


def _do_one(hid, trig, line, mid, rewake=None, fields=False):
    """0.22.0 (item 6): one exact address, no name, no title, no ListAgents row check. -> the Do-line text, or None (mail only).
    0.24.0 (item 5): `rewake` (1 or 2) builds the rewake form: the same steps, no report (the message's result slot is already filled)."""
    rep = (' No report is needed for a rewake.' if rewake else
           f' harness_admin op=nudge_result args={{msg_id:"{mid}",outcome:delivered|held|skipped,reason}}.')
    parts = []
    if hid:
        parts.append(f'Do: SendMessage to {hid}: {line} (fixed fields only, no subject or body). If the send fails (stale, archived or deleted '
                     f'session) do not retry it: report skipped with reason stale_id; the mail waits. No SendMessage tool here (a Cowork or '
                     f'cloud chat): report skipped with reason no_sendmessage. If the app refuses the send (its cross-session cap): report '
                     f'skipped with reason app_cap; a relay rings for you.'
                     + (' If it did not deliver, run the RemoteTrigger step next, then report once:' if trig else ' Then report:') + rep)
    if trig:
        parts.append(f'Do: RemoteTrigger action=run trigger_id={trig} ('
                     + ('only if the SendMessage step above did not deliver or the session holds it; ' if hid else '')
                     + 'load the tool with ToolSearch select:RemoteTrigger if it is deferred; it runs under the Claude subscription, never '
                     'with an API key; no other trigger tool; run with no body). ' + TRIG_NOT_URGENT
                     + ((' Run with no body.' + ('' if hid else rep)) if rewake else
                        (' Then report outcome woke' + (' instead of skipped.' if hid else ':' + rep)
                         + ' Start the reason with "HTTP <status>" of the run (its final status).'
                         + (' Add the run result\'s fields, copied, never computed: prompt:"<prompt as returned, at most 80 characters>",'
                            'enabled:<true|false>,session:"<bound session id as returned>".' if fields else '')
                         + ' No response at all (tool error, network down): report skipped with reason no_response; a relay rings for you.'
                         + ' No RemoteTrigger tool here: skip that step with reason no_remotetrigger.')))
    return " ; ".join(parts) or None


def _do_many(ring, line, mid, st):
    """0.26.0 (item 12): the Do-line text of a send with several recipients, given ONCE. One recipient: _do_one as before. Several that all
    take the same steps (all by session id, all by trigger, or all both): one SendMessage step naming every id (one send each, same text)
    and one RemoteTrigger step naming every distinct trigger. Recipients of different shapes keep their own steps, identical ones merged.
    Round 3 (F7): with two or more session ids the report is one nudge_result per recipient (to = that recipient's session id), so one
    recipient's refusal still asks for its relay after another's delivery was reported."""
    items = [(x, g) for _, _, x, g in ring]
    fld = lambda g: bool(g and registered_trigger(st, g))
    if len(items) == 1:
        return _do_one(items[0][0], items[0][1], line, mid, fields=fld(items[0][1]))
    shapes = {(bool(x), bool(g)) for x, g in items}
    if len(shapes) == 1:
        hids = list(dict.fromkeys(x for x, _ in items if x))
        trigs = list(dict.fromkeys(g for _, g in items if g))
        out = _do_one(" and ".join(hids) + (" (one send each, the same text)" if len(hids) > 1 else "") if hids else None,
                      (paired_trigs(items) if hids and trigs else " and ".join(trigs)) if trigs else None, line, mid, fields=any(fld(g) for g in trigs))
    else:       # 0.27.3 B (F6): one step set per route shape, not one per child (wake_batch.group_by_shape)
        out = " ; ".join(_do_one(" and ".join(b["hids"]) + (" (one send each, the same text)" if len(b["hids"]) > 1 else "") if b["hids"] else None,
                                 (paired_trigs([(x, g) for x, g in items if x in b["hids"] and g in b["trigs"]]) if b["hids"] and b["trigs"]
                                  else " and ".join(b["trigs"])) if b["trigs"] else None, line, mid, fields=any(fld(t) for t in b["trigs"]))
                         for b in group_by_shape(items))
    keys = list(dict.fromkeys(x if x else str(rid)[:8] for rid, _a, x, _g in ring))
    if out and len(keys) > 1:
        out = out.replace(f'args={{msg_id:"{mid}",outcome:', f'args={{msg_id:"{mid}",to:"<one of the to values>",outcome:')
        out += " One report per recipient, each with its own to (" + ", ".join(keys) + "): a send that went through is reported delivered, one the app refused is reported skipped with reason app_cap."
    return out


def _pick_id(h, st, rid, kind, now, wake_ok=True):
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
    if kind in RING_KINDS:
        if not wake_ok:            # 0.24.0 (item 5, R2): a woken mail to this role is unread; R2 replaces the 30-min cold-wake slot
            return None
    elif any(rid in (e["data"].get("to") or []) for e in _recent(h, now - ID_WAKE_MIN * 60, ("nudge.idwake",))):
        return None
    try:
        h.store.append("nudge.idwake", "system", {"to": [rid], "host_session_id": hid})
    except Exception:
        return None
    return hid


def _error_miss(h, r):
    """Round 7 C6c, C6d: the doorbell failed while handling a send. Best effort: every covered recipient counts a nudge.miss with the reason
    doorbell_error. Cover is judged by the same rule as the normal path (_covered, or _eff_kind and _waiting_role for a role with no holder); when the
    judgement itself fails the mail counts as covered. Never raises."""
    try:
        st = h.state()
        m = st.messages.get((r or {}).get("id") or "") or {}
        if not m or m.get("from") in ("human", "operator") or is_system_sender(m.get("from")):
            return
        rcpts = [x for x in (m.get("to_resolved") or []) if x not in ("human", "operator") and x != m.get("from")]
        roles = [t[5:] for t in (m.get("to") or []) if isinstance(t, str) and t.startswith("role:")]
        for rid in dict.fromkeys(rcpts):
            try:
                cov = bool(_covered(h, st, m, rid))
            except Exception:
                cov = True
            if cov:
                _miss(h, m["id"], rid, m.get("from"), "doorbell_error")
        for role in dict.fromkeys(roles):
            hol, key = None, "role:" + role
            try:
                hol = st.role_holder(role)
                if hol and hol in rcpts:
                    continue                        # already judged as the holder's own entry
                if hol:                             # a live holder: the same _covered rule as the normal path, recorded under the holder
                    cov, key = bool(_covered(h, st, m, hol)), hol
                else:                               # a vacant role: judged from the message and the role's earlier asks
                    eff = _eff_kind(st, m)
                    cov = eff in RING_KINDS or (eff in ("result", "handoff") and _waiting_role(st, m, role))
            except Exception:
                cov = True
            if cov:
                _miss(h, m["id"], key, m.get("from"), "doorbell_error")
    except Exception:
        pass


def _outcomes(h, st, out):
    """Round 7 C6d: the per-recipient outcome of a send, built from the records actually written for the message (nudge.offered, nudge.skipped,
    nudge.relay_offer, nudge.miss) plus the recipients named as mail only. -> [{to, key, outcome, reasons}], in the order the records were written."""
    mid = (out or {}).get("id")
    if not mid:
        return []
    names = lambda k: st.name_role(k) if k in st.agents else str(k)
    by = {}

    def add(key, outcome, reason=None):
        e = by.setdefault(key, {"to": names(key), "key": key, "outcome": None, "reasons": []})
        rank = {"ring": 5, "relay requested": 4, "miss": 3, "held": 2, "skipped": 1, "mail only": 0}
        if e["outcome"] is None or rank[outcome] > rank[e["outcome"]]:
            e["outcome"] = outcome
        if reason and reason not in e["reasons"]:
            e["reasons"].append(reason)

    for e in _tail(h, needle=b'"nudge.'):
        d = e.get("data") or {}
        if (d.get("msg") or d.get("msg_id")) != mid:
            continue
        t = e.get("type")
        if t == "nudge.offered":
            for rid in d.get("to") or []:
                add(rid, "ring")
        elif t == "nudge.skipped":
            for rid in d.get("to") or []:
                rs = str(d.get("reason") or "")
                add(rid, "held" if rs.startswith(HELD_REASONS) else "skipped", rs)
        elif t == "nudge.relay_offer" and d.get("rewake") in (None, "extra"):
            add(d.get("to"), "relay requested", str(d.get("reason") or ""))
        elif t == "nudge.miss":
            add(d.get("to"), "miss", str(d.get("reason") or ""))
    for x in (out.get("nudge_mail_only") or []):
        if x.get("key") not in by:
            add(x.get("key") or x.get("to"), "mail only", str(x.get("reason") or ""))
    return list(by.values())


def _render_outcomes(h, out):
    """Round 7 C6d: render the send result from _outcomes: `nudge_outcomes` lists every recipient; a recipient with a record that the older fields do
    not name is added to `nudge_skipped`; with no ring and no text, `nudge` carries the first miss. Never raises."""
    try:
        if not isinstance(out, dict) or not out.get("id"):
            return out
        st = h.state()
        m = st.messages.get(out["id"]) or {}
        if not m or m.get("from") in ("human", "operator") or is_system_sender(m.get("from")):
            return out
        outs = _outcomes(h, st, out)
        if not outs:
            return out
        out = dict(out, nudge_outcomes=outs)
        named = {x.get("to") for x in (out.get("nudge_skipped") or [])} | {x.get("to") for x in (out.get("nudge_mail_only") or [])}
        holders = set((out.get("holder") or {}).keys())
        add = []
        for e in outs:
            if e["outcome"] in ("ring", "mail only"):
                continue
            label = e["to"]
            soby = (st.agents.get(e["key"]) or {}).get("sobriquet")          # the older fields name a recipient by sobriquet or by "Name (role)"
            if label in named or (soby and soby in named) or (str(e["key"]).startswith("role:") and str(e["key"])[5:] in holders):
                continue
            reason = "; ".join(e["reasons"]) or e["outcome"]
            add.append({"to": label, "reason": reason, "relay": ("miss (%s)" % reason) if e["outcome"] == "miss" else e["outcome"]})
        if add:
            out["nudge_skipped"] = list(out.get("nudge_skipped") or []) + add
        if "nudge" not in out and not any(e["outcome"] == "ring" for e in outs):
            miss = [e for e in outs if e["outcome"] == "miss"]
            if miss:
                out["nudge"] = "miss (%s)" % (miss[0]["reasons"][0] if miss[0]["reasons"] else "miss")
        return out
    except Exception:
        return out


def attach_nudge(h, sender_ref, result):
    """Add `nudge` (and `skipped`) to a send result. Never raises; a failure leaves the result as it was.
    0.24.0 (item 11): plus `holder` {role: state} for each role recipient of a kind that can ring. Round 7 (C6d): a failure inside the doorbell counts a
    doorbell_error miss for covered recipients, and the result is rendered from the records written for the message (_render_outcomes)."""
    out = result
    try:
        out = _attach(h, sender_ref, result)
    except Exception:
        _error_miss(h, result)          # a failure is never silent for covered mail
        return _render_outcomes(h, result)
    try:
        out = _attach_holder(h, out)
    except Exception:
        if not isinstance(out.get("nudge"), dict) and not out.get("nudge_skipped"):     # a ring or a skip record already carries the mail
            _error_miss(h, out)
    return _render_outcomes(h, out)


# ---------------------------------------------------------------- 0.24.0 (A-b2950 item 16): wake measures

def _carrier(d, offer):
    """How a woken result rang: sendmessage or remotetrigger, with relay: in front when the reporter was not the sender."""
    c = "remotetrigger" if d.get("outcome") == "woke" else "sendmessage"
    return ("relay:" if d.get("by") and d.get("by") != (offer or {}).get("from") else "") + c


def measure_reads(h, aid, ids, now=None):
    """Called right after a message.read. For each read message that was rung or woken (a woken result: delivered, held, or a 2xx woke)
    and has no wake.measure yet, write wake.measure {direction, msg_id, carrier, sent_t, fired_t, read_t, seconds_from_sent,
    seconds_from_fire, ctx_before}. Targets are judged from sent (v2, nb 5; sent_t is the offer, written in the send call); fired_t is the time of the woken report, the first moment
    the ledger knows the ring went out. ctx_before is the reader's last reported ctx (agent.synced) before the read; the weekly report
    takes the reader's next reported ctx after the read and records the difference as the tokens of the woken turn (a floor,
    self-reported). Only the recipient (or its lineage) counts as a read. Never raises. -> [msg ids measured]"""
    out = []
    try:
        now = float(now if now is not None else time.time())
        res = {}
        for e in _tail(h, needle=b'"nudge.result"'):          # cheap first: most reads have no ring behind them
            d = e.get("data") or {}
            if e.get("type") == "nudge.result" and d.get("msg_id") in ids:
                res.setdefault(d["msg_id"], (d, float(e.get("t") or 0)))
        want = [m for m in ids if m in res and _woken(res[m][0])]
        if not want:
            return out
        done = {(e.get("data") or {}).get("msg_id") for e in _tail(h, needle=b'"wake.measure"') if e.get("type") == "wake.measure"}
        want = [m for m in want if m not in done]
        if not want:
            return out
        st = h.state()
        mine = set(st.lineage(aid)) | {aid}
        offers = {}
        for e in _tail(h, needle=b'"nudge.offered"'):
            d = e.get("data") or {}
            if e.get("type") == "nudge.offered" and (d.get("msg_id") or d.get("msg")) in want:
                offers.setdefault(d.get("msg_id") or d.get("msg"), (d, float(e.get("t") or 0)))
        ctx_before = None
        for e in _tail(h, needle=b'"agent.synced"'):
            d = e.get("data") or {}
            if e.get("type") == "agent.synced" and e.get("actor") in mine and isinstance(d.get("ctx"), int):
                ctx_before = d["ctx"]
        for mid in want:
            r = res[mid]
            od, s_t = offers.get(mid) or ({}, 0.0)
            m = st.messages.get(mid) or {}
            if not mine & set(od.get("to") or []) and not any(st.role_holder(x) == aid for x in (od.get("roles") or []) if x):
                continue
            f_t = r[1]
            data = {"direction": direction(st, m.get("from") or od.get("from"), aid), "msg_id": mid, "carrier": _carrier(r[0], od),
                    "sent_t": round(s_t, 3) if s_t else None, "fired_t": round(f_t, 3), "read_t": round(now, 3),
                    "seconds_from_sent": round(now - s_t, 1) if s_t else None, "seconds_from_fire": round(now - f_t, 1),
                    "ctx_before": ctx_before, "reader": aid}

            def _once(store, mid=mid):
                for x in store.read_all()[-3000:]:
                    if x.get("type") == "wake.measure" and (x.get("data") or {}).get("msg_id") == mid:
                        raise _Already()
            try:
                h.store.append("wake.measure", "system", data, precheck=_once)
                out.append(mid)
            except _Already:
                pass
    except Exception:
        pass
    return out


# ---------------------------------------------------------------- 0.24.0 (A-b2950 item 11): holder state in the send reply

def _surface(a):
    """'Code' for a holder with a local_ app session id, else 'Cowork' (a bridged or cloud chat)."""
    return "Code" if (a.get("host_session_id") or "").startswith("local_") else "Cowork"


def direction(st, sender, rid):
    """Relay-wake spec section 1: 'Code to Code', 'Code to Cowork', 'Cowork to Code' or 'Cowork to Cowork'."""
    return "%s to %s" % (_surface(st.agents.get(sender) or {}), _surface(st.agents.get(rid) or {}))


def _when(t):
    return time.strftime("%Y-%m-%dT%H:%MZ", time.gmtime(float(t))) if t else "?"


def holder_state(h, st, role):
    """Relay-wake spec section 2. -> one of:
    live_ringable: a local_ id on this machine, not marked stale;
    live_wake_pin: a holder with no local_ id and a usable wake pin (item 13 makes this a verified routine);
    live_mail_only (<why>): the _route reasons (no app session id, another machine, a stale mark);
    handed_off since <ts> (capsule <path>): no live holder; the last holder handed off (agent.handed_off, folded per role);
    vacant: no holder and no handoff on record."""
    import harness as H
    hol = st.role_holder(role)
    a = st.agents.get(hol) or {}
    if not hol or a.get("handed_off"):
        ho = (getattr(st, "role_handoffs", None) or {}).get(H.cr(role))
        if ho:
            return "handed_off since %s (capsule %s)" % (_when(ho.get("t")), ho.get("capsule") or "none")
        return "vacant"
    hid = a.get("host_session_id") or ""
    if hid.startswith("local_"):
        if not _same_machine(a, st):
            return "live_mail_only (holder on another machine)"
        if hid in _stale_ids(h):
            return "live_mail_only (id route closed by a stale mark)"
        return "live_ringable"
    if _wake_trigger(st, role, h):
        return "live_wake_pin"
    return "live_mail_only (no app session id)"


def _attach_holder(h, r):
    """Add `holder` for the role recipients of a send whose kind can ring. With no ring at all and no live holder for any of them:
    nudge 'none (no live holder: queued for the next restore)'."""
    if not isinstance(r, dict) or not r.get("id"):
        return r
    st = h.state()
    m = st.messages.get(r["id"])
    if not m or m["from"] in ("human", "operator") or is_system_sender(m["from"]) or _eff_kind(st, m) not in NUDGE_KINDS:
        return r
    roles = [t[5:] for t in m.get("to") or [] if isinstance(t, str) and t.startswith("role:")]
    if not roles:
        return r
    hs = {role: holder_state(h, st, role) for role in dict.fromkeys(roles)}
    out = dict(r, holder=hs)
    vac = [role for role, v in hs.items() if v.startswith(("handed_off", "vacant"))]
    if vac:
        try:    # round 7 C6 and C6b (blocker 1): every vacant role of a covered mail counts its own miss, whatever the other recipients did
            eff = _eff_kind(st, m)
            covered = eff in RING_KINDS or (eff in ("result", "handoff") and any(_waiting_role(st, m, role) for role in vac))
            if covered:
                for role in vac:
                    try:
                        _miss(h, r["id"], "role:" + role, m["from"], "no_holder")
                    except Exception:     # class F: a failure here (a ledger lock timeout) after another recipient rang must not lose this role's miss
                        try:
                            _miss(h, r["id"], "role:" + role, m["from"], "doorbell_error")
                        except Exception:
                            pass
        except Exception:
            covered = False
        if "nudge" not in out and not out.get("nudge_skipped") and len(vac) == len(hs):
            out["nudge"] = "none (no live holder: queued for the next restore" + ("; miss counted)" if covered else ")")
    return out


def _pick_trig(h, st, rid, mid, now, kind=None, wake_ok=True):
    """0.21.2 (item 1): a role with a pinned `trig_...` wake trigger gets a RemoteTrigger Do-line, at most once per role AND once per trigger
    id per 10 min summed over all senders (critic B2: roles pointed at one routine share its slot). Event nudge.trigwake, counted apart
    from offers and written when OFFERED, since the harness cannot see whether the sender fired it; a sender reporting `delivered` (the
    SendMessage step rang, so no trigger ran) frees the slot (nudge.trigwake_released). Only reached after every existing cap passed."""
    role = st.role_of(rid)
    trig = _wake_trigger(st, role, h)
    if not trig:
        return None
    if kind in RING_KINDS:         # 0.24.0 (item 5, R2): no 10-min slot for the three kinds; a woken mail still unread blocks instead
        if not wake_ok:
            return None
        try:
            h.store.append("nudge.trigwake", "system", {"role": role, "to": [rid], "msg_id": mid, "trigger": trig})
        except Exception:
            return None
        return trig
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


def _live_recipients(st, m):
    """Active or idle recipients of a message other than its sender: the direct ids plus the live holder of each role target."""
    cand = list(m.get("to_resolved") or [])
    for tgt in m.get("to") or []:
        if isinstance(tgt, str) and tgt.startswith("role:"):
            hid = st.role_holder(tgt[5:])
            if hid:
                cand.append(hid)
    return [rid for rid in dict.fromkeys(cand) if rid not in ("human", "operator") and not is_system_sender(m["from"]) and rid != m["from"]
            and (st.agents.get(rid) or {}).get("status") in ("active", "idle")]


def _attach(h, sender_ref, r):
    if not isinstance(r, dict) or not r.get("id"):
        return r
    st = h.state()
    mid = r["id"]
    m = st.messages.get(mid)
    if not m:
        return r
    if m["from"] in ("human", "operator") or is_system_sender(m["from"]):
        return r
    _ek = _eff_kind(st, m)
    if _ek != m["kind"] and _ek in ("result", "question"):
        m = dict(m, kind=_ek)               # round 6 (item 2), round 7 (gap 1): a reply to an open ask rings like a result, an expects_reply mail like a question
    if m["kind"] not in NUDGE_KINDS:
        # 0.23.0 (A-08480 item 4): a notice to a live recipient says it rings nobody; no event. Other non-ringing kinds are unchanged.
        if m["kind"] == "notice" and _live_recipients(st, m):
            return dict(r, nudge="none (kind notice starts no wake)")
        return r
    sender = m["from"]
    cfg = _opcfg(h)
    now = time.time()
    hour = _recent(h, now - 3600, OFFERS + ("nudge.skipped",))
    sent = [e for e in hour if e["type"] in OFFERS]
    seen_msg = {e["data"].get("msg") or e["data"].get("msg_id") for e in _recent(h, now - 86400, OFFERS)}
    targets, skipped, queued = [], [], []
    cand = list(m.get("to_resolved") or [])
    for tgt in m.get("to") or []:    # a role target resolves to its live holder now; groups and broadcasts never nudge
        if isinstance(tgt, str) and tgt.startswith("role:"):
            hid = st.role_holder(tgt[5:])
            if hid:
                cand.append(hid)
    for rid in dict.fromkeys(cand):
        a = st.agents.get(rid)
        if a and a.get("status") == "retired" and rid not in ("human", "operator") and rid != sender and _covered(h, st, m, rid):
            # round 7 C6b (blocker 2): covered mail to the id of a chat that retired with no successor counts a miss and says so; the inbox is never read
            reason = "no route: chat retired"
            _skip(h, sender, mid, [rid], reason)
            _miss(h, mid, rid, sender, "retired_no_successor")
            skipped.append({"to": a.get("sobriquet"), "reason": reason, "relay": "miss (no_route)"})
            continue
        if a and a.get("handed_off") and a.get("status") in ("active", "idle") and rid not in ("human", "operator") and rid != sender \
                and not (st.role_of(rid) and f"role:{st.role_of(rid)}" in (m.get("to") or [])) and _covered(h, st, m, rid):
            # round 7 C6c: covered mail sent by the agent id of a chat that handed off and is not restored yet counts a miss and says it is queued
            # (a send by role name is judged by _attach_holder as a vacant role: one miss, never two)
            _miss(h, mid, rid, sender, "handed_off")
            queued.append(rid)
        if rid in ("human", "operator") or rid == sender or not a or a.get("status") not in ("active", "idle") or a.get("handed_off"):
            continue                                   # 0.24.0 (item 11): a holder that handed off is not rung; the mail waits for the restore
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
            ent = {"to": a.get("sobriquet"), "reason": reason}
            which = _cap_which(reason)
            if which and _covered(h, st, m, rid):      # 0.24.0 (item 5, R1c): a capped answer-kind mail goes to a relay, or is a counted miss (F3: a covered result or handoff too)
                ent["relay"] = _cap_relay(h, st, sender, mid, rid, m["kind"], "capped:" + which)
            skipped.append(ent)
            continue
        targets.append((rid, a))
    out = dict(r)
    if skipped:
        out["nudge_skipped"] = skipped
    if not targets:
        if queued and not skipped:
            out["nudge"] = "none (no live holder: queued for the next restore; miss counted)"
            return out
        rel = [x["relay"] for x in skipped if str(x.get("relay") or "").startswith("relay requested")]
        if rel:
            out["nudge"] = rel[0]
        elif skipped and all(str(x.get("relay") or "").startswith("miss") for x in skipped):
            out["nudge"] = skipped[0]["relay"]
        return out
    srole = st.role_of(sender)
    line = (f"Mail {mid} from {srole or 'agent ' + sender[:8]}, thread {m['thread']}. Run harness_inbox (CLI: harness.py inbox --agent "
            f"<your id> --peek), reply with send reply_to {mid}.")
    ring, mail_only, rewakes = [], [], []
    wevs = None
    for rid, a in targets:
        wake_ok, blk, rw = True, None, None
        ek = m["kind"] if m["kind"] in RING_KINDS else ("question" if (m["kind"] in ("result", "handoff") and _waiting(st, m, rid)) else m["kind"])    # F3: a reply to a waiting asker rings like an ask (a cold holder too)
        if ek in RING_KINDS:                           # 0.24.0 (item 5): R2 and nb 6
            wevs = _wake_events(h) if wevs is None else wevs
            blk = _wake_block(st, rid, mid, now, wevs)
            if blk and blk["state"] == "pending":
                reason = f"{HELD_NB6}{SAME_SESSION_S} s ago ({blk['msg_id']}): one ring reads both"
                _skip(h, sender, mid, [rid], reason)
                skipped.append({"to": a.get("sobriquet"), "reason": reason})
                continue
            if blk:
                rw = _rewake_due(blk, now, wevs)
                wake_ok = rw is not None
        hid, why = _route(h, st, rid, a, ek, now, wake_ok)
        trig = _pick_trig(h, st, rid, mid, now, ek, wake_ok)
        if hid or trig:
            ring.append((rid, a, hid, trig))
            if rw:
                rewakes.append((blk, rw, rid))         # this ring is the rewake: one per step of the ladder
        elif blk and not wake_ok:
            reason = f"{HELD_R2} ({blk['msg_id']})"
            _skip(h, sender, mid, [rid], reason)
            skipped.append({"to": a.get("sobriquet"), "reason": reason})
        elif ek in RING_KINDS and str(why).startswith(HELD_ROUTE):
            # round 7 (gap 2): a covered mail is never left with only "mail only" because a stale mark closed the id route: a relay or a counted
            # miss, and a skip record the alarm scan reads (HELD_REASONS), exactly as for a capped ring
            reason = HELD_ROUTE + " by a stale mark"
            _skip(h, sender, mid, [rid], reason)
            skipped.append({"to": a.get("sobriquet"), "reason": reason, "relay": _cap_relay(h, st, sender, mid, rid, m["kind"], "route_closed")})
        elif ek in RING_KINDS and str(why).startswith(("no role", "no app session id", "holder on another machine")):
            # round 7 follow-up (C6): covered mail to a recipient nothing can reach counts a miss (nudge.miss) and the result says so; the mail waits
            reason = "no route: " + str(why).replace(": mail only", "")
            _skip(h, sender, mid, [rid], reason)
            _miss(h, mid, rid, sender, "no_route")
            skipped.append({"to": a.get("sobriquet"), "reason": reason, "relay": "miss (no_route)"})
        else:
            mail_only.append({"to": st.name_role(rid), "reason": why, "key": rid})
    if skipped:
        out["nudge_skipped"] = skipped
    if mail_only:
        out["nudge_mail_only"] = mail_only
    if not ring:
        if mail_only:
            out["nudge"] = "none (" + "; ".join(sorted({x["reason"].replace(": mail only", "") for x in mail_only})) + ": mail only)"
        elif all("relay" in x for x in skipped):      # round 7 (gap 2): every recipient's route is closed; each has its relay request or counted miss
            out["nudge"] = skipped[0]["relay"]
        else:       # 0.24.0 (item 5): every recipient held back by nb 6 or R2; the reasons are in nudge_skipped
            out["nudge"] = "none (" + "; ".join(sorted({x["reason"] for x in skipped if "relay" not in x})) + ")"
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
    for blk, n, rid in rewakes:
        _write_rewake(h, blk, n, rid, via=mid)
    n_hour = sum(1 for e in sent if e["data"].get("from") == sender) + 1
    to_, seen_ = [], set()
    for rid, _, x, _g in ring:        # 0.26.0 (item 12): each recipient once, with its session when it rings by id
        if rid not in seen_:
            seen_.add(rid)
            to_.append(st.name_role(rid) + (" " + x if x else ""))
    out["nudge"] = {"line": line, "to": to_, "msg_id": mid, "thread": m["thread"],
                    "cap_state": f"{n_hour}/{cfg['nudge_per_agent_hour']} this hour",
                    "do": _do_many(ring, line, mid, st)}
    return out


# ---------------------------------------------------------------- 0.24.0 (A-b2950 item 5): wake rules for task, question, review

HELD_R2, HELD_NB6 = "unread wake pending", "rung under "   # item 5: the R2 and nb 6 skip reasons start with these; built only from here
HELD_ROUTE = "id route closed"                              # round 7 (gap 2): a covered mail whose id route a stale mark closed: relay or counted miss, and the alarm
HELD_REASONS = (HELD_R2, HELD_NB6, HELD_ROUTE)                          # alarm_scan still counts this mail (fix 1; critic m-da843f8de897 nb)
_WAKE_EV = ("nudge.offered", "nudge.result", "nudge.rewake", "nudge.relay_offer", "nudge.miss")


def _wake_events(h):
    return [e for e in _tail(h, needle=b'"nudge.') if e.get("type") in _WAKE_EV]


def _rkeys(d):
    """Round 6 (item 3): the report key of each recipient of a nudge offer, in order: its app session id when it rings by id, else (a recipient
    reached only by its wake routine) the first 8 characters of its agent id."""
    tos, hids = list(d.get("to") or []), list(d.get("hids") or [])
    return [(hids[i] if i < len(hids) and hids[i] else str(rid)[:8]) for i, rid in enumerate(tos)]


def _partial_mids(evs):
    """Round 4 (addendum): messages whose nudge.result events are per-recipient (`to_session`) and do not yet cover every recipient session of
    the offer, with no whole-message result. A partial result is one recipient's report: it must not make the scans treat the whole send as
    reported (the unreported scan, the expiry scan, the alarm and the wake block read results by message id)."""
    offers, per, whole = {}, {}, set()
    for e in evs:
        d = e.get("data") or {}
        if e.get("type") == "nudge.offered":
            offers[d.get("msg_id") or d.get("msg")] = set(_rkeys(d))
        elif e.get("type") == "nudge.result":
            k = d.get("msg_id") or d.get("msg")
            if d.get("to_session"):
                per.setdefault(k, set()).add(d["to_session"])
            else:
                whole.add(k)
    return {k for k, got in per.items() if k not in whole and not (offers.get(k) and offers[k] <= got)}


def _drop_partial(evs):
    """`evs` without the per-recipient results of a message that is not fully reported yet (see _partial_mids)."""
    part = _partial_mids(evs)
    if not part:
        return evs
    return [e for e in evs if not (e.get("type") == "nudge.result" and (e.get("data") or {}).get("to_session")
                                   and ((e.get("data") or {}).get("msg_id") or (e.get("data") or {}).get("msg")) in part)]


def _closes(d, to_session=None, to=None):
    """Does the nudge.result data `d` close a relay offer for recipient session `to_session` (or, for a recipient with no session, agent `to`)? A
    whole-message result does; a per-recipient one only its own recipient's offer."""
    key = to_session or (str(to)[:8] if to else None)
    return not d.get("to_session") or not key or d.get("to_session") == key


def _first_results(evs):
    evs = _drop_partial(evs)
    out = {}
    for e in evs:
        if e.get("type") == "nudge.result":
            d = e.get("data") or {}
            out.setdefault(d.get("msg_id") or d.get("msg"), (d, float(e.get("t") or 0)))
    return out


def _woken(d):
    """R2 'woken' (v2, nb 1): a ring reported delivered or held, or a fire reported with a 2xx status (any status but 2xx is no wake)."""
    o = d.get("outcome")
    if o in ("delivered", "held"):
        return True
    return o == "woke" and result_spends(d)


def _wake_block(st, rid, mid, now, evs):
    """What stops a new wake to `rid` (its lineage counts) for message `mid`. -> None or {msg_id, state, t, from, role, to}:
    * pending (nb 6): an earlier answer-kind mail to it was offered under SAME_SESSION_S ago, is unread, and has no result yet or a woken
      one. Nothing rings for this mail: one ring brings the recipient to its inbox, where it reads both.
    * woken (R2): the earliest answer-kind mail to it in the last 24 h with a woken result is unread. No trigger and no cold id wake; a
      warm id ring still goes. `t` is the time of the woken report (the ladder runs from it)."""
    ids = set(st.lineage(rid)) | {rid}
    res = _first_results(evs)
    best = None
    for e in evs:
        if e.get("type") != "nudge.offered":
            continue
        d = e.get("data") or {}
        m0, t = d.get("msg_id") or d.get("msg"), float(e.get("t") or 0)
        if m0 == mid or now - t > WOKEN_WINDOW_S or not ids & set(d.get("to") or []):
            continue
        msg = st.messages.get(m0) or {}
        if _eff_kind(st, msg) not in RING_KINDS or ids & set(msg.get("read_by") or []) or _closed_for(st, m0, ids):
            continue
        r = res.get(m0)
        info = {"msg_id": m0, "from": d.get("from"), "role": st.role_of(rid), "to": rid}
        if now - t < SAME_SESSION_S and (r is None or _woken(r[0])):
            return dict(info, state="pending", t=t)
        if r and _woken(r[0]) and (best is None or r[1] < best["t"]):
            best = dict(info, state="woken", t=r[1])
    return best


def _rewakes_given(evs, msg_id):
    return {int((e.get("data") or {}).get("n") or 0) for e in evs
            if e.get("type") == "nudge.rewake" and (e.get("data") or {}).get("msg_id") == msg_id}


def _rewake_due(blk, now, evs):
    """R2 ladder: rewake 1 when the woken mail is 15 min past its wake, rewake 2 at 1 h; the highest step due that is not given yet, and
    nothing once step 2 is given (a step skipped while nobody called is not made up). -> 1, 2 or None."""
    due = [n for n, at in REWAKE_AT_S if now - blk["t"] >= at]
    given = _rewakes_given(evs, blk["msg_id"])
    if not due or any(g >= max(due) for g in given):
        return None
    return max(due)


def _write_rewake(h, blk, n, rid, via=None):
    """nudge.rewake {msg_id, n, role, to, for, via}. `via` is the new message whose ring carried it; with none (the scan), the woken mail's
    sender carries it on its next harness call (rewake_do). One per (message, step), under the ledger lock."""
    mid = blk["msg_id"]

    def _once(store):
        for x in store.read_all()[-3000:]:
            d = x.get("data") or {}
            if x.get("type") == "nudge.rewake" and d.get("msg_id") == mid and int(d.get("n") or 0) >= n:
                raise _Already()
    try:
        h.store.append("nudge.rewake", "system", {"msg_id": mid, "n": n, "role": blk.get("role"), "to": rid, "for": blk.get("from"),
                                                  "via": via, "woken_t": round(float(blk["t"]), 3)}, precheck=_once)
        return True
    except _Already:
        return False


def _cap_which(reason):
    r = str(reason or "")
    for k in ("sender", "pair", "global"):
        if r.startswith(k + " cap"):
            return k
    return None


def _relay_target(h, st, offer):
    """The (recipient, local_ app session id, trigger) a relay can ring: a role holder on this machine whose id is not marked stale
    (trigger None); else, 0.24.0 (item 18 point 6), a role holder whose VERIFIED routine (item 13) can be run (id None); fix round 2
    (envoy m-74dd4985787a): with no verified routine, a legacy operator pin in the ok state (never stale or spent), as _wake_trigger
    gives it, so moving to the new form never costs a wake path the operator approved. Or None."""
    stale = _stale_ids(h)
    tos = list(offer.get("to") or [])
    pairs = [(to, hid) for to, hid in zip(tos, offer.get("hids") or [])
             if hid and hid.startswith("local_") and hid not in stale and st.role_of(to) and _same_machine(st.agents.get(to) or {}, st)]
    for to, hid in smallest_first(pairs, lambda p: (st.agents.get(p[0]) or {}).get("ctx")):     # 0.27.3 B (F6): the smallest live chat first
        return to, hid, None
    for to in tos:
        role = st.role_of(to)
        if not role or st.role_holder(role) != to:
            continue
        trig = _wake_trigger(st, role, h)         # verified routine first; else an ok legacy pin; never a stale or spent one
        if trig:
            return to, None, trig
    return None


def _miss(h, mid, rid, sender, why):
    """R1c: nudge.miss {msg_id, to, from, reason}: an answer-kind mail no ring and no relay will carry. One per (message, recipient)."""
    def _once(store):
        for x in store.read_all()[-3000:]:
            d = x.get("data") or {}
            if x.get("type") == "nudge.miss" and d.get("msg_id") == mid and d.get("to") == rid:
                raise _Already()
    try:
        h.store.append("nudge.miss", "system", {"msg_id": mid, "to": rid, "from": sender, "reason": why}, precheck=_once)
    except _Already:
        pass


def _cap_relay(h, st, sender, mid, rid, kind, why):
    """R1c: a sender, pair or global cap on task, question or review asks for a relay (reason capped:<which>) instead of a bare skip. With
    no relay target, or the relay cap (RELAY_PER_SENDER_HOUR) full too: nudge.miss. -> the text for the skip entry."""
    offer = {"from": sender, "to": [rid], "hids": [_id_for(st, rid, kind)]}
    tgt = _relay_target(h, st, offer)
    r = _request_relay(h, st, offer, mid, why, actor="system") if tgt else None
    if r and r.get("relay_requested"):
        return f"relay requested ({why}; {direction(st, sender, rid)})"     # item 11: the text names the direction
    miss = why + ("; relay cap full" if tgt else "; no relay target")
    _miss(h, mid, rid, sender, miss)
    return f"miss ({miss})"


def wake_scan(h, now=None, force=False):
    """Runs inside claim_relay (any live Code holder's harness call), at most once per WAKE_SCAN_EVERY_S, so it needs no clock of its own.
    * R1b: an answer-kind offer with no nudge_result RELAY_SILENT_S after it, mail unread, no relay yet: a relay request, reason
      sender_silent (no relay target, or the relay cap full: nudge.miss). The sender's later report still counts.
    * R2 ladder: a woken answer-kind mail still unread gets rewake 1 at 15 min and rewake 2 at 1 h (nudge.rewake, carried by the sender).
    Never raises. -> [(kind, msg id)] written."""
    out = []
    try:
        now = float(now if now is not None else time.time())
        sp = os.path.join(h.store.dir, "nudge_state", "_wake_scan.json")
        stamp = _load(sp)
        if not force and now - float(stamp.get("last") or 0) < WAKE_SCAN_EVERY_S:
            return out
        stamp["last"] = round(now, 3)
        _save(sp, stamp)
        evs = _wake_events(h)
        offers = [e for e in evs if e.get("type") == "nudge.offered" and now - float(e.get("t") or 0) <= WOKEN_WINDOW_S]
        if not offers:
            return out
        st = h.state()
        res = _first_results(evs)
        relayed = {(e.get("data") or {}).get("msg_id") for e in evs if e.get("type") == "nudge.relay_offer"}
        missed = {(e.get("data") or {}).get("msg_id") for e in evs if e.get("type") == "nudge.miss"}
        relayed_p = {((e.get("data") or {}).get("msg_id"), (e.get("data") or {}).get("to")) for e in evs
                     if e.get("type") == "nudge.relay_offer" and (e.get("data") or {}).get("rewake") in (None, "extra")}
        missed_p = {((e.get("data") or {}).get("msg_id"), (e.get("data") or {}).get("to")) for e in evs if e.get("type") == "nudge.miss"}
        for e in offers:
            d = e.get("data") or {}
            mid, t = d.get("msg_id") or d.get("msg"), float(e.get("t") or 0)
            msg = st.messages.get(mid) or {}
            if msg.get("kind") not in RING_KINDS and not any(_covered(h, st, msg, r_) for r_ in (d.get("to") or [])):     # raw read F3
                continue
            ids = set()
            for rid in d.get("to") or []:
                ids |= set(st.lineage(rid)) | {rid}
            for role in d.get("roles") or []:
                hol = st.role_holder(role) if role else None
                if hol:
                    ids |= set(st.lineage(hol)) | {hol}
            r = res.get(mid)
            if r is not None and (ids & set(msg.get("read_by") or []) or _closed_for(st, mid, ids, d.get("roles") or [])):
                continue
            if r is None:
                # round 7 (C6d, spec rule 8): the sender never reported: every recipient that has not read the mail is judged on its own, not only the first
                if not (RELAY_SILENT_S <= now - t < RELAY_TTL_S):
                    continue
                tos, hids, bts = list(d.get("to") or []), list(d.get("hids") or []), list(d.get("by_trigger") or [])
                roles_ = list(d.get("roles") or [])
                rkeys = _rkeys(d)
                unread = []
                for i, rid in enumerate(tos):
                    lin = set(st.lineage(rid)) | {rid}
                    role_i = (roles_[i] if i < len(roles_) else None) or st.role_of(rid)
                    hol_i = st.role_holder(role_i) if role_i else None
                    if hol_i:
                        lin |= set(st.lineage(hol_i)) | {hol_i}
                    if lin & set(msg.get("read_by") or []) or _closed_for(st, mid, lin, [role_i]):
                        continue
                    unread.append((i, rid, role_i))
                woken_to = {(x.get("data") or {}).get("to_session") for x in evs if x.get("type") == "nudge.result"
                            and (x.get("data") or {}).get("msg_id") == mid and (x.get("data") or {}).get("to_session") and _woken(x.get("data") or {})}
                for (i, rid, role_i) in unread:
                    key_i = rkeys[i] if i < len(rkeys) else None
                    if key_i in woken_to:
                        continue                             # this recipient's own report says it was rung
                    if (mid, rid) in relayed_p or (mid, rid) in missed_p:
                        continue                             # round 7 (class A): relayed and missed are kept per (message, recipient)
                    di = dict(d, to=[rid], hids=[hids[i] if i < len(hids) else None], by_trigger=[bts[i] if i < len(bts) else False], roles=[role_i],
                              _key=key_i)
                    rr = _request_relay(h, st, di, mid, "sender_silent", actor="system")
                    if rr and rr.get("relay_requested"):
                        if not rr.get("already"):
                            out.append(("relay", mid))
                    else:
                        _miss(h, mid, rid, d.get("from"), "sender_silent; " + ("relay cap full" if _relay_target(h, st, di) else "no relay target"))
                        out.append(("miss", mid))
                    relayed_p.add((mid, rid)) if rr and rr.get("relay_requested") else missed_p.add((mid, rid))
                continue
            if not _woken(r[0]):
                continue
            rid = (d.get("to") or [None])[0]
            blk = {"msg_id": mid, "from": d.get("from"), "role": (d.get("roles") or [None])[0] or st.role_of(rid), "to": rid,
                   "state": "woken", "t": r[1]}
            n = _rewake_due(blk, now, evs)
            if n and _write_rewake(h, blk, n, rid):
                out.append(("rewake%d" % n, mid))
                if _rewake_offer(h, st, blk, n, msg):      # fix 1 (critic m-4f605b30f919): any live relay holder can carry it
                    out.append(("relay_rewake%d" % n, mid))
    except Exception:
        pass
    return out


def _rewake_route(h, st, role, rid, kind):
    """The route a rewake rings now: (holder, local_ id or None, trigger or None). The role's current holder, else the old recipient."""
    hol = (st.role_holder(role) if role else None) or rid
    tgt = _relay_target(h, st, {"to": [hol], "hids": [_id_for(st, hol, kind)]})
    trig = _wake_trigger(st, role, h) if role else None
    return hol, (tgt[1] if tgt else None), trig


def _rewake_offer(h, st, blk, n, msg):
    """0.24.0 (item 5 fix 1, critic m-4f605b30f919 blocker 1): a scan-made rewake is also a nudge.relay_offer with its own key
    (<msg>#r<n>, reason rewake_<n>), so any live relay holder claims it even when the woken mail's sender is idle. It needs no report and
    never touches the message's result slot; it is done when the mail is read or once claimed. With no id and no trigger: no offer."""
    hol, hid, trig = _rewake_route(h, st, blk.get("role"), blk.get("to"), msg.get("kind"))
    if not (hid or trig):
        return False
    key = "%s#r%d" % (blk["msg_id"], n)
    if _relay_view(h, key)["offer"]:
        return False
    h.store.append("nudge.relay_offer", "system", {"msg_id": blk["msg_id"], "key": key, "rewake": n, "to": hol, "to_session": hid,
                                                   "trigger": None if hid else trig, "from": blk.get("from"),
                                                   "role": st.role_of(blk.get("from")) or "agent", "to_role": blk.get("role"),
                                                   "thread": msg.get("thread"), "reason": "rewake_%d" % n})
    return True


def rewake_relay_line(d):
    """Fixed fields only. SendMessage to the holder's id, or the role's trigger run with no body; no report either way."""
    n, mid = d.get("rewake"), d.get("msg_id")
    if n == "extra":        # round 7 (C6d): a relay for one recipient of a send whose sender never reported; no report needed
        if d.get("to_session"):
            return (f'Do: SendMessage to {d["to_session"]}: Mail {mid} from {d.get("role") or "agent"}, thread {d.get("thread")}. Run harness_inbox. '
                    f'(Relay for a sender that cannot ring; fixed fields only.) No report is needed.')
        if not TRIGGER_DO_LINES:
            return None
        return (f'Do: RemoteTrigger action=run trigger_id={d.get("trigger")} (relay for {mid}; load the tool with ToolSearch select:RemoteTrigger if it is '
                f'deferred; run with no body; no other trigger tool). No report is needed. No RemoteTrigger tool here: skip it.')
    if d.get("to_session"):
        return (f'Do: SendMessage to {d["to_session"]}: Mail {mid} from {d.get("role") or "agent"}, thread {d.get("thread")}. Run '
                f'harness_inbox. (Rewake {n} of 2 for woken mail still unread; fixed fields only.) No report is needed.')
    if not TRIGGER_DO_LINES:        # 0.27.1 (critic 1): an offer stored before the upgrade prints no trigger line either
        return None
    return (f'Do: RemoteTrigger action=run trigger_id={d.get("trigger")} (rewake {n} of 2 for {mid}, woken mail still unread; load the tool '
            f'with ToolSearch select:RemoteTrigger if it is deferred; run with no body; no other trigger tool). No report is needed. '
            f'No RemoteTrigger tool here: skip it.')


def _claim_rewake(h, st, caller, me, e, evs, now):
    """Claim one rewake relay offer under the ledger lock. Skipped when expired, already claimed, read, the caller is the recipient,
    the sender already got it on its own call (rewake_do), or the route it names is gone. -> Do-line or None."""
    d = e.get("data") or {}
    key, mid = d.get("key"), d.get("msg_id")
    if not key or now - float(e.get("t") or 0) >= RELAY_TTL_S or _relay_view(h, key, evs)["claim"]:
        return None
    msg = st.messages.get(mid) or {}
    hol = d.get("to")
    if (set(st.lineage(hol)) | {hol}) & set(msg.get("read_by") or []):
        return None
    if caller == hol or caller in set(st.lineage(hol) or []) or (d.get("to_session") and me.get("host_session_id") == d.get("to_session")):
        return None
    if key in set(_load(_sp(h, d.get("from"))).get("rewakes_shown") or []):
        return None
    if d.get("trigger") and _wake_trigger(st, d.get("to_role"), h) != d.get("trigger"):
        return None                                    # the pin went stale or changed since the offer

    def _free(store):
        v = _relay_view(h, key, [x for x in store.read_all()[-3000:] if x.get("type", "").startswith("nudge.relay_")])
        if v["claim"]:
            raise _Already()
    try:
        h.store.append("nudge.relay_claim", caller, {"msg_id": mid, "key": key, "by": caller, "to_session": d.get("to_session")},
                       precheck=_free)
    except _Already:
        return None
    return rewake_relay_line(d)


def _envoy_for(h, st, what, trig, role):
    """0.25.0 (item 28): the live envoy that gets this verify or disable line first, or None. It must hold role envoy, be a local_ relay
    holder on this machine (ringable), and, for a verify, not be the registrant or in its lineage (the registrant never verifies)."""
    eid = st.role_holder("envoy")
    a = st.agents.get(eid) or {}
    if not eid or "envoy" not in set(_opcfg(h)["relay_roles"]) or not (a.get("host_session_id") or "").startswith("local_") \
            or not _same_machine(a, st):
        return None
    if what == "verify":
        reg = (getattr(st, "wake_reg", None) or {}).get(role) or {}
        hold = reg.get("holder")
        if hold and (eid == hold or eid in set(st.lineage(hold)) or hold in set(st.lineage(eid))):
            return None
    return eid


def wake_do(h, caller, now=None):
    """0.24.0 (item 13): one Do-line for a live Code relay holder (a relay role, a local_ id on this machine): read a pending routine and
    report wake_verify, or disable a routine a different trigger replaced and report wake_disabled. One claim per routine (wake.claim, under the
    ledger lock); after WAKE_CLAIM_S with no report another holder gets it. The registrant and its lineage never verify. Never raises."""
    if not TRIGGER_DO_LINES:
        return None
    try:
        now = float(now if now is not None else time.time())
        st = h.state()
        reg = getattr(st, "wake_reg", None) or {}
        todo = []
        for role, e in sorted(reg.items()):
            if e.get("state") == "pending" and caller != e["holder"] and caller not in set(st.lineage(e["holder"])) \
                    and e["holder"] not in set(st.lineage(caller)) and not trigger_dead(st, e["trigger"]):
                todo.append(("verify", e["trigger"], role))
        # 0.25.0 (item 22): no disable line for a routine whose last fire was 404 or 410 (it is gone); 401, 403, 400 persistent_session_gone,
        # 429 and 5xx keep it (the routine may still exist and fire)
        todo += [("disable", t, r) for t, r in sorted(wake_to_disable(st).items()) if last_fire_status(st, t) not in (404, 410)]
        if not todo:
            return None
        me = st.agents.get(caller) or {}
        if not (st.role_of(caller) in set(_opcfg(h)["relay_roles"]) and (me.get("host_session_id") or "").startswith("local_")
                and _same_machine(me, st)):
            return None
        claims = [e for e in _tail(h, needle=b'"wake.claim"') if e.get("type") == "wake.claim"]
        for what, trig, role in todo:
            if any((c.get("data") or {}).get("trigger") == trig and (c.get("data") or {}).get("what") == what
                   and now - float(c.get("t") or 0) < WAKE_CLAIM_S for c in claims):
                continue
            env_ = _envoy_for(h, st, what, trig, role)       # 0.25.0 (item 28): the envoy first; any other relay role only when none qualifies
            if env_ and st.role_of(caller) != "envoy":
                la_ = _last_call(h, env_)
                gone_ = any((c.get("data") or {}).get("trigger") == trig and (c.get("data") or {}).get("what") == what
                            and (c.get("data") or {}).get("by") == env_ for c in claims)   # an envoy claim past WAKE_CLAIM_S (the check above passed) and still listed: unreported
                if la_ is not None and now - la_ <= ID_COLD_S and not gone_:
                    continue                                    # a warm envoy that has not sat on this line yet keeps it
            who_ = "" if st.role_of(caller) == "envoy" else " (for the envoy)"

            def _free(store, trig=trig, what=what):
                for x in store.read_all()[-3000:]:
                    d = x.get("data") or {}
                    if x.get("type") == "wake.claim" and d.get("trigger") == trig and d.get("what") == what \
                            and now - float(x.get("t") or 0) < WAKE_CLAIM_S:
                        raise _Already()
            try:
                h.store.append("wake.claim", caller, {"trigger": trig, "role": role, "what": what, "by": caller}, precheck=_free)
            except _Already:
                continue
            load = "load the tool with ToolSearch select:RemoteTrigger if it is deferred; no other trigger tool"
            if what == "verify":
                return (f"Do: RemoteTrigger action=get trigger_id={trig} ({load}). Then report harness_admin op=wake_verify "
                        f'args={{trigger:"{trig}",prompt:"<prompt as returned>",enabled:<true|false>,session:"<bound session id>",'
                        f'kind:"<run_once|recurring>",run_at:"<its run date, ISO>"}} with the fields copied from the get result, never computed '
                        f"(role:{role}'s wake routine{who_}; no RemoteTrigger tool here: skip it).")
            return (f"Do: RemoteTrigger action=update trigger_id={trig} enabled=false ({load}; role:{role}'s old wake routine{who_}, its holder "
                    f"changed). Then report harness_admin op=wake_disabled args={{trigger:\"{trig}\"}}. No RemoteTrigger tool here: skip it.")
    except Exception:
        return None
    return None


def rewake_do(h, caller, now=None):
    """The rewake Do-lines a sender carries: nudge.rewake written by the scan (no `via`) for a mail this agent sent, still unread, shown once
    (kept in the agent's nudge_state file). The route is read now: the holder's current id or the role's current trigger. -> [lines]"""
    out = []
    try:
        now = float(now if now is not None else time.time())
        evs = [e for e in _tail(h, needle=b'"nudge.rewake"') if e.get("type") == "nudge.rewake"]
        if not evs:
            return out
        st = h.state()
        mine = set(st.lineage(caller)) | {caller}
        p = _sp(h, caller)
        d0 = _load(p)
        shown = set(d0.get("rewakes_shown") or [])
        new = []
        for e in evs:
            d = e.get("data") or {}
            key = "%s#r%s" % (d.get("msg_id"), d.get("n"))       # the same key as the rewake relay offer
            if d.get("via") or d.get("for") not in mine or key in shown or now - float(e.get("t") or 0) > 7200:
                continue
            msg = st.messages.get(d.get("msg_id")) or {}
            role, rid = d.get("role"), d.get("to")
            hol, hid, trig = _rewake_route(h, st, role, rid, msg.get("kind"))
            if (set(st.lineage(hol)) | {hol, rid}) & set(msg.get("read_by") or []):
                continue
            new.append(key)
            if _relay_view(h, key)["claim"]:
                continue                                   # a relay holder already rang this step (fix 1): one ring per step
            if not (hid or trig):
                continue
            line = (f"Mail {d['msg_id']} from {st.role_of(caller) or 'agent ' + caller[:8]}, thread {msg.get('thread')}. Run harness_inbox "
                    f"(CLI: harness.py inbox --agent <your id> --peek), reply with send reply_to {d['msg_id']}.")
            out.append(f"Rewake {d.get('n')} of 2 for {d['msg_id']} (woken, still unread): " + _do_one(hid, trig, line, d["msg_id"], rewake=d.get("n")))
        if new:
            d0["rewakes_shown"] = (sorted(shown | set(new)))[-200:]
            _save(p, d0)
    except Exception:
        pass
    return out


def rewake_lines(h, st, aid):
    """Sync 'Changed' line for the sender at rewake 2 (R2): '<msg> to role:x still unread after 1 h; holder state: ...'. Last 24 h only,
    and only while the mail is unread."""
    out = []
    try:
        mine = set(st.lineage(aid)) | {aid}
        for e in _tail(h, needle=b'"nudge.rewake"'):
            d = e.get("data") or {}
            if e.get("type") != "nudge.rewake" or int(d.get("n") or 0) != 2 or d.get("for") not in mine \
                    or float(e.get("t") or 0) < time.time() - 86400:
                continue
            msg = st.messages.get(d.get("msg_id")) or {}
            role = d.get("role")
            hol = st.role_holder(role) if role else None
            if (set(st.lineage(hol or d.get("to"))) | {d.get("to")}) & set(msg.get("read_by") or []):
                continue
            hs = holder_state(h, st, role) if role else "vacant"          # item 11 wording
            out.append(f"{d.get('msg_id')} to role:{role} still unread after 1 h; holder state: {hs}")
    except Exception:
        pass
    return out[:4]


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
    # 0.23.0 (gap 2, critic m-9142613e2b12): acceptance stays as before; whether the fire spends a pin is decided by the same parse as a
    # sender's reason, kept in `statuses` (so "took 200 ms HTTP 404 cse_..." does not spend)
    return {"http": st.group(1), "session": m.group(1), "statuses": fire_statuses(rest)}


def relay_fire_evidence(reason):
    """0.24.0 (A-b2950 item 3.4): a relayer's report on a trigger-offered message: the reason starts with `HTTP <3 digits>` (fire_status)
    and carries a run session id. -> evidence in the 0.23.0 shape plus `status` (int), or None. The bare `200 cse_...` form that
    relay_evidence accepts is now only replayed from old events, never accepted."""
    status = fire_status(reason)
    m = _EV_SESSION.search(str(reason or ""))
    if status is None or not m:
        return None
    return {"http": str(status), "session": m.group(1), "statuses": [str(status)], "status": status}


def record_result(h, caller, msg_id, outcome, reason=None, fire=None, to=None):
    """harness_admin op=nudge_result {msg_id, outcome, reason}. A skipped result whose reason starts stale_id marks the offer's app session
    ids stale (nudge.stale_id) until the recipient next calls the harness from that session. One result per message (a second call answers
    already_reported). A result counts even after the offer was flagged unreported. Recorded with `by` (reporter) and `for` (the sender).
    Who may report (0.22.3, A-8a3da):
      * the sender: delivered, held, skipped or woke, as before. Its skipped no_sendmessage / no_listagents to a holder with a local_ id on
        this machine asks for a relay (nudge.relay_offer) instead of filling the result slot (relay_requested).
      * a relaying agent (any non-sender): only delivered, woke or refused_by_app (item 1). On a relayed message only the recorded claimer,
        with the SendMessage `delivery:` state and `message_id:` UUID in its reason (item 4); refused_by_app releases the claim and caps
        that relayer for 60 min. On a trigger-offered message the 0.22.2 HTTP status + cse_/session_ id form. Anyone else is refused.
      Evidence is self-reported: the harness checks its shape and the claim, not the run.
    Round 3 (F7): a send with several recipients is reported once per recipient: `to` is that recipient's app session id (one of the offer's).
    The result is then keyed by (message, recipient), so a refused recipient's skip (a relay request) never hits "already reported" because
    another recipient's delivery was filed first. Without `to` the report covers the whole message, as before."""
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
    if not offer:      # 0.24.0 (item 5, R1c): a capped send has a relay offer and no nudge.offered
        rv = _relay_view(h, msg_id)["offer"]
        if rv:
            offer = {"msg_id": msg_id, "from": rv.get("from"), "to": [rv.get("to")], "hids": [rv.get("to_session")], "by_trigger": [False]}
    if not offer:
        raise H.HarnessError("no nudge was offered for %s" % msg_id)
    mine = set(st.lineage(caller)) | {caller}
    kind = (st.messages.get(msg_id) or {}).get("kind")
    why = " ".join(str(reason or "").replace("\x00", " ").split())[:80]
    to = str(to).strip() if isinstance(to, str) and to.strip() else None
    keys = _rkeys(offer)
    if len(keys) > 1:
        # round 6 (item 3): a send with several recipients is reported once per recipient. A whole-message report that arrives after some
        # per-recipient ones is never allowed to swallow a recipient that has not reported: a skipped relay-ask then names the first missing one.
        cov = set()
        for e in _tail(h, needle=b'"nudge.result"'):
            d_ = e.get("data") or {}
            if e.get("type") == "nudge.result" and d_.get("msg_id") == msg_id and d_.get("to_session"):
                cov.add(d_["to_session"])
        missing = [k_ for k_ in keys if k_ not in cov]
        if not to and cov and missing and outcome == "skipped" and offer.get("from") in mine:
            to = missing[0]
    if to:       # round 3 F7: one report per recipient; `to` must be one of this offer's recipient keys (session id, or agent id prefix)
        if to not in keys:
            raise H.HarnessError("to must be one recipient of this message's nudge (%s); nothing was recorded" % ", ".join(keys[:6] or ["none"]))
        i_ = keys.index(to)
        offer = dict(offer, to=[(offer.get("to") or [])[i_]], hids=[((offer.get("hids") or []) + [None] * len(keys))[i_]],
                     by_trigger=[((offer.get("by_trigger") or []) + [False] * len(keys))[i_]], _key=to)
    ev = None
    status = None
    by_trig = any(offer.get("by_trigger") or [])
    if offer.get("from") in mine:
        if outcome == "refused_by_app":
            raise H.HarnessError("refused_by_app is a relaying agent's outcome; the sender reports skipped")
        if outcome == "woke" and by_trig:      # 0.24.0 (A-b2950 item 3): one format; a refused report records nothing, the firer reports again
            status = fire_status(why)
            if status is None:
                raise H.HarnessError(FIRE_FORMAT + " (for example HTTP 200 or HTTP 404); nothing was recorded, report again")
        if outcome in ("held", "skipped") and by_trig:     # 0.24.2 (RD-0d97a): a held or skipped fire that names its status counts too
            status = fire_status(why)
            if outcome == "skipped" and status is not None and 200 <= status <= 299:     # a 2xx run is not a skip: it would reset the failure count and dodge the always-rings rule
                raise H.HarnessError("a fire that ran with HTTP %d is reported woke, not skipped; nothing was recorded, report again" % status)
        code = (_SKIP_CODE.match(why.lower()) or [None, ""])[1] if outcome == "skipped" else ""
        if outcome == "skipped" and kind in RING_KINDS and code not in SKIP_OK and status is None:     # 0.24.2: a fire's HTTP status is a reason too
            # 0.24.0 (item 5, R1): the three answer kinds always ring; a skip needs a reason from the fixed list (nothing is recorded)
            raise H.HarnessError("a %s always rings: skipped needs one of these reasons: %s (any other, such as 'not needed', is refused; "
                                 "nothing was recorded, ring the recipient and report again)" % (kind, ", ".join(SKIP_OK)))
        # 0.26.0 (fix round 1, critic B1): app_cap and no_remotetrigger ask for a relay for every nudge kind (result and handoff included), so with the
        # ladder gone a skipped ring of a reply is still carried; the three answer kinds keep their stricter reason list above
        if outcome == "skipped" and (code in RELAY_ASK_RING or (kind not in RING_KINDS and why.lower().startswith(RELAY_ASK_RING))):
            r = _request_relay(h, st, offer, msg_id, why)
            if r:
                _pop_pending(h, offer.get("from"), msg_id)
                return r
    else:
        if outcome not in RELAY_OUTCOMES:
            raise H.HarnessError("a relaying agent may report only " + ", ".join(RELAY_OUTCOMES) + " for %s" % msg_id)
        rel = _relay_view(h, msg_id)
        if rel["offer"]:
            claim = rel["claim"]
            # 0.24.0 (item 18 point 4): any agent that held a claim on this message, current or earlier, may report (once per message),
            # so a claim that timed out still takes its claimer's late report
            if not (claim and claim.get("by") in mine) and not _ever_claimed(h, msg_id, mine):
                raise H.HarnessError("only the sender of %s or an agent that claimed its relay can report its nudge" % msg_id)
            if outcome == "refused_by_app":
                if claim and claim.get("by") in mine:
                    return _release_relay(h, caller, msg_id, why)
                raise H.HarnessError("refused_by_app: your claim on %s is no longer live; nothing to release" % msg_id)
            if rel["offer"].get("trigger"):           # point 6: a relay through the recipient's verified routine reports its fire
                if outcome != "woke":
                    raise H.HarnessError("a relay through a wake routine reports woke with " + FIRE_FORMAT)
                status = fire_status(why)
                if status is None:
                    raise H.HarnessError(FIRE_FORMAT + " (for example HTTP 200 or HTTP 404); nothing was recorded, report again")
                by_trig = True
                ev = {"http": str(status), "statuses": [str(status)], "relay_trigger": rel["offer"]["trigger"]}
            else:
                if outcome == "woke":
                    raise H.HarnessError("a SendMessage relay reports delivered or held, with the SendMessage result")
                ev = delivery_evidence(why, outcome)
                if not ev:
                    raise H.HarnessError("a relay report needs the SendMessage result in its reason: delivery: delivered (or queued for "
                                         "held); message_id: <uuid>")
        elif by_trig and outcome != "refused_by_app":
            ev = relay_fire_evidence(why)      # 0.22.2 (A-0ce70 item 3): HTTP status + run session id; 0.24.0 (item 3.4): start-anchored
            if not ev:
                raise H.HarnessError("only the sender of %s can report its nudge; a relayer's %s and carry the run session id "
                                     "(cse_... or session_...)" % (msg_id, FIRE_FORMAT))
            status = ev.pop("status")
        else:
            raise H.HarnessError("only the sender of %s can report its nudge" % msg_id)
    stale_fields = []
    if outcome == "woke" and by_trig:        # 0.24.0 (item 13): every fire runs with no body; a registered routine's fire carries its fields
        if _BODY_RE.search(why):
            raise H.HarnessError("a fire report never names a body or text: RemoteTrigger runs with no body; nothing was recorded")
        stale_fields = _fire_check(st, msg_id, status, fire)
    data = {"msg": msg_id, "msg_id": msg_id, "by": caller, "for": offer.get("from"), "outcome": outcome, "reason": why}
    if to:
        data["to_session"] = to
    if ev:
        data["evidence"] = dict(ev, self_reported=True)
    if status is not None and outcome in ("woke", "held", "skipped"):
        data["status"] = status                 # 0.24.0 (item 3.3): the parsed status; events without it replay with the old reader

    def _fresh(store):
        for e in store.read_all()[-3000:]:
            d_ = e.get("data") or {}
            if e.get("type") == "nudge.result" and d_.get("msg_id") == msg_id and ((not d_.get("to_session")) if not to else d_.get("to_session") == to):
                raise _Already()
    try:
        h.store.append("nudge.result", caller, data, precheck=_fresh)
    except _Already:
        if offer.get("from") in mine:     # 0.24.0 (item 5, R1b): the sender's report after a relay's still counts; recorded apart, once
            prev = next(((e.get("data") or {}) for e in reversed(h.store.read_all()[-3000:]) if e.get("type") == "nudge.result"
                         and (e.get("data") or {}).get("msg_id") == msg_id), {})
            late = [e for e in _tail(h, needle=b'"nudge.result_late"') if (e.get("data") or {}).get("msg_id") == msg_id]
            if prev.get("by") not in mine and not late:
                h.store.append("nudge.result_late", caller, data)
                return {"msg_id": msg_id, "already_reported": True, "recorded_late": True}
        return {"msg_id": msg_id, "already_reported": True}
    for trig, role, field in stale_fields:       # item 13: a changed routine goes stale at once; the holder re-registers
        h.store.append("wake.stale", "system", {"role": role, "trigger": trig, "field": field, "msg_id": msg_id})
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
    if not to or msg_id not in _partial_mids([e for e in _tail(h, needle=b'"nudge.') if e.get("type") in ("nudge.offered", "nudge.result")]):
        _pop_pending(h, offer.get("from"), msg_id)         # round 4: a per-recipient report leaves the send pending until every recipient has reported
    return {"msg_id": msg_id, "reported": True, "outcome": outcome}


def _fire_check(st, msg_id, status, fire):
    """0.24.0 (item 13, B1 input A; v3 blockers 1a and 1b): for a fire through a verified routine with a 2xx status, the report must carry
    prompt, enabled and session copied from the run result; a missing field refuses the report (the pin stays). The prompt (trimmed) must
    equal WAKE_PROMPT_V2, enabled be true and the session the verified one; each mismatch -> (trigger, role, field) for wake.stale.
    A legacy pin or a failed status needs no fields. Raises HarnessError with FIRE_FIELDS."""
    import harness as H
    out = []
    if status is None or not 200 <= int(status) <= 299:
        return out
    for trig, _sq in (getattr(st, "trigwake_msgs", None) or {}).get(msg_id, ()):
        role = registered_trigger(st, trig)
        if not role:
            continue
        f = fire if isinstance(fire, dict) else {}
        if not (isinstance(f.get("prompt"), str) and isinstance(f.get("enabled"), bool) and isinstance(f.get("session"), str)):
            raise H.HarnessError(FIRE_FIELDS + "; nothing was recorded, report again")
        e = st.wake_reg[role]
        if f["prompt"][:80].strip() != WAKE_PROMPT_V2:
            out.append((trig, role, "prompt"))
        if f["enabled"] is not True:
            out.append((trig, role, "enabled"))
        if f["session"] != e.get("session"):
            out.append((trig, role, "session"))
    return out


def _pop_pending(h, sender, msg_id):
    try:
        p = _sp(h, sender)
        d = _load(p)
        if msg_id in (d.get("pending") or {}):
            d["pending"].pop(msg_id, None)
            _save(p, d)
    except Exception:
        pass


# ---- 0.22.3 (A-8a3da): cloud-to-local nudge relay. A sender that cannot ring (a cloud or Cowork chat: no SendMessage / ListAgents) asks
# for a relay by reporting its skip; the next harness call of a live local role holder on this machine claims it under the ledger lock and
# gets one fixed-field SendMessage Do-line. Events: nudge.relay_offer, nudge.relay_claim, nudge.relay_released, nudge.relay_capped.

def delivery_evidence(reason, outcome="delivered"):
    """The SendMessage result a relay claimer copies into its reason: `delivery: <state>; message_id: <uuid>`. The state must be
    delivered for outcome delivered, and queued for outcome held (0.24.0 item 18 point 4: the app holds it for a busy chat).
    Self-reported: the harness checks the shape, not the app. -> {"delivery", "message_id"} or None."""
    s = str(reason or "")
    d, m = _EV_DELIVERY.search(s), _EV_MSGID.search(s)
    want = "queued" if outcome == "held" else "delivered"
    if not (d and m) or d.group(1).lower() != want:
        return None
    return {"delivery": want, "message_id": m.group(1).lower()}


def _relay_events(h):
    return [e for e in _tail(h, needle=b'"nudge.relay_') if e.get("type") in
            ("nudge.relay_offer", "nudge.relay_claim", "nudge.relay_released", "nudge.relay_capped")]


def _relay_view(h, msg_id, evs=None):
    """-> {"offer": data|None, "offer_t", "claim": data|None (the live claim: none after a release)}, from the ledger tail."""
    out = {"offer": None, "offer_t": None, "claim": None, "claim_t": None, "timed_out": set()}
    for e in (evs if evs is not None else _relay_events(h)):
        d = e.get("data") or {}
        if (d.get("key") or d.get("msg_id")) != msg_id:     # 0.24.0 (item 5 fix 1): a rewake offer has its own key, <msg>#r<n>
            continue
        if e["type"] == "nudge.relay_offer":
            out.update(offer=d, offer_t=float(e.get("t") or 0), claim=None, claim_t=None)
        elif e["type"] == "nudge.relay_claim":
            out.update(claim=d, claim_t=float(e.get("t") or 0))
        elif e["type"] == "nudge.relay_released":
            if d.get("reason") == "claim_timeout" and d.get("claimer"):
                out["timed_out"].add(d["claimer"])      # 0.22.3b: a silent claimer does not get the same message back
            out.update(claim=None, claim_t=None)
    return out


def _results(h):
    evs = [e for e in _tail(h, needle=b'"nudge.') if e.get("type") in ("nudge.offered", "nudge.result")]
    return {(e.get("data") or {}).get("msg_id") for e in _drop_partial(evs) if e.get("type") == "nudge.result"}


def _request_relay(h, st, offer, msg_id, why, actor=None):
    """Item 2: the sender's skip no_sendmessage / no_listagents. A relay is offered only to a recipient holding a role, with a local_ app
    session id that is not marked stale, on this machine. Max RELAY_PER_SENDER_HOUR offers per sender. -> result dict, or None (record the
    skip as an ordinary result). 0.24.0 (item 5): also R1 app_cap / no_remotetrigger, R1b sender_silent and R1c capped:<which> (actor
    system); R3: a message already rung (a result delivered, held or woke) gets no relay."""
    sender = offer.get("from")
    target = _relay_target(h, st, offer)
    if not target:
        return None
    now = time.time()
    for e in _tail(h, needle=b'"nudge.result"'):
        d = e.get("data") or {}
        key_ = offer.get("_key")
        if e.get("type") == "nudge.result" and d.get("msg_id") == msg_id and _woken(d) \
                and ((key_ and d.get("to_session") == key_) or not key_):         # round 6: a recipient's own skip is judged against its own reports only       # round 3 F7: another recipient's delivery
            return {"msg_id": msg_id, "relay_requested": False,
                    "refused": "one ring per recipient session: %s was already reported %s" % (msg_id, d.get("outcome"))}
    evs = _relay_events(h)
    existing = _relay_view(h, msg_id, evs)["offer"]
    xkey = None
    if existing:
        # round 7 (C6d, class A): the lookup is per (message, recipient). The message's first relay is the reported one; another recipient of the same
        # message gets its own offer (key <msg>#x<agent8>, no report needed) instead of a false "already"
        if existing.get("to") == target[0]:
            return {"msg_id": msg_id, "relay_requested": True, "already": True}
        xkey = "%s#x%s" % (msg_id, str(target[0])[:8])
        if _relay_view(h, xkey, evs)["offer"]:
            return {"msg_id": msg_id, "relay_requested": True, "already": True}
    if sum(1 for e in evs if e["type"] == "nudge.relay_offer" and (e.get("data") or {}).get("from") == sender
           and float(e.get("t") or 0) >= now - 3600) >= RELAY_PER_SENDER_HOUR:
        return None
    m = st.messages.get(msg_id) or {}
    role = st.role_of(sender) or "agent"
    if xkey:
        h.store.append("nudge.relay_offer", actor or sender, {"msg_id": msg_id, "key": xkey, "rewake": "extra", "to": target[0], "to_session": target[1],
                                                               "trigger": target[2], "from": sender, "role": role, "to_role": st.role_of(target[0]),
                                                               "thread": m.get("thread"), "reason": why})
        return {"msg_id": msg_id, "relay_requested": True, "nudge": "relay requested (%s)" % direction(st, sender, target[0]),
                "note": "a live local role holder will ring the recipient for you; nothing else to do"}
    h.store.append("nudge.relay_offer", actor or sender, {"msg_id": msg_id, "to": target[0], "to_session": target[1], "trigger": target[2],
                                                           "fields": bool(target[2] and registered_trigger(st, target[2])),
                                                           "from": sender,
                                                  "role": role, "thread": m.get("thread"), "reason": why})
    return {"msg_id": msg_id, "relay_requested": True, "nudge": "relay requested (%s)" % direction(st, sender, target[0]),
            "note": "a live local role holder will ring the recipient for you; nothing else to do"}


def _release_relay(h, caller, msg_id, why):
    """Item 1: refused_by_app. The claim goes back to the pool and this relayer takes no claims for RELAY_CAP_S (or until it next reports
    delivered). The result slot stays free."""
    now = time.time()
    h.store.append("nudge.relay_released", caller, {"msg_id": msg_id, "by": caller, "reason": why or "refused_by_app"})
    h.store.append("nudge.relay_capped", "system", {"agent": caller, "until": round(now + RELAY_CAP_S, 3)})
    return {"msg_id": msg_id, "reported": True, "outcome": "refused_by_app", "released": True}


def _capped(h, aid, evs, now):
    until = 0.0
    for e in evs:
        if e["type"] == "nudge.relay_capped" and (e.get("data") or {}).get("agent") == aid:
            until = max(until, float((e.get("data") or {}).get("until") or 0))
    if until <= now:
        return False
    since = until - RELAY_CAP_S
    for e in _tail(h, needle=b'"nudge.result"'):     # a delivered report after the cap lifts it
        d = e.get("data") or {}
        if e.get("type") == "nudge.result" and d.get("by") == aid and d.get("outcome") == "delivered" and float(e.get("t") or 0) >= since:
            return False
    return True


def relay_expire(h, now=None):
    """0.25.0 (item 34): an offer with no result RELAY_TTL_S after it was made is closed: nudge.miss (reason relay_expired) plus relay.closed
    (reason expired) written by system, NEVER a system nudge.result (the sender's later report then still counts as the first result and the
    R2 rewakes still run). An offer already closed (read, trigger_dead, expired) is skipped; one whose recipient has read the mail gets a plain
    relay.closed (reason read) and no miss. The alarm then depends on the unread condition, not on an expiry result. Never raises. -> [msg ids]"""
    out = []
    try:
        now = float(now if now is not None else time.time())
        evs = _relay_events(h)
        offers = [e for e in evs if e["type"] == "nudge.relay_offer"]
        if not offers:
            return out
        done = _results(h) | _closed(h)
        cp = _closed_pairs(h)
        st = None
        for e in offers:
            d = e.get("data") or {}
            mid = d.get("msg_id")
            if (d.get("rewake") and d.get("rewake") != "extra") or _done(done, cp, mid, d.get("to")) or now - float(e.get("t") or 0) < RELAY_TTL_S:
                continue                                   # a rewake offer never writes a result (item 5 fix 1)
            st = st or h.state()
            read = d.get("to") in ((st.messages.get(mid) or {}).get("read_by") or [])

            def _once(store, mid=mid, ts=d.get("to_session"), tg=d.get("to")):
                for x in store.read_all()[-3000:]:
                    if x.get("type") in ("relay.closed", "nudge.result") and ((x.get("data") or {}).get("msg_id") == mid) \
                            and ((x.get("type") == "relay.closed" and (x["data"].get("to") in (None, tg))) or (x.get("type") == "nudge.result" and _closes(x.get("data") or {}, ts, tg))):      # round 4: another recipient's report is not this offer's
                        raise _Already()
            try:
                h.store.append("relay.closed", "system", {"msg_id": mid, "to": d.get("to"), "reason": "read" if read else "expired"}, precheck=_once)
                if not read:
                    _miss(h, mid, d.get("to"), d.get("from"), "relay_expired")
                out.append(mid)
            except _Already:
                pass
            cp.add((mid, d.get("to")))
    except Exception:
        pass
    return out


def relay_line(d):
    """The claimed Do-line for a relay offer: SendMessage to the holder's id, or (item 18 point 6) the recipient's verified routine."""
    if d.get("trigger") and not TRIGGER_DO_LINES:
        return relay_do_line(d.get("to_session"), d.get("msg_id"), d.get("role") or "agent", d.get("thread")) if d.get("to_session") else None
    if d.get("trigger"):
        return relay_trigger_line(d.get("trigger"), d.get("msg_id"), d.get("role") or "agent", d.get("thread"),
                                  fields=bool(d.get("fields", True)))
    return relay_do_line(d.get("to_session"), d.get("msg_id"), d.get("role") or "agent", d.get("thread"))


def relay_trigger_line(trig, msg_id, role, thread, fields=True):
    """Item 18 point 6: fixed fields only; run with no body; the report is woke with the final status, plus the run result's fields for
    a verified routine (a legacy pin needs none)."""
    f = (',prompt:"<prompt as returned, at most 80 characters>",enabled:<true|false>,session:"<bound session id as returned>"' if fields
         else '')
    return (f'Do: RemoteTrigger action=run trigger_id={trig} (relay for mail {msg_id} from {role}, thread {thread}; load the tool with '
            f'ToolSearch select:RemoteTrigger if it is deferred; run with no body; no other trigger tool). {TRIG_NOT_URGENT} Then report: '
            f'harness_admin op=nudge_result args={{msg_id:"{msg_id}",outcome:woke,reason:"HTTP <final status>"{f}}}'
            + (', copied from the run result.' if fields else '.')
            + f' No RemoteTrigger tool here: skip it; the claim passes on after {RELAY_CLAIM_S // 60} min.')


def relay_do_line(to_session, msg_id, role, thread):
    """Item 3: fixed fields only (ids from the ledger, the sender's ROLE, never a name, subject or body)."""
    return (f'Do: SendMessage to {to_session}: Mail {msg_id} from {role}, thread {thread}. Run harness_inbox. (Relay for a sender that '
            f'cannot ring; fixed fields only.) Then report: harness_admin op=nudge_result args={{msg_id:"{msg_id}",'
            f'outcome:delivered|held|refused_by_app,reason:"delivery: <state>; message_id: <id from the SendMessage result>"}} '
            f'(held when the result says delivery: queued). '
            f'If the app refuses the send (its cross-session cap), report refused_by_app; the relay passes to another holder.')


def claim_relay(h, caller, now=None):
    """Item 3: called after each harness call of an agent. A live local role holder on this machine (not the recipient, not capped) whose
    turn it is claims the oldest open offer under the ledger lock. Turn: among the warm eligible holders (a harness call in the last hour)
    the one whose last claim is oldest goes first; a tie may claim. -> Do-line text or None. Never raises."""
    try:
        now = float(now if now is not None else time.time())
        wake_scan(h, now)                              # 0.24.0 (item 5): R1b silent senders and the R2 rewake ladder, no clock of its own
        evs = _relay_events(h)
        if not any(e["type"] == "nudge.relay_offer" and now - float(e.get("t") or 0) < RELAY_TTL_S for e in evs):
            return None
        relay_expire(h, now)
        st = h.state()
        me = st.agents.get(caller) or {}
        allowed = set(_opcfg(h)["relay_roles"])
        if not (st.role_of(caller) in allowed and (me.get("host_session_id") or "").startswith("local_") and _same_machine(me, st)):
            return None
        if _capped(h, caller, evs, now):
            return None
        done = _results(h) | _closed(h)                  # item 18 point 3: a read closes the relay
        cp = _closed_pairs(h)
        last_claim = {}
        for e in evs:
            if e["type"] == "nudge.relay_claim":
                last_claim[(e.get("data") or {}).get("by")] = float(e.get("t") or 0)
        holders = [aid for aid in st.agents if st.role_of(aid) in allowed and aid != caller
                   and ((st.agents[aid].get("host_session_id") or "").startswith("local_")) and _same_machine(st.agents[aid], st)]
        for e in evs:
            if e["type"] != "nudge.relay_offer":
                continue
            d = e.get("data") or {}
            mid = d.get("msg_id")
            if d.get("rewake"):                        # 0.24.0 (item 5 fix 1): a scan-made rewake; its done-check is the read, not a result
                line = _claim_rewake(h, st, caller, me, e, evs, now)
                if line:
                    return line
                continue
            if _done(done, cp, mid, d.get("to")) or now - float(e.get("t") or 0) >= RELAY_TTL_S:
                continue
            if d.get("trigger") and trigger_dead(st, d["trigger"]):
                _close_dead(h, d)                          # 0.25.0 (item 22): a dead routine is closed here, never carried
                continue
            view = _relay_view(h, mid, evs)
            if view["claim"] and now - (view["claim_t"] or now) >= RELAY_CLAIM_S:
                old = view["claim"]

                def _same(store, mid=mid, old=old):
                    v = _relay_view(h, mid, [x for x in store.read_all()[-3000:] if x.get("type", "").startswith("nudge.relay_")])
                    if v["claim"] != old:
                        raise _Already()
                    for x in store.read_all()[-3000:]:
                        if x.get("type") == "nudge.result" and ((x.get("data") or {}).get("msg_id") == mid) and _closes(x.get("data") or {}, d.get("to_session"), d.get("to")):
                            raise _Already()
                try:    # 0.22.3b (blocker 1b): no report 5 min after the claim: release it to the next holder
                    h.store.append("nudge.relay_released", "system", {"msg_id": mid, "by": "system", "claimer": old.get("by"),
                                                                      "reason": "claim_timeout"}, precheck=_same)
                except _Already:
                    continue
                evs = _relay_events(h)
                view = _relay_view(h, mid, evs)
            if view["claim"] or caller in view["timed_out"]:
                continue
            recipient = d.get("to")
            if caller == recipient or caller in set(st.lineage(recipient) or []) or me.get("host_session_id") == d.get("to_session"):
                continue
            if recipient in ((st.messages.get(mid) or {}).get("read_by") or []):
                continue                                   # read already: nothing to ring (expiry records read_before_relay)
            rivals = [aid for aid in holders if aid != recipient and not _capped(h, aid, evs, now)
                      and (lambda la: la is not None and now - la <= ID_COLD_S)(_last_call(h, aid))]
            mine_t = last_claim.get(caller, 0.0)
            if now - float(e.get("t") or 0) < RELAY_TURN_S and any(last_claim.get(r, 0.0) < mine_t for r in rivals):
                continue                                   # 0.22.3b (addendum item 3): another holder's turn for this offer; try later offers

            def _free(store, mid=mid):
                v = _relay_view(h, mid, [x for x in store.read_all()[-3000:] if x.get("type", "").startswith("nudge.relay_")])
                if v["claim"]:
                    raise _Already()
                for x in store.read_all()[-3000:]:
                    if x.get("type") == "nudge.result" and ((x.get("data") or {}).get("msg_id") == mid) and _closes(x.get("data") or {}, d.get("to_session"), d.get("to")):
                        raise _Already()
            try:
                h.store.append("nudge.relay_claim", caller, {"msg_id": mid, "by": caller, "to_session": d.get("to_session")},
                               precheck=_free)
            except _Already:
                continue
            if d.get("trigger"):         # item 18 point 6: the fold links this fire to the routine (staleness and the fire fields)
                try:
                    h.store.append("nudge.trigwake", "system", {"role": st.role_of(recipient), "to": [recipient], "msg_id": mid,
                                                                "trigger": d["trigger"], "relay": True})
                except Exception:
                    pass
            return relay_line(d)
    except Exception:
        return None
    return None


def _last_call(h, aid):
    try:
        v = _load(_sp(h, aid)).get("last_call")
        return float(v) if v else None
    except Exception:
        return None


def _ever_claimed(h, msg_id, mine):
    return any(e.get("type") == "nudge.relay_claim" and (e.get("data") or {}).get("msg_id") == msg_id
               and not (e.get("data") or {}).get("key") and (e.get("data") or {}).get("by") in mine for e in _relay_events(h))


def _close_dead(h, d):
    """0.25.0 (item 22): close an offer whose routine is dead: relay.closed {reason trigger_dead} (NOT a nudge.result: _first_results takes the
    first result per message, so a system skipped result would shadow a later sender report and the R2 rewakes would never fire), and one
    nudge.miss per message and recipient for the audit trail. A precheck keeps it to one. Never raises."""
    try:
        mid = d.get("msg_id")

        def _once(store):
            for x in store.read_all()[-3000:]:
                if x.get("type") == "relay.closed" and (x.get("data") or {}).get("msg_id") == mid and (x["data"].get("to") in (None, d.get("to"))):
                    raise _Already()
        try:
            h.store.append("relay.closed", "system", {"msg_id": mid, "to": d.get("to"), "reason": "trigger_dead"}, precheck=_once)
        except _Already:
            return
        _miss(h, mid, d.get("to"), d.get("from"), "trigger_dead")
    except Exception:
        pass


def _closed(h):
    """Item 18 point 3: msg ids whose relay a read closed (relay.closed) for the whole message. Round 7 (C6d, class A): a close that names a recipient (`to`)
    closes only that recipient's offer: see _closed_pairs and _done."""
    return {(e.get("data") or {}).get("msg_id") for e in _tail(h, needle=b'"relay.closed"')
            if e.get("type") == "relay.closed" and not (e.get("data") or {}).get("to")}


def _closed_pairs(h):
    """Round 7 (C6d, class A): {(msg id, recipient)} whose relay a read, an expiry or a dead routine closed for that recipient only."""
    return {((e.get("data") or {}).get("msg_id"), (e.get("data") or {}).get("to")) for e in _tail(h, needle=b'"relay.closed"')
            if e.get("type") == "relay.closed" and (e.get("data") or {}).get("to")}


def _done(done, pairs, mid, to=None):
    """Is the relay of (message, recipient) done: a result for the whole message, a whole-message close, or a close for this recipient."""
    return mid in done or (mid, to) in pairs


def close_relays(h, aid, ids):
    """Item 18 point 3: called right after a message.read. A relay offer on a read message with no result yet is closed:
    relay.closed {msg_id, reason: read}. No release, no sender notice, no re-offer, no repeated Do-line; relay_expire still writes
    read_before_relay at the TTL. Only the recipient's (or its lineage's, or the role holder's) read counts. Never raises."""
    out = []
    try:
        offers = [e for e in _tail(h, needle=b'"nudge.relay_offer"') if e.get("type") == "nudge.relay_offer"
                  and (e.get("data") or {}).get("msg_id") in ids]          # fix round 1: a read closes rewake offers too
        if not offers:
            return out
        st = h.state()
        mine = set(st.lineage(aid)) | {aid}
        done = _results(h) | _closed(h)
        cp = _closed_pairs(h)
        for e in offers:
            d = e.get("data") or {}
            mid, to = d.get("msg_id"), d.get("to")
            if _done(done, cp, mid, to) or (mid, to) in cp:
                continue
            if to not in mine and not (st.role_of(to) and st.role_holder(st.role_of(to)) == aid):
                continue
            h.store.append("relay.closed", "system", {"msg_id": mid, "to": to, "reason": "read"})     # round 7 (class A): closes this recipient's offer only
            cp.add((mid, to))
            out.append(mid)
    except Exception:
        pass
    return out


def live_claim_line(h, caller, now=None):
    """Item 18 point 1: the Do-line of the caller's live, unreported claim (not timed out, no result, not closed, mail unread), or None.
    It is the same claim, never a new one."""
    try:
        now = float(now if now is not None else time.time())
        evs = _relay_events(h)
        mine_claims = [e for e in evs if e.get("type") == "nudge.relay_claim" and (e.get("data") or {}).get("by") == caller
                       and not (e.get("data") or {}).get("key") and now - float(e.get("t") or 0) < RELAY_CLAIM_S]
        if not mine_claims:
            return None
        done = _results(h) | _closed(h)
        cp = _closed_pairs(h)
        st = h.state()
        for c in reversed(mine_claims):
            mid = (c.get("data") or {}).get("msg_id")
            view = _relay_view(h, mid, evs)
            if _done(done, cp, mid, (view["offer"] or {}).get("to")) or not view["offer"] or not view["claim"] or view["claim"].get("by") != caller:
                continue
            if view["offer"].get("to") in ((st.messages.get(mid) or {}).get("read_by") or []):
                continue
            if view["offer"].get("trigger") and trigger_dead(st, view["offer"]["trigger"]):
                continue                                   # 0.25.0 (item 22): the routine died after the claim
            return relay_line(view["offer"])
    except Exception:
        return None
    return None


def hook_relay_line(h, caller, now=None):
    """Item 18 point 7: the PostToolUse hook's claim. A new claim's line at once; a live claim's line again at most once per
    RELAY_REPEAT_S (kept in the caller's nudge_state file). Shares claim_relay's ledger lock. Never raises."""
    try:
        now = float(now if now is not None else time.time())
        p = _sp(h, caller)
        d0 = _load(p)
        line = claim_relay(h, caller, now)
        if not line:
            line = live_claim_line(h, caller, now)
            if not line or now - float(d0.get("relay_hook_shown") or 0) < RELAY_REPEAT_S:
                return None
        d0["relay_hook_shown"] = round(now, 3)
        _save(p, d0)
        return line
    except Exception:
        return None


def relay_notice_lines(h, st, aid, now=None):
    """Item 18 point 5: the sender's sync line, once per offer, only when no holder claimed the relay within RELAY_NOTICE_S and the mail
    is still unread (no result, not closed)."""
    out = []
    try:
        now = float(now if now is not None else time.time())
        mine = set(st.lineage(aid)) | {aid}
        evs = _relay_events(h)
        offers = [e for e in evs if e.get("type") == "nudge.relay_offer" and (e.get("data") or {}).get("from") in mine
                  and not (e.get("data") or {}).get("rewake") and RELAY_NOTICE_S <= now - float(e.get("t") or 0) < RELAY_TTL_S]
        if not offers:
            return out
        claimed = {(e.get("data") or {}).get("msg_id") for e in evs if e.get("type") == "nudge.relay_claim"}
        done = _results(h) | _closed(h)
        cp = _closed_pairs(h)
        p = _sp(h, aid)
        d0 = _load(p)
        shown = set(d0.get("relay_notice_shown") or [])
        for e in offers:
            d = e.get("data") or {}
            mid = d.get("msg_id")
            if mid in claimed or _done(done, cp, mid, d.get("to")) or mid in shown or d.get("to") in ((st.messages.get(mid) or {}).get("read_by") or []):
                continue
            out.append(f"relay for {mid} not claimed in {RELAY_NOTICE_S // 60} min, mail still unread")
            shown.add(mid)
        if out:
            d0["relay_notice_shown"] = sorted(shown)[-200:]
            _save(p, d0)
    except Exception:
        pass
    return out[:4]


def attach_relay(h, caller, r):
    """Add a claimed relay Do-line to a harness result: appended to its text, or as `relay` in a JSON result. Claims only when the result
    can carry it. Never raises."""
    try:
        if not isinstance(r, dict):
            return r
        line = claim_relay(h, caller) or live_claim_line(h, caller)     # item 18 point 1: a live claim repeats until handled
        rw = rewake_do(h, caller)                      # 0.24.0 (item 5, R2): a rewake the scan made for mail this agent sent
        wk = wake_do(h, caller)                        # 0.24.0 (item 13): verify a pending routine, or disable a replaced one
        line = " ; ".join([x for x in [line] + rw + [wk] if x])
        if not line:
            return r
        if isinstance(r.get("text"), str):
            return dict(r, text=line + "\n" + r["text"])           # item 18 point 1: the Do-line comes first
        return dict(r, relay=line)
    except Exception:
        return r


def outcomes(events):
    """Counts for the weekly report and R5 from a list of ledger events: offers, the sender's reported outcomes, and offers with NO result,
    split in two (critic): PENDING = the sender has made no later call yet, UNREPORTED = a later call came and still no result. A result
    always wins over an unreported flag. -> dict"""
    offers, results, unrep, refused = {}, {}, set(), {}
    for e in events:
        t, d = e.get("type"), e.get("data") or {}
        k = d.get("msg_id") or d.get("msg")
        if t == "nudge.relay_capped" and d.get("agent"):      # 0.22.5 (item 4): written only when a relayer reports refused_by_app
            refused[d["agent"]] = refused.get(d["agent"], 0) + 1
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
            "refused_by_app": sum(refused.values()), "refused_by_relayer": dict(sorted(refused.items())),
            "pending": len(no_result) - len(flagged), "unreported": len(flagged)}


# ---------------------------------------------------------------- /listen

def _lineage(st, aid):
    return set(st.lineage(aid))


def _role_ids(st, role):
    """0.26.0 (item 6): every agent that held `role` (its `role` field) with its predecessors: a reply from any of them answers mail
    addressed to the role, so a no-carry successor does not inherit items its predecessor answered."""
    out = set()
    r = str(role or "").lower()
    for a_, x in st.agents.items():
        if str(x.get("role") or "").lower() == r:
            out |= set(st.lineage(a_))
    for a_ in (getattr(st, "role_ever", None) or {}).get(role) or ():
        out |= set(st.lineage(a_))
    return out


def _answers(st, x, m, mid):
    """0.26.0 (item 7): does message `x` answer mail `m`? A reply_to it; or a ref to it in a result, notice or message sent to the original
    sender or the sender's role. A bare ref in a message to a third party never does."""
    if x.get("parent") == mid:
        return True
    # refs are stored as shared-file keys, so a message id arrives as "<home folder>/m-..."; match the id as the last path part
    if not any(r == mid or str(r).endswith("/" + mid) for r in (x.get("refs") or [])) or x.get("kind") not in ("result", "notice", "message"):
        return False
    frm = m.get("from")
    if frm == "human":
        return any(t in ("human", "operator") for t in x.get("to") or [])
    if set(x.get("to_resolved") or []) & set(st.lineage(frm)):
        return True
    role = st.role_of(frm) if frm in st.agents else None
    return bool(role and "role:%s" % role in (x.get("to") or []))


def _closed_for(st, mid, ids, roles=()):
    """0.26.0 (item 10): has a recipient of mail `mid` (any id in `ids`, or a holder of one of `roles`) dismissed it with owed.closed?"""
    keys = (getattr(st, "owed_closed", None) or {}).get(mid)
    if not keys:
        return False
    rs = {st.role_of(i) for i in ids if i in st.agents} | {r for r in roles if r}
    return bool(keys & (set(ids) | {"role:%s" % r for r in rs if r}))


def owed_closed(st, mid, mine, role):
    """0.26.0 (item 10): a role (or, with no role, the agent) dismissed this item with owed.closed; task state is untouched."""
    keys = (getattr(st, "owed_closed", None) or {}).get(mid) or set()
    return bool(keys & (set(mine) | ({"role:%s" % role} if role else set())))


def owed_replies(st, aid, cap=None):
    """Ids of task/question/review mail (or mail marked expects_reply) to this agent that it has not answered yet, oldest first. 0.25.0 (item 30):
    the ONE owed function: uncapped by default; the digest, the inbox footer and the vault all call it. `cap` keeps the newest n.
    0.26.0 (items 6 to 8, 10): an item clears on an answer (reply_to, or a ref in a result, notice or message to the original sender or its
    role) from the agent or, for mail addressed to a role, from any holder of that role; a co-recipient's debt also clears when another
    recipient's result to it completes the task, never on a later message alone; a role's owed.closed dismissal clears it too."""
    mine = _lineage(st, aid)
    role = st.role_of(aid)
    out = []
    refmap = {}                         # message id -> the later messages that cite it in refs (a ref answers across threads, item 7)
    for x_ in st.order:
        for r in st.messages[x_].get("refs") or []:
            k = str(r).rsplit("/", 1)[-1]
            if k.startswith("m-"):
                refmap.setdefault(k, []).append(st.messages[x_])
    for mid in st.order:
        m = st.messages[mid]
        if m["from"] in mine or is_system_sender(m["from"]):
            continue
        by_role = bool(role and f"role:{role}" in m["to"])
        if not (mine & set(m.get("to_resolved", [])) or by_role):
            continue
        if not (m["kind"] in ("task", "question", "review") or m.get("expects_reply")):
            continue
        if (st.tasks.get(mid) or {}).get("state") in TERMINAL:
            continue
        if owed_closed(st, mid, mine, role):
            continue
        who = set(mine) | (_role_ids(st, role) if by_role else set())
        # item 8 applies to mail sent to several named recipients; a broadcast ("*" or group:) is everyone's mail, no one's task to complete
        direct = not any(t == "*" or str(t).startswith("group:") for t in m.get("to") or [])
        others = set(m.get("to_resolved", [])) - mine if direct and len(m.get("to_resolved", [])) > 1 and not by_role else set()
        cleared = False
        for x in st.threads[m["thread"]]["messages"]:
            x = st.messages[x]
            if x["seq"] <= m["seq"]:
                continue
            if x["from"] in who:
                cleared = True                  # as in 0.25.0: any later message of the agent on the thread (item 6 adds the role's other holders)
                break
            if others and x["from"] in others and x.get("kind") == "result" and x.get("parent") == mid:
                cleared = True                  # item 8: another recipient's result completes it for the co-recipients
                break
        if not cleared:
            for x in refmap.get(mid, []):       # item 7: a ref to it in a result, notice or message to the sender or its role answers across threads
                if x["seq"] > m["seq"] and x["from"] in who and _answers(st, x, m, mid):
                    cleared = True
                    break
        if cleared:
            continue
        out.append(mid)
    return out[-cap:] if cap else out


def owed_age(st, mid, now=None):
    """'3d', '5h', '40m' since the mail was sent."""
    m = st.messages.get(mid) or {}
    sec = max(0, float(now if now is not None else getattr(st, "now", time.time())) - float(m.get("t") or 0))
    return "%dd" % (sec // 86400) if sec >= 86400 else "%dh" % (sec // 3600) if sec >= 3600 else "%dm" % (sec // 60)


OWED_LINES = 5


def owed_order(st, owed):
    """Raw read F6: what the footer, the digest and the structured field all show first: the operator's own asks (from=human), then the rest,
    each oldest first, so a fresh operator ask never hides under '+N more'. Round 6 (item 4): the operator's asks are NEWEST first, so the latest
    directive is always among the lines shown; the rest stay oldest first, and harness_admin op=owed lists every id."""
    human = [m for m in owed if (st.messages.get(m) or {}).get("from") in ("human", "operator")]
    return human[::-1] + [m for m in owed if m not in set(human)]


def owed_footer(st, owed):
    """0.26.0 (item 9): the inbox footer: one line per item, oldest first, with its age; items past the cap are one count line that names
    harness_admin op=owed. Nothing is hidden silently."""
    if not owed:
        return ""
    owed = owed_order(st, owed)
    lines = ["owed reply %d (operator first, then oldest first):" % len(owed)]
    for mid in owed[:OWED_LINES]:
        m = st.messages.get(mid) or {}
        lines.append("  %s %s %s" % (mid, owed_age(st, mid), m.get("kind") or ""))
    if len(owed) > OWED_LINES:
        lines.append("  +%d more (harness_admin op=owed lists every id)" % (len(owed) - OWED_LINES))
    return "\n" + "\n".join(lines)


def open_task(st, aid):
    """Computed from the ledger (never from the agent): non-terminal tasks assigned to this agent's lineage, plus
    task/question/review mail to it that it has not answered. -> (count, [message ids])."""
    mine = _lineage(st, aid)
    role = st.role_of(aid)
    ids = [k for k, tk in st.tasks.items() if mine & set(tk["to"]) and tk.get("state") not in TERMINAL and not owed_closed(st, k, mine, role)]
    for mid in owed_replies(st, aid):        # raw read F5: the mail part is the owed list itself, so /listen never arms on an item a role holder answered
        if mid not in ids and (st.messages[mid]["kind"] in ("question", "review") or st.messages[mid].get("expects_reply")):
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


def _answered(st, mid, rid, role=None):
    """0.25.0 (item 26): "reply" or "read" when the addressee has answered mail `mid` on its thread (any kind, a notice too) or read it,
    else None. The addressee is the recipient, its lineage (a successor's reply counts: the recipient is in the successor's lineage), and
    the role's current holder with its lineage. A reply on ANOTHER thread does not count (known and kept)."""
    m = st.messages.get(mid) or {}
    who = {rid} | set(st.lineage(rid) or [])
    hol = st.role_holder(role) if role else None
    if hol:
        who |= {hol} | set(st.lineage(hol) or [])
    for a_ in list(st.agents):                    # a successor: an agent whose lineage reaches the recipient
        if a_ not in who and rid in set(st.lineage(a_) or []):
            who.add(a_)
    for x in (st.threads.get(m.get("thread")) or {}).get("messages") or []:     # 0.26.0 (item 4): a reply is checked first (it also marks the mail read)
        mx = st.messages.get(x) or {}
        if x != mid and mx.get("from") in who and (mx.get("seq") or 0) > (m.get("seq") or 0):
            return "reply"
    if who & set(m.get("read_by") or []):
        return "read"
    if _closed_for(st, mid, who, [role] if role else []):
        return "closed"
    return None


def _dead_relay_mids(h, st, now):
    """0.25.0 (item 22): msg ids whose relay offer was closed trigger_dead, or whose offer names a routine that is dead now: the alarm scan
    ignores them (the nudge.miss is the audit record, not a signal)."""
    out = set()
    for e in _tail(h, needle=b'"relay.closed"'):
        if e.get("type") == "relay.closed" and (e.get("data") or {}).get("reason") == "trigger_dead":
            out.add((e.get("data") or {}).get("msg_id"))
    for e in _relay_events(h):
        d = e.get("data") or {}
        if e.get("type") == "nudge.relay_offer" and d.get("trigger") and trigger_dead(st, d["trigger"]):
            out.add(d.get("msg_id"))
    return out


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
        relay_expire(h, now)                         # 0.22.3: an expired relay offer becomes a skipped result before the alarm reads results
        st = h.state()
        evs = [e for e in _tail(h, needle=b'"nudge.') if e.get("type") in ("nudge.offered", "nudge.result", "nudge.unreported", "nudge.alarm", "nudge.alarm_armed", "nudge.alarm_closed")
               or (e.get("type") == "nudge.skipped" and str((e.get("data") or {}).get("reason") or "").startswith(HELD_REASONS))]
        # 0.24.0 (item 5 fix 1, envoy m-7ffa2d0bcd3c): mail that R2 or nb 6 held back is still unread mail; the alarm reads it as an id offer
        evs = [dict(e, type="nudge.offered", data={"msg_id": (e.get("data") or {}).get("msg"), "from": (e.get("data") or {}).get("from"),
                                                   "to": (e.get("data") or {}).get("to") or [], "by_id": [True], "held": True})
               if e.get("type") == "nudge.skipped" else e for e in evs]
        if not any(e["type"] == "nudge.offered" and any((e.get("data") or {}).get("by_id") or []) and float(e.get("t") or 0) >= now - 86400
                   for e in evs):
            return out                               # nothing could alarm: write nothing (a read-only call stays read-only)
        armed = next((e for e in evs if e["type"] == "nudge.alarm_armed"), None) or stamp.get("armed")
        if not armed:
            ev = h.store.append("nudge.alarm_armed", "system", {"t": round(now, 3)})
            stamp["armed"] = {"t": ev.get("t", now)}
            armed = stamp["armed"]
        armed_t = float((armed.get("data") or {}).get("t") or armed.get("t") or now) if isinstance(armed, dict) else now
        alarmed = {((e.get("data") or {}).get("msg_id"), (e.get("data") or {}).get("to")) for e in evs if e["type"] == "nudge.alarm"}     # round 7: per (message, recipient)
        a_closed = {((e.get("data") or {}).get("msg_id"), (e.get("data") or {}).get("to")) for e in evs if e["type"] == "nudge.alarm_closed"}
        for e in evs:                                # 0.25.0 (item 26): an open alarm closes when the addressee answered or read the mail
            d = e.get("data") or {}
            if e["type"] == "nudge.alarm" and (d.get("msg_id"), d.get("to")) not in a_closed and (d.get("msg_id"), None) not in a_closed \
                    and float(e.get("t") or 0) >= now - 86400:
                why = _answered(st, d.get("msg_id"), d.get("to"), d.get("role"))
                if why:
                    try:
                        h.store.append("nudge.alarm_closed", "system", {"msg_id": d.get("msg_id"), "to": d.get("to"), "reason": why})
                        a_closed.add((d.get("msg_id"), d.get("to")))
                    except Exception:
                        pass
        dead_mids = _dead_relay_mids(h, st, now)
        results = {(e.get("data") or {}).get("msg_id"): e.get("data") or {} for e in _drop_partial(evs) if e["type"] == "nudge.result"}
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
            if not mid or mid in dead_mids:
                continue                                 # 0.25.0 (item 22): a dead routine's offer raises no alarm
            m = st.messages.get(mid) or {}
            for i, rid in enumerate(d.get("to") or []):
                if not (d.get("by_id") or [])[i:i + 1] or not d["by_id"][i]:
                    continue                                 # A1 and A2 apply only when an id Do-line was offered (critic m-fcb579e7e932)
                if (mid, rid) in alarmed:
                    continue                                 # one alarm per (message, recipient)
                a = st.agents.get(rid) or {}
                if not (a.get("host_session_id") or "").startswith("local_"):
                    continue
                last = _last_activity(h, st, rid)
                if last is None or not (now - last <= act or abs(last - sent_t) <= act):
                    continue                                 # not active at send time or at scan time
                role = (d.get("roles") or [None] * (i + 1))[i] or st.role_of(rid)
                res = results.get(mid) or {}
                if _answered(st, mid, rid, role):         # 0.25.0 (item 26): the addressee replied on the thread or read the mail: no alarm
                    continue
                cond = reason = None
                if res.get("outcome") == "skipped" and not _is_cap(res.get("reason")) and res.get("reason") not in RELAY_NO_ALARM:
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
                alarmed.add((mid, rid))
                role_hour[role] = role_hour.get(role, 0) + 1
                out.append(data)
                if now - armed_t >= cfg["alarm_mail_after_days"] * 86400:
                    try:    # ids only, never subject or body text of the message
                        h.send(SYSTEM_SENDER, ["role:envoy"], f"nudge.alarm {mid} role {role} cond {cond} age {data['age_min']} min",
                               subject="nudge alarm", kind="notice")
                    except Exception:
                        pass
        stamp["suppressed_mids"] = sorted(sup_seen)[-500:]
        _save(sp, stamp)
    except Exception:
        pass
    return out


def alarm_lines(h, st, aid):
    """Sync 'Changed' lines: alarms in the last 24 h for this agent whose message it still has not read."""
    out = []
    try:
        evs_ = _tail(h, needle=b"nudge.alarm")
        shut = {((e.get("data") or {}).get("msg_id"), (e.get("data") or {}).get("to")) for e in evs_ if e.get("type") == "nudge.alarm_closed"}
        for e in evs_:
            d = e.get("data") or {}
            if e.get("type") == "nudge.alarm" and d.get("to") == aid and float(e.get("t") or 0) >= time.time() - 86400 \
                    and (d.get("msg_id"), d.get("to")) not in shut and (d.get("msg_id"), None) not in shut:
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
