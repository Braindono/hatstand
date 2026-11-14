"""cc 0.26.0 item 17: housekeeping. Steward or envoy archive and pin of routine (non-decision, unpinned) entries skip approval; restore auto-confirms
on a matching open capsule when the holder is idle. Run: python3 -B tests/test_c260_item17.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _env  # noqa: F401  isolate HOME and HARNESS_* first
import os
import unittest
from unittest import mock

import test_cc154_restore_auto as R
from test_cc154_restore_auto import H, M
from test_cc151_w1 import Base, MODEL


class Housekeeping(Base):
    def test_a_steward_pins_a_routine_note_without_approval(self):
        steward, w = self.agent("steward"), self.agent()
        n = self.note(w)
        self.as_(steward)
        r = self.adm("pin", steward, ids=[n], reason='"rule line text"')
        self.assertIn("pinned", r)
        self.assertEqual(self.types("approval.requested"), [])

    def test_not_routine_still_needs_approval(self):
        steward, owner, w = self.agent("steward"), self.agent("writer-role"), self.agent()
        d = self.h.record(owner, "decision", "owned", "the decision rule")["id"]
        n = self.note(w)
        self.as_(steward)
        self.assertIn("pending", self.adm("pin", steward, ids=[d], reason='"the decision rule"'))          # a decision
        self.assertIn("pending", self.adm("pin", steward, ids=[n, d], reason='"rule line text"'))           # one decision among routine ones
        self.assertIn("pinned", self.adm("pin", steward, ids=[n], reason='"rule line text"'))
        self.assertIn("pending", self.adm("pin", steward, ids=[n], reason='"rule line text"'))             # already pinned: not routine
        self.assertIn("pending", self.adm("pin", steward, ids=[n], off=True, reason='"rule line text"'))   # an unpin is never routine

    def test_a_plain_agent_and_unknown_ids_still_need_approval(self):
        a = self.agent()
        n = self.note(a)
        self.as_(a)
        self.assertIn("pending", self.adm("pin", a, ids=[n], reason='"rule line text"'))

    def test_the_role_comes_from_registration(self):
        a = self.agent()
        n = self.note(a)
        with self.assertRaisesRegex(H.HarnessError, "unknown args"):
            self.adm("pin", a, ids=[n], role="steward")

    def test_envoy_archives_a_routine_note_directly_and_the_open_capsule_is_still_refused(self):
        envoy, w = self.agent("envoy"), self.agent()
        n = self.note(w)
        self.as_(envoy)
        self.assertIn("archived", self.adm("archive", envoy, ids=[n], reason='"rule line text"'))
        self.assertEqual(self.types("approval.requested"), [])


class RestoreIdle(R.RestoreAuto):
    """The inherited tests run again unchanged (explicit capsule + confirmed); the new ones are below."""

    def plain(self, role="lead"):
        M.BOUND.update(home=None, id=None)
        return M.call(self.h, "harness_restore", {"role": role, "model": MODEL})          # no confirmed, no capsule

    def test_an_idle_holder_with_a_matching_open_capsule_restores_with_no_confirm_and_no_capsule_path(self):
        a = self.holder()
        self.handoff(a)
        with mock.patch.object(H.Harness, "holder_activity", return_value=900):          # the last hook ran 15 minutes ago: known idle
            r = self.plain()
        self.assertNotIn("pending", r, r)
        self.assertNotIn("was seen", r.get("text", ""))
        self.assertEqual(len(self.types("restore.auto")), 1)
        self.assertEqual(self.pending(), [])

    def test_a_holder_with_no_hook_record_is_not_known_idle_and_is_not_auto_confirmed(self):     # critic (non-blocking)
        a = self.holder()
        self.handoff(a)
        with mock.patch.object(H.Harness, "holder_activity", return_value=None):
            r = self.plain()
        self.assertIn("was seen", r.get("text", ""))
        self.assertEqual(self.types("restore.auto"), [])

    def test_a_busy_holder_is_not_auto_confirmed(self):
        a = self.holder()
        self.handoff(a)
        with mock.patch.object(H.Harness, "holder_activity", return_value=5):               # a hook ran 5 s ago
            r = self.plain()
        self.assertIn("was seen", r.get("text", ""))
        self.assertEqual(self.types("restore.auto"), [])

    def test_a_holder_that_handed_off_nothing_is_not_auto_confirmed(self):
        self.holder()
        r = self.plain()
        self.assertIn("was seen", r.get("text", ""))
        self.assertEqual(self.types("restore.auto"), [])

    def test_a_gated_role_is_not_auto_confirmed(self):
        a = self.holder("corpus-envoy")
        self.handoff(a, role="corpus-envoy")
        r = self.plain("corpus-envoy")
        self.assertIn("was seen", r.get("text", ""))
        self.assertEqual(self.types("restore.auto"), [])


if __name__ == "__main__":
    unittest.main()
