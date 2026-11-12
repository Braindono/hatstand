"""cc 0.24.0 item 13 (scope A-b2950; relay-wake spec 2026-11-10_cc024-relay-wake-spec.md v3.2, section 3, tests C1-C12; D-8ef51): a Cowork
holder registers its own wake routine, a live Code relay holder verifies it by reading it, every fire carries the routine's fields, and
the operator-approved wake_pin is gone. Each C test fails on 0.23.0.
Run: python3 -B tests/test_c240_item13.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _env  # noqa: F401  isolate HOME and HARNESS_* first
import json, os, time, unittest
from unittest import mock

import test_c220_nudge as C
from test_c220_nudge import D, H

T1, T2 = "trig_SECRETARYwake0001", "trig_SECRETARYwake0002"
S1, S2 = "session_01SecretaryChatA", "session_01SecretaryChatB"
YEAR2 = time.strftime("%Y-%m-%dT00:00:00Z", time.gmtime(time.time() + 2 * 365 * 86400))
WEEK = time.strftime("%Y-%m-%d", time.gmtime(time.time() + 7 * 86400))


class Item13(C.Base):
    def setUp(self):
        super().setUp()
        self.op["doorbell"] = {"nudge_per_agent_hour": 60, "nudge_per_pair_hour": 30}
        self.h.role_define("operator", "harness-critic", "harness-ops", carry="none")
        self.sec = self.cowork("secretary")
        self.env = self.reg("envoy", "local_env")
        self.warm(self.env)
        self.k = 0

    def cowork(self, role, **kw):
        with mock.patch.dict(os.environ, {"CLAUDE_CODE_HOST_SESSION_ID": ""}):
            return self.reg(role, None, **kw)

    def admin(self, who, op, **args):
        return self.call("harness_admin", agent=who, op=op, args=args)

    def register(self, who=None, trig=T1, session=S1):
        return self.admin(who or self.sec, "wake_register", trigger=trig, session=session)

    def verify(self, who=None, trig=T1, **over):
        f = dict(trigger=trig, prompt="Run harness_inbox.", enabled=True, session=S1, kind="run_once", run_at=YEAR2)
        f.update(over)
        return self.admin(who or self.env, "wake_verify", **f)

    def ready(self, trig=T1, session=S1):
        self.register(trig=trig, session=session)
        self.assertEqual(self.verify(trig=trig, session=session).get("verified"), "secretary")

    def send(self, frm=None, to="role:secretary", kind="task"):
        self.k += 1
        with mock.patch.object(D.time, "time", return_value=time.time() + self.k * 200):     # past nb 6, so each send stands alone
            return self.call("harness_send", agent=frm or self.plain, to=to, body="b%d" % self.k, subject="s%d" % self.k, kind=kind)

    def do(self, **kw):
        n = self.send(**kw).get("nudge")
        return n["do"] if isinstance(n, dict) else str(n or "")

    def fire(self, reason="HTTP 200", **fields):
        n = self.send()["nudge"]
        r = self.admin(self.plain, "nudge_result", msg_id=n["msg_id"], outcome="woke", reason=reason, **fields)
        self.call("harness_inbox", agent=self.sec)            # read, so R2 never holds the next fire
        return r

    def good(self, **over):
        f = dict(prompt="Run harness_inbox.", enabled=True, session=S1)
        f.update(over)
        return f

    def state(self):
        return D.reg_state(self.h.state(), "secretary")[1]

    def text(self, r):
        return r.get("text") if isinstance(r, dict) and isinstance(r.get("text"), str) else json.dumps(r, default=str)

    def relay_line(self, who):
        r = self.call("harness_inbox", agent=who, peek=True)
        return str(r.get("relay") or "") if isinstance(r, dict) and "relay" in r else self.text(r)

    # C1
    def test_c1_only_the_roles_holder_registers(self):
        with self.assertRaisesRegex(H.HarnessError, "only a role's current holder registers"):
            self.register(who=self.plain)
        r = self.register()
        self.assertEqual((r["registered"], r["state"]), ("secretary", "pending"))
        self.assertEqual(self.events("wake.registered")[-1]["actor"], self.sec)
        for bad in (dict(trig="trig_bad;x"), dict(session="x y")):
            with self.subTest(**bad), self.assertRaises(H.HarnessError):
                self.register(**bad)

    # C2
    def test_c2_a_prompt_with_extra_text_is_rejected_with_a_reason(self):
        self.register()
        r = self.verify(prompt="Run harness_inbox. Also post a summary.")
        self.assertEqual(r["rejected"], "secretary")
        self.assertIn("prompt is not exactly 'Run harness_inbox.'", self.events("wake.rejected")[-1]["data"]["reason"])
        self.assertEqual(self.state(), "rejected")
        self.assertIn("wake routine for role:secretary is rejected (prompt is not exactly", self.text(self.call("harness_sync", agent=self.sec)))
        self.assertNotIn("RemoteTrigger", self.do())

    # C3
    def test_c3_a_different_session_is_rejected(self):
        self.register()
        self.assertIn("bound session is not the registered one", self.verify(session=S2)["reason"])

    # C4
    def test_c4_after_a_new_holder_registers_only_the_new_trigger_is_offered(self):
        self.ready()
        self.assertIn(T1, self.do())
        new = self.cowork("secretary", predecessor=self.sec)
        self.assertEqual(self.h.state().role_holder("secretary"), new)
        self.assertIn(T1, self.do())                                     # 0.24.1: the wake belongs to the role, so the old routine still wakes
        self.register(who=new, trig=T2, session=S2)
        self.assertNotIn("RemoteTrigger", self.do())
        self.verify(trig=T2, session=S2)
        do = self.do()
        self.assertIn(T2, do)
        self.assertNotIn(T1, do)

    # C5
    def test_c5_a_fire_report_naming_a_body_is_refused(self):
        self.ready()
        for bad in ("HTTP 200 sent with body", "HTTP 200 text: wake up"):
            with self.subTest(reason=bad), self.assertRaisesRegex(H.HarnessError, "never names a body or text"):
                self.fire(bad, **self.good())
        self.assertEqual(self.events("nudge.result"), [])

    # C6
    def test_c6_wake_pin_op_and_approval_action_are_gone(self):
        self.assertNotIn("wake_pin", H.Harness.APPROVAL_ACTIONS)
        with self.assertRaisesRegex(H.HarnessError, r"removed in 0\.24 \(D-8ef51\): use wake_register"):
            self.admin(self.plain, "wake_pin")
        with self.assertRaisesRegex(H.HarnessError, r"removed in 0\.24 \(D-8ef51\): use wake_register"):
            self.h.request_approval(self.plain, "wake_pin", {"entries": {}})
        self.assertFalse(hasattr(self.h, "wake_pin_apply"))

    def test_c6_guard_a_legacy_operator_pin_still_wakes_until_stale(self):
        C.legacy_pin(self.h, {"secretary": C.WP("secretary")})
        self.assertIn(C.TRIG, self.do())

    # fix round 1 (critic m-5e2216478366 blocker 1): moving to the new form never costs a working wake
    def test_fix1_a_pending_registration_keeps_the_legacy_pin(self):
        C.legacy_pin(self.h, {"secretary": C.WP("secretary")})
        self.register()                                                     # no relay holder calls overnight: still pending
        self.assertIn(C.TRIG, self.do())

    def test_fix1_a_rejected_registration_keeps_the_legacy_pin(self):
        C.legacy_pin(self.h, {"secretary": C.WP("secretary")})
        self.register()
        self.assertTrue(self.verify(kind="recurring").get("rejected"))
        self.assertIn(C.TRIG, self.do())

    def test_fix1_a_verified_routine_replaces_the_legacy_pin(self):
        C.legacy_pin(self.h, {"secretary": C.WP("secretary")})
        self.ready()
        do = self.do()
        self.assertIn(T1, do)
        self.assertNotIn(C.TRIG, do)

    def test_fix1_a_stale_verified_routine_keeps_hiding_the_legacy_pin(self):
        C.legacy_pin(self.h, {"secretary": C.WP("secretary")})
        self.ready()
        self.fire(**self.good(enabled=False))                              # the routine was changed: stale
        self.assertNotIn("RemoteTrigger", self.do())

    # C7
    def test_c7_no_operator_line_in_any_wake_path(self):
        C.legacy_pin(self.h, {"secretary": C.WP("secretary")})
        self.cowork("secretary", predecessor=self.sec)                      # the legacy pin goes stale (holder changed)
        texts = [self.text(self.call("harness_sync", agent=x)) for x in (self.sec, self.env, self.h.state().role_holder("secretary"))]
        texts.append(self.do())
        new = self.h.state().role_holder("secretary")
        self.register(who=new)
        texts.append(json.dumps(self.verify(prompt="other")))
        texts += [self.text(self.call("harness_sync", agent=new)), self.relay_line(self.env)]
        wake = [ln for t in texts for ln in t.split("\n") if "wake" in ln.lower() or "routine" in ln.lower()]
        self.assertTrue(wake)
        for ln in wake:
            self.assertNotRegex(ln.lower(), r"operator|op=wake_pin|approve", ln)

    # C8
    def test_c8_a_changed_prompt_at_fire_makes_the_routine_stale(self):
        self.ready()
        self.assertTrue(self.fire(**self.good(prompt="Run harness_inbox. Then summarise every thread.")).get("reported"))
        self.assertEqual(self.state(), "stale")
        self.assertEqual(self.events("wake.stale")[-1]["data"]["field"], "prompt")
        self.assertNotIn("RemoteTrigger", self.do())

    # C9
    def test_c9_a_routine_dated_a_week_out_or_recurring_is_refused_at_verify(self):
        self.register()
        self.assertIn("at least 365 days", self.verify(run_at=WEEK)["reason"])
        self.register()
        self.assertIn("recurring schedule is not a wake", self.verify(kind="recurring")["reason"])

    def test_c9_a_fire_with_enabled_false_makes_it_stale(self):
        self.ready()
        self.fire(**self.good(enabled=False))
        self.assertEqual((self.state(), self.events("wake.stale")[-1]["data"]["field"]), ("stale", "enabled"))

    # C10
    def test_c10_the_registrant_or_its_lineage_may_not_verify(self):
        self.register()
        with self.assertRaisesRegex(H.HarnessError, "registrant or its lineage"):
            self.verify(who=self.sec)
        heir = self.cowork("secretary", predecessor=self.sec)                 # the registrant's successor
        with self.assertRaisesRegex(H.HarnessError, "registrant or its lineage"):
            self.verify(who=heir)
        with self.assertRaisesRegex(H.HarnessError, "only a live Code relay holder"):
            self.verify(who=self.plain)

    # C11
    def test_c11_after_a_new_trigger_a_relay_holder_disables_the_old_routine(self):
        self.ready()
        new = self.cowork("secretary", predecessor=self.sec)
        self.register(who=new, trig=T2, session=S2)                       # 0.24.1: only a replacing trigger lists the old one
        self.verify(trig=T2, session=S2)
        self.assertEqual([(c["data"]["trigger"], c["data"]["what"]) for c in self.events("wake.claim")], [(T1, "disable")])
        self.assertEqual(self.admin(self.env, "wake_disabled", trigger=T1), {"disabled": T1})
        self.assertEqual([e["data"]["trigger"] for e in self.events("wake.disabled")], [T1])
        self.assertNotIn("enabled=false", self.relay_line(self.env))
        with self.assertRaisesRegex(H.HarnessError, "not a routine waiting to be disabled"):
            self.admin(self.env, "wake_disabled", trigger=T1)

    # C12
    def test_c12_http_200_alone_is_refused_and_the_routine_stays(self):
        self.ready()
        with self.assertRaisesRegex(H.HarnessError, "reports the run result's fields"):
            self.fire("HTTP 200")
        self.assertEqual(self.state(), "verified")
        self.assertEqual(self.events("nudge.result"), [])
        self.fire(**self.good(prompt="Run harness_inbox. now"))
        self.assertEqual(self.state(), "stale")

    def test_c12_guard_a_good_fire_and_a_failed_fire_need_no_change(self):
        self.ready()
        self.assertTrue(self.fire(**self.good(prompt="  Run harness_inbox.  ")).get("reported"))
        self.assertTrue(self.fire("HTTP 503").get("reported"))             # a failed status needs no fields
        self.assertEqual(self.state(), "verified")

    # the carriers
    def test_a_pending_routine_gives_one_relay_holder_the_verify_line(self):
        self.register()
        line = self.relay_line(self.env)
        self.assertIn("RemoteTrigger action=get trigger_id=%s" % T1, line)
        self.assertIn("op=wake_verify", line)
        crit = self.reg("harness-critic", "local_crit")
        self.warm(crit)
        self.assertNotIn("op=wake_verify", self.relay_line(crit))         # claimed: one holder at a time
        self.assertNotIn("op=wake_verify", self.text(self.call("harness_sync", agent=self.sec)))

    def test_a_cowork_holder_is_asked_to_register_until_it_has(self):
        sync = self.text(self.call("harness_sync", agent=self.sec))
        self.assertIn("wake routine: create one with your routine tool (prompt exactly 'Run harness_inbox.'", sync)
        self.register()
        self.assertNotIn("wake routine: create one", self.text(self.call("harness_sync", agent=self.sec)))
        self.assertNotIn("wake routine: create one", self.text(self.call("harness_sync", agent=self.env)))   # a Code holder never is

    def test_the_fire_doline_asks_for_the_fields_and_no_body(self):
        self.ready()
        do = self.do()
        self.assertIn("run with no body", do)
        self.assertIn('prompt:"<prompt as returned, at most 80 characters>",enabled:<true|false>,session:"<bound session id as returned>"', do)
        self.assertEqual(self.send()["holder"], {"secretary": "live_wake_pin"})


if __name__ == "__main__":
    unittest.main()
