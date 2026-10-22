"""Context gauge + state-note hook (PostToolUse + UserPromptSubmit). Costs 0 model tokens unless it injects.

Gauge: exact ctx from the transcript's last usage record, per-model window (window_for).
hr 0.12.2 (design specs/2026-09-30-design-hr-0.12.2-restore.md): absolute thresholds win: ctx_plan_tokens
(130k) / ctx_handoff_tokens (160k), config keys, 0 = off -> the older pct bands ctx_plan/ctx_handoff of working
headroom (ctx_mode baseline|absolute). Defaults live here too: cloud hooks see no config (F1).
Cold cache (§3): on UserPromptSubmit, last usage record >60 min old and ctx >= plan -> suggest /restore.
State note (§C3 + envoy C3): harness send/commit/claim/record set a dirty flag in <state dir>/harness-note-<sid>.json;
any harness_* call with a non-empty state_note (or role-state tags) clears it; while dirty, one inject per
operator turn. Steward runs ("[scheduled] corpus-steward pass") never get it.
Idle wake v2 (hr 0.12.4, opt-in per project via config idle_wake_projects; the server prints "idle-wake: on (55m)"):
state in <state dir>/harness-idle-<sid>.json. Operator prompts stamp + arm (once per 55 min); notification wrappers
never stamp and are checked against the armed nonce; steward runs never arm."""
import json
import os
import re
import secrets
import sys
import tempfile
import time
from datetime import datetime

# D-5d771 (amended by D-8ee87): plan/handoff are a share of the surface's window; window per model x surface.
# Haiku is always an ephemeral subagent: "silent" = no plan or handoff point, the hook prints no ctx text.
SURFACES = ("code", "chat", "cowork")
CTX_TABLE = {
    "claude-opus-5-5": {"plan": 0.60, "handoff": 0.80,
                        "window": {"code": 500000, "chat": 500000, "cowork": 500000}},    # code unmeasured, conservative
    "claude-sonnet-5-5": {"plan": 0.60, "handoff": 0.80,
                          "window": {"code": 1000000, "chat": 500000, "cowork": 500000}},  # measured
    "claude-haiku": {"silent": True, "window": {"code": 200000, "chat": 200000, "cowork": 200000}},
}
COLD_S = 3600
STEWARD = ("[scheduled] corpus-steward pass", "[scheduled] steward pass")   # 0.16.0: both prompts (the schedule is renamed later)
DIRTY_TOOLS = ("harness_send", "harness_commit", "harness_claim", "harness_record")
WAKE = "[idle-handoff]"
LISTEN = "/listen"
IDLE_MIN = 55
ROLE_UNSET_LINE = "Role unset: propose a one-line role, ask the operator to confirm, then harness_admin op=set_expertise."
NOTE_LINE = "State changed: add state_note= to your next harness call."


NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)


def state_dir():
    """0.15.1 (P5): per-user state dir (0700) instead of the shared /tmp. HARNESS_STATE_DIR overrides (tests)."""
    d = os.environ.get("HARNESS_STATE_DIR") or os.path.expanduser("~/.claude/crew-coordinator/state")
    try:
        os.makedirs(d, mode=0o700, exist_ok=True)
        if hasattr(os, "getuid") and os.stat(d).st_uid == os.getuid():
            os.chmod(d, 0o700)
    except OSError:
        pass
    return d


def state_path(name):
    return os.path.join(state_dir(), name)


def read_state(path):
    """Text of a state file, or '' (never follows a symlink)."""
    try:
        fd = os.open(path, os.O_RDONLY | NOFOLLOW)
        with os.fdopen(fd, encoding="utf-8") as f:
            return f.read()
    except (OSError, ValueError):
        return ""


def write_state(path, text):
    """Write a state file: refuse a symlink at the target, then mkstemp (O_EXCL, 0600) in the same dir + replace."""
    if os.path.islink(path):
        raise OSError("state file is a symlink; refused")
    d = os.path.dirname(path)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=os.path.basename(path) + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def home_cfg():
    home = os.environ.get("HARNESS_HOME") or os.path.expanduser("~/Claude/Projects/Exchange")
    try:
        return json.load(open(os.path.join(home, "_harness", "config.json")))
    except Exception:
        return {}


_DESKTOP_HOME = re.compile(r"^/(?:Users|home)/([^/]+)/\.claude/projects/")


def surface_src(path=None):
    """-> (surface, source); source is explicit | path | unknown. Explicit HARNESS_SURFACE always wins.
    0.15.5 (WP1.1): "code" by path only under a desktop user home (/Users/<name>/.claude/projects/ or
    /home/<name>/.claude/projects/, name not "claude"). Cloud paths (/root/.claude/..., /sessions/...) and any
    other path that merely contains /.claude/projects/ are "unknown" (smallest window of the model row)."""
    s = (os.environ.get("HARNESS_SURFACE") or "").strip().lower()
    if s in SURFACES:
        return s, "explicit"
    p = str(path or "").replace("\\", "/")
    if "/local-agent-mode-sessions/" in p:
        return "cowork", "path"
    m = _DESKTOP_HOME.match(p)
    if m and m.group(1) != "claude":
        return "code", "path"
    return "unknown", "unknown"


def surface(path=None):
    """code | chat | cowork | unknown (see surface_src)."""
    return surface_src(path)[0]


PRECOMPACT_PREFIX = "harness-precompact-"
_SID_OK = re.compile(r"[^A-Za-z0-9_-]")


def precompact_stub(sid, agent, role, trigger, now=None):
    """0.15.5 (WP1.4, curator ruling m-2f799cf488db): marker + one-line stub in the per-user state dir only.
    Temp file then os.link (never overwrites), unique per session and call, no ledger call. -> path or None
    (fail open: any error returns None). The next harness_sync/register turns it into a role-state record."""
    try:
        d = state_dir()
        t = int(now if now is not None else time.time())
        sid = _SID_OK.sub("", str(sid or "nosid"))[:64] or "nosid"
        final = os.path.join(d, f"{PRECOMPACT_PREFIX}{sid}-{t}-{secrets.token_hex(3)}.json")
        stamp = datetime.fromtimestamp(t).strftime("%Y-%m-%d %H:%M")
        rec = {"v": 1, "agent": str(agent), "role": str(role), "t": t, "trigger": str(trigger or "")[:16],
               "stub": f"pre-compaction auto-save {stamp} ({str(trigger or 'auto')[:16]}): pending actions not captured; "
                       "run /update, check Owes reply and unread mail, then rewrite this note."}
        fd, tmp = tempfile.mkstemp(dir=d, prefix=PRECOMPACT_PREFIX, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(rec, f)
            os.chmod(tmp, 0o600)
            os.link(tmp, final)
        finally:
            try:
                os.unlink(tmp)
            except OSError:
                pass
        return final
    except Exception as e:
        try:
            _log("precompact", e)
        except Exception:
            pass
        return None


def take_precompact(agent):
    """-> list of stub records for this agent (files removed once read). Never raises."""
    out = []
    try:
        d = state_dir()
        for n in sorted(os.listdir(d)):
            if not (n.startswith(PRECOMPACT_PREFIX) and n.endswith(".json")):
                continue
            p = os.path.join(d, n)
            try:
                rec = json.loads(read_state(p))
            except ValueError:
                rec = None
            if isinstance(rec, dict) and rec.get("agent") == agent and isinstance(rec.get("stub"), str):
                out.append(rec)
                try:
                    os.unlink(p)
                except OSError:
                    pass
    except Exception:
        pass
    return out


def _longest(table, model):
    m = str(model or "")
    hits = [k for k in table if k and m.startswith(k)]
    return max(hits, key=len) if hits else None


def limits(model=None, path=None, c=None):
    """-> {window, plan, handoff (share), plan_tok, handoff_tok (0 = off), silent, surface}.
    Table value by model prefix x surface; config ctx_table merges over it, ctx_window_by_model (flat) wins for
    any surface, ctx_plan_tokens / ctx_handoff_tokens > 0 override the thresholds. Unlisted model:
    HARNESS_CTX_WINDOW or config ctx_window or 200k, shares from config ctx_plan / ctx_handoff (default 60/80)."""
    c = home_cfg() if c is None else c
    surf = surface(path)
    table = {k: {**v, "window": dict(v.get("window") or {})} for k, v in CTX_TABLE.items()}
    for k, v in (c.get("ctx_table") or {}).items():
        if isinstance(v, dict):
            row = table.setdefault(k, {"window": {}})
            row.update({x: y for x, y in v.items() if x != "window"})
            if isinstance(v.get("window"), dict):
                row["window"].update(v["window"])
    key = _longest(table, model)
    row = table.get(key) if key else None
    if row:
        wins = [int(x) for x in row["window"].values()] or [int(c.get("ctx_window", 200000))]
        w = int(row["window"].get(surf) or min(wins))
        plan, hand, silent = float(row.get("plan", 0.6)), float(row.get("handoff", 0.8)), bool(row.get("silent"))
    else:
        w = int(os.environ.get("HARNESS_CTX_WINDOW") or c.get("ctx_window", 200000))
        plan, hand, silent = float(c.get("ctx_plan", 0.6)), float(c.get("ctx_handoff", 0.8)), False
    over = c.get("ctx_window_by_model") or {}
    ok = _longest(over, model)
    if ok:
        w = int(over[ok])
    pt = 0 if silent else int(w * plan)
    nt = 0 if silent else int(w * hand)
    pt = int(c.get("ctx_plan_tokens") or 0) or pt
    nt = int(c.get("ctx_handoff_tokens") or 0) or nt
    return {"window": w, "plan": plan, "handoff": hand, "plan_tok": pt, "handoff_tok": nt,
            "silent": silent, "surface": surf}


def window_for(model=None, c=None, path=None):
    return limits(model, path, c)["window"]


def cfg(model=None, path=None, c=None):
    """-> (window, plan_pct, handoff_pct, mode, plan_tokens, handoff_tokens); token thresholds 0 = off.
    Mode default "absolute" (tokens = window x share); an explicit "baseline" uses the shares of headroom."""
    c = home_cfg() if c is None else c
    L = limits(model, path, c)
    mode = c.get("ctx_mode", "absolute")
    if mode not in ("baseline", "absolute"):
        mode = "absolute"
    pt, nt = L["plan_tok"], L["handoff_tok"]
    if mode == "baseline" and not L["silent"]:
        pt, nt = int(c.get("ctx_plan_tokens") or 0), int(c.get("ctx_handoff_tokens") or 0)
    return L["window"], L["plan"], L["handoff"], mode, pt, nt


def _usage_n(u):
    return sum(int(u.get(k) or 0) for k in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"))


def band_for(ctx, baseline=0, win=None, plan=None, now=None, mode=None, plan_tok=None, now_tok=None,
             model=None, path=None, c=None):
    """Shared by the hook and harness.py ctx_band(): -> (band, pct); band is "ok"|"plan"|"now".
    Absolute token thresholds (plan_tok/now_tok; None = from the table/config, 0 = off) win over the pct bands.
    pct (always returned, for display): baseline mode (ctx-baseline)/(win-baseline); else ctx/win.
    A silent model (Haiku, D-8ee87) is always "ok"."""
    w, p, n, m, pt, nt = cfg(model, path, c)
    win, plan, now, mode = win or w, plan or p, now or n, mode or m
    pt = pt if plan_tok is None else int(plan_tok or 0)
    nt = nt if now_tok is None else int(now_tok or 0)
    b = int(baseline or 0) if mode == "baseline" else 0
    if b <= 0 or b >= win:
        b = 0
    pct = (int(ctx) - b) / max(1, win - b)
    if limits(model, path, c)["silent"]:
        return "ok", pct
    if pt or nt:
        return ("now" if nt and int(ctx) >= nt else "plan" if pt and int(ctx) >= pt else "ok"), pct
    return ("now" if pct >= now else "plan" if pct >= plan else "ok"), pct


def _tail_lines(path, n=400000):
    with open(path, "rb") as f:
        f.seek(0, 2)
        f.seek(max(0, f.tell() - n))
        return f.read().decode("utf-8", "ignore").splitlines()


def _ts(v):
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


def last_usage_rec(path):
    """(ctx, model, epoch) from the transcript's last non-empty usage record, else (None, None, None)."""
    try:
        lines = _tail_lines(path)
    except Exception:
        return None, None, None
    for ln in reversed(lines):
        if '"usage"' not in ln:
            continue
        try:
            j = json.loads(ln)
        except Exception:
            continue
        msg = j.get("message") or {}
        n = _usage_n(msg.get("usage") or {})
        if n:
            return n, msg.get("model"), _ts(j.get("timestamp"))
    return None, None, None


def last_usage(path):
    """(ctx, model) from the transcript's last non-empty usage record, else (None, None)."""
    return last_usage_rec(path)[:2]


def last_ctx(path):
    return last_usage(path)[0]


def first_ctx_and_count(path):
    """First usage record in the transcript (fixed overhead: system prompt + tool schemas), and
    how many usage records exist at all (a lone record can't give a meaningful baseline)."""
    first, count = None, 0
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            for ln in f:
                if '"usage"' not in ln:
                    continue
                try:
                    u = (json.loads(ln).get("message") or {}).get("usage") or {}
                except Exception:
                    continue
                n = _usage_n(u)
                if n:
                    count += 1
                    if first is None:
                        first = n
    except Exception:
        return None, 0
    return first, count


def _tool_output_size(resp):
    """Extract text size from tool response (chars). Returns None if no text."""
    text = _text(resp) if resp is not None else ""
    return len(text) if text else None


_BAND_RANK = {"": 0, "plan": 1, "now": 2}


def _log(where, exc):
    """0.15.3 (P7): hook failures are never shown to the chat, but they are not lost: one line in the state dir,
    capped at 20 KB (the file is replaced, not appended, when it grows past the cap)."""
    try:
        p = state_path("harness-ctx-hook.log")
        old = read_state(p)
        if len(old) > 20000:
            old = ""
        write_state(p, old + f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {where}: {type(exc).__name__}: {str(exc)[:200]}\n")
    except Exception:
        pass


def gauge(inp, path):
    ctx, model = last_usage(path)
    if not ctx:
        return None
    L = limits(model, path)
    if L["silent"]:    # D-8ee87: Haiku is ephemeral, no plan/handoff point
        return None
    win, plan, now, mode, pt, nt = cfg(model, path)
    baseline = 0
    if mode == "baseline":
        first, count = first_ctx_and_count(path)
        if first is not None and count > 1 and first < win:
            baseline = first
    band, pct = band_for(ctx, baseline, win, plan, now, mode, pt, nt)
    band = "" if band == "ok" else band
    mark = state_path(f"harness-ctx-{_sid(inp)}")
    seen = read_state(mark).strip()
    # 0.15.3 (P7): after /compact or a handoff the context falls back; a band that was already told must not stay
    # "seen" forever, or the next climb is silent. Reset when the current band is lower than the remembered one.
    if seen and _BAND_RANK.get(band, 0) < _BAND_RANK.get(seen, 0):
        write_state(mark, band)
        seen = band
    
    # B1 (P3): Adaptive urgent warning based on tool output sizes
    sizes_path = state_path(f"harness-sizes-{_sid(inp)}")
    try:
        sizes_data = json.loads(read_state(sizes_path))
        if not isinstance(sizes_data, dict):
            raise ValueError
    except Exception:
        sizes_data = {"sizes": [], "warned": False}
    last_sizes = sizes_data.get("sizes", [])
    max_recent_size = max(last_sizes) if last_sizes else 0
    limit = nt if nt else int(win * now)   # fix 10: never 0
    warning_threshold = max(int(0.10 * limit), 2 * max_recent_size)
    
    # Check if we're approaching handoff threshold
    handoff_val = nt if (pt or nt) else int(win * now) if mode == "baseline" else int(win * now)
    distance_to_handoff = handoff_val - ctx if (pt or nt) else (handoff_val - ctx)
    adaptive_warn = distance_to_handoff < warning_threshold and warning_threshold > 0
    
    # Reset warned flag if context dropped back above the line
    if not adaptive_warn and sizes_data.get("warned"):
        sizes_data["warned"] = False
        write_state(sizes_path, json.dumps(sizes_data))
    
    if not band or band == seen or (seen == "now"):
        if not adaptive_warn:
            return None
        if sizes_data.get("warned"):
            return None
        sizes_data["warned"] = True
        write_state(sizes_path, json.dumps(sizes_data))
        band = "adaptive-warn"
    
    write_state(mark, band)
    k = ctx // 1000
    if pt or nt:
        pk, nk = (pt or int(win * plan)) // 1000, (nt or int(win * now)) // 1000
        head = f"Context {k}k (plan {pk}k, handoff {nk}k; {win // 1000}k window)."
        due = f"{nk}k"
    elif baseline:
        head = f"Context {pct:.0%} of working headroom ({k}k used, {baseline // 1000}k baseline, {win // 1000}k window)."
        due = f"{now:.0%}"
    else:
        head = f"Context {pct:.0%} ({k}k of {win // 1000}k)."
        due = f"{now:.0%}"
    return (f"{head} Report it now: harness_sync agent=<your short id> ctx={ctx}" + (f" base={baseline}" if baseline else "") + ". "
            + ("Then run /handoff before doing more work." if band == "now"
               else f"Plan a handoff at a natural break; it becomes mandatory at {due}."))


# ---- cold cache (hr 0.12.2 §3) ----

def cold(inp, t):
    path = inp.get("transcript_path") or ""
    ctx, model, ts = last_usage_rec(path)
    if not ctx or not ts:
        return None
    if limits(model, path)["silent"]:
        return None
    w, plan, _, _, pt, nt = cfg(model, path)
    thr = pt or nt or int(w * plan)
    gap = t - ts
    if not thr or gap <= COLD_S or ctx < thr:
        return None
    return (f"Cache is cold ({int(gap // 60)} min, N={ctx // 1000}k): if more work follows, "
            "suggest /restore <role> in a new chat.")


# ---- state-note dirty flag (hr 0.12.2 §C3, envoy C3) ----

def _sid(inp):
    return re.sub(r"[^A-Za-z0-9_.-]", "_", str(inp.get("session_id") or "x"))


def note_path(inp):
    return state_path(f"harness-note-{_sid(inp)}.json")


def load_note(p):
    try:
        s = json.loads(read_state(p))
        return s if isinstance(s, dict) else {}
    except Exception:
        return {}


def save_note(p, s):
    write_state(p, json.dumps(s))


def idle_path(inp):
    return state_path(f"harness-idle-{_sid(inp)}.json")


def armed(s, t):
    return bool(s.get("trig_id")) and float(s.get("fires_at") or 0) > t


def _text(x):
    """Flatten a tool_response (str | dict | list of content blocks) into text."""
    if x is None:
        return ""
    if isinstance(x, str):
        return x
    if isinstance(x, list):
        return "\n".join(_text(i) for i in x)
    if isinstance(x, dict):
        if isinstance(x.get("text"), str):
            return x["text"]
        if "content" in x:
            return _text(x["content"])
        return json.dumps(x)
    return str(x)


BIND_TOOLS = ("harness_register", "harness_restore")
_BANNER_TOP = re.compile(r"^[ \t]*\u256d\u2500 CREW COORDINATOR\b")
_BANNER_ID = re.compile(r"^[ \t]*\u2502 id: ([0-9a-f]{64})[ \t]*$")


def banner_head(inp):
    """0.15.1 (P6): the verified banner of a harness_register / harness_restore / harness_admin op=whoami result:
    -> {"line": the '◆ name #id ...' line, "id": 64 hex} or None. Only the FIRST lines of the result count and the
    box must carry `id: <64 hex>`; banner-looking text anywhere else (a file read, mail, a pasted ledger) is ignored."""
    name = str(inp.get("tool_name") or "")
    ti = inp.get("tool_input") if isinstance(inp.get("tool_input"), dict) else {}
    ok = name.endswith(BIND_TOOLS) or (name.endswith("harness_admin") and str(ti.get("op") or "") == "whoami")
    if not ok or not re.search(r"harness_[a-z_]+$", name):
        return None
    lines = _text(inp.get("tool_response")).splitlines()
    first = [i for i, l in enumerate(lines[:6]) if l.strip()]
    if not first or not _BANNER_TOP.match(lines[first[0]]) or first[0] > 2:
        return None
    top, diamond, ident = first[0], None, None
    for l in lines[top + 1: top + 14]:
        if l.lstrip().startswith("\u2570"):
            break
        t = l.strip()
        if diamond is None and re.match(r"^\u2502 \u25c6 ", t):
            diamond = t[1:].strip()
        m = _BANNER_ID.match(l)
        if m:
            ident = m.group(1)
    if diamond and ident:
        return {"line": diamond, "id": ident}
    return None


def _epoch(v):
    try:
        if isinstance(v, (int, float)):
            return float(v)
        return datetime.fromisoformat(str(v).replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


def parse_trigger(resp):
    """(trigger_id, fire_at_epoch) from a send_later result. JSON first, regex fallback."""
    raw = resp if isinstance(resp, dict) and "trigger_id" in resp else None
    txt = _text(resp)
    if raw is None:
        for cand in (txt, txt[txt.find("{"):txt.rfind("}") + 1] if "{" in txt else ""):
            try:
                j = json.loads(cand)
            except Exception:
                continue
            if isinstance(j, dict) and j.get("trigger_id"):
                raw = j
                break
    if raw is not None:
        return str(raw.get("trigger_id")), _epoch(raw.get("fire_at"))
    m = re.search(r"trig_[A-Za-z0-9]+", txt)
    f = re.search(r'"fire_at"\s*:\s*"([^"]+)"', txt)
    return (m.group(0) if m else None), (_epoch(f.group(1)) if f else None)


def is_wrapper(prompt):
    """A notification wrapper (a fired trigger delivered as a prompt), not an operator prompt.
    Cowork delivers it as '<task-notification>' with '1 unread notification (scheduled trigger…)'
    (events 10-01, N-03dd9). Anchored to the first 3 non-empty lines so an operator prompt that
    merely mentions 'scheduled trigger' is still stamped (A8)."""
    if prompt.startswith(WAKE):
        return True
    head = [ln.strip().lower() for ln in prompt.split("\n") if ln.strip()][:3]
    return any(re.match(r"(<task-notification\b|\[?\d*\s*unread notifications?\b|\[?scheduled trigger\b)", ln)
               for ln in head)


def idle_prompt(inp, t, steward):
    """UserPromptSubmit idle logic (D4, D5, D7). -> inject text or None."""
    p = idle_path(inp)
    s = load_note(p)
    prompt = str(inp.get("prompt") or "").lstrip()
    # F2: after handoff/supersede, a wake (or wrapper) is stale; operator prompts pass through
    if (s.get("handed_off") or s.get("superseded")) and is_wrapper(prompt):
        return 'Stale idle wake. Reply "·" and stop.'
    if prompt.startswith(LISTEN):   # 0.15.5 (WP4): the /listen self-wake is not operator activity (never stamps idle-wake)
        return None
    if steward:
        s["steward"] = True
        save_note(p, s)
        return None
    if is_wrapper(prompt):    # D5: never stamp
        if prompt.startswith(WAKE):
            parts = prompt.split()
            nonce = parts[1].strip("[]") if len(parts) > 1 else ""
            if not s.get("trig_id") or not nonce or s.get("nonce") != nonce:
                return 'Stale idle wake. Reply "·" and stop. Do not re-arm.'
            s["trig_id"], s["fires_at"] = "", 0    # the one-shot fired
            save_note(p, s)
            last_prompt_ts = float(s.get("last_prompt_ts") or 0)
            arm_ts = float(s.get("arm_ts") or 0)
            if last_prompt_ts > arm_ts:
                # 0.15.5 (WP2f): a fire skipped because the operator was active re-arms itself, every time, with a fresh
                # nonce (the old one is now stale, so timers never stack). A fire that finds the chat idle hands off and
                # does not re-arm; a handed-off or superseded chat never reaches here (stale check above).
                nonce = secrets.token_hex(3)
                proj = re.sub(r"[^A-Za-z0-9_.-]", "_", s.get("project") or os.path.basename(str(inp.get("cwd") or "").rstrip("/")) or "p")
                minutes_since = max(0, int((t - last_prompt_ts) / 60))
                delay = max(5, IDLE_MIN - minutes_since)
                s["nonce"], s["arm_ts"] = nonce, t
                s["rearmed"] = True
                save_note(p, s)
                return (f'Operator active since arming. Reply "·" and stop. Re-armed: alongside your next tool call, call send_later(delay_minutes={delay}, '
                        f'name="idle-handoff {proj} {nonce}", message="{WAKE} {nonce}")')
            s["rearmed"] = False
            save_note(p, s)
            return "Idle wake. Run /handoff and stop."
        if not s.get("on") or not s.get("trig_id") or not s.get("nonce"):
            return None    # someone else's notification (mail, GitHub, reminders): pass through
        return (f'Call ReadNotifications. If a body is "{WAKE} {s["nonce"]}" and no operator prompt since arming: '
                'run /handoff and stop. Handle any other notifications normally. Re-arm only when the wake is skipped because the operator was active.')
    s["last_prompt_ts"] = t
    msg = None
    if s.get("on") and not s.get("steward") and t - float(s.get("arm_ts") or 0) >= IDLE_MIN * 60:
        nonce = secrets.token_hex(3)
        proj = re.sub(r"[^A-Za-z0-9_.-]", "_", s.get("project") or os.path.basename(str(inp.get("cwd") or "").rstrip("/")) or "p")
        s["nonce"], s["arm_ts"] = nonce, t
        s["rearmed"] = False    # A8: a fresh arm starts a new cycle
        msg = (f'Idle wake: alongside your next tool call, call send_later(delay_minutes={IDLE_MIN}, '
               f'name="idle-handoff {proj} {nonce}", message="{WAKE} {nonce}")')
        if armed(s, t):
            msg += f', then update_trigger(trigger_id="{s["trig_id"]}", enabled=false)'
        msg += ". Use only the id in this chat's state file; scheduled tasks are never deleted here (the Idle-handoff cleanup runner does that)."
    save_note(p, s)
    return msg


def idle_tool(inp, t):
    """PostToolUse idle logic (D3, D6): idle-wake on/off from responses; capture the armed send_later;
    update_trigger on the armed id (or a manual delete elsewhere) clears it. This code never asks for a delete (D-314f2)."""
    name = str(inp.get("tool_name") or "")
    ti = inp.get("tool_input") or {}
    if not isinstance(ti, dict):
        ti = {}
    p = idle_path(inp)
    s = load_note(p)
    ch = False
    
    # F1: disarm only when the handoff/restore response shows success
    ret = None
    if name.endswith("harness_handoff"):
        htxt = _text(inp.get("tool_response"))
        if re.search(r"(?m)^handoff-ok m-[0-9a-f]+", htxt):
            s["handed_off"] = True
            s["on"] = False
            if s.get("trig_id"):
                ret = f'Idle-wake disarmed: call update_trigger(trigger_id="{s["trig_id"]}", enabled=false)'
                s["trig_id"], s["fires_at"] = "", 0
            ch = True
    elif name.endswith("harness_restore"):
        rtxt = _text(inp.get("tool_response"))
        if "agent was superseded" in rtxt.lower():
            s["handed_off"] = True
            s["on"] = False
            if s.get("trig_id"):
                ret = f'Idle-wake disarmed: call update_trigger(trigger_id="{s["trig_id"]}", enabled=false)'
                s["trig_id"], s["fires_at"] = "", 0
            ch = True
    txt = _text(inp.get("tool_response")) if re.search(r"harness_[a-z_]+$", name) else ""
    bh = banner_head(inp)
    ln = bh["line"] if bh else ""
    segs = [x.strip() for x in ln.split(" · ")]
    if len(segs) >= 3 and re.fullmatch(r"[A-Za-z0-9_.-]+", segs[-1]) and s.get("project") != segs[-1]:
        s["project"] = segs[-1]
        ch = True
    hits = re.findall(r"(?m)^idle-wake: (on|off)\b", "\n".join(txt.splitlines()[-3:]))   # server tail lines only
    if hits:
        s["on"] = hits[-1] == "on"
        ch = True
    if name.endswith("send_later") and str(ti.get("message") or "").startswith(WAKE):
        trig, fire = parse_trigger(inp.get("tool_response"))
        if trig:
            parts = str(ti["message"]).split()
            s["trig_id"] = trig
            s["fires_at"] = fire or t + 60 * float(ti.get("delay_minutes") or IDLE_MIN)
            if len(parts) > 1:
                s["nonce"] = parts[1].strip("[]")
            ch = True
    elif name.endswith(("update_trigger", "delete_trigger")):
        if s.get("trig_id") and str(ti.get("trigger_id") or "") == s["trig_id"]:
            s["trig_id"], s["fires_at"] = "", 0
            ch = True
    if ch:
        save_note(p, s)
    return ret


def on_prompt(inp, t=None):
    """UserPromptSubmit: reset the once-per-turn flag, mark steward runs, run idle-wake. -> inject or None."""
    t = time.time() if t is None else t
    p = note_path(inp)
    s = load_note(p)
    steward = str(inp.get("prompt") or "").lstrip().startswith(STEWARD)
    if steward:
        s["steward"] = True
    s["told"] = False
    save_note(p, s)
    return idle_prompt(inp, t, steward or bool(s.get("steward")))


def _has_note(ti):
    if str(ti.get("state_note") or "").strip():
        return True
    tags = ti.get("tags")
    return isinstance(tags, list) and any(str(x).strip().lower().startswith("role-state") for x in tags)


UNREAD_AGE_S = 120        # mail must be this old before the line appears
UNREAD_EVERY_S = 600      # and the line shows at most once per this many seconds per chat


def _unread_line(inp):
    """0.16.0 (spec bind-send-visibility C): on a non-harness tool result, one counts-only line when the chat has unread
    mail older than 2 minutes, at most once per 10 minutes. Reads the marker file the server keeps (no ledger replay, no
    sender or subject text); the chat is told to run harness_inbox. Never wakes an idle chat and never polls."""
    p = note_path(inp)
    s = load_note(p)
    ag = s.get("agent")
    if not ag or s.get("steward") or not re.fullmatch(r"[0-9a-f]{8}", str(ag)):
        return None
    try:
        mk = json.loads(read_state(state_path(f"harness-unread-{ag}.json")))
        n, oldest = int(mk["n"]), float(mk["oldest"])
    except Exception:
        return None
    now = time.time()
    if n <= 0 or now - oldest < UNREAD_AGE_S or now - float(s.get("unread_shown") or 0) < UNREAD_EVERY_S:
        return None
    s["unread_shown"] = now
    save_note(p, s)
    return f"\u2709{n} unread mail for you (oldest {int((now - oldest) // 60)} min): run harness_inbox."


def on_tool(inp):
    """PostToolUse: any harness_* call with a state note clears dirty (unless the server rejected it);
    send/commit/claim/record without one set it. Track norole from response. -> the reminder once per operator turn, or None."""
    # B1 (P3): Track last 3 tool output sizes for adaptive warning (store as tokens: chars//4) - do this for all tools
    if True:   # fix 10: harness_* outputs count too
        size_chars = _tool_output_size(inp.get("tool_response"))
        if size_chars is not None:
            size_tokens = size_chars // 4
            sizes_path = state_path(f"harness-sizes-{_sid(inp)}")
            try:
                sizes_data = json.loads(read_state(sizes_path))
                if not isinstance(sizes_data, dict):
                    raise ValueError
            except Exception:
                sizes_data = {"sizes": [], "warned": False}
            sizes_data["sizes"] = (sizes_data.get("sizes", []) + [size_tokens])[-3:]  # keep last 3
            try:
                write_state(sizes_path, json.dumps(sizes_data))
            except Exception:
                pass  # never crash on sizes file write
    
    m = re.search(r"harness_[a-z_]+", str(inp.get("tool_name") or ""))
    if not m:
        return _unread_line(inp)
    tool = m.group(0)
    ti = inp.get("tool_input") or {}
    if not isinstance(ti, dict):
        ti = {}
    rtxt = _text(inp.get("tool_response"))
    p = note_path(inp)
    s = load_note(p)

    # B: norole from the "◆ name #id · <role|role unset> [· project]" line; register/sync also append "Role unset: propose ..."
    # 0.15.1 (P6): only the verified banner head of register/restore/whoami counts, never text elsewhere in a result
    bh = banner_head(inp)
    line = bh["line"] if bh else None
    if bh:
        s["agent"] = bh["id"][:8]      # 0.16.0: lets the unread line find this chat's marker file
    if line is not None:
        s["norole"] = bool(re.search(r"(?:^|·)\s*role unset\s*(?:·|$)", line.strip()))
    elif tool in ("harness_sync", "harness_register", "harness_restore") and any(
            l.strip() == ROLE_UNSET_LINE for l in rtxt.splitlines()[-3:]):   # the server's own appended tail line
        s["norole"] = True
    noheld = "no role held" in rtxt

    # Don't set dirty while norole
    if not s.get("norole"):
        if _has_note(ti) and "state_note rejected" not in rtxt:
            s["dirty"] = False
        elif tool in DIRTY_TOOLS:
            s["dirty"] = True
    if noheld:
        s["dirty"] = False
    msg = None
    if s.get("dirty") and not s.get("told") and not s.get("steward"):
        s["told"] = True
        msg = NOTE_LINE
    save_note(p, s)
    return msg


def main():
    try:
        inp = json.load(sys.stdin)
    except Exception:
        return
    if not isinstance(inp, dict):
        return
    t = time.time()
    ev = inp.get("hook_event_name") or "PostToolUse"
    msgs = []
    try:
        if ev == "UserPromptSubmit":
            for fn_, name_ in ((on_prompt, "on_prompt"), (cold, "cold")):
                try:   # 0.15.3 (P7): one failing hook does not silence the others
                    m = fn_(inp, t)
                except Exception as e:
                    _log(name_, e)
                    m = None
                if m:
                    msgs.append(m)
            m = None
        else:
            try:
                im = idle_tool(inp, t)
                if im:
                    msgs.append(im)
            except Exception as e:
                _log("idle_tool", e)
            try:
                m = on_tool(inp)
            except Exception as e:
                _log("on_tool", e)
                m = None
        if m:
            msgs.append(m)
    except Exception as e:
        _log("main", e)
    try:
        g = gauge(inp, inp.get("transcript_path") or "")
        if g:
            msgs.append(g)
    except Exception as e:
        _log("gauge", e)
    if msgs:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": ev, "additionalContext": " ".join(msgs)}}))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
