"""cc 0.24.1 (wake belongs to the role): a verified routine stays the role's wake across any holder change; it is listed for disabling only
when a different trigger replaced it; a same-trigger re-registration keeps it; a new holder sees which chat it wakes.
Run: python3 -B tests/test_c241_wake_role.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _env  # noqa: F401  isolate HOME and HARNESS_* first
import unittest

import test_c240_item13 as I
from test_c240_item13 import D, H, T1, T2, S1, S2

CREATE = "wake routine: create one"
LINE = "wake routine for role:secretary is bound to session"


class WakeRole(I.C.Base):
    # helpers borrowed from the item 13 tests (no inheritance from a test class)
    for _n in ("cowork", "admin", "register", "verify", "ready", "send", "do", "fire", "good", "state", "text", "relay_line"):
        locals()[_n] = I.Item13.__dict__[_n]
    del _n

    def setUp(self):
        I.C.Base.setUp(self)
        self.op["doorbell"] = {"nudge_per_agent_hour": 60, "nudge_per_pair_hour": 30}
        self.h.role_define("operator", "harness-critic", "harness-ops", carry="none")
        self.sec = self.cowork("secretary")
        self.env = self.reg("envoy", "local_env")
        self.warm(self.env)
        self.k = 0

    def sync(self, who):
        return self.text(self.call("harness_sync", agent=who))

    def heir(self, **kw):
        return self.cowork("secretary", predecessor=self.sec, **kw)

    def reg_entry(self):
        return D.reg_state(self.h.state(), "secretary")[0]

    # items 1 and 2: the holder changes, the wake stays
    def test_same_chat_successor_keeps_the_wake_and_lists_nothing(self):
        self.ready()
        new = self.heir()
        self.assertEqual(self.state(), "verified")
        self.assertIn(T1, self.do())
        self.assertNotIn("enabled=false", self.relay_line(self.env))
        self.assertEqual(D.wake_to_disable(self.h.state()), {})
        self.assertNotIn(CREATE, self.sync(new))                            # item 6: no "create one" line

    def test_fresh_no_carry_restore_keeps_the_wake(self):
        self.ready()
        new = self.cowork("secretary")                                       # no predecessor: a fresh chat takes the role
        self.assertEqual(self.h.state().role_holder("secretary"), new)
        self.assertEqual(self.state(), "verified")
        self.assertIn(T1, self.do())
        self.assertEqual(D.wake_to_disable(self.h.state()), {})
        self.assertNotIn(CREATE, self.sync(new))

    def test_the_current_verified_routine_is_never_listed(self):
        self.ready()
        self.heir()
        self.heir()
        self.assertEqual(D.wake_to_disable(self.h.state()), {})
        with self.assertRaisesRegex(H.HarnessError, "not a routine waiting to be disabled"):
            self.admin(self.env, "wake_disabled", trigger=T1)

    # item 3
    def test_reregister_the_same_trigger_and_session_holds_the_wake_before_any_verify(self):
        self.ready()
        new = self.heir()
        self.register(who=new)
        e = self.reg_entry()
        self.assertEqual((e["state"], e["holder"], e["trigger"]), ("verified", new, T1))
        self.assertIn(T1, self.do())
        self.assertEqual(D.wake_to_disable(self.h.state()), {})

    def test_a_new_trigger_lists_the_old_one_for_disabling(self):
        self.ready()
        new = self.heir()
        self.register(who=new, trig=T2, session=S2)
        self.assertEqual(self.state(), "pending")
        self.assertEqual(D.wake_to_disable(self.h.state()), {T1: "secretary"})
        self.verify(trig=T2, session=S2)
        self.assertEqual([(c["data"]["trigger"], c["data"]["what"]) for c in self.events("wake.claim")], [(T1, "disable")])   # the envoy's call carried it
        self.assertEqual(self.admin(self.env, "wake_disabled", trigger=T1), {"disabled": T1})
        self.assertEqual(D.wake_to_disable(self.h.state()), {})
        do = self.do()
        self.assertIn(T2, do)
        self.assertNotIn(T1, do)

    def test_the_same_trigger_with_a_new_session_is_a_plain_replacement(self):
        self.ready()
        new = self.heir()
        self.register(who=new, session=S2)
        e = self.reg_entry()
        self.assertEqual((e["state"], e["session"], e["trigger"]), ("pending", S2, T1))
        self.assertEqual(D.wake_to_disable(self.h.state()), {})
        self.assertNotIn(T1, self.h.state().wake_old)

    # added after the critic's read
    def test_a_fire_stale_routine_re_registered_unchanged_stays_stale_until_a_new_trigger(self):
        self.ready()
        for _ in range(D.FIRE_STALE_AFTER):
            self.fire("HTTP 503")                                            # failed fires after the verify: stale by fire_stale
        self.assertEqual(self.state(), "stale")
        self.assertEqual(self.reg_entry()["state"], "verified")
        self.register()
        self.assertEqual(self.state(), "stale")
        self.assertNotIn("RemoteTrigger", self.do())
        self.register(trig=T2, session=S2)
        self.assertEqual(self.state(), "pending")
        self.verify(trig=T2, session=S2)
        self.assertEqual(self.state(), "verified")

    def test_a_routine_made_stale_by_a_changed_prompt_goes_pending_when_re_registered(self):
        self.ready()
        self.fire(**self.good(enabled=False))
        self.assertEqual(self.state(), "stale")
        self.register()
        self.assertEqual(self.state(), "pending")

    def test_re_registering_a_rejected_or_pending_routine_goes_to_pending_as_before(self):
        self.register()
        self.register()
        self.assertEqual(self.state(), "pending")
        self.verify(session=S2)                                              # rejected: wrong session
        self.assertEqual(self.state(), "rejected")
        self.register()
        self.assertEqual(self.state(), "pending")

    def test_a_relay_holder_in_the_registrants_lineage_is_not_offered_the_verify(self):
        self.admin(self.env, "wake_register", trigger=T1, session=S1)        # the envoy holder registers its own routine
        kin = self.reg("envoy", "local_env2", predecessor=self.env)          # its successor is in the registrant's lineage
        self.warm(kin)
        self.assertNotIn("op=wake_verify", self.relay_line(kin))
        crit = self.reg("harness-critic", "local_crit")
        self.warm(crit)
        self.assertIn("op=wake_verify", self.relay_line(crit))

    def test_a_replayed_log_folds_to_the_same_states(self):
        self.ready()                                                         # registered, verified
        self.register(trig=T2, session=S2)                                   # replaced by a new trigger, T1 waits
        self.verify(trig=T2, session=S2)
        st = self.h.state()
        e = st.wake_reg["secretary"]
        self.assertEqual((e["trigger"], e["session"], e["state"], e["holder"]), (T2, S2, "verified", self.sec))
        self.assertEqual(dict(st.wake_old), {T1: "secretary"})
        self.admin(self.env, "wake_disabled", trigger=T1)
        st = self.h.state()
        self.assertEqual((dict(st.wake_old), st.wake_disabled), ({}, {T1}))

    # item 4: the verify needs a pending routine, a verifier other than the registrant, no current-holder test
    def test_verify_of_a_routine_registered_by_a_past_holder_is_accepted(self):
        self.register()
        self.heir()                                                          # the registrant is no longer the holder
        self.assertEqual(self.verify().get("verified"), "secretary")

    def test_verify_by_the_registrants_own_lineage_is_still_refused(self):
        self.register()
        heir = self.heir()
        with self.assertRaisesRegex(H.HarnessError, "registrant or its lineage"):
            self.verify(who=heir)

    # item 5: the holder line
    def test_unknown_session_successor_sees_the_line_until_it_re_registers(self):
        self.ready()
        new = self.heir()
        for _ in range(2):
            self.assertIn(LINE, self.sync(new))                              # recomputed each sync
        self.register(who=new)
        self.assertNotIn(LINE, self.sync(new))
        self.assertEqual(self.state(), "verified")

    def test_the_registrant_itself_never_sees_the_line(self):
        self.ready()
        self.assertNotIn(LINE, self.sync(self.sec))

    def test_a_code_holder_sees_no_holder_line_and_no_create_line(self):
        self.ready()
        new = self.reg("secretary", "local_newsec", predecessor=self.sec)      # a Code holder (local_ id) of a role with a verified routine
        for _ in range(2):
            out = self.sync(new)
            self.assertNotIn(LINE, out)
            self.assertNotIn(CREATE, out)

    def test_a_known_non_code_session_that_differs_shows_the_line_each_sync(self):
        self.ready()
        new = self.reg("secretary", "cowork_newsec", predecessor=self.sec)      # a known id that is not a local_ app session
        for _ in range(2):
            self.assertIn(LINE, self.sync(new))

    def test_a_known_matching_session_shows_no_line(self):
        self.ready(session="cowork_newsec")
        self.assertNotIn(LINE, self.sync(self.reg("secretary", "cowork_newsec", predecessor=self.sec)))

    # item 6
    def test_no_create_line_while_the_role_has_a_verified_routine(self):
        self.assertIn(CREATE, self.sync(self.sec))
        self.ready()
        self.assertNotIn(CREATE, self.sync(self.sec))
        self.assertNotIn(CREATE, self.sync(self.heir()))

    # guards: the legacy pin and fire-failure staleness behave as before
    def test_guard_a_legacy_pin_still_goes_stale_when_its_holder_changes(self):
        I.C.legacy_pin(self.h, {"secretary": I.C.WP("secretary")})
        self.assertIn(I.C.TRIG, self.do())
        self.heir()
        self.assertNotIn(I.C.TRIG, self.do())

    def test_guard_fire_failures_still_stale_a_routine(self):
        self.ready()
        self.heir()
        self.fire(**self.good(prompt="Run harness_inbox. now"))
        self.assertEqual(self.state(), "stale")


if __name__ == "__main__":
    unittest.main()
