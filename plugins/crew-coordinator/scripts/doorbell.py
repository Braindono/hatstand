"""Doorbell nudge on send + /listen self-wake bookkeeping (cc 0.15.5, WP4, H-020).

Design: plans/2026-10-14_h020-doorbell-design-and-test-plan.md; spec 2026-10-15-doorbell-listen-cc0155.md v2.
- The push is made by the SENDING chat's Claude (the server cannot call SendMessage): a send returns a `nudge`
  object whose `line` is ids-only (no message text). Every nudge or skip is a ledger event (nudge.sent /
  nudge.skipped {reason}).
- /listen is an opt-in self-wake. The OPERATOR enables roles in operator.json (never the agent-writable
  config.json). The harness decides from the ledger whether a task is open and whether to re-arm; the agent's own
  say-so is never an input. Arms expire (default 12 h, and when the agent hands off or is superseded).
- A wake may run harness_inbox and routine coordination only; wake_guard() refuses everything gated.
All reads scan the ledger tail (bounded by the window), so a call costs O(recent events)."""
import time

NUDGE_KINDS = ("task", "question", "review", "handoff", "result")   # notice / plain message start no wake
TERMINAL = ("completed", "failed", "canceled", "rejected")
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
            "interval_min": 10, "max_per_hour": 6, "expire_h": 12, "wake_window_min": 15}
BOUNDS = {"nudge_per_agent_hour": (1, 60), "nudge_per_pair_hour": (1, 30), "global_per_hour": (1, 120),
          "interval_min": (5, 120), "max_per_hour": (1, 12), "expire_h": (1, 48), "wake_window_min": (5, 60)}


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

def attach_nudge(h, sender_ref, result):
    """Add `nudge` (and `skipped`) to a send result. Never raises; a failure leaves the result as it was."""
    try:
        return _attach(h, sender_ref, result)
    except Exception:
        return result


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
    hour = _recent(h, now - 3600, ("nudge.sent", "nudge.skipped"))
    sent = [e for e in hour if e["type"] == "nudge.sent"]
    seen_msg = {e["data"].get("msg") for e in _recent(h, now - 86400, ("nudge.sent",))}
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
    sname = (st.agents.get(sender) or {}).get("sobriquet") or sender[:8]
    srole = st.role_of(sender)
    line = (f"Mail {mid} from {srole or sname}, thread {m['thread']}. Run harness_inbox (CLI: harness.py inbox --agent "
            f"<your id> --peek), reply with send reply_to {mid}.")
    ids = [rid for rid, _ in targets]
    h.store.append("nudge.sent", "system", {"msg": mid, "from": sender, "to": ids, "thread": m["thread"]})
    n_hour = sum(1 for e in sent if e["data"].get("from") == sender) + 1
    out["nudge"] = {"line": line, "to": [a.get("sobriquet") for _, a in targets], "msg_id": mid, "thread": m["thread"],
                    "cap_state": f"{n_hour}/{cfg['nudge_per_agent_hour']} this hour",
                    "do": "Do: SendMessage to " + " and ".join(a.get("sobriquet") or rid[:8] for rid, a in targets)
                          + f": {line} (skip if ListAgents does not list it; the mail waits)"}
    return out


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
    glob = len(_recent(h, now - 3600, ("nudge.sent", "listen.wake")))
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
