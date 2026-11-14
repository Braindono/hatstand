"""cc 0.22.0 items 6 and 7 (addendum v2.1, D-3e5e7): role-only addressing (tests 6a-6h) and the delivery alarm (7a-7i).
Run: python3 -B tests/test_c220_nudge.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _env  # noqa: F401  isolate HOME and HARNESS_* first
import inspect, json, os, shutil, sys, tempfile, time, unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
import harness as H
import mcp_server as M
import doorbell as D

MODEL = "claude-sonnet-5-5"
REAL_MACHINE_ID = H.machine_id                                                      # before any test patches it
TRIG = "trig_FAKEsecretary0001x"


def WP(role, trig=TRIG, kind="recurring"):
    """0.23.0 (A-08480 item 3 gap 6): a pin entry in the only accepted form; plain trig_ strings are refused."""
    return {"trigger": trig, "kind": kind, "prompt": D.wake_prompt(role)}


def legacy_pin(h, entries):
    """0.24.0 (A-b2950 item 13): write a wake.pinned event as an operator grant wrote it before 0.24 (the approval path is removed;
    legacy pins stay readable until stale). Each entry passes the 0.23.0 check, so the shapes the old grant wrote are the only ones."""
    st = h.state()
    out = {}
    for k, v in entries.items():
        ent = h._wake_entry_ok(k, v, st.role_holder(k))
        if ent is None:
            raise H.HarnessError("0.23.0 refused this pin entry too: %r" % (v,))
        out[k] = ent
    h.store.append("wake.pinned", "human", {"entries": dict(sorted(out.items()))})


def record_v023(h, caller, msg_id, outcome, reason):
    """0.24.0 (A-b2950 item 3): write a nudge.result as 0.23.0 wrote it (free-text reason, no `status`), so rows from before 0.24.0 replay
    through the old reader. Relayer evidence in the 0.23.0 shape when the caller is not the sender."""
    offer = next(e["data"] for e in reversed(h.store.read_all()) if e.get("type") in D.OFFERS and e["data"].get("msg_id", e["data"].get("msg")) == msg_id)
    why = " ".join(str(reason or "").split())[:80]
    data = {"msg": msg_id, "msg_id": msg_id, "by": caller, "for": offer.get("from"), "outcome": outcome, "reason": why}
    if offer.get("from") not in set(h.state().lineage(caller)) | {caller}:
        ev = D.relay_evidence(why)
        assert ev, "0.23.0 refused this relayer report too: %r" % reason
        data["evidence"] = dict(ev, self_reported=True)
    h.store.append("nudge.result", caller, data)


class Base(unittest.TestCase):
    # 0.24.0 (A-b2950 item 5, envoy m-7ffa2d0bcd3c): every suite runs with item 5 on. A suite that needs back-to-back sends to one
    # recipient as setup turns off only the nb 6 window (SAME_SESSION_S = 0), named in its setUp (test_c223_relay, test_cc155_doorbell).

    def setUp(self):
        m = mock.patch.object(H, "machine_id", lambda: "machine-mac")             # 0.22.1: every sender in these tests is on "the Mac"
        m.start()
        self.addCleanup(m.stop)
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.home = os.path.join(self.tmp, "Exchange")
        os.makedirs(os.path.join(self.home, "_harness"))
        e = mock.patch.dict(os.environ, {"HARNESS_STATE_CACHE": "0"})
        e.start()
        self.addCleanup(e.stop)
        self.op = {}
        p = mock.patch.object(H, "_operator_file", lambda: (self.op, []))
        p.start()
        self.addCleanup(p.stop)
        self.h = H.Harness(self.home)
        for r in ("curator", "envoy", "secretary"):
            self.h.role_define("operator", r, "harness-ops", carry="none")
        self.plain = self.reg(host="local_plain")

    def reg(self, role=None, host=None, machine=None, hostname=None, **kw):
        with mock.patch.object(H, "machine_id", lambda: machine or "machine-mac"), mock.patch.object(H, "HOSTNAME", hostname or H.HOSTNAME):
            return self.h.register(project="harness-ops", model=MODEL, task="t", role=role, host_session_id=host, **kw)["id"]

    def warm(self, aid):
        D.settle(self.h, aid)

    def call(self, name, **a):
        M.BOUND.update(home=None, id=None)
        return M.call(self.h, name, a)

    def send(self, frm, to, kind="task"):
        self.n = getattr(self, "n", 0) + 1
        return self.call("harness_send", agent=frm, to=to, body="b%d" % self.n, subject="s%d" % self.n, kind=kind)

    def events(self, t):
        return [e for e in self.h.store.read_all() if e["type"] == t]


class Item6RoleOnly(Base):
    def test_6a_one_exact_address_no_name_no_title(self):
        c = self.reg("curator", "local_cur")
        n = self.send(self.plain, "role:curator")["nudge"]
        self.assertTrue(n["do"].startswith("Do: SendMessage to local_cur:"))
        sob = self.h.state().agents[c]["sobriquet"]
        self.assertNotIn(sob, n["do"])
        self.assertNotIn("CURATOR -", n["do"])
        self.assertNotIn("ListAgents", n["do"])

    def test_6b_no_id_means_mail_only(self):
        with mock.patch.dict(os.environ, {"CLAUDE_CODE_HOST_SESSION_ID": ""}):
            self.reg("curator", None)
        r = self.send(self.plain, "role:curator")
        self.assertEqual(r["nudge"], "miss (no_route)")                       # round 7 C6
        self.assertEqual(len([e for e in self.h.store.read_all() if e["type"] == "nudge.miss"]), 1)                                               # exactly one counted miss
        self.assertEqual(self.events("nudge.offered"), [])

    def test_6c_compaction_in_the_same_chat_keeps_the_address(self):
        a = self.reg("curator", "local_same")
        self.reg("curator", "local_same", predecessor=a, spawn_reason="compaction")
        self.assertTrue(self.send(self.plain, "role:curator")["nudge"]["do"].startswith("Do: SendMessage to local_same:"))

    def test_6d_restore_into_a_new_chat_uses_the_new_id(self):
        a = self.reg("curator", "local_old")
        self.reg("curator", "local_new", predecessor=a, spawn_reason="restore")
        self.assertTrue(self.send(self.plain, "role:curator", "review")["nudge"]["do"].startswith("Do: SendMessage to local_new:"))

    def test_6e_a_result_rings_only_a_warm_holder(self):
        c = self.reg("curator", "local_res")
        self.assertEqual(self.send(self.plain, "role:curator", "result")["nudge"], "none (result to a cold holder: mail only)")
        self.warm(c)
        self.assertTrue(self.send(self.plain, "role:curator", "result")["nudge"]["do"].startswith("Do: SendMessage to local_res:"))

    def test_6f_no_do_line_builder_reads_a_name(self):
        for fn in (D._do_one, D._route, D._pick_id, D._id_for):
            self.assertNotIn("sobriquet", inspect.getsource(fn))
            self.assertNotIn("title_of", inspect.getsource(fn))
        for gone in ("match_rows", "_allowed_names", "_bare_ok"):
            self.assertFalse(hasattr(D, gone))

    def test_6g_a_pinned_trigger_with_no_id_gives_the_trigger_line_only(self):
        with mock.patch.dict(os.environ, {"CLAUDE_CODE_HOST_SESSION_ID": ""}):
            self.reg("secretary", None)
        legacy_pin(self.h, {"secretary": WP("secretary")})     # 0.23.0 (gap 3, gap 6): dict form, holder registered first
        do = self.send(self.plain, "role:secretary")["nudge"]["do"]
        self.assertTrue(do.startswith("Do: RemoteTrigger action=run trigger_id=" + TRIG))
        self.assertNotIn("SendMessage", do)

    def test_6h_another_machine_gets_no_ring_a_counted_miss_and_never_alarms(self):          # critic m-00ea2ad60bc4, m-fcb579e7e932
        pc = self.reg("curator", "local_pc", machine="machine-pc")
        self.assertEqual(self.send(self.plain, "role:curator")["nudge"], "miss (no_route)")      # round 7 C6
        self.assertEqual(len([e for e in self.h.store.read_all() if e["type"] == "nudge.miss"]), 1)                                               # exactly one counted miss
        self.assertEqual(self.events("nudge.offered"), [])
        t0 = time.time()
        for k in range(18):                                                    # three hours of scans, half from the PC
            now = t0 + 600 * (k + 1)
            with mock.patch.object(H, "machine_id", (lambda: "machine-pc") if k % 2 else (lambda: "machine-mac")):
                D._save(D._sp(self.h, pc), {"last_call": now - 60})            # the PC holder stays active
                D.alarm_scan(self.h, now=now, force=True)
        self.assertEqual(self.events("nudge.alarm"), [])
        local = self.reg("envoy", "local_env")                                  # same machine, failing id: still alarms on stale_id
        n = self.send(self.plain, "role:envoy")["nudge"]
        self.call("harness_admin", op="nudge_result", agent=self.plain, args={"msg_id": n["msg_id"], "outcome": "skipped", "reason": "stale_id"})
        D._save(D._sp(self.h, local), {"last_call": time.time()})
        D.alarm_scan(self.h, force=True)
        self.assertEqual([e["data"]["cond"] for e in self.events("nudge.alarm")], ["skipped"])


    def test_0221_a_hostname_change_on_the_same_machine_still_routes(self):      # envoy m-ea0c30970c55 failing input
        self.reg("curator", "local_same_mac", hostname="host-a")
        with mock.patch.object(H, "HOSTNAME", "host-b"):
            n = self.send(self.plain, "role:curator")["nudge"]
        self.assertTrue(n["do"].startswith("Do: SendMessage to local_same_mac:"))

    def test_0221_a_different_machine_id_stays_mail_only_whatever_the_hostname(self):
        self.reg("curator", "local_other", machine="machine-other", hostname=H.HOSTNAME)
        self.assertEqual(self.send(self.plain, "role:curator")["nudge"], "miss (no_route)")      # round 7 C6
        self.assertEqual(len([e for e in self.h.store.read_all() if e["type"] == "nudge.miss"]), 1)                                               # exactly one counted miss

    def test_0221_a_record_without_an_id_routes_only_by_this_machines_own_host_names(self):   # A-4d611 item 4
        self.reg("envoy", "local_learn", hostname="host-a")                       # a 0.22.1 registration: host-a is an alias now
        st = self.h.state()
        self.assertIn("host-a", {x.lower() for x in st.machine_hosts.get("machine-mac", ())})
        with mock.patch.object(H, "HOSTNAME", "host-b"):
            self.assertTrue(D._same_machine({"host": "host-a"}, st))                  # old record, alias host: this machine
            self.assertTrue(D._same_machine({"host": "host-b"}, st))                   # the current name is always an alias
            self.assertFalse(D._same_machine({"host": "SomeOtherBox"}, st))               # any other string: mail only
        self.assertFalse(D._same_machine({"machine": "machine-pc", "host": H.HOSTNAME}, st))
        with mock.patch.object(H, "machine_id", lambda: None):                           # unreadable id: fail safe, mail only
            self.assertFalse(D._same_machine({"machine": "machine-mac"}, st))

    def test_0221_sync_records_the_machine_id(self):
        with mock.patch.dict(os.environ, {"CLAUDE_CODE_HOST_SESSION_ID": ""}):
            old = self.h.register(project="harness-ops", model=MODEL, task="t", role="curator", host_session_id="local_oldrec")["id"]
        st = self.h.state()
        st.agents[old].pop("machine", None)
        self.call("harness_sync", agent=old)
        self.assertEqual(self.h.state().agents[old]["machine"], "machine-mac")

    def test_0221_the_machine_id_is_a_salted_hash_and_a_lost_salt_gives_a_new_id(self):
        import hashlib
        uuid_ = "12345678-1234-1234-1234-123456789ABC"
        sd = os.path.join(self.tmp, "st")
        run = mock.Mock(return_value=mock.Mock(stdout=f'  "IOPlatformUUID" = "{uuid_}"\n'))

        def fresh():
            with mock.patch.object(H, "_MACHINE_ID", [None, False]), mock.patch.object(H, "_SIM_CHILD", False), \
                    mock.patch.object(H.subprocess, "run", run), mock.patch.object(H.sys, "platform", "darwin"), \
                    mock.patch.dict(os.environ, {"HARNESS_STATE_DIR": sd}):
                return REAL_MACHINE_ID()
        a = fresh()
        salt_p = os.path.join(sd, "machine-salt")
        salt = open(salt_p).read().strip()
        self.assertEqual(a, hashlib.sha256(f"{salt}:{uuid_.lower()}".encode()).hexdigest()[:16])
        self.assertEqual(oct(os.stat(salt_p).st_mode & 0o777), "0o600")
        self.assertNotIn(uuid_.lower()[:8], a)
        self.assertEqual(fresh(), a)                                                      # the salt is never rewritten
        os.remove(salt_p)
        b = fresh()                                                                       # a lost salt: a new id, no crash
        self.assertTrue(b and b != a)
        with mock.patch.object(H, "_MACHINE_ID", [None, False]), mock.patch.object(H, "_SIM_CHILD", True):
            self.assertEqual(REAL_MACHINE_ID(), "sim-machine")                           # the fenced simulator child starts no process


class Item7Alarm(Base):
    def active(self, role, host):
        a = self.reg(role, host)
        self.warm(a)
        return a

    def test_7a_an_active_unread_recipient_alarms(self):                       # MUST fail on 0.21.2 (no nudge.alarm there)
        c = self.active("curator", "local_a7")
        n = self.send(self.plain, "role:curator")["nudge"]
        D._save(D._sp(self.h, c), {"last_call": time.time() - 300})            # a harness call 5 minutes ago
        out = D.alarm_scan(self.h, now=time.time() + 11 * 60, force=True)
        self.assertEqual([(x["msg_id"], x["cond"], x["to"]) for x in out], [(n["msg_id"], "unread", c)])
        self.assertEqual(len(self.events("nudge.alarm")), 1)

    def test_7a_inverse_read_in_time_raises_nothing(self):
        c = self.active("curator", "local_a7r")
        self.send(self.plain, "role:curator")
        self.call("harness_inbox", agent=c)
        self.assertEqual(D.alarm_scan(self.h, now=time.time() + 11 * 60, force=True), [])

    def test_7b_a_long_turn_gives_one_alarm_per_hour(self):                    # the false-alarm test
        c = self.active("curator", "local_a7b")
        t0 = time.time()
        self.send(self.plain, "role:curator")
        self.send(self.reg(host="local_o2"), "role:curator")
        D._save(D._sp(self.h, c), {"last_call": t0})
        first = D.alarm_scan(self.h, now=t0 + 11 * 60, force=True)
        again = D.alarm_scan(self.h, now=t0 + 31 * 60, force=True)
        self.assertEqual((len(first), len(again)), (1, 0))
        self.send(self.reg(host="local_o3"), "role:curator")
        D._save(D._sp(self.h, c), {"last_call": t0 + 3600 + 60 * 60})          # still active at the later scan
        nxt = D.alarm_scan(self.h, now=t0 + 3600 + 61 * 60, force=True)
        self.assertTrue(nxt and nxt[0]["suppressed"] >= 1)                      # the held-back hit shows on the next alarm
        self.assertGreaterEqual(D.alarm_summary(self.h)["suppressed"], 1)

    def test_7c_one_alarm_per_message(self):
        self.active("curator", "local_a7c")
        self.send(self.plain, "role:curator")
        for k in range(5):
            D.alarm_scan(self.h, now=time.time() + (11 + 70 * k) * 60, force=True)
        self.assertEqual(len(self.events("nudge.alarm")), 1)

    def test_7d_quiet_or_idless_holders_raise_nothing(self):
        c = self.reg("curator", "local_a7d")
        self.send(self.plain, "role:curator")
        D._save(D._sp(self.h, c), {"last_call": time.time() - 3 * 3600})        # quiet before the send and since
        self.assertEqual(D.alarm_scan(self.h, now=time.time() + 11 * 60, force=True), [])
        e = self.active("envoy", "local_a7d2")
        self.send(self.plain, "role:envoy")
        D._save(D._sp(self.h, e), {"last_call": time.time()})                  # active at send, quiet by the scan 2 h later
        self.assertEqual(len(D.alarm_scan(self.h, now=time.time() + 2 * 3600, force=True)), 1)

    def test_7e_cap_skips_raise_nothing_stale_and_unreported_do(self):
        c = self.active("curator", "local_a7e")
        n1 = self.send(self.plain, "role:curator", kind="handoff")["nudge"]["msg_id"]    # 0.24.0 (item 5, R1): a task may not skip for a cap
        self.call("harness_admin", op="nudge_result", agent=self.plain, args={"msg_id": n1, "outcome": "skipped", "reason": "sender cap 10/h"})
        self.call("harness_inbox", agent=c)                                    # read, so A1 does not fire either
        self.assertEqual(D.alarm_scan(self.h, force=True), [])
        s2 = self.reg(host="local_s2")
        n2 = self.send(s2, "role:curator")["nudge"]["msg_id"]
        self.call("harness_admin", op="nudge_result", agent=s2, args={"msg_id": n2, "outcome": "skipped", "reason": "stale_id"})
        self.warm(c)
        self.assertEqual([x["cond"] for x in D.alarm_scan(self.h, now=time.time() + 3700, force=True)], ["skipped"])
        # a trigger-only offer (no id line) skipped with no_remotetrigger raises nothing (critic m-99bea4382739)
        with mock.patch.dict(os.environ, {"CLAUDE_CODE_HOST_SESSION_ID": ""}):
            sec = self.reg("secretary", None)
        legacy_pin(self.h, {"secretary": WP("secretary")})     # 0.23.0 (gap 3, gap 6): dict form, holder registered first
        s3 = self.reg(host="local_s3")
        n3 = self.send(s3, "role:secretary")["nudge"]["msg_id"]
        self.call("harness_admin", op="nudge_result", agent=s3, args={"msg_id": n3, "outcome": "skipped", "reason": "no_remotetrigger"})
        self.warm(sec)
        self.assertEqual([x for x in D.alarm_scan(self.h, now=time.time() + 7300, force=True) if x["msg_id"] == n3], [])

    def test_7e_unreported_alarms_and_names_the_sender(self):
        c = self.active("curator", "local_a7u")
        s = self.reg(host="local_su")
        n = self.send(s, "role:curator")["nudge"]["msg_id"]
        self.h.store.append("nudge.unreported", "system", {"msg": n, "msg_id": n, "by": s})
        out = D.alarm_scan(self.h, force=True)
        self.assertEqual([(x["cond"], x["from"]) for x in out], [("unreported", s)])

    def test_7f_log_only_in_week_one_then_mail_the_envoy_ids_only(self):
        self.active("envoy", "local_env7")
        c = self.active("curator", "local_a7f")
        self.send(self.plain, "role:curator")
        D.alarm_scan(self.h, now=time.time() + 11 * 60, force=True)
        mails = lambda: [m for m in self.h.state().messages.values() if m.get("subject") == "nudge alarm"]
        self.assertEqual(mails(), [])
        armed = self.events("nudge.alarm_armed")
        self.assertEqual(len(armed), 1)
        t8 = time.time() + 8 * 86400
        o7 = self.reg(host="local_o7")
        with mock.patch("time.time", return_value=t8):                         # the second nudge goes out a week later
            self.call("harness_send", agent=o7, to="role:curator", body="SECRET-BODY-7F", subject="SECRET-SUBJ-7F", kind="task")
        D._save(D._sp(self.h, c), {"last_call": t8})
        D.alarm_scan(self.h, now=t8 + 11 * 60, force=True)
        self.assertEqual(len(mails()), 1)
        body = mails()[0]["body"]
        self.assertTrue(body.startswith("nudge.alarm m-"))
        self.assertEqual(mails()[0]["from"], "system")                           # item 39: a named system sender, never the operator
        self.assertNotIn("SECRET-", body)                                        # no subject or body text of the message

    def test_7g_thresholds_come_from_operator_json_only(self):
        self.op["doorbell"] = {"alarm_unread_min": 500, "alarm_active_min": 3}   # out of bounds: defaults
        cfg = D._opcfg(self.h)
        self.assertEqual((cfg["alarm_unread_min"], cfg["alarm_active_min"]), (10, 30))
        self.op["doorbell"] = {"alarm_unread_min": 20}
        self.assertEqual(D._opcfg(self.h)["alarm_unread_min"], 20)
        self.op["listen"] = {"alarm_unread_min": 99}                              # only the doorbell section counts
        self.assertEqual(D._opcfg(self.h)["alarm_unread_min"], 20)
        with open(os.path.join(self.home, "_harness", "config.json"), "w") as f:
            json.dump({"doorbell": {"alarm_unread_min": 2}}, f)                  # agent-writable: ignored
        self.assertEqual(D._opcfg(self.h)["alarm_unread_min"], 20)

    def test_7h_settle_scans_once_a_minute_and_the_cli_matches(self):
        self.active("curator", "local_a7h")
        self.send(self.plain, "role:curator")
        os.remove(os.path.join(self.home, "_harness", "nudge_state", "_alarm_scan.json"))   # the sends above already scanned
        scans = []
        real = D._tail
        with mock.patch.object(D, "_tail", lambda h, nbytes=D.TAIL_BYTES, needle=None: (scans.append(needle), real(h, nbytes, needle))[1]):
            D.settle(self.h, self.plain)
            D.settle(self.h, self.plain)
        self.assertEqual(scans.count(b'"nudge.'), 1)                            # the second call within a minute does not scan
        with mock.patch.dict(os.environ, {"HARNESS_HOME": self.home}):
            import contextlib, io
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                H.main(["alarm-scan"])
        self.assertIn("alarms", buf.getvalue())

    def test_7i_a_scan_over_a_big_ledger_is_fast(self):
        line = json.dumps({"seq": 0, "type": "pad", "t": time.time(), "actor": "system", "data": {"x": "y" * 1000}}) + "\n"
        with open(self.h.store.log, "a") as f:
            f.write(line * 20000)
        self.active("curator", "local_a7i")
        t0 = time.time()
        D.alarm_scan(self.h, force=True)
        self.assertLess(time.time() - t0, 0.5)

    def test_sync_shows_a_waiting_alarm(self):
        c = self.active("curator", "local_sync")
        self.send(self.plain, "role:curator")
        D.alarm_scan(self.h, now=time.time() + 11 * 60, force=True)
        txt = self.call("harness_sync", agent=c).get("text", "")
        self.assertIn("nudge alarm", txt)


if __name__ == "__main__":
    unittest.main()
