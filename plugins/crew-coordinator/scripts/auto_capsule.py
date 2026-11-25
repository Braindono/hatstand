"""auto_capsule: 0.27.3 item 2. Builds a successor's handoff capsule from the ledger (role, state note, unread mail, held leases), git (read only) and open items.
Depends on: stdlib; the Harness object passed in (read calls only: state(), _role_note(), unread_ids()). Called from Harness._handoff when capsule_md == "auto".
It writes nothing and runs no git write: the text goes back into the same handoff call, which runs every existing gate (budget, vault, untagged asks, model stamp,
holder commit) on it, so restore_auto_check sees an ordinary capsule committed by the holder. Ids not content; Next action first; at most MAX_CHARS (1,500 tokens at chars/4).
Interface: build(h, aid, git_dir=None) -> markdown text (starts with '# '). Every section fails soft: a failed read leaves that section as one line saying so."""
import subprocess

MAX_CHARS = 5600      # under check_capsule_budget's 1,500 tokens (6,000 chars) with room for the model stamp
NOTE_CHARS = 1400
GIT = (("status", "--short", "--branch"), ("log", "--oneline", "-5"))


def git_lines(git_dir, args, limit):
    """Read-only git, 5 s cap; -> list of lines, or [] on any failure (no repo, no git, timeout)."""
    if not git_dir or args[0] not in ("status", "log"):
        return []
    try:
        r = subprocess.run(["git", "-C", str(git_dir), "--no-optional-locks"] + list(args), capture_output=True, text=True, timeout=5,
                           env={"PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin", "GIT_OPTIONAL_LOCKS": "0", "HOME": "/nonexistent"})
    except Exception:
        return []
    return [l[:160] for l in (r.stdout.splitlines() if r.returncode == 0 else [])][:limit]


def _first_line(text):
    for l in str(text or "").splitlines():
        l = l.strip().lstrip("#- ").strip()
        if l:
            return l[:200]
    return ""


def build(h, aid, git_dir=None):
    st = h.state()
    a = st.agents.get(aid) or {}
    role = st.role_of(aid) or ""
    out = ["# Handoff (auto-built): %s" % (role or a.get("sobriquet") or aid[:8]), ""]
    note = None
    try:
        rows = h._role_note(role) if role else []
        note = rows[0] if rows else None
    except Exception:
        note = None
    nb = ""
    try:
        nb = str(h.corpus.get([note["id"]], budget=NOTE_CHARS // 3)[0]).split("\n", 1)[-1] if note else ""   # first line is the entry header
    except Exception:
        nb = ""
    out += ["## Next action", "- " + (_first_line(nb) or "read the role state note, then the unread mail; no state note was found"), ""]
    out += ["## Ledger", "- agent %s, role %s, project %s, model %s" % (aid[:8], role or "none", a.get("project") or "none", a.get("model") or "unknown")]
    try:
        ids = list(h.unread_ids(st, aid))
        subj = [(i, str((st.messages.get(i) or {}).get("subject") or "")[:60]) for i in ids[:8]]
        out.append("- unread mail: %d%s" % (len(ids), (" (" + "; ".join("%s %s" % (i[:8], s) for i, s in subj) + ")") if subj else ""))
    except Exception:
        out.append("- unread mail: unknown (read failed)")
    held = sorted(p for p, L in st.leases.items() if L.get("holder") == aid and st.active_lease(p))
    out.append("- leases held: %s" % (", ".join(held[:6]) + (" +%d more" % (len(held) - 6) if len(held) > 6 else "") if held else "none"))
    if note:
        out.append("- state note: %s (%s)" % (note.get("id"), note.get("ts")))
    out.append("")
    gs, gl = git_lines(git_dir, GIT[0], 12), git_lines(git_dir, GIT[1], 5)
    out += ["## Git (read only)"] + (["- " + l for l in gs + gl] if (gs or gl) else ["- no repository found at the project folder (or git failed)"]) + [""]
    if nb:
        out += ["## Open items (state note, cut)", nb.strip()[:NOTE_CHARS]]
    text = "\n".join(out).rstrip() + "\n"
    return text[:MAX_CHARS]
