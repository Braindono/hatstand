"""harness_event_map: which human-actor ledger events exist, what he is shown, and how each is digested.

What it does: one table of every human event type (kind label, display-only fields, high-risk flag) and the
digest rule event_digest(). Installed root-owned beside the helper and the verifier; loaded only from there.
Why: the digest a grant signs must be recomputed by root from the ledger event itself, never taken from a client.
Cost: a new human event type needs this file (and so the helper install) updated by a root reinstall.
Depends on: json, hashlib. Interface: KINDS, EXCLUDED, canonical(obj), event_digest(ev), high_risk(ev), kind_of(ev).
"""
import hashlib
import json

# type -> (kind shown to him, display-only fields replay never reads)
KINDS = {
    "approval.granted": ("approve", ("result",)),
    "approval.denied": ("deny", ()),
    "role.defined": ("define role", ()),
    "role.assigned": ("assign or vacate role", ()),
    "agent.updated": ("update agent", ()),
    "corpus.pinned": ("pin", ()),
    "corpus.archived": ("archive", ()),
    "corpus.retagged": ("retag", ()),
    "lesson.curated": ("curate lesson", ()),
    "message.sent": ("message as operator", ()),
    "release.scope": ("release scope", ()),
    "release.published": ("publish", ()),
    "release.flagged": ("flag release", ()),
    "release.gate_override": ("gate override", ()),
    "wake.pinned": ("pin wake", ()),
    "hatstand.synced": ("sync", ()),
    "corpus_index.pinned": ("pin corpus_index", ()),
}
CASE_PREFIX = "case."          # case events written with actor human share one kind
ALWAYS_HIGH = {"message.sent", "release.published", "release.gate_override", "corpus_index.pinned"}


KNOWN_ROLES = frozenset((
    "automations", "claude-code", "corpus-envoy", "corpus-steward", "critic", "curator", "design-coder", "design-system", "detective",
    "dreamer", "envoy", "guru", "harness-critic", "letters-manager", "listings-manager", "ops-coder", "proctor", "research-lead",
    "researcher", "resume-manager", "secretary", "skill-curation-lead", "steward", "thinker"))   # live roles at the cutover; a new one needs a reinstall


def _norm(v):
    return str(v or "").strip().lstrip("#@").strip().lower()


def enforced(etype, actor, data):
    """True when an event has operator effect and so needs a consumed grant, WHATEVER its actor field says.
    Built kinds only (the rest keep today's behaviour and are listed as open gaps): a granted approval, the operator role
    assigned or defined, and a message written as the operator. Part of this root-installed file: changing it needs a reinstall."""
    d = data if isinstance(data, dict) else {}
    if etype == "approval.granted":
        return True
    if etype == "role.defined":
        return _norm(d.get("role")) == "operator"
    if etype == "role.assigned":      # an unknown name may be an alias of the seat (the alias file is user-writable): enforce it too
        r = _norm(d.get("role"))
        return r == "operator" or r not in KNOWN_ROLES
    if etype == "message.sent":
        return actor == "human" or _norm(d.get("from")) in ("human", "operator")
    return False


def canonical(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def kind_of(ev):
    t = str(ev.get("type"))
    if t in KINDS:
        return KINDS[t][0]
    return "case grant" if t.startswith(CASE_PREFIX) else None


def excluded(t):
    return KINDS.get(t, ("", ()))[1]


def event_digest(ev):
    """sha256 over {type, data minus display-only fields}. None for a type with no row (nothing can be signed for it)."""
    t = str(ev.get("type"))
    if kind_of(ev) is None:
        return None
    data = {k: v for k, v in (ev.get("data") or {}).items() if k not in excluded(t)}
    return hashlib.sha256(canonical({"type": t, "data": data}).encode("utf-8")).hexdigest()


def high_risk(ev):
    t = str(ev.get("type"))
    d = ev.get("data") or {}
    if t in ALWAYS_HIGH:
        return True
    if t in ("role.defined", "role.assigned"):
        return str(d.get("role", "")).strip().lower() == "operator"
    if t == "corpus.archived":
        return str(d.get("id", "")).startswith("D-")
    return False
