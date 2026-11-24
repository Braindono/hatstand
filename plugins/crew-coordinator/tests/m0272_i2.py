"""0.27.2 matrix rows for I2 (archive and pin reasons checked when the approval is requested). Each ROWS entry is one row of the I2 table: fn(testcase).
Depends on: scripts/harness.py (request_approval, archive, pin), scripts/corpus.py (check_reason)."""
import os, shutil, sys, tempfile
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
import harness as H

MODEL = "claude-sonnet-5-5"
LINE_A, LINE_B = "the first rule line of entry A", "the second rule line of entry B"


class World:
    """A temporary home with a requester, two live notes by it, one mechanical note (completed: its author retired) and one decision-free capsule-less set."""

    def __init__(self, tc):
        self.tmp = tempfile.mkdtemp(prefix="i2-")
        tc.addCleanup(shutil.rmtree, self.tmp, True)
        env = mock.patch.dict(os.environ, {"HARNESS_CACHE": os.path.join(self.tmp, "cache")})
        env.start()
        tc.addCleanup(env.stop)
        self.h = H.Harness(os.path.join(self.tmp, "home"))
        self.me = self.h.register(project="orchestration", model=MODEL)["id"]
        self.a = self.h.record(self.me, "note", "note A", LINE_A)["id"]
        self.b = self.h.record(self.me, "note", "note B", LINE_B)["id"]
        old = self.h.register(project="orchestration", model=MODEL)["id"]
        self.m = self.h.record(old, "note", "completed note", "a finished note")["id"]
        self.h.retire(old, "gone")
        self.h.corpus.refresh()

    def ask(self, action, ids, reason, **extra):
        return self.h.request_approval(self.me, action, dict({"ids": ids, "reason": reason}, **extra))

    def refused(self, tc, action, ids, reason, text=None, **extra):
        with tc.assertRaises(H.HarnessError) as cm:
            self.ask(action, ids, reason, **extra)
        if text:
            tc.assertIn(text, str(cm.exception))
        return str(cm.exception)

    def events(self, t):
        return [e for e in self.h.store.read_all() if e.get("type") == t]


def r_quotes_each(tc):
    w = World(tc)
    r = w.ask("archive_operator", [w.a, w.b], f'rule lines: "{LINE_A}" and "{LINE_B}"')
    tc.assertIn("pending", r)
    tc.assertTrue(w.ask("pin_operator", [w.a], f'"{LINE_A}"', on=True)["pending"])


def r_quotes_some(tc):
    w = World(tc)
    msg = w.refused(tc, "archive_operator", [w.a, w.b], f'only "{LINE_A}"', "no matching quote")
    tc.assertIn(w.b, msg)
    tc.assertNotIn(w.a, msg)
    tc.assertEqual(w.events("approval.requested"), [])


def r_no_quote(tc):
    w = World(tc)
    at_request = w.refused(tc, "archive_operator", [w.a], "I think this is old")
    with tc.assertRaises(H.HarnessError) as cm:                                      # apply keeps its own check, with the same text
        w.h.archive("operator", [w.a], "I think this is old", _approved=True)
    tc.assertEqual(at_request, str(cm.exception))


def r_empty_mechanical(tc):
    w = World(tc)
    for reason in ("", "   \n\t"):                                                  # whitespace-only counts as empty
        tc.assertIn("pending", w.ask("archive_operator", [w.m], reason))
    out = w.h.archive("operator", [w.m], "", _approved=True)                         # the gate auto-fills at apply
    tc.assertEqual(out["archived"], [w.m])


def r_empty_non_mechanical(tc):
    w = World(tc)
    w.refused(tc, "archive_operator", [w.a], "", "reason required")
    w.refused(tc, "archive_operator", [w.a, w.m], "  ", "reason required")           # one non-mechanical entry spoils the set
    w.refused(tc, "pin_operator", [w.m], "", "reason required", on=True)             # pin has no mechanical auto-fill


def r_unknown_id(tc):
    w = World(tc)
    text = w.refused(tc, "archive_operator", ["N-00000"], f'"{LINE_A}"', "unknown ids")
    with tc.assertRaises(H.HarnessError) as cm:
        w.h.archive("operator", ["N-00000"], f'"{LINE_A}"', _approved=True)
    tc.assertEqual(text, str(cm.exception))
    w.refused(tc, "pin_operator", ["N-00000"], f'"{LINE_A}"', "unknown ids")
    w.refused(tc, "archive_operator", [], f'"{LINE_A}"', "ids required")


def r_unpin_and_pin(tc):
    w = World(tc)
    w.refused(tc, "pin_operator", [w.a], "no quote here", "unpin: reason must quote", on=False)
    w.refused(tc, "pin_operator", [w.a], "no quote here", "pin: reason must quote", on=True)
    w.refused(tc, "pin_operator", [w.a], "", "unpin: reason required", on=False)
    tc.assertIn("pending", w.ask("pin_operator", [w.a], f'"{LINE_A}"', on=False))


def r_already_archived(tc):
    """As at apply: an archived entry is still a known id, so the request passes exactly when apply would (the same check, not a new refusal)."""
    w = World(tc)
    w.h.archive("operator", [w.a], f'"{LINE_A}"', _approved=True)
    w.h.corpus.refresh()
    tc.assertIn("pending", w.ask("archive_operator", [w.a], f'"{LINE_A}"'))
    w.refused(tc, "archive_operator", [w.a], "no quote")


def r_apply_keeps_check(tc):
    w = World(tc)
    for reason in ("", "no quote"):
        with tc.assertRaises(H.HarnessError):
            w.h.archive("operator", [w.a], reason, _approved=True)
        with tc.assertRaises(H.HarnessError):
            w.h.pin("operator", [w.a], True, reason)


def r_one_classifier(tc):
    import inspect
    src = inspect.getsource(H.Harness._archive_gate) + inspect.getsource(H.Harness._check_reason_at_request)
    tc.assertEqual(src.count("_mechanical_row"), 1)                                  # the gate calls the one classifier; the request check calls the gate (B1), no copy
    tc.assertIn("self._archive_gate(", inspect.getsource(H.Harness._check_reason_at_request))
    tc.assertNotIn('("capsule", "note")', src)


def _owned_decision(w):
    """A decision written by an agent holding the role writer-role (its owner), plus that owner's id."""
    w.h.role_define("operator", "writer-role", "orchestration")
    owner = w.h.register(project="orchestration", model=MODEL)["id"]
    w.h.role_assign("operator", "writer-role", owner)
    d = w.h.record(owner, "decision", "owned decision", "the decision rule line")["id"]
    w.h.corpus.refresh()
    return d, owner


def r_decision_needs_ack(tc):
    """Critic code round 1 B1: a D-* entry without the owner's ack is refused when requested, as apply would refuse it."""
    w = World(tc)
    d, _owner = _owned_decision(w)
    msg = w.refused(tc, "archive_operator", [d], '"the decision rule line"', "need the owner's ack")
    tc.assertIn(d, msg)
    tc.assertEqual(w.events("approval.requested"), [])
    with tc.assertRaises(H.HarnessError) as cm:
        w.h.archive("operator", [d], '"the decision rule line"', _approved=True)
    tc.assertEqual(msg, str(cm.exception))


def r_decision_with_ack(tc):
    w = World(tc)
    d, owner = _owned_decision(w)
    ack = w.h.send(owner, w.me, f"ack archive {d}")["id"]
    tc.assertIn("pending", w.ask("archive_operator", [d], '"the decision rule line"', ack=ack))
    tc.assertEqual(w.h.archive("operator", [d], '"the decision rule line"', ack=ack, _approved=True)["archived"], [d])


def r_open_handoff_capsule(tc):
    w = World(tc)
    cap = w.h.record(w.me, "capsule", "open handoff capsule", "a capsule of a live author")["id"]
    w.h.corpus.refresh()
    w.refused(tc, "archive_operator", [cap], '"a capsule of a live author"', "never archived")
    tc.assertEqual(w.events("approval.requested"), [])


ROWS = {"I2-01": r_quotes_each, "I2-02": r_quotes_some, "I2-03": r_no_quote, "I2-04": r_empty_mechanical, "I2-05": r_empty_non_mechanical, "I2-06": r_unknown_id,
        "I2-07": r_unpin_and_pin, "I2-08": r_already_archived, "I2-09": r_apply_keeps_check, "I2-10": r_one_classifier,
        "I2-11": r_decision_needs_ack, "I2-12": r_decision_with_ack, "I2-13": r_open_handoff_capsule}
