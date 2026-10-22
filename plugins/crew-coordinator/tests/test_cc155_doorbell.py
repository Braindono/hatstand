"""cc 0.15.5 WP4: doorbell nudge on send and /listen self-wake (6 safety conditions). Run: python3 -B tests/test_cc155_doorbell.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _env  # noqa: F401  isolate HOME and HARNESS_* first
import json, os, sys, time, unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
import ctx_hook as C
import doorbell as D
import harness as H
import mcp_server as M
from test_cc151_w1 import Base, MODEL


class DB(Base):
    def setUp(self):
        super().setUp()
        self.op = {}
        self._p = mock.patch.object(H, "_operator_file", lambda: (self.op, []))
        self._p.start()
        self.addCleanup(self._p.stop)
        for r in ("alpha", "beta", "gamma"):
            self.h.role_define("operator", r, "proj")
        self.a, self.b, self.c = (self.agent(r, "proj") for r in ("alpha", "beta", "gamma"))

    def send(self, frm, to, body="please do the thing", kind="task", **kw):
        return M.call(self.h, "harness_send", dict({"agent": frm, "to": to, "body": body, "kind": kind}, **kw))

    def ev(self, t):
        return self.types(t)


class Nudge(DB):
    def test_ids_only_line_and_do(self):
        r = self.send(self.a, f"role:beta", body="SECRET-BODY-TEXT")
        n = r["nudge"]
        self.assertIn(r["id"], n["line"])
        self.assertNotIn("SECRET-BODY-TEXT", json.dumps(n))
        self.assertTrue(n["do"].startswith("Do: SendMessage to "))
        self.assertEqual(self.ev("nudge.sent")[0]["data"]["msg"], r["id"])

    def test_notice_and_operator_get_none(self):
        self.assertNotIn("nudge", self.send(self.a, "role:beta", kind="notice"))
        self.assertNotIn("nudge", self.send(self.a, "operator"))
        self.assertEqual(self.ev("nudge.sent"), [])

    def test_off_and_mute_are_operator_owned(self):
        self.op["doorbell"] = {"mute_roles": ["beta"]}
        r = self.send(self.a, "role:beta")
        self.assertNotIn("nudge", r)
        self.assertIn("muted", r["nudge_skipped"][0]["reason"])
        self.assertIn("muted", self.ev("nudge.skipped")[0]["data"]["reason"])
        self.op["doorbell"] = {"off": True}
        self.assertIn("off", self.send(self.a, "role:gamma")["nudge_skipped"][0]["reason"])
        # config.json (agent-writable) cannot switch it back on or change caps
        os.makedirs(os.path.join(self.home, "_harness"), exist_ok=True)
        json.dump({"doorbell": {"off": False}}, open(os.path.join(self.home, "_harness", "config.json"), "w"))
        self.assertIn("nudge_skipped", self.send(self.a, "role:gamma"))

    def test_sender_cap_per_hour(self):
        self.op["doorbell"] = {"nudge_per_pair_hour": 30, "global_per_hour": 120}
        n = 0
        for i in range(8):
            r = self.send(self.a, [self.b, self.c][i % 2], body=f"x{i}")
            n += "nudge" in r
        self.assertEqual(n, 6)
        self.assertTrue(any("sender cap" in e["data"]["reason"] for e in self.ev("nudge.skipped")))

    def test_ping_pong_stops_at_pair_cap(self):
        sent = 0
        for i in range(8):
            frm, to = (self.a, self.b) if i % 2 == 0 else (self.b, self.a)
            sent += "nudge" in self.send(frm, to, kind="question", body=f"ack {i}")
        self.assertEqual(sent, 3)     # default pair cap, counted both directions
        self.assertTrue(any("pair cap" in e["data"]["reason"] for e in self.ev("nudge.skipped")))

    def test_global_cap(self):
        self.op["doorbell"] = {"global_per_hour": 2, "nudge_per_pair_hour": 30}
        flags = ["nudge" in self.send(self.a, self.b, body=f"m{i}") for i in range(4)]
        self.assertEqual(flags, [True, True, False, False])

    def test_once_per_message_id(self):
        r = self.send(self.a, self.b)
        again = D.attach_nudge(self.h, self.a, {"id": r["id"]})
        self.assertNotIn("nudge", again)
        self.assertIn("already nudged", self.ev("nudge.skipped")[-1]["data"]["reason"])

    def test_cli_send_returns_nudge_and_inbox_lists_owed(self):
        r = self.send(self.a, self.b, body="do it")
        box = self.h.inbox(self.b, unread_only=True, mark_read=False)
        self.assertEqual(box["owed"], [r["id"]])
        self.assertIn("owed reply: " + r["id"], box["text"])


class Listen(DB):
    def enable(self, *roles):
        self.op["listen"] = {"roles": list(roles)}

    def L(self, agent, action):
        return self.adm("listen", agent, action=action)

    def test_self_enable_refused(self):
        self.send(self.a, self.b)
        with self.assertRaisesRegex(H.HarnessError, "only the operator enables"):
            self.L(self.b, "arm")
        os.makedirs(os.path.join(self.home, "_harness"), exist_ok=True)       # config.json is agent-writable and ignored
        json.dump({"listen": {"roles": ["beta"]}, "listen_roles": ["beta"]}, open(os.path.join(self.home, "_harness", "config.json"), "w"))
        with self.assertRaises(H.HarnessError):
            self.L(self.b, "arm")
        with self.assertRaisesRegex(H.HarnessError, "unknown args"):
            self.adm("listen", self.b, action="arm", roles=["beta"])
        self.assertEqual(self.ev("listen.armed"), [])
        self.assertTrue(self.ev("nudge.skipped"))

    def test_open_task_is_computed_not_claimed(self):
        self.enable("beta")
        r = self.L(self.b, "arm")
        self.assertFalse(r["arm"])
        self.assertIn("no open task", r["reason"])
        with self.assertRaisesRegex(H.HarnessError, "unknown args"):
            self.adm("listen", self.b, action="arm", open_task=True)
        self.assertEqual(self.ev("listen.armed"), [])
        t = self.send(self.a, self.b, body="real task")["id"]
        r = self.L(self.b, "arm")
        self.assertTrue(r["arm"])
        self.assertEqual((r["delay_min"], r["message"]), (10, D.WAKE_TEXT))
        self.h.task_update(self.b, t, "completed")
        self.assertIn("no open task", self.L(self.b, "rearm")["reason"])
        self.assertFalse(D.listen_state(self.h)[0])          # the refusal ended the arm

    def test_wake_rearm_cycle_and_status(self):
        self.enable("beta")
        self.send(self.a, self.b)
        self.L(self.b, "arm")
        self.assertTrue(self.L(self.b, "wake")["ok"])
        r = self.L(self.b, "rearm")
        self.assertTrue(r["rearm"])
        st = self.h.status()
        self.assertEqual(st["listen"]["armed"][0]["role"], "beta")
        self.assertEqual(st["listen"]["wakes_this_hour"], 1)
        self.assertIn("next_in_min", st["listen"]["armed"][0])

    def test_hourly_wake_cap(self):
        self.enable("beta")
        self.op["listen"]["max_per_hour"] = 2
        self.send(self.a, self.b)
        self.L(self.b, "arm")
        oks = []
        for _ in range(4):
            oks.append(self.L(self.b, "wake").get("ok"))
            self.L(self.b, "rearm")
        self.assertEqual(oks[:2], [True, True])
        self.assertFalse(oks[-1])

    def test_expiry_and_session_end(self):
        self.enable("beta")
        self.send(self.a, self.b)
        self.L(self.b, "arm")
        live, _ = D.listen_state(self.h, now=time.time() + 13 * 3600)
        self.assertEqual(live, {})                           # 12 h default
        live, _ = D.listen_state(self.h, now=time.time() + 11 * 3600)
        self.assertEqual(len(live), 1)
        self.h.handoff(self.b, None, None, False, None)       # session end
        self.assertEqual(D.listen_state(self.h)[0], {})

    def test_two_armed_roles_cannot_ping_pong_forever(self):
        self.enable("alpha", "beta")
        self.op["listen"]["max_per_hour"] = 12
        self.op["doorbell"] = {"global_per_hour": 4}
        self.send(self.a, self.b, kind="question")
        self.send(self.b, self.a, kind="question")
        self.L(self.a, "arm")
        self.L(self.b, "arm")
        results = []
        for i in range(6):
            who = self.a if i % 2 == 0 else self.b
            results.append(bool(self.L(who, "wake").get("ok")))
            self.L(who, "rearm")
        self.assertLess(sum(results), 6)                     # the shared cap stops it
        self.assertTrue(any("cap" in e["data"]["reason"] for e in self.ev("nudge.skipped")))

    def test_gated_ops_refused_inside_a_wake_only(self):
        self.enable("beta")
        self.send(self.a, self.b)
        self.L(self.b, "arm")
        n = self.note(self.b)
        # outside a wake: not blocked by the guard (this op only needs a curation role, so it files an approval)
        self.assertIn("pending", self.adm("archive", self.b, ids=[n], reason='"rule line text"'))
        self.L(self.b, "wake")
        for name, args in (("harness_admin", {"op": "archive", "args": {"ids": [n], "reason": '"x"'}}),
                           ("harness_admin", {"op": "publish_release", "args": {"path": self.tmp}}),
                           ("harness_admin", {"op": "pin_corpus_index", "args": {}}),
                           ("harness_admin", {"op": "retag", "args": {"entry": n, "project": "proj"}}),
                           ("harness_restore", {"role": "alpha", "model": MODEL}),
                           ("harness_claim", {"path": "notes/x.md"}),
                           ("harness_handoff", {}),
                           ("harness_record", {"kind": "note", "title": "t", "tier": "foundation"})):
            with self.assertRaisesRegex(H.HarnessError, "refused during a /listen wake"):
                M.call(self.h, name, dict(args, agent=self.b))
        # routine coordination still works
        self.assertIn("id", self.send(self.b, self.a, kind="result", body="done"))
        self.assertIn("count", M.call(self.h, "harness_inbox", {"agent": self.b}))
        self.assertTrue(self.L(self.b, "rearm")["rearm"])
        # the rearm ended the wake window: gated ops are no longer blocked by the guard
        self.assertIn("pending", self.adm("archive", self.b, ids=[n], reason='"rule line text"'))

    def test_wake_text_and_skill_state_the_restriction(self):
        for must in ("approvals", "publishes", "pins", "gated"):
            self.assertIn(must, D.WAKE_TEXT)
        sk = open(os.path.join(HERE, "..", "skills", "listen", "SKILL.md"), encoding="utf-8").read()
        for must in ("Never approve, publish, pin or archive", "operator.json", "ids-only", "Never put message text"):
            self.assertIn(must, sk)
        self.assertLess(len(sk.split("---", 2)[2]) / 4, 600)

    def test_listen_prompt_is_not_operator_activity(self):
        import tempfile
        with mock.patch.dict(os.environ, {"HARNESS_STATE_DIR": tempfile.mkdtemp()}):
            inp = {"session_id": "s-l", "cwd": "/x/p"}
            C.save_note(C.idle_path(inp), {"on": True, "trig_id": "T", "nonce": "n1", "arm_ts": 1000, "last_prompt_ts": 500})
            self.assertIsNone(C.idle_prompt(dict(inp, prompt="/listen: run harness_inbox"), 9000, False))
            self.assertEqual(C.load_note(C.idle_path(inp))["last_prompt_ts"], 500)


if __name__ == "__main__":
    unittest.main()
