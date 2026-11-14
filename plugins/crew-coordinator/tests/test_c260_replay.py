"""cc 0.26.0 replay test: a ledger written before 0.26.0 (only event types 0.25.0 knew) folds into the same derived state through the new State: roles,
wake routines, cases, defects, tasks, messages and reads, release scopes. The owed lists differ only where an item says so (items 6 to 10), and each
such difference is asserted here. A real-ledger comparison against the 0.25.0 tree is `projects/orchestration/scripts/ledger_replay_diff.py`.
Run: python3 -B tests/test_c260_replay.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _env  # noqa: F401  isolate HOME and HARNESS_* first
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
import doorbell as D
import harness as H

MODEL = "claude-sonnet-5-5"
NEW_TYPES = {"owed.closed", "result.measured", "hook.virtue", "hook.barepath"}


def old_owed(st, aid):
    """The 0.25.0 owed_replies, as it was, so the new list can be compared with it."""
    mine = set(st.lineage(aid))
    role = st.role_of(aid)
    out = []
    for mid in st.order:
        m = st.messages[mid]
        if m["from"] in mine or D.is_system_sender(m["from"]):
            continue
        if not (mine & set(m.get("to_resolved", [])) or (role and f"role:{role}" in m["to"])):
            continue
        if not (m["kind"] in ("task", "question", "review") or m.get("expects_reply")):
            continue
        if (st.tasks.get(mid) or {}).get("state") in D.TERMINAL:
            continue
        if any(st.messages[x]["from"] in mine and st.messages[x]["seq"] > m["seq"] for x in st.threads[m["thread"]]["messages"]):
            continue
        out.append(mid)
    return out


def derived(st):
    return {
        "roles": {r: v.get("holder") for r, v in sorted(st.roles.items())},
        "wake_reg": {k: {kk: vv for kk, vv in v.items() if kk in ("trigger", "state", "holder", "session")} for k, v in sorted(st.wake_reg.items())},
        "cases": {k: (c["severity"], bool(c["closed"]), len(c["cards"])) for k, c in sorted(st.cases.items())},
        "defects": {k: (v.get("severity"), v.get("superseded_by")) for k, v in sorted(st.defects.items())},
        "tasks": {k: tk["state"] for k, tk in sorted(st.tasks.items())},
        "messages": len(st.messages),
        "reads": sorted((m, sorted(v["read_by"])) for m, v in st.messages.items()),
        "scopes": sorted("%s %s" % k for k in st.release_scopes),
    }


class Replay(unittest.TestCase):
    def setUp(self):
        self.home = os.path.join(tempfile.mkdtemp(), "h")
        os.makedirs(self.home)
        self.h = H.Harness(self.home)
        for r in ("lead", "coder", "other"):
            self.h.role_define("operator", r, "orch")
        self.ids = {}
        for r in ("lead", "coder", "other"):
            a = self.h.register(project="orch", model=MODEL, session_id="s-" + r)["id"]
            self.h.role_assign("operator", r, a)
            self.ids[r] = a
        L, C, O = self.ids["lead"], self.ids["coder"], self.ids["other"]
        self.t1 = self.h.send(L, C, "do x", kind="task")["id"]
        self.q1 = self.h.send(L, "role:coder", "question?", kind="question")["id"]
        self.n1 = self.h.send(L, C, "fyi", kind="notice")["id"]
        self.both = self.h.send(L, [C, O], "both", kind="task")["id"]
        self.h.inbox(C)                                              # reads t1, q1, n1, both
        self.h.send(C, L, "ok", kind="notice", reply_to=self.t1)      # answers t1 on its thread
        self.h.task_update(C, self.t1, "working")
        self.events = self.h.store.read_all()

    def test_the_ledger_holds_no_event_type_the_new_code_added(self):
        self.assertFalse({e["type"] for e in self.events} & NEW_TYPES)

    def test_the_fold_of_the_raw_events_equals_the_live_state(self):
        self.assertEqual(derived(H.State(self.events)), derived(self.h.state()))

    def test_the_derived_state_is_what_0_25_0_derived(self):
        d = derived(H.State(self.events))
        self.assertEqual(d["roles"], {r: self.ids[r] for r in ("coder", "lead", "other")})
        self.assertEqual(d["tasks"][self.t1], "working")
        self.assertEqual(d["tasks"][self.both], "submitted")
        self.assertEqual(d["messages"], 5)
        reads = dict(d["reads"])
        self.assertEqual(sorted(reads[self.t1]), [self.ids["coder"]])
        self.assertEqual(reads[self.n1], [self.ids["coder"]])
        self.assertEqual(d["wake_reg"], {})
        self.assertEqual((d["cases"], d["defects"], d["scopes"]), ({}, {}, []))

    def test_the_new_fold_fields_start_empty_on_an_old_ledger(self):
        st = H.State(self.events)
        self.assertEqual(st.owed_closed, {})
        self.assertEqual({r: sorted(v) for r, v in st.role_ever.items()}, {r: [self.ids[r]] for r in ("coder", "lead", "other")})

    def test_owed_lists_equal_the_0_25_0_lists_for_this_ledger(self):
        st = H.State(self.events)
        for r, a in self.ids.items():
            self.assertEqual(D.owed_replies(st, a), old_owed(st, a), r)

    def test_owed_differs_only_where_an_item_says_so(self):
        L, C, O = self.ids["lead"], self.ids["coder"], self.ids["other"]
        # item 7: a ref to the mail in a notice to the sender clears it across threads (0.25.0 kept it owed)
        self.h.send(C, L, "see " + self.q1, kind="notice", refs=[self.q1])
        st = H.State(self.h.store.read_all())
        self.assertIn(self.q1, old_owed(st, C))
        self.assertNotIn(self.q1, D.owed_replies(st, C))                # item 7
        # item 6: another holder of the role answers role mail for the role
        c2 = self.h.register(project="orch", model=MODEL, session_id="s-c2")["id"]
        self.h.role_assign("operator", "coder", c2)
        q2 = self.h.send(L, "role:coder", "second?", kind="question")["id"]
        self.h.send(c2, L, "answer", kind="notice", reply_to=q2)
        st = H.State(self.h.store.read_all())
        self.assertEqual(D.owed_replies(st, c2), [])                    # item 6: nothing inherited, nothing owed after its own answer
        # item 8: a co-recipient's result completes it for the other recipient
        self.assertIn(self.both, D.owed_replies(st, O))
        self.h.send(C, L, "done", kind="result", reply_to=self.both)
        st = H.State(self.h.store.read_all())
        self.assertIn(self.both, old_owed(st, O))
        self.assertNotIn(self.both, D.owed_replies(st, O))


if __name__ == "__main__":
    unittest.main()
