"""cc 0.21.2 (scope A-4f925): item 1 wake-trigger Do-line for roles with an operator-pinned trigger (wake_pin; 1 per role and per trigger
id per 10 min; subscription only; critic N-fbba5 B1-B3); item 2 stale-id clear from the ledger only; item 3 bounded stale-id read; item 4
mirror from a read-only tree; item 5 settle on CLI.
Run: python3 -B tests/test_c212_nudge.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _env  # noqa: F401  isolate HOME and HARNESS_* first
import contextlib, io, json, os, shutil, stat, sys, tempfile, time, unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
import harness as H
import mcp_server as M
import doorbell as D

MODEL = "claude-sonnet-5-5"
TRIG = "trig_FAKEsecretary0001x"


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.home = os.path.join(self.tmp, "Exchange")
        os.makedirs(os.path.join(self.home, "_harness"))
        e = mock.patch.dict(os.environ, {"HARNESS_STATE_CACHE": "0"})
        e.start()
        self.addCleanup(e.stop)
        self.h = H.Harness(self.home)
        for r in ("curator", "secretary", "design-system", "design-coder", "ops-coder"):
            self.h.role_define("operator", r, "harness-ops", carry="none")
        self.plain = self.reg(host="local_plain")

    def wake_file(self, d):
        with open(os.path.join(self.home, "_harness", "wake.json"), "w") as f:
            json.dump(d, f)

    def wake(self, d):
        """0.24.0 (item 13): the operator-approved pin is gone; a legacy pin is written as the 0.23.0 grant wrote it, from the file's
        entries that pass the 0.23.0 check (legacy pins stay readable until stale)."""
        self.wake_file(d)
        entries, _ = self.h.wake_entries_from_file()
        st = self.h.state()
        self.h.store.append("wake.pinned", "human", {"entries": {k: self.h._wake_entry_ok(k, v, st.role_holder(k)) for k, v in entries.items()}})
        return {"entries": entries}

    def reg(self, role=None, host=None, **kw):
        return self.h.register(project="harness-ops", model=MODEL, task="t", role=role, host_session_id=host, **kw)["id"]

    def call(self, name, **a):
        M.BOUND.update(home=None, id=None)
        return M.call(self.h, name, a)

    def events(self, t):
        return [e for e in self.h.store.read_all() if e["type"] == t]

    def nudge(self, frm, to, kind="task"):
        self.n = getattr(self, "n", 0) + 1
        n = self.call("harness_send", agent=frm, to=to, body="b%d" % self.n, subject="s%d" % self.n, kind=kind).get("nudge")
        return n if isinstance(n, dict) else {"do": n or ""}                              # 0.22.0: a mail-only send returns a plain string


def E(role, trig=TRIG, kind="recurring"):
    """0.23.0 (A-08480 item 3 gap 6): a pin entry in the only accepted form; plain trig_ strings are refused."""
    return {"trigger": trig, "kind": kind, "prompt": D.wake_prompt(role)}


class Item1WakeTrigger(Base):
    def test_a_role_with_a_trigger_gets_the_remotetrigger_line(self):
        s = self.reg("secretary")
        self.wake({"secretary": E("secretary")})
        n = self.nudge(self.plain, "role:secretary", "task")
        self.assertIn("Do: RemoteTrigger action=run trigger_id=%s" % TRIG, n["do"])
        self.assertTrue(n["do"].startswith("Do: RemoteTrigger"))                          # 0.22.0: no id, so the trigger line stands alone
        self.assertNotIn("SendMessage", n["do"])
        self.assertIn("never with an API key", n["do"])
        self.assertIn("report outcome woke", n["do"])
        self.assertIn("op=nudge_result", n["do"])
        tw = self.events("nudge.trigwake")
        self.assertEqual([(e["data"]["role"], e["data"]["to"], e["data"]["trigger"]) for e in tw], [("secretary", [s], TRIG)])
        self.assertEqual(self.events("nudge.offered")[-1]["data"]["by_trigger"], [True])

    def test_one_wake_per_role_per_10_minutes_over_all_senders(self):
        self.reg("secretary")
        self.wake({"secretary": E("secretary")})
        senders = [self.reg(host="local_s%d" % i) for i in range(3)]
        outs = [self.nudge(x, "role:secretary", "task")["do"] for x in senders]
        self.assertEqual(["RemoteTrigger" in o for o in outs], [True, False, False])
        self.assertEqual(len(self.events("nudge.trigwake")), 1)
        later = time.time() + D.TRIG_WAKE_MIN * 60 + 5
        with mock.patch.object(D.time, "time", return_value=later):
            self.assertIn("RemoteTrigger", self.nudge(self.reg(host="local_s9"), "role:secretary", "task")["do"])
        self.assertEqual(len(self.events("nudge.trigwake")), 2)

    def test_the_cap_is_per_role(self):
        self.reg("secretary")
        self.reg("design-system")
        self.wake({"secretary": E("secretary"), "design-system": E("design-system", "trig_FAKEdesignsys0002x")})
        self.assertIn(TRIG, self.nudge(self.plain, "role:secretary")["do"])
        self.assertIn("trig_FAKEdesignsys0002x", self.nudge(self.reg(host="local_o"), "role:design-system")["do"])

    def test_entries_that_are_not_triggers_are_ignored(self):
        self.wake({"ops-coder": "sendmessage:OPS-CODER - Gritty Myrtle", "design-coder": "m-8b0234136d6d",
                   "curator": "trig_bad;rm -rf", "secretary": ["trig_FAKEsecretary0001x"]})
        for role in ("ops-coder", "design-coder", "curator", "secretary"):
            self.reg(role)
            self.assertNotIn("RemoteTrigger", self.nudge(self.reg(host="local_" + role), "role:" + role)["do"])
        self.assertEqual(self.events("nudge.trigwake"), [])

    def test_no_pin_gives_no_trigger(self):
        self.reg("secretary")
        self.assertNotIn("RemoteTrigger", self.nudge(self.plain, "role:secretary")["do"])

    def test_critic_b1_a_file_write_changes_nothing(self):
        """N-fbba5 B1 failing input: a role-less agent writes wake.json; the next task must carry 0 trigger lines."""
        self.reg("curator")
        self.wake_file({"curator": "trig_ATTACKERchosen01"})
        self.assertNotIn("RemoteTrigger", self.nudge(self.plain, "role:curator")["do"])
        self.assertEqual(self.events("nudge.trigwake"), [])

    def test_pin_then_an_edited_file_is_ignored_until_pinned_again(self):
        self.reg("secretary")
        self.wake({"secretary": E("secretary")})
        self.wake_file({"secretary": "trig_ATTACKERchosen01"})
        do = self.nudge(self.plain, "role:secretary")["do"]
        self.assertIn(TRIG, do)
        self.assertNotIn("ATTACKER", do)
        self.wake({"secretary": E("secretary", "trig_NEWoperatorPinned1")})                               # the operator re-pins: now it counts
        with mock.patch.object(D.time, "time", return_value=time.time() + D.TRIG_WAKE_MIN * 60 + 5):
            self.assertIn("trig_NEWoperatorPinned1", self.nudge(self.reg(host="local_r"), "role:secretary")["do"])

    def test_only_human_wake_pinned_events_count(self):     # 0.24.0 (item 13): legacy pins; the operator-only apply is removed
        self.h.store.append("wake.pinned", self.plain, {"entries": {"secretary": TRIG}})   # forged actor
        self.reg("secretary")
        self.assertIsNone(self.h.state().wake_pin)
        self.assertNotIn("RemoteTrigger", self.nudge(self.plain, "role:secretary")["do"])

    def test_an_empty_pin_unpins(self):
        self.reg("secretary")
        self.wake({"secretary": E("secretary")})
        self.wake({})
        self.assertNotIn("RemoteTrigger", self.nudge(self.plain, "role:secretary")["do"])

    def test_critic_b2_two_roles_one_trigger_share_the_slot(self):
        self.reg("secretary")
        self.reg("design-system")
        self.wake({"secretary": E("secretary"), "design-system": E("design-system")})
        self.assertIn(TRIG, self.nudge(self.plain, "role:secretary", "handoff")["do"])   # 0.24.0 (item 5): R2 replaces this slot for task/question/review; it stays for handoff
        self.assertNotIn("RemoteTrigger", self.nudge(self.reg(host="local_o"), "role:design-system", "handoff")["do"])
        self.assertEqual(len(self.events("nudge.trigwake")), 1)

    def test_delivered_frees_the_slot_skipped_and_woke_do_not(self):
        self.reg("secretary")
        self.wake({"secretary": E("secretary")})
        n = self.nudge(self.plain, "role:secretary", "handoff")   # 0.24.0 (item 5): R2 replaces this slot for task/question/review; it stays for handoff
        self.call("harness_admin", op="nudge_result", agent=self.plain, args={"msg_id": n["msg_id"], "outcome": "delivered", "reason": "row"})
        b = self.reg(host="local_fb")
        n2 = self.nudge(b, "role:secretary", "handoff")
        self.assertIn("RemoteTrigger", n2["do"])                                          # slot freed by the delivered report
        self.call("harness_admin", op="nudge_result", agent=b, args={"msg_id": n2["msg_id"], "outcome": "woke", "reason": "HTTP 200"})
        self.assertNotIn("RemoteTrigger", self.nudge(self.reg(host="local_fc"), "role:secretary", "handoff")["do"])
        self.assertEqual(len(self.events("nudge.trigwake_released")), 1)

    def test_notice_kind_and_a_capped_offer_never_wake(self):
        s = self.reg("secretary")
        self.wake({"secretary": E("secretary")})
        r = self.call("harness_send", agent=self.plain, to="role:secretary", body="b", kind="notice")
        self.assertEqual(r.get("nudge"), "none (kind notice starts no wake)")     # 0.23.0 (A-08480 item 4): the notice says it rings nobody
        with mock.patch.object(D, "_opcfg", return_value=dict(D._opcfg(self.h), global_per_hour=1)):
            self.h.store.append("nudge.offered", "system", {"msg": "m-x", "from": "z", "to": ["q"]})     # fills the global cap of 1
            r = self.call("harness_send", agent=self.reg(host="local_c2"), to="role:secretary", body="b2", kind="task")
        # 0.24.0 (item 5 R1c + item 18 fix round 2): a capped task asks for a relay, which may target the role's ok legacy pin;
        # the send itself still fires nothing (no trigger line, no trigwake)
        self.assertEqual(r.get("nudge"), "relay requested (capped:global; Code to Cowork)")
        self.assertEqual(self.events("nudge.trigwake"), [])
        self.assertTrue(s)

    def test_both_sides_get_a_working_line(self):
        self.reg("secretary")
        cowork_sender = self.reg("design-system")
        self.wake({"secretary": E("secretary")})
        c = self.reg("curator", "local_cur")
        to_code = self.nudge(cowork_sender, c[:8], "task")["do"]                       # Cowork sender to a Code chat
        self.assertIn("No SendMessage tool here (a Cowork or cloud chat): report skipped with reason no_sendmessage", to_code)
        self.assertNotIn("ListAgents", to_code)                                           # 0.22.0: no row check at all
        self.assertNotIn("RemoteTrigger", to_code)                                    # curator has no trigger
        to_cowork = self.nudge(c, "role:secretary", "task")["do"]                    # Code sender to a Cowork role
        self.assertIn("RemoteTrigger action=run", to_cowork)
        self.assertIn("No RemoteTrigger tool here: skip that step with reason no_remotetrigger", to_cowork)
        self.assertNotIn("fire_trigger", to_cowork)                                       # critic B3: billing unverified (D-f6eaa)

    def test_woke_is_a_valid_outcome(self):
        self.reg("secretary")
        self.wake({"secretary": E("secretary")})
        n = self.nudge(self.plain, "role:secretary", "task")
        res = self.call("harness_admin", op="nudge_result", agent=self.plain, args={"msg_id": n["msg_id"], "outcome": "woke", "reason": "HTTP 200"})
        self.assertEqual(res["outcome"], "woke")
        self.assertEqual(D.outcomes(self.h.store.read_all())["woke"], 1)


class Item2LedgerOnly(Base):
    def _stale(self, host):
        r = self.reg("curator", host)
        a = self.reg(host="local_a_" + host[-2:])
        n = self.nudge(a, r[:8], "task")
        self.assertTrue(n["do"].startswith("Do: SendMessage to %s:" % host))
        self.call("harness_admin", op="nudge_result", agent=a, args={"msg_id": n["msg_id"], "outcome": "skipped", "reason": "stale_id"})
        return r

    def test_the_state_file_holds_no_mark(self):
        r = self._stale("local_f1")
        self.assertNotIn("stale_hids", D._load(D._sp(self.h, r)))
        self.assertEqual(D._stale_ids(self.h), {"local_f1"})

    def test_interleaved_writes_never_leave_a_mark(self):
        """The 0.21.1 race: the recipient's settle loads its state file, a sender marks the recipient stale (0.21.1 wrote the mark into that
        same file), then settle saves its old copy. 0.21.1 lost the mark's file entry, so no clear ever came. Here the mark lives in the ledger,
        so the recipient's next call from that session clears it."""
        r = self.reg("curator", "local_race")
        a = self.reg(host="local_ra")
        n = self.nudge(a, r[:8], "task")
        real_save, fired = D._save, []

        def racing_save(p, d):
            if p == D._sp(self.h, r) and not fired:
                fired.append(1)
                D.record_result(self.h, a, n["msg_id"], "skipped", "stale_id")       # the sender's write lands mid-settle
            real_save(p, d)
        with mock.patch.dict(os.environ, {"CLAUDE_CODE_HOST_SESSION_ID": "local_race"}), mock.patch.object(D, "_save", racing_save):
            D.settle(self.h, r)
        self.assertEqual(fired, [1])
        with mock.patch.dict(os.environ, {"CLAUDE_CODE_HOST_SESSION_ID": "local_race"}):
            self.call("harness_inbox", agent=r)
        self.assertEqual(D._stale_ids(self.h), set())

    def test_a_compaction_successor_in_the_same_chat_clears_the_mark(self):
        r = self._stale("local_cs")
        s = self.reg("curator", "local_cs", predecessor=r, spawn_reason="compaction")
        with mock.patch.dict(os.environ, {"CLAUDE_CODE_HOST_SESSION_ID": "local_cs"}):
            self.call("harness_inbox", agent=s)
        self.assertEqual(D._stale_ids(self.h), set())

    def test_no_env_clears_only_marks_naming_the_caller(self):
        r = self._stale("local_n1")
        other = self.reg("design-coder", "local_n2")
        with mock.patch.dict(os.environ, {"CLAUDE_CODE_HOST_SESSION_ID": ""}):
            D.settle(self.h, other)
            self.assertEqual(D._stale_ids(self.h), {"local_n1"})
            D.settle(self.h, r)
        self.assertEqual(D._stale_ids(self.h), set())

    def test_an_old_021_file_field_is_dropped(self):
        r = self.reg("curator", "local_old")
        D._save(D._sp(self.h, r), {"stale_hids": ["local_old"], "last_call": 1})
        D.settle(self.h, r)
        self.assertNotIn("stale_hids", D._load(D._sp(self.h, r)))
        self.assertEqual(self.events("nudge.stale_cleared"), [])                        # a file field alone is no mark


class Item3Bounded(Base):
    def _pad(self, n):
        line = json.dumps({"seq": 0, "type": "pad", "t": time.time(), "actor": "system", "data": {"x": "y" * 1000}}) + "\n"
        with open(self.h.store.log, "a") as f:
            f.write(line * n)

    def test_the_stale_read_never_parses_the_whole_ledger(self):
        self.h.store.append("nudge.stale_id", "system", {"host_session_id": "local_far", "to": "z"})
        self._pad(20000)                                                                # ~21 MB, past the 4 MB tail
        self.h.store.append("nudge.stale_id", "system", {"host_session_id": "local_near", "to": "z"})
        with mock.patch.object(self.h.store, "read_all", side_effect=AssertionError("full read")):
            t0 = time.time()
            ids = D._stale_ids(self.h)
            took = time.time() - t0
        self.assertEqual(ids, {"local_near"})                                           # a mark past the window is forgotten
        self.assertLess(took, 1.0)

    def test_a_partial_first_line_is_dropped(self):
        self.h.store.append("nudge.stale_id", "system", {"host_session_id": "local_p", "to": "z"})
        with open(self.h.store.log, "rb") as f:
            last = f.read().rstrip(b"\n").rsplit(b"\n", 1)[-1]
        self.assertEqual(D._stale_marks(self.h, nbytes=len(last) - 5), {})             # cut inside that line: dropped, not parsed
        self.assertEqual(D._stale_marks(self.h, nbytes=len(last) + 2), {"local_p": "z"})

    def test_a_symlinked_ledger_is_refused(self):
        real = self.h.store.log + ".real"
        os.replace(self.h.store.log, real)
        os.symlink(real, self.h.store.log)
        with self.assertRaises(Exception):
            D._tail(self.h)


class Item4FrozenMirror(Base):
    def test_a_read_only_source_mirrors_twice(self):
        root = os.path.join(self.tmp, "plug")
        for sub, fn in (("scripts", "a.py"), ("data", "x.json")):
            os.makedirs(os.path.join(root, sub))
            with open(os.path.join(root, sub, fn), "w") as f:
                f.write("1")

        def freeze(on):
            for d_, _, fs in os.walk(root):
                for f_ in fs:
                    os.chmod(os.path.join(d_, f_), 0o444 if on else 0o644)
        freeze(True)
        self.h._mirror_launcher(root)
        freeze(False)
        with open(os.path.join(root, "scripts", "a.py"), "w") as f:
            f.write("2")
        freeze(True)
        self.h._mirror_launcher(root)                                                   # 0.21.1: PermissionError here
        dst = os.path.join(self.home, "_harness", "bin", "a.py")
        with open(dst) as f:
            self.assertEqual(f.read(), "2")
        self.assertTrue(os.stat(dst).st_mode & stat.S_IWUSR)

    def test_an_existing_read_only_copy_is_replaced(self):
        root = os.path.join(self.tmp, "plug2")
        os.makedirs(os.path.join(root, "scripts"))
        with open(os.path.join(root, "scripts", "b.py"), "w") as f:
            f.write("new")
        dst = os.path.join(self.home, "_harness", "bin")
        os.makedirs(dst, exist_ok=True)
        with open(os.path.join(dst, "b.py"), "w") as f:
            f.write("old")
        os.chmod(os.path.join(dst, "b.py"), 0o444)                                      # left by a 0.21.1 mirror of a frozen tree
        self.h._mirror_launcher(root)
        with open(os.path.join(dst, "b.py")) as f:
            self.assertEqual(f.read(), "new")


class Item5CliSettle(Base):
    def test_a_cli_call_records_the_same_last_call_as_an_mcp_call(self):
        r = self.reg("curator", "local_cli")
        self.assertIsNone(D._load(D._sp(self.h, r)).get("last_call"))
        with mock.patch.dict(os.environ, {"HARNESS_HOME": self.home}), contextlib.redirect_stdout(io.StringIO()):
            H.main(["inbox", "--agent", r[:8], "--peek"])
        cli_t = D._load(D._sp(self.h, r)).get("last_call")
        self.assertTrue(cli_t and time.time() - cli_t < 60)
        self.call("harness_inbox", agent=r)
        self.assertGreaterEqual(D._load(D._sp(self.h, r)).get("last_call"), cli_t)

    def test_a_cli_caller_counts_as_warm_for_the_id_wake_cap(self):
        r = self.reg("curator", "local_warmcli")
        with mock.patch.dict(os.environ, {"HARNESS_HOME": self.home}), contextlib.redirect_stdout(io.StringIO()):
            H.main(["inbox", "--agent", r[:8], "--peek"])
        outs = [self.nudge(self.reg(host="local_wc%d" % i), r[:8], "handoff")["do"] for i in range(3)]   # 0.24.0 (item 5): R2 replaces this slot for task/question/review; it stays for handoff
        self.assertTrue(all(o.startswith("Do: SendMessage to local_warmcli") for o in outs))
        self.assertEqual(self.events("nudge.idwake"), [])

    def test_operator_and_agentless_cli_calls_do_not_settle(self):
        with mock.patch.object(D, "settle", side_effect=AssertionError("settled")), \
                mock.patch.dict(os.environ, {"HARNESS_HOME": self.home}), contextlib.redirect_stdout(io.StringIO()):
            H.main(["ledger"])


if __name__ == "__main__":
    unittest.main()
