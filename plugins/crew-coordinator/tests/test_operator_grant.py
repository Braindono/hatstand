"""Operator seat stage 2: the root helper, event map and verifier, run on a temp tree with a test key (never shipped).
Run: python3 -B tests/test_operator_grant.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _env  # noqa: F401
import io, json, os, subprocess, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "root"))
import harness_event_map as MAP
import harness_verify as V
import harness_grant_helper as G

TTY = "/dev/ttys099"


def ev(seq, typ, data, actor="human", t=1000):
    e = {"v": 1, "seq": seq, "ts": "x", "t": t, "type": typ, "actor": actor, "data": data, "prev": "p", "via": {}}
    import hashlib
    e["hash"] = hashlib.sha256(MAP.canonical({k: v for k, v in e.items()}).encode()).hexdigest()
    return e


class Base(unittest.TestCase):
    def setUp(self):
        self.d = os.path.realpath(tempfile.mkdtemp())
        sd = os.path.join(self.d, "state"); os.makedirs(sd); os.makedirs(os.path.join(self.d, "pending"))
        key = os.path.join(sd, "key"); pub = os.path.join(self.d, "pub.pem")
        subprocess.run(["/usr/bin/openssl", "genrsa", "-out", key, "2048"], capture_output=True, check=True)
        subprocess.run(["/usr/bin/openssl", "rsa", "-in", key, "-pubout", "-out", pub], capture_output=True, check=True)
        self.cfg = dict(G.CFG, state_dir=sd, key=key, pub=pub, log=os.path.join(self.d, "grants.log"),
                        pending=os.path.join(self.d, "pending"), ledger=os.path.join(self.d, "events.jsonl"),
                        uid=os.getuid(), min_gap_s=0)
        self.now = 10000.0
        self.led = [ev(1, "agent.registered", {"id": "a"}, actor="a"), ev(2, "agent.updated", {"x": 1}, actor="a")]
        self.write_ledger()
        G.cmd_cutover(self.cfg)

    def write_ledger(self):
        open(self.cfg["ledger"], "w").write("".join(json.dumps(e, sort_keys=True) + "\n" for e in self.led))

    DETAIL = {"action": "retag_operator", "args": {"entry": "N-1", "project": "p"}}

    def dig(self, name="aaaaaaaaaaaa"):
        """The args digest `request` fills in for the request called `name`."""
        det = {"action": self.DETAIL["action"], "args": dict(self.DETAIL["args"], n=name)}
        return __import__("hashlib").sha256(MAP.canonical(det).encode()).hexdigest()

    def request(self, events, kind="approve", name="aaaaaaaaaaaa", expires=None, raw=None, detail="auto"):
        """An approval request carries its action and args (0.27.0); by default a true detail and the matching digest are filled in."""
        req = {"v": 1, "kind": kind, "requester": "someone", "created": 1, "expires": expires or int(self.now) + 600, "events": events}
        if kind == "approve" and detail == "auto" and len(events) == 1 and events[0].get("type") == "approval.granted":
            det = {"action": self.DETAIL["action"], "args": dict(self.DETAIL["args"], n=name)}
            dig = __import__("hashlib").sha256(MAP.canonical(det).encode()).hexdigest()
            req["events"] = [dict(events[0], data=dict(events[0]["data"], args_digest=dig))]
            req["detail"] = det
        elif detail not in ("auto", None):
            req["detail"] = detail
        b = raw if raw is not None else MAP.canonical(req).encode()
        open(os.path.join(self.cfg["pending"], name + ".json"), "wb").write(b)
        return b

    def sign(self, answer="ab12"):
        """One `approve` run: every live pending request shown, one code typed, each signed. -> (act records, what was shown)."""
        out = io.StringIO()
        acts = G.cmd_approve(self.cfg, TTY, io.StringIO(answer + "\n"), out, self.now, G.ledger_id(self.cfg), rnd=lambda n: "ab12", same_tty=lambda: True)
        return acts, out.getvalue()

    def sent(self, seq, typ, data):
        e = ev(seq, typ, data, t=int(self.now)); self.led.append(e); self.write_ledger(); return (seq, e["hash"])


class Helper(Base):
    def test_padded_body_shown_whole_and_escapes(self):
        self.request([{"type": "role.assigned", "data": {"role": "operator", "agent": "A" * 300 + "TAILFIELD\x1b[2J‮"}}], kind="role_assign")
        _, shown = self.sign()
        self.assertIn("TAILFIELD", shown)
        self.assertNotIn("\x1b", shown); self.assertNotIn("‮", shown); self.assertIn("HIGH RISK", shown)

    def test_unknown_type_noncanonical_duplicate_float_refused(self):
        for raw in (self.request([{"type": "weird.type", "data": {}}]),
                    b'{"kind": "x"}',
                    b'{"a":1,"a":2}', b'{"a":1.0}', b'{"a":NaN}'):
            self.request([], raw=raw)
            with self.assertRaises(G.Refuse): self.sign()

    def test_symlink_fifo_and_huge_refused(self):
        p = os.path.join(self.cfg["pending"], "aaaaaaaaaaaa.json")
        for make in (lambda: os.symlink("/etc/hosts", p), lambda: os.mkfifo(p)):
            make()
            with self.assertRaises(G.Refuse): self.sign()
            os.unlink(p)
        open(p, "wb").write(b"x" * 70000)
        with self.assertRaises(G.Refuse): self.sign()
        with self.assertRaises(G.Refuse):
            os.rename(self.cfg["pending"], self.cfg["pending"] + "_real"); os.symlink(self.cfg["pending"] + "_real", self.cfg["pending"])
            G.open_regular(os.path.join(self.cfg["pending"], "aaaaaaaaaaaa.json"), os.getuid(), 70000)

    def test_installed_helper_has_no_user_path_writes_and_no_dead_commands(self):
        src = open(os.path.join(HERE, "..", "root", "harness_grant_helper.py")).read()
        self.assertNotIn("subprocess.run([\"/usr/bin/sudo", src)
        for w in ("getpass", "input(", "/dev/zero", "def cmd_grant", "def cmd_sign_pending", "def cmd_consume", "def real_auth", "def _window"):
            self.assertNotIn(w, src)


class Verifier(Base):
    def test_forged_human_event_and_deleted_consumed_event(self):
        d = {"id": "A-9"}
        self.request([{"type": "approval.granted", "data": d}]); acts, _ = self.sign()
        tail = G.ledger_tail_seq(self.cfg)
        self.sent(3, "approval.granted", dict(d, args_digest=self.dig()))
        G.consume_matched(self.cfg, acts, tail, self.now)
        self.assertEqual(V.audit(self.cfg["ledger"], self.cfg["log"], self.cfg["pub"]), [])
        self.sent(4, "role.assigned", {"role": "operator", "agent": "evil"})            # forged, no grant
        self.assertTrue(any("seq 4" in p for p in V.audit(self.cfg["ledger"], self.cfg["log"], self.cfg["pub"])))
        self.led = [e for e in self.led if e["seq"] != 3]; self.write_ledger()          # deleted consumed event
        self.assertTrue(any("seq 3" in p for p in V.audit(self.cfg["ledger"], self.cfg["log"], self.cfg["pub"])))

    def test_forged_log_line_rejected(self):
        open(self.cfg["log"], "a").write(json.dumps({"rec": {"t": "consume", "act": "x", "events": [[9, "h"]]}, "sig": "AAAA"}) + "\n")
        cut, ok = V.accepted(self.cfg["log"], self.cfg["pub"])
        self.assertNotIn((9, "h"), ok)


class EventMap(unittest.TestCase):
    def test_digest_excludes_display_only_and_covers_rest(self):
        a = {"type": "approval.granted", "data": {"id": "1", "state": "granted", "result": "A"}}
        b = {"type": "approval.granted", "data": {"id": "1", "state": "granted", "result": "B"}}
        c = {"type": "approval.granted", "data": {"id": "1", "state": "failed", "result": "A"}}
        self.assertEqual(MAP.event_digest(a), MAP.event_digest(b))
        self.assertNotEqual(MAP.event_digest(a), MAP.event_digest(c))
        self.assertIsNone(MAP.event_digest({"type": "x.y", "data": {}}))
        self.assertTrue(MAP.event_digest({"type": "case.opened", "data": {}}))

    def test_every_human_writer_type_has_a_row(self):
        import re
        types = set()
        for f in ("harness.py", "corpus.py", "hatstand_check.py", "wake.py"):
            p = os.path.join(HERE, "..", "scripts", f)
            if os.path.exists(p):
                types |= set(re.findall(r'append\("([a-z_.]+)",\s*"human"', open(p).read()))
        self.assertTrue(types)
        for t in types:
            self.assertIn(t, MAP.KINDS, f"human event type {t} has no map row")


class Setup(unittest.TestCase):
    def test_script_embeds_sources_and_refuses_unsafe_sudo(self):
        sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
        import seat_setup
        t = seat_setup.build("/Users/x/Exchange", 501)
        for n in ("harness_event_map.py", "harness_verify.py"):
            self.assertIn(open(os.path.join(HERE, "..", "root", n)).read().rstrip("\n"), t)
        for w in ("NOPASSWD", "!authenticate", "timestamp_type", "mktemp -d /var/root", "root:wheel", "/usr/local is group-writable"):
            self.assertIn(w, t)
        self.assertNotIn("/Users/x/Exchange/_harness/operator-scripts", t.split("HARNESS_EOF_harness-grant'", 1)[0])
        self.assertIn('"pending": "/Users/x/Exchange/_harness/operator-pending"', t)
        p = subprocess.run(["/bin/bash", "-n", "/dev/stdin"], input=t, capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr)


class OneCommand(Base):
    """0.26.2: the signer lists every live pending request, one 4-hex code, signs each; root matches the applied events itself."""
    D = {"id": "A-1", "channel": "cli-tty", "by": "operator", "state": "granted", "args_digest": "x"}

    def sign_all(self, answer="ab12", tty=TTY, same=True, now=None):
        out = io.StringIO()
        acts = G.cmd_approve(self.cfg, tty, io.StringIO(answer + "\n"), out, now or self.now, G.ledger_id(self.cfg),
                             rnd=lambda n: "ab12", same_tty=lambda: same)
        return acts, out.getvalue()

    def two(self):
        self.request([{"type": "approval.granted", "data": self.D}], name="aaaaaaaaaaaa")
        self.request([{"type": "approval.granted", "data": dict(self.D, id="A-2")}], name="bbbbbbbbbbbb")

    def test_all_live_requests_shown_in_full_one_code_signs_each_no_window(self):
        self.two()
        acts, shown = self.sign_all()
        self.assertEqual(len(acts), 2)
        self.assertIn("A-1", shown); self.assertIn("A-2", shown); self.assertIn("2 request(s), 2 event(s)", shown)

    def test_wrong_code_signs_nothing(self):
        self.two()
        with self.assertRaises(G.Refuse): self.sign_all(answer="zz")
        recs, _ = V.load_log(self.cfg["log"], self.cfg["pub"])
        self.assertFalse([r for r in recs if r["t"] == "act"])

    def test_no_tty_other_tty_nothing_pending_expired_refused(self):
        with self.assertRaises(G.Refuse): self.sign_all()                       # nothing pending
        self.two()
        with self.assertRaises(G.Refuse): self.sign_all(tty="")
        with self.assertRaises(G.Refuse): self.sign_all(same=False)             # code reader is not the sudo tty
        with self.assertRaises(G.Refuse): self.sign_all(now=self.now + 99999)   # both expired: nothing live

    def test_oversize_request_refused_nothing_signed(self):
        self.request([{"type": "approval.granted", "data": {"id": "A-9", "pad": ["x"] * 500}}])
        with self.assertRaises(G.Refuse): self.sign_all()
        recs, _ = V.load_log(self.cfg["log"], self.cfg["pub"])
        self.assertFalse([r for r in recs if r["t"] == "act"])

    def test_root_matches_applied_events_by_digest_and_hides_the_request(self):
        self.two()
        acts, _ = self.sign_all()
        tail = G.ledger_tail_seq(self.cfg)
        self.sent(3, "approval.granted", dict(self.D, id="A-2", args_digest=self.dig("bbbbbbbbbbbb")))     # applied out of order
        self.sent(4, "approval.granted", dict(self.D, args_digest=self.dig("aaaaaaaaaaaa")))
        self.sent(5, "approval.granted", dict(self.D, id="A-EXTRA"))            # an extra enforced event nobody signed
        out = G.consume_matched(self.cfg, acts, tail, self.now)
        self.assertTrue(all("consumed 1" in o for o in out), out)
        cut, ok = V.accepted(self.cfg["log"], self.cfg["pub"])
        self.assertEqual({s for s, _ in ok}, {3, 4})                             # the extra stays unconsumed
        self.assertEqual(G.live_pending(self.cfg, self.now)[0], [])              # signed and consumed: no longer pending

    def test_unmatched_act_records_nothing(self):
        self.two()
        acts, _ = self.sign_all()
        out = G.consume_matched(self.cfg, acts, G.ledger_tail_seq(self.cfg), self.now)
        self.assertTrue(all("not applied" in o for o in out))
        recs, _ = V.load_log(self.cfg["log"], self.cfg["pub"])
        self.assertFalse([r for r in recs if r["t"] == "consume"])

    def test_run_apply_kills_tickets_first_no_stdin_own_session_escaped_capped(self):
        import subprocess, types
        calls = []
        def stub(cmd, **kw):
            calls.append((cmd, kw))
            return types.SimpleNamespace(stdout="x\x1b[2J" + "y" * 5000, stderr="", returncode=0)
        out = G.run_apply(dict(self.cfg, home="/h", bin="/h/b.py"), "/hh", run=stub)
        self.assertEqual(calls[0][0], ["/usr/bin/sudo", "-K"])
        self.assertEqual(calls[0][1]["user"], self.cfg["uid"])
        cmd, kw = calls[1]
        self.assertEqual(kw["stdin"], subprocess.DEVNULL)
        self.assertTrue(kw["start_new_session"]); self.assertEqual(kw["timeout"], 60)
        self.assertEqual(kw["user"], self.cfg["uid"]); self.assertEqual(kw["cwd"], "/")
        self.assertNotIn("\x1b", out); self.assertLessEqual(len(out), 2000)

    def test_run_apply_timeout_reported(self):
        import subprocess
        def stub(cmd, **kw):
            if cmd[0] == "/usr/bin/sudo":
                import types
                return types.SimpleNamespace(returncode=0)
            raise subprocess.TimeoutExpired(cmd, 60)
        self.assertIn("timed out", G.run_apply(dict(self.cfg, home="/h", bin="/h/b.py"), "/hh", run=stub))

    def test_sudo_kill_failure_aborts_before_the_apply_child(self):
        import types
        calls = []
        def stub(cmd, **kw):
            calls.append(cmd)
            return types.SimpleNamespace(returncode=1, stdout="", stderr="")
        out = G.run_apply(dict(self.cfg, home="/h", bin="/h/b.py"), "/hh", run=stub)
        self.assertIn("could not be ended", out)
        self.assertEqual(calls, [["/usr/bin/sudo", "-K"]])                         # the apply child never started

    def test_deeply_nested_planted_file_is_one_skipped_request_not_a_crash(self):
        """The critic's input: one canonical ~6 kB file nested 3000 deep sat next to a good request and made `approve` die with RecursionError."""
        self.request([{"type": "approval.granted", "data": {"id": "A-1"}}])
        deep = ("[" * 3000 + "]" * 3000)
        junk = ('{"created":1,"events":[' + deep + '],"expires":99999999,"kind":"approve","requester":"x","v":1}').encode()
        open(os.path.join(self.cfg["pending"], "bbbbbbbbbbbb.json"), "wb").write(junk)
        items, skipped = G.live_pending(self.cfg, self.now)
        self.assertEqual(len(items), 1)
        self.assertTrue(any("nested too deeply" in s for s in skipped), skipped)
        acts, _ = self.sign()
        self.assertEqual(len(acts), 1)

    def test_approval_needs_exactly_one_event_and_its_text_and_shows_the_approval_id(self):
        det = {"action": self.DETAIL["action"], "args": dict(self.DETAIL["args"], n="aaaaaaaaaaaa")}
        e1 = {"type": "approval.granted", "data": {"id": "A-77", "args_digest": self.dig()}}
        self.request([e1, dict(e1, data={"id": "A-78", "args_digest": "x"})], detail=det)        # a second event would be signed with no text
        with self.assertRaises(G.Refuse): self.sign()
        os.unlink(os.path.join(self.cfg["pending"], "aaaaaaaaaaaa.json"))
        self.request([{"type": "approval.granted", "data": {"id": "A-77"}}], detail=None)         # no text at all
        try:
            self.sign()
        except G.Refuse as e:
            self.assertIn("ask again", str(e))
        os.unlink(os.path.join(self.cfg["pending"], "aaaaaaaaaaaa.json"))
        self.request([{"type": "approval.granted", "data": {"id": "A-77"}}])
        _, shown = self.sign()
        self.assertIn("APPROVAL: A-77", shown); self.assertIn("ACTION: retag_operator", shown)

    def test_a_deep_ledger_line_never_crashes_the_signer(self):
        """The critic's B1: a planted 3000-deep last ledger line made ledger_tail_seq and consume_matched die with RecursionError."""
        junk = "[" * 3000 + "]" * 3000
        with open(self.cfg["ledger"], "a") as f:
            f.write(junk + "\n")
        self.assertEqual(G.ledger_tail_seq(self.cfg), 2)                          # the last real event, junk skipped
        self.assertEqual(G.consume_matched(self.cfg, [], 2, self.now), [])
        self.assertIsNone(G.parse_line(junk)); self.assertIsNone(G.parse_line("[1]")); self.assertEqual(G.parse_line('{"a":1}'), {"a": 1})
        open(self.cfg["ledger"], "w").write(junk + "\n")
        with self.assertRaises(G.Refuse): G.ledger_tail_seq(self.cfg)
        with self.assertRaises(G.Refuse): G.ledger_id(self.cfg)

    def test_two_requests_naming_the_same_approval_id_refused_and_odd_ids_refused(self):
        e = lambda i: {"type": "approval.granted", "data": {"id": i}}
        self.request([e("A-1")], name="aaaaaaaaaaaa"); self.request([e("A-1")], name="bbbbbbbbbbbb")
        with self.assertRaises(G.Refuse) as c: self.sign()
        self.assertIn("same approval", str(c.exception))
        os.unlink(os.path.join(self.cfg["pending"], "bbbbbbbbbbbb.json"))
        self.request([e("A-1")], name="aaaaaaaaaaaa"); self.sign()                 # one request: fine
        os.unlink(os.path.join(self.cfg["pending"], "aaaaaaaaaaaa.json"))
        self.request([e("not an id\x1b[2J")], name="aaaaaaaaaaaa")
        with self.assertRaises(G.Refuse): self.sign()

    def test_sudo_kill_is_checked_before_anything_else(self):
        import types
        self.assertFalse(G.end_tickets(self.cfg, "/hh", run=lambda c, **k: types.SimpleNamespace(returncode=1)))
        self.assertTrue(G.end_tickets(self.cfg, "/hh", run=lambda c, **k: types.SimpleNamespace(returncode=0)))

    def test_vet_refusal_names_both_devices(self):
        try:
            G.vet_sudo_tty("/dev/ttys000", os.getuid(), 0)
        except G.Refuse as e:
            if "device" in str(e):
                self.assertIn("SUDO_TTY", str(e)); self.assertIn("stdin is", str(e))
        else:
            self.skipTest("/dev/ttys000 passes here")

    def test_open_tty_failure_is_a_refusal(self):
        with self.assertRaises(G.Refuse):
            with G.open_tty("/dev/ttys000", 99999): pass

    def test_tty_matches(self):
        self.assertFalse(G.tty_matches(0, ""))
        self.assertFalse(G.tty_matches(99999, TTY))


class RealTty(unittest.TestCase):
    """0.26.3: the terminal check on real ptys (a stub hid the /dev/tty alias bug in 0.26.2). Skipped only where the sandbox has no pty."""
    def run_in_pty(self, child, feed=b""):
        import pty
        try:
            pid, fd = pty.fork()
        except OSError as e:
            self.skipTest("no pty in this sandbox: " + str(e))
        if pid == 0:
            try:
                os._exit(child())
            except BaseException:
                os._exit(4)
        if feed:
            os.write(fd, feed)
        out = b""
        try:
            while True:
                d = os.read(fd, 100)
                if not d:
                    break
                out += d
        except OSError:
            pass
        _, status = os.waitpid(pid, 0)
        return os.waitstatus_to_exitcode(status), out

    def test_open_tty_on_the_real_sudo_terminal_reads_and_writes(self):
        def child():
            path = os.ttyname(0)                       # what sudo would put in SUDO_TTY
            with G.open_tty(path, os.getuid()) as (tin, tout):
                tout.write("hello\n"); tout.flush()
                return 0 if tin.readline().strip() == "ping" and G.tty_matches(tin.fileno(), path) else 3
        code, out = self.run_in_pty(child, b"ping\n")
        self.assertEqual(code, 0, out)
        self.assertIn(b"hello", out)

    def test_the_dev_tty_alias_never_matches(self):
        def child():
            fd = os.open("/dev/tty", os.O_RDWR)
            return 0 if not G.tty_matches(fd, os.ttyname(0)) else 3      # this was the 0.26.2 bug: ttyname/rdev of the alias differ
        self.assertEqual(self.run_in_pty(child)[0], 0)

    def test_another_pty_named_in_sudo_tty_is_refused(self):
        def child():
            m, s = os.openpty()
            try:
                with G.open_tty(os.ttyname(s), os.getuid()):
                    return 3
            except G.Refuse:
                return 0
        self.assertEqual(self.run_in_pty(child)[0], 0)

    def test_stdin_redirected_is_refused(self):
        def child():
            os.dup2(os.open("/dev/null", os.O_RDONLY), 0)
            try:
                G.vet_sudo_tty("/dev/ttys000", os.getuid(), 0)
                return 3
            except G.Refuse:
                return 0
        self.assertEqual(self.run_in_pty(child)[0], 0)

    def test_wrong_owner_refused(self):
        def child():
            try:
                G.vet_sudo_tty(os.ttyname(0), os.getuid() + 1, 0)
                return 3
            except G.Refuse:
                return 0
        self.assertEqual(self.run_in_pty(child)[0], 0)


class VetSudoTty(unittest.TestCase):
    def test_not_a_terminal_device_refused(self):
        for p in ("", "/dev/tty", "/tmp/x", "/dev/null", "/dev/ttys999999", "/dev/../dev/ttys000"):
            with self.assertRaises(G.Refuse, msg=p):
                G.vet_sudo_tty(p, os.getuid())


if __name__ == "__main__":
    unittest.main()
