#!/usr/bin/python3 -I -S
"""harness_grant_helper: the root-owned signer for operator acts (installed as /usr/local/libexec/harness-grant).

What it does: `approve` (run by him through sudo in Terminal.app; sudo's own prompt is the password) lists every live pending request in full,
asks ONE 4-hex code typed on the sudo tty, signs each (single-use), runs `harness.py apply-all` as HIS uid (clean env), then records the
consume itself by matching ledger event digests to the signed digests. `cutover` is run once by the install script.
Why: only code he cannot edit may decide what is signed, and he must read the exact text first.
Never: stores or sees his password, follows a path he controls, or writes under /Users.
Depends on: the standard library, /usr/bin/openssl, /usr/bin/dscl, /bin/ps, harness_event_map and harness_verify (same folder).
Size note: about 460 lines (over the 300 default) because path safety, rendering and the commands share one set of checks and must stay in one root-owned file.
Test seams: every command takes cfg, tty_in, tty_out and clock explicitly (the old grant/sign-pending/consume functions stay for tests, no longer reachable from main); main() fixes the real values.
"""
import base64
import contextlib
import hmac
import json
import os
import pwd
import re
import secrets
import stat
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness_event_map as MAP          # noqa: E402
import harness_verify as V               # noqa: E402

CFG = {"state_dir": "/var/db/harness-grant", "key": "/var/db/harness-grant/key", "pub": "/usr/local/etc/harness-grant.pub", "log": "/usr/local/var/harness-grants.log",
       "pending": "/EXCHANGE_HOME/_harness/operator-pending", "home": "/EXCHANGE_HOME", "bin": "/EXCHANGE_HOME/_harness/bin/harness.py",
       "ledger": "/EXCHANGE_HOME/_harness/events.jsonl", "uid": 501, "window_s": 300, "act_s": 300,
       "min_gap_s": 5, "max_prompts": 10, "tries": 3, "flag": "/usr/local/var/harness-grants.disabled"}
REQ_NAME = re.compile(r"^[0-9a-f]{12}\.json$")
ADMIN_FILTER = ("claude", "Claude", "node-claude", "mcp_server")


class Refuse(Exception):
    pass


def open_regular(path, uid, cap):
    """Open `path` component by component with O_NOFOLLOW, then fstat: regular file, his uid, size <= cap. Returns bytes."""
    parts = [p for p in path.split("/") if p]
    fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    try:
        for p in parts[:-1]:
            nfd = os.open(p, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = nfd
        ffd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
    except OSError as e:
        raise Refuse(f"cannot open {path!r} safely: {e.strerror}")
    finally:
        os.close(fd)
    try:
        st = os.fstat(ffd)
        if not stat.S_ISREG(st.st_mode) or st.st_uid != uid or st.st_size > cap:
            raise Refuse(f"{path!r}: not a regular file of his, or too large")
        chunks, left = [], st.st_size
        while left > 0:                      # chunked: never allocate cap bytes for a small file
            b = os.read(ffd, min(left, 1 << 20))
            if not b:
                break
            chunks.append(b)
            left -= len(b)
        return b"".join(chunks)
    finally:
        os.close(ffd)


def esc(s):
    """ASCII-only, control and bidi characters shown literally."""
    return json.dumps(str(s), ensure_ascii=True)[1:-1]


def canonical_bytes_ok(raw):
    """True with the parsed object only when raw is already canonical (sorted keys, no spaces, no duplicates, ints only)."""
    def pairs(p):
        d = {}
        for k, v in p:
            if k in d:
                raise ValueError("duplicate key")
            d[k] = v
        return d
    def bad(_):
        raise ValueError("float or constant")
    o = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs, parse_float=bad, parse_constant=bad)
    if MAP.canonical(o).encode("utf-8") != raw:
        raise ValueError("not canonical")
    return o


def _sign(cfg, rec):
    text = V.sign_text(rec).encode("utf-8")
    p = subprocess.run([V.OPENSSL, "dgst", "-sha256", "-sign", cfg["key"]], input=text, capture_output=True, env={})
    if p.returncode != 0:
        raise Refuse("signing failed")
    return base64.b64encode(p.stdout).decode()


def _log_append(cfg, rec):
    line = json.dumps({"rec": rec, "sig": _sign(cfg, rec)}, sort_keys=True, separators=(",", ":")) + "\n"
    fd = os.open(cfg["log"], os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o644)
    try:
        os.write(fd, line.encode())
        os.fsync(fd)
    finally:
        os.close(fd)


def _read_json(path):
    try:
        return json.load(open(path))
    except Exception:
        return None


def _window(cfg, tty, now):
    w = _read_json(os.path.join(cfg["state_dir"], "window.json"))
    if not tty:
        raise Refuse("SUDO_TTY is not set: run this through sudo in Terminal.app")
    if not w or now > w["expires"] or w["tty"] != tty:
        raise Refuse("no live window on this tty: run `sudo /usr/local/libexec/harness-grant grant` first")
    return w


def _save_window(cfg, w):
    p = os.path.join(cfg["state_dir"], "window.json")
    fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    os.write(fd, json.dumps(w).encode())
    os.close(fd)


def ancestry_ok(pid=None, run=subprocess.run):
    """Filter only (a double fork passes): refuse when a Claude process is above us."""
    pid = pid or os.getppid()
    for _ in range(12):
        r = run(["/bin/ps", "-o", "ppid=,comm=", "-p", str(pid)], capture_output=True, text=True, env={})
        parts = r.stdout.strip().split(None, 1)
        if len(parts) < 2:
            return True
        if any(n in parts[1] for n in ADMIN_FILTER):
            return False
        pid = int(parts[0])
        if pid <= 1:
            return True
    return True


def cmd_grant(cfg, tty, user, auth_fn, now, ids=secrets.token_hex):
    if not tty:
        raise Refuse("SUDO_TTY is not set")
    ok = False
    for i in range(cfg["tries"]):
        if auth_fn(user):
            ok = True
            break
        _log_append(cfg, {"t": "authfail", "n": i + 1, "time": int(now)})
    if not ok:
        raise Refuse("password check failed")
    w = {"id": ids(8), "tty": tty, "minted": int(now), "expires": int(now) + cfg["window_s"], "prompts": 0, "last": 0}
    _save_window(cfg, w)
    _log_append(cfg, {"t": "window", "id": w["id"], "minted": w["minted"], "expires": w["expires"]})
    return w["id"]


def render(req):
    out = [f"KIND: {esc(req['kind'])}", f"requester (unverified): {esc(req.get('requester'))}"]
    for i, ev in enumerate(req["events"], 1):
        if MAP.high_risk(ev):
            out.append("!!!!!! HIGH RISK: seat, publish, pin, archive or operator mail !!!!!!")
        out.append(f"-- event {i} of {len(req['events'])}: {esc(MAP.kind_of(ev))} ({esc(ev['type'])})")
        out += json.dumps(ev.get("data"), sort_keys=True, indent=1, ensure_ascii=True).splitlines()
    return out


def list_pending(cfg):
    names = []
    try:
        for n in os.listdir(cfg["pending"]):
            if REQ_NAME.match(n):
                try:
                    names.append((os.lstat(os.path.join(cfg["pending"], n)).st_mtime, n))
                except OSError:
                    pass
    except OSError:
        pass
    return [n for _, n in sorted(names, reverse=True)]


def consumed_requests(cfg):
    """sha256 of every request whose signed act root has already consumed (applied requests leave the list)."""
    recs, _ = V.load_log(cfg["log"], cfg["pub"])
    acts = {r["id"]: r.get("req") for r in recs if r.get("t") == "act"}
    return {acts.get(r.get("act")) for r in recs if r.get("t") == "consume"}


def _vet(cfg, name, now):
    """Read one pending request safely and check its shape: -> (raw bytes, request, per-event digests) or Refuse."""
    raw = open_regular(os.path.join(cfg["pending"], name), cfg["uid"], 65536)
    try:
        req = canonical_bytes_ok(raw)
        evs = req["events"]
        if not (isinstance(evs, list) and 1 <= len(evs) <= 50) or not isinstance(req.get("kind"), str):
            raise ValueError("shape")
        digests = []
        for e in evs:
            d = MAP.event_digest(e)
            if d is None:
                raise ValueError("event type has no map row: " + esc(e.get("type")))
            digests.append(d)
        if int(req.get("expires", 0)) < now:
            raise ValueError("request expired")
    except (ValueError, KeyError, TypeError, AttributeError) as e:
        raise Refuse(f"request refused: {e}")
    return raw, req, digests


def _record_act(cfg, raw, digests, now, ledger_id, window_id, ids):
    import hashlib
    rec = {"t": "act", "id": ids(8), "req": hashlib.sha256(raw).hexdigest(), "digests": digests, "n": len(digests),
           "expires": int(now) + cfg["act_s"], "nonce": ids(8), "ledger": ledger_id, "window": window_id}
    _log_append(cfg, rec)
    return rec


def cmd_sign_pending(cfg, tty, tty_in, tty_out, now, ledger_id, rnd=secrets.token_hex, ids=secrets.token_hex):
    w = _window(cfg, tty, now)
    if w["prompts"] >= cfg["max_prompts"] or now - w["last"] < cfg["min_gap_s"]:
        raise Refuse("too many or too fast prompts in this window")
    import hashlib
    gone = consumed_requests(cfg)
    names = [n for n in list_pending(cfg)
             if hashlib.sha256(open_regular(os.path.join(cfg["pending"], n), cfg["uid"], 65536)).hexdigest() not in gone]
    if not names:
        raise Refuse("no pending requests")
    tty_out.write(f"{len(names)} pending request(s), newest first, showing {min(20, len(names))}:\n")
    for i, n in enumerate(names[:20], 1):
        tty_out.write(f"  {i}. {n}\n")
    tty_out.write("number to review: ")
    tty_out.flush()
    try:
        name = names[int(tty_in.readline().strip()) - 1]
    except (ValueError, IndexError):
        raise Refuse("no such request")
    raw, req, digests = _vet(cfg, name, now)
    lines = render(req)
    if len(lines) > 400:
        raise Refuse("request too long to read; refused")
    for k in range(0, len(lines), 40):
        tty_out.write("\n".join(lines[k:k + 40]) + "\n")
        if k + 40 < len(lines):
            tty_out.write("-- Enter for more -- ")
            tty_out.flush()
            tty_in.readline()
    code = rnd(2)
    w["prompts"] += 1
    w["last"] = int(now)
    _save_window(cfg, w)
    tty_out.write(f"Type {code} to sign exactly this (one attempt): ")
    tty_out.flush()
    if not hmac.compare_digest(tty_in.readline().strip().lower(), code):
        raise Refuse("wrong code: nothing signed")
    return _record_act(cfg, raw, digests, now, ledger_id, w["id"], ids)["id"]


def live_pending(cfg, now):
    """Pending requests root has not consumed yet: -> ([(name, raw, req, digests)], [skipped reason strings]). Newest first."""
    import hashlib
    gone = consumed_requests(cfg)
    ok, skipped = [], []
    for n in list_pending(cfg):
        try:
            raw, req, digests = _vet(cfg, n, now)
        except Refuse as e:
            skipped.append(f"{n[:-5]}: {e}")
            continue
        if hashlib.sha256(raw).hexdigest() not in gone:
            ok.append((n, raw, req, digests))
    return ok, skipped


def tty_matches(fd, sudo_tty):
    """True when fd is the device the path sudo_tty names (compared by device number: an fd from the /dev/tty alias never matches, by design)."""
    try:
        return bool(sudo_tty) and os.fstat(fd).st_rdev == os.stat(sudo_tty).st_rdev and os.isatty(fd)
    except OSError:
        return False


def vet_sudo_tty(path, uid, stdin_fd=0):
    """Refuse unless path is the real terminal device sudo ran on: a /dev/ttys* character device owned by him, and stdin is that terminal."""
    if not path or not path.startswith("/dev/ttys") or os.path.realpath(path) != path:
        raise Refuse("SUDO_TTY is not a terminal device: run this through sudo in Terminal.app")
    try:
        st = os.stat(path)
        ok_stdin = os.isatty(stdin_fd) and os.ttyname(stdin_fd) == path
    except OSError:
        raise Refuse("cannot check the terminal sudo ran on")
    if not stat.S_ISCHR(st.st_mode) or st.st_uid != uid:
        raise Refuse("the terminal sudo ran on is not a character device owned by the configured account")
    if not ok_stdin:
        raise Refuse("the code must be typed on the terminal sudo ran on (stdin is not that terminal)")


def cmd_approve(cfg, tty, tty_in, tty_out, now, ledger_id, rnd=secrets.token_hex, ids=secrets.token_hex, same_tty=lambda: True):
    """0.26.2: sudo's own prompt was the password. List every live pending request in full, ask ONE 4-hex code, sign each. -> [act records]."""
    if not tty:
        raise Refuse("SUDO_TTY is not set: run this through sudo in Terminal.app")
    if not same_tty():
        raise Refuse("the code must be typed on the terminal sudo ran on")
    items, skipped = live_pending(cfg, now)
    if not items:
        raise Refuse("no pending requests" + (" (skipped: " + "; ".join(skipped) + ")" if skipped else ""))
    items = items[:20]
    lines = []
    for n, raw, req, digests in items:
        part = [f"===== request {n[:-5]} ====="] + render(req)
        if len(part) > 400:
            raise Refuse(f"request {n[:-5]} is too long to read; refused, nothing signed")
        lines += part
    if len(lines) > 1200:
        raise Refuse("too much to read at once (over 1200 lines); nothing signed")
    total_events = sum(len(d) for _, _, _, d in items)
    lines.append(f"==== {len(items)} request(s), {total_events} event(s) in all" + (f"; skipped {len(skipped)}: " + "; ".join(skipped) if skipped else "") + " ====")
    for k in range(0, len(lines), 40):
        tty_out.write("\n".join(lines[k:k + 40]) + "\n")
        if k + 40 < len(lines):
            tty_out.write("-- Enter for more -- ")
            tty_out.flush()
            tty_in.readline()
    code = rnd(2)
    tty_out.write(f"Type {code} to sign exactly these {len(items)} request(s) (one attempt): ")
    tty_out.flush()
    if not hmac.compare_digest(tty_in.readline().strip().lower(), code):
        raise Refuse("wrong code: nothing signed")
    return [_record_act(cfg, raw, dg, now, ledger_id, None, ids) for _, raw, _, dg in items]


def ledger_tail_seq(cfg):
    raw = open_regular(cfg["ledger"], cfg["uid"], 1 << 30).splitlines()
    return json.loads(raw[-1])["seq"]


def consume_matched(cfg, acts, after_seq, now):
    """After the apply run: find, for every signed act, the enforced ledger events written since `after_seq` whose digests equal the act's,
    and record each act once. Extra enforced events stay unconsumed (ignored at replay). -> [text per act]."""
    raw = open_regular(cfg["ledger"], cfg["uid"], 1 << 30)
    new = []
    for line in raw.splitlines():
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if isinstance(e, dict) and isinstance(e.get("seq"), int) and e["seq"] > after_seq and MAP.enforced(e.get("type"), e.get("actor"), e.get("data")):
            new.append(e)
    used, out = set(), []
    recs, _ = V.load_log(cfg["log"], cfg["pub"])
    done = {r.get("act") for r in recs if r.get("t") == "consume"}
    for act in acts:
        if act["id"] in done:
            out.append(f"{act['id']}: already consumed")
            continue
        pairs = []
        for d in act["digests"]:
            hit = next((e for e in new if e["seq"] not in used and MAP.event_digest(e) == d and e.get("t", 0) <= act["expires"] + 5), None)
            if hit is None:
                pairs = None
                break
            used.add(hit["seq"])
            pairs.append([hit["seq"], hit["hash"]])
        if pairs is None:
            out.append(f"{act['id']}: not applied (no ledger event matches the grant); nothing recorded")
            continue
        _log_append(cfg, {"t": "consume", "act": act["id"], "events": pairs, "time": int(now)})
        out.append(f"{act['id']}: consumed {len(pairs)} event(s)")
    return out


def run_apply(cfg, user_env_home, file_only=False, run=subprocess.run):
    """Apply as HIS uid, never root: the editable harness.py cannot forge what root records (root matches digests itself).
    His sudo tickets are killed first (sudo -K as his uid), so the child cannot ride the ticket sudo just made; the child has no stdin,
    its own session (no controlling tty), a 60 s limit, and its output is shown once, escaped and capped."""
    as_him = dict(user=cfg["uid"], group=pwd.getpwuid(cfg["uid"]).pw_gid, extra_groups=[], cwd="/",
                  env={"HOME": user_env_home, "HARNESS_HOME": cfg["home"], "PATH": "/usr/bin:/bin"})
    run(["/usr/bin/sudo", "-K"], stdin=subprocess.DEVNULL, capture_output=True, **as_him)
    try:
        r = run(["/usr/bin/python3", "-E", "-s", cfg["bin"], "--home", cfg["home"], "apply-all"] + (["--file-only"] if file_only else []),
                stdin=subprocess.DEVNULL, start_new_session=True, timeout=60, capture_output=True, text=True, **as_him)
    except subprocess.TimeoutExpired:
        return "apply timed out after 60 s"
    return esc((r.stdout + r.stderr).strip())[:2000]


def _ledger_events(cfg, seqs):
    raw = open_regular(cfg["ledger"], cfg["uid"], 1 << 30)
    want, out = set(seqs), {}
    for line in raw.splitlines():
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if isinstance(e, dict) and e.get("seq") in want:
            out[e["seq"]] = e
    return out


def cmd_consume(cfg, tty, act_id, pairs, now):
    """pairs: [(seq, hash)]. Order of events must equal the grant's digest list; recorded once (same set again is a no-op)."""
    if not tty:
        raise Refuse("SUDO_TTY is not set: run this through sudo in Terminal.app")
    recs, _ = V.load_log(cfg["log"], cfg["pub"])
    act = next((r for r in recs if r.get("t") == "act" and r.get("id") == act_id), None)
    if act is None or now > act["expires"] + 3600 * 24 * 14:
        raise Refuse("unknown or old grant")
    done = [r for r in recs if r.get("t") == "consume" and r.get("act") == act_id]
    if done:
        if [list(p) for p in pairs] == [list(p) for p in done[0]["events"]]:
            return "already consumed (same events)"
        raise Refuse("grant already consumed for other events")
    if len(pairs) != act["n"]:
        raise Refuse("event count does not match the grant")
    evs = _ledger_events(cfg, [s for s, _ in pairs])
    for (s, h), d in zip(pairs, act["digests"]):
        e = evs.get(s)
        if e is None or e.get("hash") != h or not MAP.enforced(e.get("type"), e.get("actor"), e.get("data")) or MAP.event_digest(e) != d:
            raise Refuse(f"ledger event {s} does not match the grant")
        if e.get("t", 0) > act["expires"] + 5:
            raise Refuse(f"event {s} was written after the grant expired")
    _log_append(cfg, {"t": "consume", "act": act_id, "events": [[s, h] for s, h in pairs], "time": int(now)})
    return "consumed"


def cmd_cutover(cfg):
    """Run by the install script as root: records the ledger tail as the cutover."""
    raw = open_regular(cfg["ledger"], cfg["uid"], 1 << 30).splitlines()
    first, last = json.loads(raw[0]), json.loads(raw[-1])
    _log_append(cfg, {"t": "cutover", "seq": last["seq"], "hash": last["hash"], "ledger": first["hash"]})


def ledger_id(cfg):
    raw = open_regular(cfg["ledger"], cfg["uid"], 1 << 30)
    return json.loads(raw.split(b"\n", 1)[0])["hash"]


def real_auth(user, tty_path="/dev/tty"):
    with open(tty_path) as t:
        return subprocess.run(["/usr/bin/dscl", ".", "-authonly", user], stdin=t, env={}).returncode == 0


@contextlib.contextmanager
def open_tty(path, uid, stdin_fd=0):
    """0.26.3: open the terminal device sudo ran on (SUDO_TTY) itself, never the /dev/tty alias, as separate read and write handles (a tty is not seekable)."""
    vet_sudo_tty(path, uid, stdin_fd)
    tin = tout = None
    try:
        tin = os.fdopen(os.open(path, os.O_RDONLY | os.O_NOCTTY), "r")
        tout = os.fdopen(os.open(path, os.O_WRONLY | os.O_NOCTTY), "w")
        if not (tty_matches(tin.fileno(), path) and tty_matches(tout.fileno(), path)):
            raise Refuse("the terminal handle is not the sudo terminal")
    except OSError as e:
        for f in (tin, tout):
            if f:
                f.close()
        raise Refuse("cannot open the terminal: " + esc(e))
    try:
        yield tin, tout
    finally:
        tin.close()
        tout.close()


def main(argv):
    cmd = argv[1] if len(argv) > 1 else ""
    tty, user = os.environ.get("SUDO_TTY"), os.environ.get("SUDO_USER")
    if os.geteuid() != 0 or not user:
        print("run through sudo: sudo /usr/local/libexec/harness-grant approve")
        return 2
    if os.environ.get("SUDO_UID") != str(CFG["uid"]):
        print("refused: not run by the account this signer is set up for")
        return 1
    if not ancestry_ok():
        print("refused: run this in Terminal.app, not inside a Claude chat or its terminal pane")
        return 1
    try:
        if cmd == "approve" and len(argv) == 2:
            with open_tty(tty, CFG["uid"]) as (tin, tout):
                acts = cmd_approve(CFG, tty, tin, tout, time.time(), ledger_id(CFG), same_tty=lambda: tty_matches(tin.fileno(), tty))
            tail = ledger_tail_seq(CFG)
            print("signed", len(acts), "request(s); applying as", user)
            print(run_apply(CFG, pwd.getpwuid(CFG["uid"]).pw_dir))
            for line in consume_matched(CFG, acts, tail, time.time()):
                print(line)
            print(run_apply(CFG, pwd.getpwuid(CFG["uid"]).pw_dir, file_only=True))       # files consumed requests away; applies nothing twice
        elif cmd == "cutover":
            cmd_cutover(CFG)
            print("cutover recorded")
        else:
            print("usage: approve | cutover")
            return 2
    except Refuse as e:
        print("refused:", e)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
