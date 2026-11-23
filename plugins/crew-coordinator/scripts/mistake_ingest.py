"""mistake_ingest: turns the correction hook's spool lines into candidate records (0.27.1 item 1; hardened after the critic's read).
Depends on: stdlib, mistake_pointer. Called from the harness sync (one method, Harness.ingest_mistake_spool).
Interface: ingest(home, resolve_agent, record_fn, projects_dir=None) -> number filed. resolve_agent(session_id) -> agent id or None;
record_fn(agent, title, body, tags) files one note (the harness's own writer; the body carries every required field except Model, which the caller adds).
How a line is trusted: the spool is claimed by an atomic rename, so a hook append during ingest lands in a fresh spool and nothing is lost; a line is
filed only if the session has a real transcript (found by its id, never the path in the line) and the agent's act line and his later user line (his quoted words, through the cue match) are both in that transcript, so a forged line is
dropped (mistake_verify, ops-coder); the Session path in the record is always the real transcript's. A line whose agent is not known yet goes back to the spool. A done mark per line key
(mistake_seen/<key>.filed) stops a double filing after a crash. No file is opened through a symlink."""
import hashlib, json, os, time

import mistake_pointer, mistake_verify

def _clean(v, n):
    return str(v or "")[:n].replace("\n", " ").replace("\r", " ")


def _body(r, path):
    mdl = [("Model: " + _clean(r.get("model"), 80))] if r.get("model") else []     # the model the transcript's own assistant line names (critic 8)
    return "\n".join(mdl + ["Act: " + _clean(r.get("act"), 300), "Found by: operator", "Kind: %s" % (r.get("kind") if r.get("kind") in ("claim", "code") else "claim"),
                      "Operator's words: " + _clean(r.get("quote"), 300), "Cue: " + _clean(r.get("cue"), 20),
                      "Session: " + path, "Line: %s" % (r.get("line") if isinstance(r.get("line"), int) else "unknown"),
                      "Candidate: filed by the correction hook; the agent adds one description line."])


MAX_PER_SYNC = 50
MIN_ACT = 8


def _young(r, hours=2):
    try:
        return time.time() - time.mktime(time.strptime(str(r.get("ts")), "%Y-%m-%dT%H:%M:%S")) < hours * 3600
    except ValueError:
        return False


def _append(path, lines):
    if not lines:
        return
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600)
    try:
        os.write(fd, "".join(l + "\n" for l in lines).encode("utf-8"))
    finally:
        os.close(fd)


def ingest(home, resolve_agent, record_fn, projects_dir=None):
    base = os.path.join(home, "_harness")
    spool, claimed = os.path.join(base, "mistake_spool.jsonl"), os.path.join(base, "mistake_spool.claimed")
    seen = os.path.join(base, "mistake_seen")
    if os.path.islink(spool) or os.path.islink(claimed) or os.path.islink(seen):
        return 0
    os.makedirs(seen, exist_ok=True)
    if os.path.isfile(spool) and not os.path.exists(claimed):
        try:
            os.rename(spool, claimed)                       # atomic: a hook append from now on starts a new spool
        except OSError:
            return 0
    if not os.path.isfile(claimed):
        return 0
    keep, done, rejected, n = [], [], [], 0
    try:
        lines = open(claimed, encoding="utf-8").read().splitlines()
        for i, ln in enumerate(lines):
            if i >= MAX_PER_SYNC:
                keep.extend(lines[i:])                      # the rest waits for the next sync (a flood cannot stall one sync)
                break
            try:
                r = json.loads(ln)
                sid, quote, act = r["session_id"], str(r["quote"]), str(r["act"])
                key = hashlib.sha256(("%s|%s|%s" % (sid, r.get("line"), " ".join(quote.split()))).encode("utf-8", "replace")).hexdigest()[:20]
                real = mistake_pointer.find_transcript(sid, projects_dir)
                agent = resolve_agent(sid)
            except (ValueError, KeyError, TypeError, AttributeError):
                continue                                    # a torn or foreign line is dropped
            if os.path.exists(os.path.join(seen, key + ".filed")):
                continue                                    # this correction (session, line, his words) was filed already: replays file nothing
            if not agent:
                keep.append(ln)
                continue
            if len(" ".join(act.split())) < MIN_ACT or not real or not mistake_verify.verify(real, r.get("line"), act, quote):
                if _young(r):
                    keep.append(ln)                         # his message may not be in the transcript yet: try at the next sync
                continue                                    # unverifiable after 2 hours: a forged line
            try:
                record_fn(agent, "Correction candidate (%s): %s" % (_clean(r.get("cue"), 20), _clean(quote, 70)), _body(r, real), ["mistake", "hindsight", "candidate"])
            except Exception:
                rejected.append(ln)                         # one refused line never stalls the spool
                continue
            try:
                os.close(os.open(os.path.join(seen, key + ".filed"), os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600))
            except OSError:
                pass
            done.append(ln)
            n += 1
    finally:
        _append(spool, keep)
        _append(os.path.join(base, "mistake_spool.done.jsonl"), done)
        _append(os.path.join(base, "mistake_spool.rejected.jsonl"), rejected)
        try:
            os.unlink(claimed)
        except OSError:
            pass
    return n
