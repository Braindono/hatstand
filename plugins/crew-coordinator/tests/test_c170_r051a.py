"""cc 0.17.0 R-051a: vault writer (deterministic ask extraction, Haiku tags only, verifier, redaction in and out,
purge --vault, failure path). Spec: skill-curation/specs/2026-10-24-stage2-context-loss.md sections 1, 2 and 9.
Run: python3 -B tests/test_c170_r051a.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _env  # noqa: F401  isolate HOME and HARNESS_* first
import json, os, sys, tempfile, time, unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
import harness as H
import mcp_server as M
import transcript_indexer as TI
import vault as V

MODEL = "claude-opus-5-5"
# one planted fake value per redaction pattern -> the substring that must never appear downstream
PLANTED = {
    "anthropic-key": ("sk-ant-" + "Q" * 30, "Q" * 30),
    "openai-key": ("sk-" + "a1" * 12, "a1" * 12),
    "api-key-prefix": ("key-" + "abcdef123456XYZ", "abcdef123456XYZ"),
    "github-token": ("gh" + "p_" + "g" * 24, "g" * 24),   # split: the hatstand push scan reads literals
    "aws-key": ("AKIA" + "ABCDEFGHIJKLMNOP", "AK" + "IAABCDEFGHIJKLMNOP"),
    "google-key": ("AIza" + "B" * 35, "B" * 35),
    "slack-token": ("xoxb-" + "1234567890abc", "1234567890abc"),
    "bearer": ("Bearer " + "c" * 24, "c" * 24),
    "jwt": ("eyJabcdefghij.eyJklmnopqrs.sigabcdefgh", "sigabcdefgh"),
    "private-key": ("-----BEGIN RSA " + "PRIVATE KEY-----\nMIIEowPLANT\n-----END RSA " + "PRIVATE KEY-----", "MIIEowPLANT"),
    "url-credentials": ("https://user:hunter2pass@example.com", "hunter2pass"),
    "secret-assignment": ("password=Sup3rS3cretVal", "Sup3rS3cretVal"),
    "long-hex-or-b64-value": ("mytoken: " + "Z" * 40, "Z" * 40),
    "card": ("4111 1111 1111 1111", "4111 1111 1111 1111"),
    "ssn": ("123-45-6789", "123-45-6789"),
}


def ts(t):
    return time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(t))


def ix_file(blocks, session="s", project="p"):
    """Indexer-format text: [(role, t, text)]. Raw text is written as is (simulates an indexer miss)."""
    out = ["# Transcript %s (%s)\n\n⟦UNTRUSTED⟧\n" % (session, project)]
    for role, t, text in blocks:
        out.append("### %s %s\n%s\n" % (role, ts(t), "\n".join("> " + x for x in text.split("\n"))))
    return "\n".join(out) + "\n"


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.home = os.path.join(self.tmp, "Exchange")
        os.makedirs(os.path.join(self.home, "_harness"))
        self.ixroot = os.path.join(self.tmp, "ix")
        os.makedirs(self.ixroot)
        e = mock.patch.dict(os.environ, {"INDEXER_ROOT": self.ixroot, "HARNESS_STATE_CACHE": "0"})
        e.start()
        self.addCleanup(e.stop)
        self.cfg({"vault": "on"})
        self.h = H.Harness(self.home)
        self.h.role_define("operator", "ops-coder", "harness-ops")
        self.aid = self.h.register(project="harness-ops", model=MODEL)["id"]
        self.h.role_assign("operator", "ops-coder", self.aid)
        self.t0 = time.time() + 2          # asks fall after spawned_at (second resolution)
        self.calls = []

    def cfg(self, d):
        with open(os.path.join(self.home, "_harness", "config.json"), "w") as f:
            json.dump(d, f)

    def bind(self, sid, aid=None):
        self.h.store.append("session.bound", aid or self.aid, {"session_id": sid, "agent": aid or self.aid})

    def put(self, sid, blocks, name=None):
        p = os.path.join(self.ixroot, name or "2026-10-25-proj-%s.md" % sid[:8])
        with open(p, "w") as f:
            f.write(ix_file(blocks, sid))
        return p

    def model(self, reply):
        def fn(prompt, model):
            self.calls.append(prompt)
            return reply(prompt) if callable(reply) else reply
        return fn

    def run_w(self, reply='{"tags":[]}', **kw):
        return V.write(self.h, self.aid, model_fn=self.model(reply), now=self.t0 + 600, **kw)

    def doc(self, r):
        with open(os.path.join(self.home, r["path"])) as f:
            return f.read()


class Privacy(Base):
    def test_planted_key_per_pattern_absent_from_prompt_and_vault(self):
        sid = "aaaaaaaa-1111"
        self.bind(sid)
        blocks = [("operator", self.t0 + i, "please use %s for %s" % (v, k)) for i, (k, (v, _)) in enumerate(PLANTED.items())]
        self.put(sid, blocks)
        r = self.run_w()
        self.assertEqual(r["status"], "written")
        self.assertEqual(r["asks"], len(PLANTED))
        self.assertEqual(len(self.calls), 1)
        d = self.doc(r)
        for k, (_v, secret) in PLANTED.items():
            self.assertNotIn(secret, self.calls[0], k)
            self.assertNotIn(secret, d, k)
        self.assertIn("[redacted:", d)

    def test_end_to_end_from_raw_jsonl_through_indexer(self):
        sid = "bbbbbbbb-2222-3333"
        self.bind(sid)
        src = os.path.join(self.tmp, "src", "proj")
        os.makedirs(src)
        iso = lambda t: time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(t))   # noqa: E731
        lines = [
            {"type": "user", "timestamp": iso(self.t0), "origin": {"kind": "human"},
             "message": {"content": "deploy with token=" + "T" * 30}},
            {"type": "user", "timestamp": iso(self.t0 + 1), "message": {"content": [{"type": "tool_result", "content": "TOOLRESULTSECRET"}]}},
            {"type": "user", "timestamp": iso(self.t0 + 2), "origin": {"kind": "human"}, "message": {"content": "[private] my pin is 4455"}},
            {"type": "assistant", "timestamp": iso(self.t0 + 3), "message": {"content": [{"type": "text", "text": "Done."}]}},
        ]
        with open(os.path.join(src, sid + ".jsonl"), "w") as f:
            f.write("\n".join(json.dumps(x) for x in lines) + "\n")
        with open(os.path.join(self.ixroot, ".allow"), "w") as f:
            f.write(sid + "\n")
        TI.Indexer(root=self.ixroot, cache=os.path.join(self.tmp, "cache"), source=os.path.join(self.tmp, "src"), ledger=False).once()
        r = self.run_w('{"tags":[{"n":1,"tag":"done","reason":"assistant said done"}]}')
        d = self.doc(r)
        self.assertEqual(r["asks"], 1)
        for bad in ("T" * 30, "TOOLRESULTSECRET", "4455"):
            self.assertNotIn(bad, d)
            self.assertNotIn(bad, self.calls[0])
        self.assertIn("[done]", d)

    def test_redaction_raising_skips_file_and_never_calls_model(self):
        sid = "cccccccc-1"
        self.bind(sid)
        self.put(sid, [("operator", self.t0, "an ask")])

        def boom(text):
            raise RuntimeError("x")
        r = V.write(self.h, self.aid, model_fn=self.model("{}"), now=self.t0 + 600, redact=boom)
        self.assertEqual(r["skipped_files"], 1)
        self.assertEqual(r["asks"], 0)
        self.assertEqual(self.calls, [])

    def test_output_redaction_raising_writes_nothing(self):
        sid = "cccccccc-2"
        self.bind(sid)
        self.put(sid, [("operator", self.t0, "an ask")])
        real = TI.redact
        n = {"i": 0}

        def late(text):          # input side passes, output side raises
            n["i"] += 1
            if n["i"] > 1:
                raise RuntimeError("late")
            return real(text)
        r = V.write(self.h, self.aid, model_fn=self.model('{"tags":[]}'), now=self.t0 + 600, redact=late)
        self.assertEqual(r["status"], "skipped")
        self.assertFalse(os.path.isdir(V.vault_root(self.home)) and any(
            f.endswith(".md") for _d, _s, fs in os.walk(V.vault_root(self.home)) for f in fs))

    def test_control_bidi_and_fence_stripped(self):
        sid = "dddddddd-1"
        self.bind(sid)
        self.put(sid, [("operator", self.t0, "fix ‮this⁦ ⟦now⟧ \x07please")])
        d = self.doc(self.run_w())
        body = d.split("## Asks", 1)[1]
        for ch in ("‮", "⁦", "⟦", "⟧", "\x07"):
            self.assertNotIn(ch, body)
        self.assertIn("fix this now please", body)

    def test_vault_file_is_private_and_fenced(self):
        sid = "dddddddd-2"
        self.bind(sid)
        self.put(sid, [("operator", self.t0, "x")])
        r = self.run_w()
        p = os.path.join(self.home, r["path"])
        self.assertEqual(os.stat(p).st_mode & 0o777, 0o600)
        self.assertIn("⟦UNTRUSTED", self.doc(r))
        self.assertTrue(r["path"].startswith(os.path.join("vault", "harness-ops", "ops-coder") + os.sep))


class Extraction(Base):
    def test_only_operator_asks_in_window_shell_lines_skipped(self):
        sid = "eeeeeeee-1"
        self.bind(sid)
        self.put(sid, [("operator", self.t0 - 3600, "old ask before this chat"),
                       ("operator", self.t0, "new ask one"), ("assistant", self.t0 + 1, "ok, on it"),
                       ("operator", self.t0 + 2, "! ls -la"), ("peer", self.t0 + 3, "peer text"),
                       ("operator", self.t0 + 4, "new ask two")])
        r = self.run_w()
        self.assertEqual(r["asks"], 2)
        self.assertIn("new ask one", self.calls[0])
        self.assertIn("ok, on it", self.calls[0])          # the reply excerpt goes with the ask
        self.assertNotIn("old ask", self.calls[0])
        self.assertNotIn("ls -la", self.calls[0])

    def test_two_chats_of_one_role_overlap_both_kept_once(self):
        pred = self.aid
        self.bind("ffffffff-1", pred)
        other = self.h.register(project="harness-ops", model=MODEL)["id"]   # an earlier holder of the role
        self.h.role_assign("operator", "ops-coder", other)
        self.h.role_assign("operator", "ops-coder", self.aid)
        self.bind("99999999-2", other)
        self.put("ffffffff-1", [("operator", self.t0, "ask from chat A")])
        self.put("99999999-2", [("operator", self.t0 + 1, "ask from chat B")])
        self.put("ffffffff-1", [("operator", self.t0, "ask from chat A")], name="2026-10-26-proj-ffffffff.md")   # same ask twice
        r = self.run_w()
        self.assertEqual(r["asks"], 2)
        d = self.doc(r)
        self.assertIn("ask from chat A", d)
        self.assertIn("ask from chat B", d)

    def test_second_write_starts_where_the_last_one_ended(self):
        sid = "abababab-1"
        self.bind(sid)
        self.put(sid, [("operator", self.t0, "first ask")])
        r1 = self.run_w()
        self.assertEqual(r1["asks"], 1)
        self.put(sid, [("operator", self.t0, "first ask"), ("operator", self.t0 + 700, "second ask")])
        r2 = V.write(self.h, self.aid, model_fn=self.model('{"tags":[]}'), now=self.t0 + 1200)
        self.assertEqual(r2["asks"], 1)
        self.assertIn("second ask", self.doc(r2))
        self.assertNotIn("first ask", self.doc(r2).split("## Asks", 1)[1])


class TagsAndVerifier(Base):
    def test_three_fixtures_each_with_a_dropped_ask_are_flagged(self):
        for i in range(3):
            sid = "1234567%d-x" % i
            self.bind(sid)
            self.put(sid, [("operator", self.t0 + 10 * i, "kept ask %d" % i), ("operator", self.t0 + 10 * i + 1, "dropped ask %d" % i)])
        # the model tags the first ask of each pair and silently drops the second
        def reply(prompt):
            n = prompt.count("\n   reply: ")
            return json.dumps({"tags": [{"n": k, "tag": "open"} for k in range(1, n + 1, 2)]})
        r = self.run_w(reply)
        self.assertEqual(r["asks"], 6)
        self.assertEqual(r["untagged"], 3)
        d = self.doc(r)
        for i in range(3):
            self.assertRegex(d, r"\[untagged\][^\n]*\n   > dropped ask %d" % i)

    def test_verifier_rejects_invented_ask_and_unknown_ids(self):
        asks = [{"ts": "t", "session": "s", "text": "real ask", "reply": ""},
                {"ts": "t", "session": "s", "text": "invented ask", "reply": ""},
                {"ts": "t", "session": "s", "text": "real two", "reply": ""}]
        tags = {1: {"tag": "done", "id": "D-00000", "reason": ""}, 3: {"tag": "done", "id": "D-abcde", "reason": ""}}
        rows, c = V.verify(asks, tags, {"s": "real ask\nreal two"}, lambda i: i == "D-abcde")
        self.assertEqual(c["quote"], 1)
        self.assertEqual(c["id"], 1)
        self.assertEqual([r["tag"] for r in rows], ["done", "done"])   # unknown id removed and counted; done needs none (10-25)
        self.assertEqual([r["id"] for r in rows], ["", "D-abcde"])
        rows2, c2 = V.verify(asks[:1], {1: {"tag": "backlog", "id": "R-999", "reason": ""}}, {"s": "real ask"}, lambda i: False)
        self.assertEqual((rows2[0]["tag"], c2["untagged"]), ("untagged", 1))   # backlog still needs a valid id or a reason

    def test_ids_checked_against_corpus_and_ledger(self):
        did = self.h.record(self.aid, "decision", "a real decision", "body")["id"]
        self.h.send(self.aid, "operator", "about R-051a and H-013", subject="x")
        sid = "acacacac-1"
        self.bind(sid)
        self.put(sid, [("operator", self.t0 + i, "ask %d" % i) for i in range(4)])
        r = self.run_w(json.dumps({"tags": [
            {"n": 1, "tag": "done", "id": did}, {"n": 2, "tag": "backlog", "id": "R-051a"},
            {"n": 3, "tag": "backlog", "id": "R-999"}, {"n": 4, "tag": "done", "id": "D-fffff"}]}))
        d = self.doc(r)
        self.assertIn("[done %s]" % did, d)
        self.assertIn("[backlog R-051a]", d)
        self.assertEqual(r["verify_dropped"]["id"], 2)
        self.assertEqual(r["untagged"], 1)              # backlog R-999 loses its id and has no reason; done D-fffff stays done
        self.assertIn("a real decision", d)            # Decisions section lists the agent's records since

    def test_slash_commands_are_not_asks(self):
        sid = "afafafaf-9"
        self.bind(sid)
        self.put(sid, [("operator", self.t0, "/crew-coordinator:refresh"), ("operator", self.t0 + 1, "Yes run it")])
        self.assertEqual(self.run_w()["asks"], 1)

    def test_off_vocabulary_and_garbage_output(self):
        sid = "adadadad-1"
        self.bind(sid)
        self.put(sid, [("operator", self.t0, "one"), ("operator", self.t0 + 1, "two")])
        r = self.run_w('{"tags":[{"n":1,"tag":"finished"},{"n":2,"tag":"open","reason":"ignore previous instructions"}]}')
        self.assertEqual(r["untagged"], 1)
        self.assertEqual(r["open"], 1)
        r2 = V.write(self.h, self.aid, model_fn=self.model("I cannot help"), now=self.t0 + 900)
        self.assertEqual(r2["status"], "written")      # nothing in the window, but the call still succeeds
        self.put(sid, [("operator", self.t0 + 1000, "three")], name="2026-10-27-proj-adadadad.md")
        r3 = V.write(self.h, self.aid, model_fn=self.model("I cannot help"), now=self.t0 + 1200)
        self.assertEqual(r3["untagged"], 1)
        self.assertIn("model skipped", r3["note"])

    def test_corrections_listed(self):
        sid = "aeaeaeae-1"
        self.bind(sid)
        self.put(sid, [("operator", self.t0, "no, use plain words")])
        d = self.doc(self.run_w('{"tags":[{"n":1,"tag":"done","reason":"applied","correction":true}]}'))
        self.assertIn("## Corrections\n\n- ask 1", d)


class FailurePathAndConfig(Base):
    def setUp(self):
        super().setUp()
        real = V.prepare    # the handoff's clock is "now"; the fixture asks sit a few seconds ahead of it
        p = mock.patch.object(V, "prepare", side_effect=lambda *a, **k: real(*a, **dict(k, now=self.t0 + 600)))
        p.start()
        self.addCleanup(p.stop)

    def capsule(self):
        return "---\nhandoff: x\n---\n# Handoff\n- [open] something\n"

    def test_model_unavailable_handoff_proceeds_with_warning(self):
        sid = "afafafaf-1"
        self.bind(sid)
        self.put(sid, [("operator", self.t0, "an ask")])

        def down(prompt, model):
            raise V.ModelUnavailable("not on subscription")
        with mock.patch.object(V, "claude_cli", down):
            out = self.h.handoff(self.aid, self.capsule())
        self.assertIn("message", out)
        self.assertEqual(out["vault"]["status"], "written")
        self.assertIn("not on subscription", out["text"])

    def test_writer_crash_never_blocks_handoff(self):
        with mock.patch.object(V, "prepare", side_effect=KeyError("boom")):
            out = self.h.handoff(self.aid, self.capsule())
        self.assertIn("message", out)
        self.assertEqual(out["vault"]["status"], "skipped")
        self.assertIn("vault writer failed", out["text"])

    def test_config_off_writes_nothing(self):
        self.cfg({"vault": "off"})
        self.assertEqual(self.h.vault_write(self.aid)["status"], "skipped")
        with mock.patch.object(V, "prepare", side_effect=AssertionError("must not run")):
            out = self.h.handoff(self.aid, self.capsule())
        self.assertNotIn("vault", out)

    def test_config_on_runs_at_handoff_before_capsule(self):
        order = []
        with mock.patch.object(V, "prepare", side_effect=lambda *a, **k: (order.append("vault"), {"done": {"status": "written", "asks": 0}})[1]):
            with mock.patch.object(self.h, "record", side_effect=lambda *a, **k: (order.append("capsule"), {"id": "K-00000"})[1]):
                self.h.handoff(self.aid, self.capsule())
        self.assertEqual(order[:2], ["vault", "capsule"])

    def test_dry_run_no_model_no_file(self):
        self.cfg({"vault": "off"})
        sid = "babababa-1"
        self.bind(sid)
        self.put(sid, [("operator", self.t0, "an ask")])
        r = V.write(self.h, self.aid, model_fn=self.model("{}"), dry_run=True, now=self.t0 + 600)
        self.assertEqual(r["status"], "dry-run")
        self.assertEqual(r["asks"], 1)
        self.assertEqual(self.calls, [])
        self.assertFalse(os.path.exists(V.vault_root(self.home)))

    def test_admin_op_dry_run(self):
        r = M.admin(self.h, {"op": "vault_write", "agent": self.aid, "args": {"dry_run": True}})
        self.assertEqual(r["status"], "dry-run")
        with self.assertRaises(H.HarnessError):
            M.admin(self.h, {"op": "vault_write", "agent": self.aid, "args": {"target": "x"}})

    def test_no_role_skipped(self):
        b = self.h.register(project="harness-ops", model=MODEL)["id"]
        self.assertEqual(V.write(self.h, b, model_fn=self.model("{}"))["status"], "skipped")


class ModelRunner(unittest.TestCase):
    def test_refuses_without_claude_ai_login(self):
        calls = []

        def run(argv, **kw):
            calls.append(argv)
            return mock.Mock(returncode=0, stdout=json.dumps({"loggedIn": True, "authMethod": "apiKey"}))
        with self.assertRaises(V.ModelUnavailable):
            V.claude_cli("p", "haiku", run=run)
        self.assertEqual(calls, [["claude", "auth", "status"]])

    def test_isolated_call_without_api_key_env(self):
        seen = {}

        def run(argv, **kw):
            if argv[:3] == ["claude", "auth", "status"]:
                return mock.Mock(returncode=0, stdout=json.dumps({"loggedIn": True, "authMethod": "claude.ai"}))
            seen.update(argv=argv, **kw)
            return mock.Mock(returncode=0, stdout='{"tags":[]}', stderr="")
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-x", "HARNESS_HOME": "/nope"}):
            out = V.claude_cli("the prompt", "haiku", run=run)
        self.assertEqual(out, '{"tags":[]}')
        a = seen["argv"]
        for flag in ("--tools", "--setting-sources", "--strict-mcp-config", "--no-session-persistence"):
            self.assertIn(flag, a)
        self.assertEqual(a[a.index("--tools") + 1], "")
        self.assertEqual(a[a.index("--setting-sources") + 1], "")
        self.assertNotIn("ANTHROPIC_API_KEY", seen["env"])
        self.assertNotIn("HARNESS_HOME", seen["env"])
        self.assertEqual(seen["input"], "the prompt")

    def test_parse_tags_bounds(self):
        t = V.parse_tags('noise {"tags":[{"n":0,"tag":"done"},{"n":2,"tag":"open"},{"n":2,"tag":"done"},{"n":true,"tag":"open"},{"n":9,"tag":"open"}]}', 3)
        self.assertEqual(list(t), [2])
        self.assertEqual(t[2]["tag"], "open")
        with self.assertRaises(ValueError):
            V.parse_tags("no json", 3)


class Purge(Base):
    def test_purge_vault_by_session(self):
        for sid in ("cdcdcdcd-1", "cececece-2"):
            self.bind(sid)
        self.put("cdcdcdcd-1", [("operator", self.t0, "leaky ask")])
        r1 = self.run_w()
        self.put("cececece-2", [("operator", self.t0 + 700, "other ask")])
        # second file drawn only from the other session (the first one's window has passed)
        os.remove(os.path.join(self.ixroot, "2026-10-25-proj-cdcdcdcd.md"))
        r2 = V.write(self.h, self.aid, model_fn=self.model("{}"), now=self.t0 + 1200)
        vroot = V.vault_root(self.home)
        gone = TI.purge_vault("cdcdcdcd-1", vroot=vroot)
        self.assertEqual(gone, [os.path.relpath(os.path.join(self.home, r1["path"]), vroot)])
        self.assertFalse(os.path.exists(os.path.join(self.home, r1["path"])))
        self.assertTrue(os.path.exists(os.path.join(self.home, r1["path"]) + ".purged"))
        self.assertTrue(os.path.exists(os.path.join(self.home, r2["path"])))
        with open(os.path.join(vroot, ".purged.jsonl")) as f:
            line = json.loads(f.readline())
        self.assertNotIn("leaky", json.dumps(line))
        with open(os.path.join(self.home, r1["path"]) + ".purged") as f:
            self.assertNotIn("leaky", f.read())

    def test_purge_cli_needs_yes(self):
        with self.assertRaises(SystemExit):
            TI.main(["purge", "--session", "x", "--vault"])


if __name__ == "__main__":
    unittest.main()
