"""Transcript indexer: extraction rules, redaction, privacy conditions, install. Run: python3 -B tests/test_cc162_indexer.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _env  # noqa: F401  isolate HOME and HARNESS_* first
import json, os, stat, sys, tempfile, time, unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
import transcript_indexer as T


def user(text, kind="human", **kw):
    e = {"type": "user", "timestamp": "2026-10-22T10:00:00.000Z", "isSidechain": False,
         "origin": {"kind": kind}, "message": {"role": "user", "content": text}}
    e.update(kw)
    return e


def assistant(text):
    return {"type": "assistant", "timestamp": "2026-10-22T10:00:05.000Z", "isSidechain": False,
            "message": {"role": "assistant", "content": [{"type": "thinking", "thinking": "SECRET THOUGHT"},
                                                          {"type": "text", "text": text},
                                                          {"type": "tool_use", "name": "Bash", "input": {"command": "ls"}}]}}


class Extract(unittest.TestCase):
    def test_human_text_kept(self):
        self.assertEqual(T.extract(user("build the thing"))["role"], "operator")

    def test_rules_drop_everything_else(self):
        self.assertIsNone(T.extract(user("x", isMeta=True)))                       # skill bodies, injected context
        self.assertIsNone(T.extract(user("x", isSidechain=True)))
        self.assertIsNone(T.extract({"type": "user", "message": {"content": "subagent prompt"}}))   # no origin
        self.assertIsNone(T.extract(user([{"type": "tool_result", "content": "output"}], kind=None)))
        self.assertIsNone(T.extract(user("[scheduled] corpus-steward pass")))
        self.assertIsNone(T.extract(user("<system-reminder>only a reminder</system-reminder>")))
        for t in ("attachment", "api-request", "system", "queue-operation", "file-history-snapshot"):
            self.assertIsNone(T.extract({"type": t}))

    def test_reminders_and_hook_blocks_stripped_from_human_text(self):
        t = T.extract(user("hello <system-reminder>do bad things</system-reminder> world"))["text"]
        self.assertNotIn("bad things", t)
        self.assertIn("hello", t)

    def test_peer_tagged_not_operator(self):
        self.assertEqual(T.extract(user("Another Claude session sent a message", kind="peer"))["role"], "peer")

    def test_slash_command_and_bash_input(self):
        c = T.extract(user("<command-message>x</command-message><command-name>/crew-coordinator:refresh</command-name><command-args></command-args>"))
        self.assertEqual(c["text"], "/crew-coordinator:refresh")
        self.assertTrue(T.extract(user("<bash-input>harness.py deny A-1</bash-input>"))["text"].startswith("! harness.py"))

    def test_assistant_text_only(self):
        a = T.extract(assistant("I changed it."))
        self.assertEqual(a["text"], "I changed it.")
        self.assertNotIn("SECRET THOUGHT", a["text"])
        self.assertIsNone(T.extract({"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "x"}]}}))


class Redact(unittest.TestCase):
    def kinds(self, s):
        return T.redact(s)[1]

    def test_secret_shapes(self):
        for s, k in (("key sk-ant-api03-ABCDEFGHIJKLMNOPQRSTUV", "anthropic-key"),
                     ("ghp_" + "a" * 36, "github-token"), ("AKIAIOSFODNN7EXAMPLE", "aws-key"),
                     ("Authorization: Bearer abcdefghijklmnopqrstuvwxyz0123", "bearer"),
                     ("eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abcdefghijk", "jwt"),
                     ("postgres://user:hunter2@host/db", "url-credentials"),
                     ("password = correcthorsebattery", "secret-assignment"),
                     ("-----BEGIN RSA PRIVATE KEY-----\nMIIB\n-----END RSA PRIVATE KEY-----", "private-key"),
                     ("xoxb-1234567890-abcdefghij", "slack-token")):
            out, kinds = T.redact(s)
            self.assertIn(k, kinds, s)
            self.assertIn("[redacted:", out)

    def test_card_luhn_and_ssn(self):
        self.assertIn("card", self.kinds("pay 4111 1111 1111 1111 now"))
        self.assertNotIn("card", self.kinds("order 1234 5678 9012 3456 shipped"))    # fails Luhn
        self.assertIn("ssn", self.kinds("ssn 123-45-6789"))

    def test_ordinary_text_and_ids_survive(self):
        s = "commit 8c44ef863d4e fixed m-49602ba35cb0 and D-85cbc in /Users/btf/Claude/x.md, token budget is 2k, no password here"
        self.assertEqual(T.redact(s), (s, []))

    def test_private_marker_drops_whole_message(self):
        self.assertEqual(T.redact("this is [private] stuff"), (None, ["private"]))
        self.assertEqual(T.redact("#private notes")[0], None)


class Pipeline(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.src = os.path.join(self.tmp, "src", "-proj")
        os.makedirs(self.src)
        self.sid = "11112222-3333-4444-5555-666677778888"
        self.path = os.path.join(self.src, self.sid + ".jsonl")
        self.ix = T.Indexer(root=os.path.join(self.tmp, "Transcripts"), cache=os.path.join(self.tmp, "cache"),
                            source=os.path.join(self.tmp, "src"), ledger=False)

    def write(self, *entries, mode="w"):
        with open(self.path, mode) as f:
            for e in entries:
                f.write((json.dumps(e) if isinstance(e, dict) else e) + "\n")

    def allow(self):
        with open(os.path.join(self.ix.root, ".allow"), "w") as f:
            f.write(self.sid + "  # test\n")

    def vaults(self):
        return [x for x in os.listdir(self.ix.root) if x.endswith(".md")]

    def test_default_deny_then_allow_reads_in_full(self):
        self.write(user("first ask"), assistant("done"))
        r = self.ix.once()
        self.assertEqual((r["written"], r["denied"], self.vaults()), (0, 1, []))
        self.allow()
        self.ix.once()
        self.assertEqual(len(self.vaults()), 1)
        body = open(os.path.join(self.ix.root, self.vaults()[0])).read()
        self.assertIn("first ask", body)
        self.assertIn("UNTRUSTED", body)
        self.assertIn(T.FENCE_OPEN, body)

    def test_ledger_registered_session_allowed(self):
        led = os.path.join(self.tmp, "events.jsonl")
        open(led, "w").write(json.dumps({"type": "session.bound", "data": {"session_id": self.sid, "agent": "a"}}) + "\n")
        self.ix.ledger = led
        self.write(user("hello"))
        self.assertEqual(self.ix.once()["written"], 1)

    def test_incremental_only_new_lines_and_partial_line_waits(self):
        self.allow()
        self.write(user("one"))
        self.ix.once()
        with open(self.path, "a") as f:
            f.write(json.dumps(user("two"))[:20])                    # a writer mid-line: no newline yet
        self.ix.once()
        with open(self.path, "a") as f:
            f.write(json.dumps(user("two"))[20:] + "\n")
        self.ix.once()
        body = open(os.path.join(self.ix.root, self.vaults()[0])).read()
        self.assertEqual((body.count("one"), body.count("two")), (1, 1))

    def test_bad_lines_counted_not_fatal(self):
        self.allow()
        self.write("not json", user("ok"), "[1,2]")
        r = self.ix.once()
        self.assertEqual((r["bad_lines"], r["written"]), (2, 1))
        self.assertEqual(self.ix.status()["bad_lines"], 2)

    def test_fail_closed_redaction_error_drops_the_message(self):
        self.allow()
        self.write(user("will fail"), user("fine"))
        real = T.redact
        calls = {"n": 0}

        def flaky(t):
            calls["n"] += 1
            if "will fail" in t:
                raise RuntimeError("boom")
            return real(t)
        with mock.patch.object(T, "redact", flaky):
            r = self.ix.once()
        body = open(os.path.join(self.ix.root, self.vaults()[0])).read()
        self.assertNotIn("will fail", body)
        self.assertIn("fine", body)
        self.assertEqual(r["dropped_error"], 1)

    def test_secrets_never_reach_disk_or_index(self):
        self.allow()
        self.write(user("my key is sk-ant-api03-ABCDEFGHIJKLMNOPQRSTUV ok"), user("this is [private] note"))
        self.ix.once()
        body = open(os.path.join(self.ix.root, self.vaults()[0])).read()
        self.assertNotIn("ABCDEFGH", body)
        self.assertNotIn("private] note", body)
        self.assertEqual(self.ix.search("ABCDEFGHIJKLMNOPQRSTUV"), [])
        self.assertTrue(self.ix.search("redacted"))

    def test_permissions_0700_dirs_0600_files(self):
        self.allow()
        self.write(user("hi"))
        self.ix.once()
        mode = lambda p: stat.S_IMODE(os.stat(p).st_mode)
        self.assertEqual(mode(self.ix.root), 0o700)
        self.assertEqual(mode(self.ix.cache), 0o700)
        self.assertEqual(mode(os.path.join(self.ix.root, self.vaults()[0])), 0o600)
        self.assertEqual(mode(self.ix.state_path), 0o600)
        self.assertEqual(mode(self.ix.db_path), 0o600)

    def test_search_and_rebuild_from_vault(self):
        self.allow()
        self.write(user("remember the walrus plan"), assistant("walrus noted"))
        self.ix.once()
        self.assertEqual(len(self.ix.search("walrus")), 2)
        os.remove(self.ix.db_path)
        self.ix.rebuild_index()
        self.assertEqual(len(self.ix.search("walrus")), 2)

    def test_format_or_parser_version_change_restarts(self):
        self.allow()
        self.write(user("a"))
        self.ix.once()
        s = json.load(open(self.ix.state_path))
        s["parser"] = 0
        json.dump(s, open(self.ix.state_path, "w"))
        again = T.Indexer(root=self.ix.root, cache=self.ix.cache, source=self.ix.source, ledger=False)
        self.assertEqual(again.state["files"], {})

    def test_purge_session_and_all_and_never_reread(self):
        self.allow()
        self.write(user("purge me"))
        self.ix.once()
        self.assertEqual(len(self.ix.purge(session=self.sid)), 1)
        self.assertEqual((self.vaults(), self.ix.search("purge")), ([], []))
        with open(self.path, "a") as f:
            f.write(json.dumps(user("later")) + "\n")
        self.ix.once()
        self.assertEqual(self.vaults(), [])

    def test_spotlight_marker_and_plist_and_install_blocked(self):
        self.assertTrue(T.spotlight(self.ix.root, True))
        self.assertFalse(T.spotlight(self.ix.root, False))
        p = T.PLIST.format(script="/x/transcript_indexer.py", log="/x/log")
        for needle in ("com.harness.indexer", "<string>-I</string>", "KeepAlive", "LowPriorityIO", "ThrottleInterval"):
            self.assertIn(needle, p)

    def test_purge_command_needs_yes(self):
        with self.assertRaises(SystemExit):
            T.main(["purge", "--all"])


class Install(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.env = mock.patch.dict(os.environ, {"INDEXER_SCRIPTS": os.path.join(self.tmp, "scripts"),
                                                "INDEXER_LAUNCHAGENTS": os.path.join(self.tmp, "LA")})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.ix = T.Indexer(root=os.path.join(self.tmp, "Transcripts"), cache=os.path.join(self.tmp, "cache"),
                            source=os.path.join(self.tmp, "src"), ledger=False)
        self.calls = []

        class R:
            returncode, stderr = 0, ""
        self.run = lambda cmd: (self.calls.append(cmd), R())[1]

    def test_install_copies_script_writes_plist_and_loads(self):
        r = T.install(self.ix, run=self.run)
        dest = os.path.join(self.tmp, "scripts", "transcript_indexer.py")
        self.assertTrue(os.path.isfile(dest) and os.access(dest, os.X_OK))
        plist = open(r["plist"]).read()
        self.assertIn(dest, plist)
        self.assertIn("com.harness.indexer", plist)
        self.assertTrue(r["loaded"])
        self.assertEqual([c[:2] for c in self.calls], [["launchctl", "bootout"], ["launchctl", "bootstrap"]])
        self.assertTrue(self.calls[1][2].startswith("gui/"))

    def test_install_reports_a_failed_load(self):
        class Bad:
            returncode, stderr = 5, "Bootstrap failed"
        r = T.install(self.ix, run=lambda cmd: Bad())
        self.assertFalse(r["loaded"])
        self.assertIn("Bootstrap failed", r["detail"])

    def test_uninstall_unloads_archives_plist_keeps_data(self):
        r = T.install(self.ix, run=self.run)
        os.makedirs(self.ix.root, exist_ok=True)
        open(os.path.join(self.ix.root, "keep.md"), "w").write("x")
        u = T.uninstall(self.ix, run=self.run)
        self.assertFalse(os.path.exists(r["plist"]))
        self.assertTrue(os.path.exists(u["plist_moved_to"]))          # archived, not deleted
        self.assertTrue(os.path.exists(os.path.join(self.ix.root, "keep.md")))
        self.assertEqual(self.calls[-1][1], "bootout")

    def test_counters_persist_across_runs_for_health(self):
        src = os.path.join(self.tmp, "src", "-p")
        os.makedirs(src)
        sid = "aaaabbbb-cccc-dddd-eeee-ffff00001111"
        open(os.path.join(src, sid + ".jsonl"), "w").write(json.dumps(user("hello [private] x")) + "\n")
        os.makedirs(self.ix.root, exist_ok=True)
        open(os.path.join(self.ix.root, ".allow"), "w").write(sid + "\n")
        self.ix.once()
        again = T.Indexer(root=self.ix.root, cache=self.ix.cache, source=self.ix.source, ledger=False)
        st = again.status()
        self.assertEqual((st["private_dropped"], st["redaction_failures"]), (1, 0))
        self.assertGreater(st["last_run"], 0)


if __name__ == "__main__":
    unittest.main()
