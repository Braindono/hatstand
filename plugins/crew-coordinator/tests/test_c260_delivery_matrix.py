"""cc 0.26.0 delivery matrix: the delivery rules of docs/delivery-invariants.md, asserted over the cross product of mail kind x recipient state x reply
shape (send outcome), plus repeat and mixed-kind pairs, several recipients, senders, superseded chats, read and owed state, the inbox cut and the backstops.
The oracle `spec` below is written from the document's words and tables, not from the code's branches. Each cell is one generated test. A cell where the code
differs is a bug (fixed here, the cell is its test) or a spec choice (listed in the document, section 4).
Cells that can never fail (they pin what no code path can change): notice and plain-message cells whatever the state (the kind is checked before any route),
and the vacant-role cells (no holder exists to route to).
Run: python3 -B tests/test_c260_delivery_matrix.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _env  # noqa: F401  isolate HOME and HARNESS_* first
import os
import tempfile
import time
import unittest
from unittest import mock

import test_c250_relay_fixes as F
from test_c250_relay_fixes import D, H

MODEL = "claude-sonnet-5-5"
CAPSULE = "---\nhandoff: x\n---\n# H\nRoutine handoff.\n"
KINDS = ("task", "question", "review", "result", "handoff", "notice", "message")
ASK = ("task", "question", "review")
STATES = ("warm", "cold", "pair_cap", "sender_cap", "global_cap", "trigger_only", "stale", "no_route", "retired_id", "handed_off_id", "vacant")
# reply shapes: none; reply_to an open ask; reply_to an answered ask; citing an open or answered ask by ref; an acknowledgement then the real mail;
# the same thread without reply_to the ask; sent with expects_reply; the ask is a finished task; the ask was dismissed with owed_close
SHAPES = ("none", "reply_open", "reply_answered", "ref_open", "ref_answered", "ack_then", "thread_only", "expects", "ask_done", "ask_dismissed")


def is_covered(kind, shape):
    """Covered mail (the document, section 1): an ask; a result or handoff that answers an open ask; a message that replies (reply_to) to one."""
    asklike = kind in ASK or shape == "expects"
    reply_direct = shape in ("reply_open", "ack_then")                              # reply_to the open ask itself
    waiting = shape in ("reply_open", "ref_open", "ack_then", "thread_only")        # an open ask of the recipient is answered by this mail
    return asklike or (kind in ("result", "handoff") and waiting) or (kind == "message" and reply_direct)


def spec(kind, state, shape):
    """The document (docs/delivery-invariants.md, section 2): what the send returns for this cell."""
    covered = is_covered(kind, shape)
    if not covered and kind in ("notice", "message"):
        return "notice_silent" if (kind == "notice" and state not in ("vacant", "retired_id")) else "no_nudge"      # CHOICE C1 for a vacant role or a retired id
    if state == "vacant":
        return "vacant"
    if state in ("warm", "trigger_only"):
        return "ring"
    if state == "cold":
        return "ring" if (covered or kind == "handoff") else "mail_only"
    if state == "handed_off_id":
        return "vacant" if covered else "no_nudge"                                  # a handed-off chat's id: queued for the restore; covered mail counts a miss
    if state == "retired_id":
        return "no_route_miss" if covered else "no_nudge"                            # a retired chat's id: covered mail counts a miss, uncovered says nothing
    if state == "no_route":
        return "no_route_miss" if covered else "mail_only"                          # C6 (decided): covered mail to a recipient nothing can reach counts a miss
    if state == "stale":
        return "route_backstop" if covered else "mail_only"
    return "capped_relay" if covered else "capped_norelay"                          # pair, sender or global cap


def outcome(r):
    n, sk = r.get("nudge"), r.get("nudge_skipped")
    if isinstance(n, dict):
        return "ring"
    if sk and str(sk[0].get("reason") or "").startswith("rung under"):
        return "held"
    if isinstance(n, str) and "no live holder" in n:
        return "vacant"                                                             # a vacant or handed-off recipient: queued for the restore
    if sk and str(sk[0].get("reason") or "").startswith("no route"):
        return "no_route_miss"
    if sk:
        rel = str(sk[0].get("relay") or "")
        why = str(sk[0].get("reason") or "")
        if why.startswith("id route closed"):
            return "route_backstop" if rel.startswith(("relay requested", "miss")) else "route_nobackstop"
        return "capped_relay" if rel.startswith(("relay requested", "miss")) else "capped_norelay"
    if isinstance(n, str):
        if n.startswith("relay requested"):
            return "capped_relay"
        if "no live holder" in n:
            return "vacant"
        if "kind notice" in n:
            return "notice_silent"
        if "mail only" in n:
            return "mail_only"
        return "other:" + n[:60]
    return "no_nudge"


def named(tc, r):
    """The universal invariant (document, section 2 rule 7), checked in every cell: the recipients with a nudge.offered, nudge.skipped, nudge.relay_offer or
    nudge.miss record for this send are exactly the recipients the result names (`nudge_outcomes`), with the same reasons, and the older fields
    (`nudge`, `nudge_skipped`, `nudge_mail_only`, `holder`) leave none of them out."""
    mid = r.get("id")
    if not mid:
        return
    rec, reasons = set(), {}
    for e in tc.h.store.read_all():
        d = e.get("data") or {}
        if (d.get("msg") or d.get("msg_id")) != mid:
            continue
        t = e["type"]
        if t == "nudge.offered":
            for x in d.get("to") or []:
                rec.add(x)
        elif t == "nudge.skipped":
            for x in d.get("to") or []:
                rec.add(x)
                reasons.setdefault(x, set()).add(str(d.get("reason")))
        elif t == "nudge.relay_offer" and d.get("rewake") in (None, "extra"):
            rec.add(d.get("to"))
            reasons.setdefault(d.get("to"), set()).add(str(d.get("reason")))
        elif t == "nudge.miss":
            rec.add(d.get("to"))
            reasons.setdefault(d.get("to"), set()).add(str(d.get("reason")))
    outs = {o["key"]: o for o in (r.get("nudge_outcomes") or []) if o["outcome"] != "mail only"}
    tc.assertEqual(set(outs), rec, "recorded %s but the result names %s: %s" % (sorted(map(str, rec)), sorted(map(str, outs)), brief(r)))
    for k, rs in reasons.items():
        for reason in rs:
            tc.assertIn(reason, outs[k]["reasons"], "reason %r of %s missing from the result: %s" % (reason, k, outs[k]))
    # the older fields name every recipient that has a non-ring record
    st = tc.h.state()
    ring_names = " ".join((r.get("nudge") or {}).get("to") or []) if isinstance(r.get("nudge"), dict) else ""
    skipped_names = {x.get("to") for x in (r.get("nudge_skipped") or [])} | {x.get("to") for x in (r.get("nudge_mail_only") or [])}
    holders = set((r.get("holder") or {}).keys())
    for k, o in outs.items():
        if o["outcome"] == "ring":
            tc.assertIn((st.agents.get(k) or {}).get("sobriquet", "?"), ring_names, "ring for %s not in nudge.to: %s" % (k, brief(r)))
        elif str(k).startswith("role:") and str(k)[5:] in holders:
            pass
        else:
            soby = (st.agents.get(k) or {}).get("sobriquet")
            tc.assertTrue(o["to"] in skipped_names or (soby and soby in skipped_names), "recipient %s has a record but is not named in nudge_skipped: %s" % (k, brief(r)))


def brief(r):
    return {k: r.get(k) for k in ("nudge", "nudge_skipped", "nudge_mail_only")}


class Matrix(F.Fixes):
    """One fresh world per cell. Recipient: the curator (a warm session), the secretary (Cowork: its wake routine only, or nothing) or a vacant role."""

    def world(self, state, shape):
        if state == "trigger_only":
            self.ready()
            self.rcpt, self.role = self.sec, "secretary"
        elif state == "no_route":
            self.rcpt, self.role = self.sec, "secretary"                           # a Cowork role with no session id and no wake routine
        elif state == "retired_id":                  # a chat that asked (if the shape needs an ask) and then retired with no successor: addressed by its agent id
            self.h.role_define("operator", "scribe", "harness-ops", carry="none")
            self.rcpt, self.role = self.reg("scribe", "local_rt"), "scribe"
            self.warm(self.rcpt)
        elif state == "handed_off_id":               # a chat that asked (if the shape needs an ask) and then handed its role off: addressed by its agent id
            self.h.role_define("operator", "keeper", "harness-ops", carry="none")
            self.rcpt, self.role = self.reg("keeper", "local_ho"), "keeper"
            self.warm(self.rcpt)
        elif state == "vacant":                      # the holder asked (if the shape needs an ask) and then left: the role has no live holder
            self.h.role_define("operator", "ghost", "harness-ops", carry="none")
            self.rcpt, self.role = self.reg("ghost", "local_gh"), "ghost"
            self.warm(self.rcpt)
        else:
            if "curator" not in self.h.state().roles:
                self.h.role_define("operator", "curator", "harness-ops", carry="none")
            self.rcpt, self.role = self.reg("curator", "local_mx"), "curator"
            self.warm(self.rcpt)
        self.q = None
        if shape not in ("none", "expects") and self.rcpt:
            askkind = "task" if shape == "ask_done" else "question"
            self.q = self.call("harness_send", agent=self.rcpt, to=self.plain, body="please do x", subject="ask", kind=askkind)["id"]
            if shape.endswith("answered"):          # a result from the sender closes the ask
                with mock.patch.object(D.time, "time", return_value=time.time() + 700):
                    self.call("harness_send", agent=self.plain, to="role:" + self.role, body="done", subject="re", kind="result", reply_to=self.q)
            if shape == "ask_done":
                self.h.task_update(self.plain, self.q, "completed", note="done: proof")
            if shape == "ask_dismissed":
                self.h.owed_close(self.plain, [self.q], "not needed")
            if shape == "thread_only":              # an earlier message of the sender on the ask's thread; the target will reply to THAT, not to the ask
                with mock.patch.object(D.time, "time", return_value=time.time() + 700):
                    self.mid2 = self.call("harness_send", agent=self.plain, to="role:" + self.role, body="looking", subject="ack", kind="notice", reply_to=self.q)["id"]
        if state == "cold":
            D._save(D._sp(self.h, self.rcpt), {"last_call": time.time() - 4000})
        if state in ("vacant", "retired_id"):
            self.h.retire(self.rcpt, "left", by=self.rcpt)
        if state == "handed_off_id":
            self.h.handoff(self.rcpt, CAPSULE)
        if state == "stale":                        # a first task rang, its sender reported skipped stale_id: the id is marked stale
            first = self.call("harness_send", agent=self.plain, to="role:" + self.role, body="first", subject="f", kind="task")
            self.admin(self.plain, "nudge_result", msg_id=first["nudge"]["msg_id"], outcome="skipped", reason="stale_id")
        if state.endswith("_cap"):
            cap = {"pair_cap": "nudge_per_pair_hour", "sender_cap": "nudge_per_agent_hour", "global_cap": "global_per_hour"}[state]
            self.op["doorbell"] = dict({"nudge_per_agent_hour": 60, "nudge_per_pair_hour": 30, "global_per_hour": 100}, **{cap: 1})
            self.call("harness_send", agent=self.plain, to="role:" + self.role, body="uses the slot", subject="w", kind="task")

    def cell(self, kind, state, shape):
        self.world(state, shape)
        kw = {}
        if shape in ("reply_open", "reply_answered", "ack_then", "ask_done", "ask_dismissed") and self.q:
            kw["reply_to"] = self.q
        if shape == "thread_only" and self.q:
            kw["reply_to"] = self.mid2
        if shape.startswith("ref") and self.q:
            kw["refs"] = [self.q]
        if shape == "expects":
            kw["expects_reply"] = True
        if shape == "ack_then":
            with mock.patch.object(D.time, "time", return_value=time.time() + (700 if state == "trigger_only" else 0)):
                self.call("harness_send", agent=self.plain, to="role:" + self.role, body="on it", subject="ack", kind="message", reply_to=self.q)
        to = self.rcpt if state in ("retired_id", "handed_off_id") else "role:" + self.role
        with mock.patch.object(D.time, "time", return_value=time.time() + (1400 if state == "trigger_only" else 0)):
            r = self.call("harness_send", agent=self.plain, to=to, body="the body", subject="s", kind=kind, **kw)
        got, want = outcome(r), spec(kind, state, shape)
        self.assertEqual(got, want, "kind=%s state=%s shape=%s -> %s" % (kind, state, shape, brief(r)))
        named(self, r)
        if state in ("no_route", "vacant", "retired_id", "handed_off_id"):             # C6: covered mail to a recipient nothing can reach counts a miss; uncovered mail does not
            misses = [e for e in self.h.store.read_all() if e["type"] == "nudge.miss" and e["data"].get("msg_id") == r["id"]]
            self.assertEqual(bool(misses), is_covered(kind, shape) and spec(kind, state, shape) != "no_nudge", "miss for %s %s %s: %s" % (kind, state, shape, misses))


for _n in [n for n in dir(F.Fixes) if n.startswith("test_")]:
    setattr(Matrix, _n, None)


def _make(kind, state, shape):
    def t(self):
        self.cell(kind, state, shape)
    return t


for _k in KINDS:
    for _s in STATES:
        for _sh in SHAPES:
            setattr(Matrix, "test_send_%s_%s_%s" % (_k, _s, _sh), _make(_k, _s, _sh))


SPEC_COLUMNS = {"Warm chat": "warm", "Cold chat (last call over 1 h)": "cold", "Wake routine only": "trigger_only",
                "Capped (pair, sender or global)": ("pair_cap", "sender_cap", "global_cap"), "Route closed (stale mark)": "stale",
                "No route at all": "no_route", "Retired chat's id (no successor)": "retired_id", "Handed-off chat's id": "handed_off_id", "Vacant role": "vacant"}


def spec_row(kind, shape):
    """Which row of the document's send table a (kind, shape) pair belongs to: 0 ask, 1 answer to an open ask, 2 uncovered result or handoff, 3 silent."""
    cell = spec(kind, "warm", shape)
    if kind in ASK or shape == "expects":
        return 0
    if kind in ("result", "handoff", "message") and shape in ("reply_open", "ref_open", "ack_then", "thread_only") and not (kind == "message" and shape not in ("reply_open", "ack_then")):
        return 1
    if kind in ("result", "handoff"):
        return 2
    return 3


class SpecCoverage(unittest.TestCase):
    """The cell list is derived from the document's tables, so a column or a row the code never branches on still gets cells."""

    def table(self):
        text = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "docs", "delivery-invariants.md"), encoding="utf-8").read()
        sec = text.split("## 2. What a send does")[1].split("Further rules")[0]
        rows = [[c.strip() for c in ln.strip().strip("|").split("|")] for ln in sec.splitlines() if ln.startswith("|") and "---" not in ln]
        return rows[0], rows[1:]

    def test_every_column_of_the_documents_send_table_has_a_state_and_every_state_a_column(self):
        head, rows = self.table()
        cols = head[1:]
        self.assertEqual(set(cols), set(SPEC_COLUMNS), cols)                          # a new column in the document fails here until the matrix has a state for it
        states = set()
        for c in cols:
            v = SPEC_COLUMNS[c]
            states |= set(v) if isinstance(v, tuple) else {v}
        self.assertEqual(states, set(STATES))

    def test_every_row_of_the_documents_send_table_has_cells_in_every_column(self):
        head, rows = self.table()
        self.assertEqual(len(rows), 4)
        have = {}
        for kind in KINDS:
            for state in STATES:
                for shape in SHAPES:
                    have.setdefault((spec_row(kind, shape), state), 0)
                    have[(spec_row(kind, shape), state)] += 1
        for r in range(4):
            for state in STATES:
                self.assertGreater(have.get((r, state), 0), 0, "no cell for document row %d in state %s" % (r, state))

    def test_every_kind_appears_in_every_row_it_can_belong_to(self):
        seen = {(k, spec_row(k, s)) for k in KINDS for s in SHAPES}
        self.assertEqual({r for k, r in seen if k == "notice"}, {0, 3})                  # a notice is silent, or an ask with expects_reply
        self.assertEqual({r for k, r in seen if k == "message"}, {0, 1, 3})
        self.assertEqual({r for k, r in seen if k == "result"}, {0, 1, 2})
        self.assertEqual({r for k, r in seen if k == "task"}, {0})


class Mixes(F.Fixes):
    """A send to several recipients in different states: each recipient is judged on its own row (document, rule 3). Pairs of distinct states; the stale mark
    cannot be combined with the pair cap (the ring that marks a role stale uses that role's pair slot), and the sender and global caps hit every recipient, so
    those are not mixed."""

    MIXED = ("warm", "cold", "pair_cap", "trigger_only", "stale", "no_route", "retired_id", "handed_off_id", "vacant")
    ROLES = {"warm": "curator", "cold": "ops-coder", "pair_cap": "reviewer", "stale": "auditor", "retired_id": "scribe", "handed_off_id": "keeper", "vacant": "ghost"}

    def build(self, state):
        """-> (address, agent id or None)"""
        if state == "trigger_only":
            self.ready()
            return "role:secretary", self.sec
        if state == "no_route":
            self.h.role_define("operator", "librarian", "harness-ops", carry="none")
            a = self.cowork("librarian")
            return "role:librarian", a
        role = self.ROLES[state]
        self.h.role_define("operator", role, "harness-ops", carry="none")
        a = self.reg(role, "local_mx_" + state)
        self.warm(a)
        if state == "cold":
            D._save(D._sp(self.h, a), {"last_call": time.time() - 4000})
        if state == "stale":
            first = self.call("harness_send", agent=self.plain, to="role:" + role, body="first", subject="f", kind="task")
            self.admin(self.plain, "nudge_result", msg_id=first["nudge"]["msg_id"], outcome="skipped", reason="stale_id")
        if state == "pair_cap":
            self.call("harness_send", agent=self.plain, to="role:" + role, body="uses the slot", subject="w", kind="task")
        if state == "vacant":
            self.h.retire(a, "left", by=a)
            return "role:" + role, a
        if state == "retired_id":
            self.h.retire(a, "left", by=a)
            return a, a
        if state == "handed_off_id":
            self.h.handoff(a, CAPSULE)
            return a, a
        return "role:" + role, a

    def mix(self, kind, s1, s2):
        for s in (s1, s2):
            if s == "pair_cap":
                self.op["doorbell"] = {"nudge_per_agent_hour": 60, "nudge_per_pair_hour": 1}
        to = [self.build(s)[0] for s in (s1, s2)]
        with mock.patch.object(D.time, "time", return_value=time.time() + (1400 if "trigger_only" in (s1, s2) else 0)):
            r = self.call("harness_send", agent=self.plain, to=to, body="the body", subject="s", kind=kind)
        covered = is_covered(kind, "none")
        want = [spec(kind, s, "none") for s in (s1, s2)]
        rings = [w for w in want if w == "ring"]
        n = r.get("nudge")
        if rings:
            self.assertIsInstance(n, dict, (kind, s1, s2, brief(r)))
            self.assertEqual(len(n["to"]), len(rings), (kind, s1, s2, n["to"]))              # exactly the recipients whose own row says ring
        else:
            self.assertNotIsInstance(n, dict, (kind, s1, s2, brief(r)))
        evs = self.h.store.read_all()
        misses = [e for e in evs if e["type"] == "nudge.miss" and e["data"].get("msg_id") == r["id"]]
        # a miss is counted for each recipient the spec says counts one (no route, retired id, vacant role, or a stale route with no relay target)
        want_miss = sum(1 for s in (s1, s2) if covered and s in ("no_route", "retired_id", "handed_off_id", "vacant", "stale"))
        self.assertEqual(len(misses), want_miss, "misses for %s %s+%s: %s" % (kind, s1, s2, [m["data"] for m in misses]))
        named(self, r)
        relays = [e for e in evs if e["type"] == "nudge.relay_offer" and e["data"].get("msg_id") == r["id"]]
        self.assertEqual(len(relays), 1 if covered and "pair_cap" in (s1, s2) else 0, (kind, s1, s2))   # the capped recipient is relayed


for _n in [n for n in dir(F.Fixes) if n.startswith("test_")]:
    setattr(Mixes, _n, None)
import itertools
for _k in ("task", "result", "handoff", "notice", "message"):
    for _a, _b in itertools.combinations(Mixes.MIXED, 2):
        if {_a, _b} == {"pair_cap", "stale"}:
            continue
        setattr(Mixes, "test_mix_%s_%s_%s" % (_k, _a, _b), (lambda k, a, b: (lambda self: self.mix(k, a, b)))(_k, _a, _b))


class SameState(F.Fixes):
    """Class A (foresight): two recipients in the SAME state. Every backstop record is keyed by (message, recipient), so each recipient gets its own relay,
    miss or ring, in the send result and after the backstop scan, and no recipient's record hides the other's."""

    STATES2 = ("warm", "cold", "pair_cap", "stale", "no_route", "retired_id", "handed_off_id", "vacant")

    def build2(self, state, n):
        sfx = str(n)
        if state == "no_route":
            role = "librarian" + sfx
            self.h.role_define("operator", role, "harness-ops", carry="none")
            return "role:" + role, self.cowork(role)
        role = {"warm": "curator", "cold": "coder", "pair_cap": "reviewer", "stale": "auditor", "retired_id": "scribe",
                "handed_off_id": "keeper", "vacant": "ghost"}[state] + sfx
        self.h.role_define("operator", role, "harness-ops", carry="none")
        a = self.reg(role, "local_s2_%s_%s" % (state, sfx))
        self.warm(a)
        if state == "cold":
            D._save(D._sp(self.h, a), {"last_call": time.time() - 4000})
        if state == "stale":
            first = self.call("harness_send", agent=self.plain, to="role:" + role, body="first", subject="f", kind="task")
            self.admin(self.plain, "nudge_result", msg_id=first["nudge"]["msg_id"], outcome="skipped", reason="stale_id")
        if state == "pair_cap":
            self.call("harness_send", agent=self.plain, to="role:" + role, body="uses the slot", subject="w", kind="task")
        if state == "vacant":
            self.h.retire(a, "left", by=a)
        if state == "retired_id":
            self.h.retire(a, "left", by=a)
            return a, a
        if state == "handed_off_id":
            self.h.handoff(a, CAPSULE)
            return a, a
        return "role:" + role, a

    def go(self, kind, state):
        if state == "pair_cap":
            self.op["doorbell"] = {"nudge_per_agent_hour": 60, "nudge_per_pair_hour": 1}
        built = [self.build2(state, n) for n in (1, 2)]
        r = self.call("harness_send", agent=self.plain, to=[b[0] for b in built], body="the body", subject="s", kind=kind)
        named(self, r)
        covered = is_covered(kind, "none")
        evs = self.h.store.read_all()
        mid = r["id"]
        misses = {e["data"]["to"] for e in evs if e["type"] == "nudge.miss" and e["data"].get("msg_id") == mid}
        relays = {e["data"]["to"] for e in evs if e["type"] == "nudge.relay_offer" and e["data"].get("msg_id") == mid}
        agents = [b[1] for b in built]
        keys = {"no_route": set(agents), "retired_id": set(agents), "handed_off_id": set(agents), "vacant": {"role:" + b[0][5:] for b in built}}
        if covered and state in keys:
            self.assertEqual(misses, keys[state], (kind, state, brief(r)))                       # one counted miss per recipient, not one for the pair
        if covered and state == "pair_cap":
            self.assertEqual(relays, set(agents), (kind, state, brief(r)))                       # both capped recipients are relayed (was: "already")
        if covered and state == "stale":
            self.assertEqual(misses | relays, set(agents), (kind, state, brief(r)))
        if state in ("warm", "cold"):
            self.assertEqual(len((r["nudge"] or {}).get("to") or []) if isinstance(r.get("nudge"), dict) else 0, 2 if (covered or state == "warm") else 0)
        # the backstop scan after a silent sender: every recipient that was rung and has not read the mail gets its own relay or counted miss
        if covered and state in ("warm", "cold"):
            D.wake_scan(self.h, now=time.time() + 20 * 60, force=True)
            evs = self.h.store.read_all()
            covered_keys = {e["data"]["to"] for e in evs if e["type"] in ("nudge.relay_offer", "nudge.miss") and e["data"].get("msg_id") == mid}
            self.assertEqual(covered_keys, set(agents), (kind, state, covered_keys))


for _n in [n for n in dir(F.Fixes) if n.startswith("test_")]:
    setattr(SameState, _n, None)
for _k in ("task", "result"):
    for _s in SameState.STATES2:
        setattr(SameState, "test_same_%s_%s" % (_k, _s), (lambda k, s_: (lambda self: self.go(k, s_)))(_k, _s))


class DoorbellError(F.Fixes):
    """A failure inside the doorbell is never silent for covered mail: every covered recipient counts a miss with the reason doorbell_error."""

    def setUp(self):
        super().setUp()
        if "curator" not in self.h.state().roles:
            self.h.role_define("operator", "curator", "harness-ops", carry="none")
        self.c = self.reg("curator", "local_de")
        self.warm(self.c)

    def misses(self, mid):
        return [e["data"] for e in self.h.store.read_all() if e["type"] == "nudge.miss" and e["data"].get("msg_id") == mid]

    def test_an_error_in_the_ring_code_counts_a_miss_for_a_covered_mail(self):
        with mock.patch.object(D, "_attach", side_effect=RuntimeError("boom")):
            r = self.call("harness_send", agent=self.plain, to="role:curator", body="b", subject="s", kind="task")
        self.assertIn(r["id"], self.h.inbox(self.c, mark_read=False)["ids"])                  # the send itself still succeeded
        self.assertEqual([m["reason"] for m in self.misses(r["id"])], ["doorbell_error"] * len(self.misses(r["id"])))
        self.assertTrue(self.misses(r["id"]))

    def test_an_error_in_the_holder_code_counts_a_miss_when_nothing_rang(self):
        self.h.role_define("operator", "ghost", "harness-ops", carry="none")                 # a vacant role: no ring, so the holder code is the only path
        with mock.patch.object(D, "_attach_holder", side_effect=RuntimeError("boom")):
            r = self.call("harness_send", agent=self.plain, to="role:ghost", body="b", subject="s", kind="question")
        self.assertEqual([m["reason"] for m in self.misses(r["id"])], ["doorbell_error"])

    def test_an_error_in_the_holder_code_counts_nothing_when_the_mail_already_rang(self):
        with mock.patch.object(D, "_attach_holder", side_effect=RuntimeError("boom")):
            r = self.call("harness_send", agent=self.plain, to=self.c, body="b", subject="s", kind="question")
        self.assertEqual(self.misses(r["id"]), [])

    def test_expects_reply_mail_counts_one_and_uncovered_mail_counts_none(self):
        with mock.patch.object(D, "_attach", side_effect=RuntimeError("boom")):
            a = self.call("harness_send", agent=self.plain, to="role:curator", body="b", subject="s", kind="message", expects_reply=True)
            b = self.call("harness_send", agent=self.plain, to="role:curator", body="b", subject="s", kind="notice")
            c = self.call("harness_send", agent=self.plain, to="role:curator", body="b", subject="s", kind="result")
        self.assertTrue(self.misses(a["id"]))
        self.assertEqual(self.misses(b["id"]), [])
        self.assertEqual(self.misses(c["id"]), [])

    def test_a_covered_task_counts_a_miss_and_the_result_says_so(self):
        with mock.patch.object(D, "_attach", side_effect=RuntimeError("boom")):
            r = self.call("harness_send", agent=self.plain, to="role:curator", body="b", subject="s", kind="task")
        self.assertEqual(r.get("nudge"), "miss (doorbell_error)")                         # the sender is told, from the same records
        named(self, r)

    def test_a_result_answering_an_open_ask_is_covered_on_the_error_path_too(self):         # raw read r5, blocker 2
        q = self.call("harness_send", agent=self.c, to=self.plain, body="please", subject="ask", kind="question")["id"]
        with mock.patch.object(D, "_attach", side_effect=RuntimeError("boom")):
            r = self.call("harness_send", agent=self.plain, to="role:curator", body="done", subject="re", kind="result", reply_to=q)
        self.assertEqual([m["reason"] for m in self.misses(r["id"])], ["doorbell_error"])
        self.assertEqual(r.get("nudge"), "miss (doorbell_error)")
        named(self, r)

    def test_a_message_replying_to_an_open_task_is_covered_on_the_error_path_too(self):
        t = self.call("harness_send", agent=self.c, to=self.plain, body="please", subject="ask", kind="task")["id"]
        with mock.patch.object(D, "_attach", side_effect=RuntimeError("boom")):
            r = self.call("harness_send", agent=self.plain, to="role:curator", body="on it", subject="re", kind="message", reply_to=t)
        self.assertEqual([m["reason"] for m in self.misses(r["id"])], ["doorbell_error"])
        named(self, r)

    def test_a_result_answering_an_answered_ask_counts_nothing_on_the_error_path(self):
        q = self.call("harness_send", agent=self.c, to=self.plain, body="please", subject="ask", kind="question")["id"]
        self.call("harness_send", agent=self.plain, to="role:curator", body="done", subject="re", kind="result", reply_to=q)
        with mock.patch.object(D, "_attach", side_effect=RuntimeError("boom")):
            r = self.call("harness_send", agent=self.plain, to="role:curator", body="late", subject="re", kind="result", reply_to=q)
        self.assertEqual(self.misses(r["id"]), [])                                          # the same covered rule as the normal path

    def test_a_failing_miss_for_a_vacant_role_after_another_recipient_rang_is_not_lost(self):      # foresight class F
        self.h.role_define("operator", "ghost", "harness-ops", carry="none")
        real = D._miss

        def flaky(h, mid, rid, sender, why):
            if why == "no_holder":
                raise OSError("ledger lock timeout")
            return real(h, mid, rid, sender, why)
        with mock.patch.object(D, "_miss", side_effect=flaky):
            r = self.call("harness_send", agent=self.plain, to=["role:curator", "role:ghost"], body="b", subject="s", kind="task")
        self.assertIsInstance(r.get("nudge"), dict)                                           # the curator was rung
        self.assertEqual([m["reason"] for m in self.misses(r["id"]) if m["to"] == "role:ghost"], ["doorbell_error"])
        named(self, r)

    def test_a_working_doorbell_writes_no_doorbell_error(self):
        r = self.call("harness_send", agent=self.plain, to="role:curator", body="b", subject="s", kind="task")
        self.assertEqual([m for m in self.misses(r["id"]) if m["reason"] == "doorbell_error"], [])


for _n in [n for n in dir(F.Fixes) if n.startswith("test_")]:
    setattr(DoorbellError, _n, None)


class Pairs(F.Fixes):
    """Mixed-kind pairs: an answer-kind mail rang the recipient less than 60 s ago and is unread; a second mail of any kind follows."""

    def go(self, first, second, state):
        if "curator" not in self.h.state().roles:
            self.h.role_define("operator", "curator", "harness-ops", carry="none")
        c = self.reg("curator", "local_pp")
        self.warm(c)
        if state == "cold":
            D._save(D._sp(self.h, c), {"last_call": time.time() - 4000})
        a = self.call("harness_send", agent=self.plain, to="role:curator", body="one", subject="s1", kind=first)
        self.assertEqual(outcome(a), "ring", a)
        b = self.call("harness_send", agent=self.plain, to="role:curator", body="two", subject="s2", kind=second)
        # the document, rule 1: a second mail that would ring like an ask is held; any other mail follows its own row
        want = "held" if second in ASK else spec(second, state, "none")
        if second == "handoff" and state == "cold":
            want = "mail_only"                       # the first ring used the cold chat's 30-minute wake slot: it reads both (document, rule 6)
        self.assertEqual(outcome(b), want, "%s then %s (%s): %s" % (first, second, state, brief(b)))
        named(self, b)

    def test_a_held_mail_is_still_unread_mail_and_the_alarm_reads_it(self):
        if "curator" not in self.h.state().roles:
            self.h.role_define("operator", "curator", "harness-ops", carry="none")
        c = self.reg("curator", "local_pq")
        self.warm(c)
        self.call("harness_send", agent=self.plain, to="role:curator", body="one", subject="s1", kind="task")
        b = self.call("harness_send", agent=self.plain, to="role:curator", body="two", subject="s2", kind="question")
        self.assertEqual(outcome(b), "held")
        self.assertTrue(b["nudge_skipped"][0]["reason"].startswith("rung under 60 s ago"), b["nudge_skipped"])      # the text and the document agree
        self.assertIn(b["id"], self.h.inbox(c, mark_read=False)["ids"])                                           # still delivered, unread
        held = [e for e in self.h.store.read_all() if e["type"] == "nudge.skipped" and e["data"]["msg"] == b["id"]]
        self.assertTrue(held)                                                                                     # the record the alarm scan reads


for _n in [n for n in dir(F.Fixes) if n.startswith("test_")]:
    setattr(Pairs, _n, None)
for _f in ASK:
    for _k in KINDS:
        for _s in ("warm", "cold"):
            setattr(Pairs, "test_pair_%s_then_%s_%s" % (_f, _k, _s), (lambda f, k, s: (lambda self: self.go(f, k, s)))(_f, _k, _s))


class Several(F.Fixes):
    """Several recipients: one instruction text, one report per recipient, the keys listed; each recipient follows its own row."""

    def two(self, second):
        self.h.role_define("operator", "ops-coder", "harness-ops", carry="none")
        if "curator" not in self.h.state().roles:
            self.h.role_define("operator", "curator", "harness-ops", carry="none")
        a = self.reg("curator", "local_sv_a")
        self.warm(a)
        if second == "warm":
            b = self.reg("ops-coder", "local_sv_b")
            self.warm(b)
            self.keys = ["local_sv_a", "local_sv_b"]
            return ["role:curator", "role:ops-coder"]
        self.ready()
        self.keys = ["local_sv_a", self.sec[:8]]
        return ["role:curator", "role:secretary"]

    def test_one_waiting_and_one_not_each_follow_their_own_row(self):
        self.h.role_define("operator", "ops-coder", "harness-ops", carry="none")
        if "curator" not in self.h.state().roles:
            self.h.role_define("operator", "curator", "harness-ops", carry="none")
        a = self.reg("curator", "local_sv_w")
        b = self.reg("ops-coder", "local_sv_n")
        self.warm(a)
        self.warm(b)
        q = self.call("harness_send", agent=a, to=self.plain, body="please", subject="ask", kind="question")["id"]
        D._save(D._sp(self.h, a), {"last_call": time.time() - 4000})
        D._save(D._sp(self.h, b), {"last_call": time.time() - 4000})                       # both cold
        r = self.call("harness_send", agent=self.plain, to=["role:curator", "role:ops-coder"], body="done", subject="re", kind="result", reply_to=q)
        n = r["nudge"]
        self.assertIsInstance(n, dict, r)
        self.assertEqual(len(n["to"]), 1)                                                   # only the waiting one is rung
        self.assertIn("local_sv_w", n["to"][0])
        self.assertTrue(r.get("nudge_mail_only"), r)                                        # the other cold, nobody waits: mail only


def _make_several(kind, second):
    def t(self):
        to = self.two(second)
        r = self.call("harness_send", agent=self.plain, to=to, body="b", subject="s", kind=kind)
        if kind in ASK or kind in ("handoff", "result"):
            n = r["nudge"]
            self.assertIsInstance(n, dict, r)
            self.assertEqual(n["do"].count("Do: SendMessage"), 1)                       # the text once
            self.assertIn("One report per recipient", n["do"])
            for k in self.keys:
                self.assertIn(k, n["do"])
            self.assertEqual(len(n["to"]), 2)
        else:
            self.assertNotIsInstance(r.get("nudge"), dict)
            if kind == "notice":
                self.assertEqual(r.get("nudge"), "none (kind notice starts no wake)")        # the wording
            else:
                self.assertIsNone(r.get("nudge"))                                              # a plain message says nothing
            self.assertFalse(r.get("nudge_skipped"))
            evs = self.h.store.read_all()
            self.assertEqual([e for e in evs if e["type"] in ("nudge.relay_offer", "nudge.miss", "nudge.offered") and (e["data"].get("msg_id") == r["id"])], [])   # no relay, no miss
    return t


for _k in KINDS:
    for _sec in ("warm", "with_trigger"):
        setattr(Several, "test_several_%s_%s" % (_k, _sec), _make_several(_k, _sec))


for _n in [n for n in dir(F.Fixes) if n.startswith("test_")]:
    setattr(Several, _n, None)


class Chats(F.Fixes):
    """Superseded chats: a send to a predecessor's agent id reaches the successor; a reply to an ask the recipient's predecessor sent is a reply to an open ask."""

    def test_a_send_to_the_agent_id_of_a_superseded_chat_rings_its_successor(self):
        if "curator" not in self.h.state().roles:
            self.h.role_define("operator", "curator", "harness-ops", carry="none")
        old = self.reg("curator", "local_old")
        self.warm(old)
        new = self.reg("curator", "local_new")                                              # a no-carry successor takes the role
        self.warm(new)
        r = self.call("harness_send", agent=self.plain, to=old, body="b", subject="s", kind="task")
        n = r.get("nudge")
        self.assertIsInstance(n, dict, r)
        self.assertIn("local_new", " ".join(n["to"]))
        self.assertIn(r["id"], self.h.inbox(new, mark_read=False)["ids"])

    def test_a_reply_to_an_ask_the_predecessor_sent_rings_the_cold_successor(self):
        if "curator" not in self.h.state().roles:
            self.h.role_define("operator", "curator", "harness-ops", carry="none")
        old = self.reg("curator", "local_old2")
        self.warm(old)
        q = self.call("harness_send", agent=old, to=self.plain, body="please", subject="ask", kind="question")["id"]
        new = self.reg("curator", "local_new2")
        self.warm(new)
        D._save(D._sp(self.h, new), {"last_call": time.time() - 4000})
        r = self.call("harness_send", agent=self.plain, to="role:curator", body="done", subject="re", kind="result", reply_to=q)
        self.assertIsInstance(r.get("nudge"), dict, brief(r))


for _n in [n for n in dir(F.Fixes) if n.startswith("test_") and n not in ("test_a_send_to_the_agent_id_of_a_superseded_chat_rings_its_successor",
                                                                          "test_a_reply_to_an_ask_the_predecessor_sent_rings_the_cold_successor")]:
    setattr(Chats, _n, None)


class Senders(F.Fixes):
    """Operator and system mail start no ring; operator mail is owed, never cut and never dismissed."""

    def setUp(self):
        super().setUp()
        if "curator" not in self.h.state().roles:
            self.h.role_define("operator", "curator", "harness-ops", carry="none")
        self.c = self.reg("curator", "local_sd")
        self.warm(self.c)


def _make_sender(kind, who):
    def t(self):
        r = self.h.send(who, self.c, "from " + who, kind=kind)
        self.assertFalse(isinstance(r.get("nudge"), dict), r.get("nudge"))
        self.assertIn(r["id"], self.h.inbox(self.c, mark_read=False)["ids"])             # delivered
        owed = D.owed_replies(self.h.state(), self.c)
        self.assertEqual(r["id"] in owed, kind in ASK and who == "operator")            # operator asks are owed; system mail never is
        if who == "operator":
            self.assertEqual(self.h.owed_close(self.c, [r["id"]]).get("refused_operator_mail"), [r["id"]])   # never dismissed
    return t


for _k in KINDS:
    for _w in ("operator", "system"):
        setattr(Senders, "test_sender_%s_%s" % (_k, _w), _make_sender(_k, _w))
for _n in [n for n in dir(F.Fixes) if n.startswith("test_")]:
    setattr(Senders, _n, None)


class Records(unittest.TestCase):
    """Read and owed state, and the inbox cut, per kind."""

    def setUp(self):
        self.home = os.path.join(tempfile.mkdtemp(), "h")
        os.makedirs(self.home)
        self.h = H.Harness(self.home)
        self.a = self.h.register(project="orch", model=MODEL, session_id="s-a")["id"]
        self.b = self.h.register(project="orch", model=MODEL, session_id="s-b")["id"]

    def unread(self):
        return self.h.inbox(self.b, mark_read=False)["ids"]

    def owed(self):
        return D.owed_replies(self.h.state(), self.b)


def _make_records(kind):
    def t(self):
        mid = self.h.send(self.a, self.b, "short body", kind=kind)["id"]
        self.assertEqual(self.unread(), [mid])                                         # delivered: unread until read
        self.assertEqual(mid in self.owed(), kind in ASK)                              # owed iff an ask
        self.h.inbox(self.b)
        self.assertEqual(self.unread(), [])                                            # a short mail is read by one listing
        self.assertEqual(mid in self.owed(), kind in ASK)                              # reading does not answer
        if kind in ASK:
            self.h.send(self.b, self.a, "on it", kind="message", reply_to=mid)         # an acknowledgement
            self.assertNotIn(mid, self.owed())                                         # clears the replier's owed list (0.25.0 rule)
            st = self.h.state()
            probe = dict(st.messages[mid], id="m-x", seq=10 ** 9, **{"from": self.b})
            self.assertTrue(D._ask_open(st, st.messages[mid], probe))                  # but the asker's wait stays open
            self.h.send(self.b, self.a, "done", kind="result", reply_to=mid)
            st = self.h.state()
            probe = dict(st.messages[mid], id="m-y", seq=10 ** 9, **{"from": self.b})
            self.assertFalse(D._ask_open(st, st.messages[mid], probe))                 # a result closes it
    return t


def _make_expects(kind):
    def t(self):
        mid = self.h.send(self.a, self.b, "short body", kind=kind, expects_reply=True)["id"]
        self.assertIn(mid, self.owed())                                                # expects_reply is an ask: owed
        self.h.send(self.b, self.a, "ack", kind="message", reply_to=mid)
        st = self.h.state()
        probe = dict(st.messages[mid], id="m-x", seq=10 ** 9, **{"from": self.b})
        self.assertTrue(D._ask_open(st, st.messages[mid], probe))                      # an ack does not close it
    return t


def _make_cut(kind, how):
    """how: short | long | long_expects | long_operator."""
    def t(self):
        body = ("word " * 400)[: 900 if how == "short" else 1497] + "QQQ"
        kw = {"expects_reply": True} if how == "long_expects" else {}
        sender = "operator" if how == "long_operator" else self.a
        mid = self.h.send(sender, self.b, body, kind=kind, **kw)["id"]
        text = self.h.inbox(self.b)["text"]
        cut = how == "long" and kind not in ASK + ("handoff",)                          # the document, section 3
        self.assertEqual("QQQ" not in text, cut)
        self.assertEqual(self.unread() == [mid], cut)                                  # a cut mail stays unread after the first listing
        if cut:
            self.assertIn("harness_recall ids=[%s]" % mid, text)                         # the pointer
            self.h.inbox(self.b)                                                        # the second listing: no ask waits on it, so it is read
            self.assertEqual(self.unread(), [])
    return t


for _k in KINDS:
    setattr(Records, "test_records_%s" % _k, _make_records(_k))
    setattr(Records, "test_expects_%s" % _k, _make_expects(_k))
    for _l in ("short", "long", "long_expects", "long_operator"):
        setattr(Records, "test_cut_%s_%s" % (_k, _l), _make_cut(_k, _l))


class Scan(F.Fixes):
    """Backstops: a ring that was reported delivered and never read is rewoken at 15 minutes; a ring its sender never reported gets a relay (or a counted
    miss) within 20 minutes. Both only for covered mail."""

    def go(self, kind, shape, report):
        self.ready()
        if "curator" not in self.h.state().roles:
            self.h.role_define("operator", "curator", "harness-ops", carry="none")
        c = self.reg("curator", "local_sc")
        self.warm(c)
        kw = {}
        if shape in ("reply_open", "reply_answered"):
            q = self.call("harness_send", agent=c, to=self.plain, body="ask", subject="ask", kind="question")["id"]
            if shape == "reply_answered":
                self.call("harness_send", agent=self.plain, to="role:curator", body="done", subject="re", kind="result", reply_to=q)
            kw["reply_to"] = q
        if shape == "expects":
            kw["expects_reply"] = True
        t0 = time.time()
        r = self.call("harness_send", agent=self.plain, to="role:curator", body="b", subject="s", kind=kind, **kw)
        covered = kind in ASK or (shape == "expects") or (shape == "reply_open" and kind in ("result", "handoff", "message"))
        n = r.get("nudge")
        if not isinstance(n, dict):
            self.assertFalse(covered and kind != "notice" or covered and shape == "expects", (kind, shape, r))     # a covered mail always rings a warm chat
            return
        mid = n["msg_id"]
        if report == "delivered":
            self.admin(self.plain, "nudge_result", msg_id=mid, outcome="delivered", reason="")
            out = D.wake_scan(self.h, now=t0 + 16 * 60, force=True)
            got = any(k_.startswith("rewake") and m_ == mid for k_, m_ in out)
        else:
            out = D.wake_scan(self.h, now=t0 + 20 * 60, force=True)
            got = any(k_ in ("relay", "miss") and m_ == mid for k_, m_ in out)
        self.assertEqual(got, covered, "kind=%s shape=%s %s: %s" % (kind, shape, report, out))


for _n in [n for n in dir(F.Fixes) if n.startswith("test_")]:
    setattr(Scan, _n, None)
for _k in KINDS:
    for _sh in ("none", "reply_open", "reply_answered", "expects"):
        for _rp in ("delivered", "silent"):
            setattr(Scan, "test_scan_%s_%s_%s" % (_k, _sh, _rp), (lambda k, sh, rp: (lambda self: self.go(k, sh, rp)))(_k, _sh, _rp))


class SilentSender(F.Fixes):
    """Spec rule 8: a sender that never reports the ring of a covered send to several recipients gets a relay request or a counted miss for EVERY
    recipient that has not read the mail, not only the first."""

    def setUp(self):
        super().setUp()
        self.h.role_define("operator", "ops-coder", "harness-ops", carry="none")
        if "curator" not in self.h.state().roles:
            self.h.role_define("operator", "curator", "harness-ops", carry="none")
        self.a = self.reg("curator", "local_ss_a")
        self.b = self.reg("ops-coder", "local_ss_b")
        self.warm(self.a)
        self.warm(self.b)

    def events(self, t, mid):
        return [e["data"] for e in self.h.store.read_all() if e["type"] == t and (e["data"].get("msg_id") == mid)]

    def test_each_unread_recipient_gets_its_own_relay(self):
        r = self.call("harness_send", agent=self.plain, to=["role:curator", "role:ops-coder"], body="b", subject="s", kind="task")
        mid = r["nudge"]["msg_id"]
        out = D.wake_scan(self.h, now=time.time() + 20 * 60, force=True)                      # the sender never reported
        offers = self.events("nudge.relay_offer", mid)
        self.assertEqual(sorted(o["to"] for o in offers), sorted([self.a, self.b]), offers)  # one relay request per recipient
        self.assertEqual(len([o for o in out if o[1] == mid]), 2)

    def test_a_recipient_that_read_the_mail_gets_no_relay(self):
        r = self.call("harness_send", agent=self.plain, to=["role:curator", "role:ops-coder"], body="b", subject="s", kind="task")
        mid = r["nudge"]["msg_id"]
        self.call("harness_inbox", agent=self.a)                                              # the first recipient reads it
        D.wake_scan(self.h, now=time.time() + 20 * 60, force=True)
        self.assertEqual([o["to"] for o in self.events("nudge.relay_offer", mid)], [self.b])

    def test_a_recipient_with_no_route_counts_a_miss_not_silence(self):
        self.ready()
        r = self.call("harness_send", agent=self.plain, to=["role:curator", "role:secretary"], body="b", subject="s", kind="task")
        mid = r["nudge"]["msg_id"]
        D.wake_scan(self.h, now=time.time() + 20 * 60, force=True)
        keys = {o["to"] for o in self.events("nudge.relay_offer", mid)} | {m["to"] for m in self.events("nudge.miss", mid)}
        self.assertEqual(keys, {self.a, self.sec})                                            # both are covered by a relay or a counted miss

    def test_a_single_recipient_send_is_unchanged(self):
        r = self.call("harness_send", agent=self.plain, to="role:curator", body="b", subject="s", kind="task")
        mid = r["nudge"]["msg_id"]
        D.wake_scan(self.h, now=time.time() + 20 * 60, force=True)
        self.assertEqual(len(self.events("nudge.relay_offer", mid)), 1)


for _n in [n for n in dir(F.Fixes) if n.startswith("test_")]:
    setattr(SilentSender, _n, None)


class Stale(F.Fixes):
    """The class rule on a closed route: the second task after a stale mark has a relay or a counted miss, a record the alarm scan reads, and an alarm."""

    def test_a_second_task_after_a_stale_mark_is_not_silent(self):
        self.ready()
        if "curator" not in self.h.state().roles:
            self.h.role_define("operator", "curator", "harness-ops", carry="none")
        c = self.reg("curator", "local_st")
        self.warm(c)
        first = self.call("harness_send", agent=self.plain, to="role:curator", body="one", subject="s1", kind="task")
        self.admin(self.plain, "nudge_result", msg_id=first["nudge"]["msg_id"], outcome="skipped", reason="stale_id")
        second = self.call("harness_send", agent=self.plain, to="role:curator", body="two", subject="s2", kind="task")
        self.assertEqual(outcome(second), "route_backstop", brief(second))
        evs = self.h.store.read_all()
        self.assertTrue([e for e in evs if e["type"] == "nudge.miss" and e["data"]["msg_id"] == second["id"]]
                        or [e for e in evs if e["type"] == "nudge.relay_offer" and e["data"]["msg_id"] == second["id"]])
        self.assertTrue([e for e in evs if e["type"] == "nudge.skipped" and e["data"]["msg"] == second["id"]])     # what the alarm scan reads
        later = time.time() + 4000
        seen = []
        with mock.patch.object(D, "_last_activity", lambda h, st, rid: later):
            seen += [x["msg_id"] for x in D.alarm_scan(self.h, now=later, force=True)]
            for k in range(1, 4):                      # at most one alarm per role per hour: the next one follows in the next hour
                later += 3700
                seen += [x["msg_id"] for x in D.alarm_scan(self.h, now=later, force=True)]
        self.assertIn(second["id"], seen)                                                                         # the alarm covers it


for _n in [n for n in dir(F.Fixes) if n.startswith("test_") and n != "test_a_second_task_after_a_stale_mark_is_not_silent"]:
    setattr(Stale, _n, None)


if __name__ == "__main__":
    unittest.main()
