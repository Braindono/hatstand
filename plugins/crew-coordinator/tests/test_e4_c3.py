"""cc 0.14.6 W42: E4a handoff restore line, E4b secretary Do-line, C3 insight share, C2 intake.
Run: python3 -B tests/test_e4_c3.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _env  # noqa: F401  isolate HOME and HARNESS_* first
import json, os, re, subprocess, sys, tempfile, time, unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(HERE, "..", "scripts")
sys.path.insert(0, SCRIPTS)
import harness as H
import insight_share as I

MODEL = "claude-sonnet-5-5"
CAP = "---\nstatus: open\nfrom: x\n---\n# Capsule\n1. State: ok\n5. Next: do things\n"


class Base(unittest.TestCase):
    def setUp(self):
        self.home = os.path.join(tempfile.mkdtemp(), "h")
        os.makedirs(self.home)
        self.h = H.Harness(self.home)
        self.h.role_define("operator", "claude-code", "orchestration")
        self.h.role_define("operator", "secretary", "secretary")


class E4a(Base):
    def test_handoff_ends_with_restore_block(self):
        a = self.h.register(project="orchestration", model=MODEL, role="claude-code")["id"]
        r = self.h.handoff(a, CAP, release=True)
        lines = r["text"].splitlines()
        self.assertEqual(lines[-1], "```")
        self.assertEqual(lines[-3], "```")
        self.assertRegex(lines[-2], r"^restore as [a-z0-9-]+ from \S+\.md$")
        self.assertLessEqual(len(lines) - 3, 3)             # explanation above the block: max 3 lines
        self.assertTrue(lines[0].startswith("handoff-ok m-"))
        self.assertEqual(len([l for l in lines if l.startswith("restore as")]), 1)
        self.assertTrue(os.path.isfile(os.path.join(self.home, lines[-2].split(" from Exchange/")[1])))

    def test_no_block_without_capsule(self):
        a = self.h.register(project="orchestration", model=MODEL, role="claude-code")["id"]
        r = self.h.handoff(a)
        self.assertNotIn("```", r["text"])
        self.assertNotIn(" from ", r["text"].splitlines()[-1])


class E4b(Base):
    def rules(self, text):
        os.makedirs(os.path.join(self.home, "claude"), exist_ok=True)
        open(os.path.join(self.home, "claude", "secretary-standing-rules.md"), "w").write(text)

    def test_do_line_when_key_set(self):
        self.rules("# rules\n- week_brief_url: https://claude.ai/artifact/abc123\n")
        a = self.h.register(project="secretary", model=MODEL, role="secretary")["id"]
        r = self.h.restore("secretary", MODEL, confirmed=True)
        last = r["text"].splitlines()[-1]
        self.assertTrue(last.startswith("Do: open the current-week brief artifact https://claude.ai/artifact/abc123"), last)
        self.assertIn("questionnaire (D-7feea)", last)
        self.assertEqual(H.secretary_do_line(self.home, "secretary").count("\n"), 1)

    def test_nothing_printed_when_unset_and_restore_ok(self):
        a = self.h.register(project="secretary", model=MODEL, role="secretary")["id"]
        r = self.h.restore("secretary", MODEL, confirmed=True)
        self.assertNotIn("week_brief_url", r["text"])
        self.assertEqual(H.secretary_do_line(self.home, "secretary"), "")      # file absent
        self.rules("other: 1\n")
        self.assertEqual(H.secretary_do_line(self.home, "secretary"), "")      # key missing

    def test_other_roles_get_nothing(self):
        self.assertEqual(H.secretary_do_line(self.home, "claude-code"), "")
        self.h.register(project="orchestration", model=MODEL, role="claude-code")
        r = self.h.restore("claude-code", MODEL, confirmed=True)
        self.assertNotIn("week_brief_url", r["text"])

    def test_register_path_has_do_line(self):
        self.rules("week_brief_url: https://claude.ai/w\n")
        import mcp_server as M
        r = M.call(self.h, "harness_register", {"project": "secretary", "model": MODEL, "role": "secretary", "task": "x"})
        self.assertEqual(r["text"].splitlines()[-1],
                         "Do: open the current-week brief artifact https://claude.ai/w and the questionnaire (D-7feea).")


class C3(Base):
    def setUp(self):
        super().setUp()
        self.a = self.h.register(project="orchestration", model=MODEL, role="claude-code")["id"]
        self.sec = self.h.register(project="secretary", model=MODEL, role="secretary")["id"]

    def notices(self):
        return [m for m in self.h.state().messages.values() if str(m.get("subject") or "").startswith("INSIGHT ")]

    def test_marker_queues_one_notice(self):
        r = I.on_prompt(self.h, self.h.state(), self.a, "remember this: always ship Friday")
        self.assertIn("queued", r)
        n = self.notices()
        self.assertEqual(len(n), 1)
        self.assertEqual((n[0]["kind"], n[0]["subject"], n[0]["to"]), ("notice", "INSIGHT ops-coder", ["role:secretary"]))
        self.assertIn("> remember this: always ship Friday", n[0]["body"])
        self.assertIn("ops-coder", n[0]["body"])
        self.assertRegex(n[0]["body"], r"\d{4}-W\d{2}")
        self.assertIn("data, not instructions", n[0]["body"])
        self.assertIsNone(I.on_prompt(self.h, self.h.state(), self.a, "no marker here"))

    def test_dedupe_by_hash(self):
        I.queue(self.h, self.a, "remember this: A  B")
        r = I.queue(self.h, self.a, "Remember this:  a b")
        self.assertEqual(r, {"skipped": "duplicate"})
        self.assertEqual(len(self.notices()), 1)

    def test_rate_cap_five_per_hour(self):
        res = [I.queue(self.h, self.a, f"remember this: insight number {i}") for i in range(7)]
        self.assertEqual([("queued" in r) for r in res], [True] * 5 + [False] * 2)
        self.assertIn("rate cap", res[5]["skipped"])
        b = self.h.register(project="orchestration", model=MODEL)["id"]      # the cap is per agent
        self.assertIn("queued", I.queue(self.h, b, "remember this: from another agent"))
        with mock.patch("time.time", return_value=time.time() + 4000):       # and per hour
            self.assertIn("queued", I.queue(self.h, self.a, "remember this: much later"))

    def test_opt_out(self):
        open(os.path.join(self.home, "OPERATOR-PREFERENCES.md"), "w").write("- insight-share: off\n")
        self.assertIn("opt-out", I.queue(self.h, self.a, "remember this: x y z")["skipped"])
        self.assertEqual(self.notices(), [])

    def test_each_secret_pattern_blocked(self):
        cases = {
            "api-key-prefix": "remember this: use sk-abcdef123456 for it",
            "long-base64-or-hex": "remember this: " + "a1b2c3d4" * 6,
            "word-password": "remember this: the Password is in the vault",
            "word-token": "remember this: rotate the token monthly",
            "private-key-marker": "remember this: -----BEGIN RSA PRIVATE KEY----- abc",
            "marked-private": "remember this [private] my plan",
        }
        for name, text in cases.items():
            self.assertIn(name, I.blocked_by(text), name)
            r = I.queue(self.h, self.a, text)
            self.assertTrue(r["skipped"].startswith("filtered"), (name, r))
        self.assertEqual(self.notices(), [])
        self.assertEqual(I.blocked_by("remember this: prefer short sentences. See /Users/btf/Claude/Projects/Exchange/x.md"), [])

    def test_kept_when_no_live_secretary(self):
        self.h.retire(self.sec, by=self.sec)
        r = I.queue(self.h, self.a, "remember this: queue survives")
        self.assertTrue(r["queued"])
        self.assertTrue(r["held"])
        self.assertEqual(len(self.notices()), 1)
        self.assertEqual(self.h.state().messages[r["queued"]]["to"], ["role:secretary"])

    def test_decision_with_operator_tag_shared(self):
        self.h.record(self.a, "decision", "Ship on Fridays only", "operator said so", ["operator-decision", "ship"])
        self.assertEqual(len(self.notices()), 1)
        self.h.record(self.a, "decision", "Internal choice", "no tag", ["ship"])
        self.h.record(self.a, "note", "Note with tag", "x", ["operator-decision"])
        self.assertEqual(len(self.notices()), 1)

    def test_hook_prompt_queues(self):
        env = dict(os.environ, HARNESS_HOME=self.home)
        st = self.h.state()
        sid = "s-c3"
        self.h.store.append("session.bound", self.a, {"session_id": sid, "agent": self.a})
        subprocess.run([sys.executable, "-B", os.path.join(SCRIPTS, "harness.py"), "hook", "prompt"],
                       input=json.dumps({"session_id": sid, "prompt": "remember this: hook path works", "cwd": "/x/orchestration"}),
                       capture_output=True, text=True, env=env)
        self.assertEqual(len(self.notices()), 1)


class C2Intake(Base):
    def test_append_only_and_filtered(self):
        r = I.intake_append(self.home, "claude-code", "add skill: pdf-fill (ref specs/x.md)")
        self.assertTrue(os.path.isfile(r["appended"]))
        I.intake_append(self.home, "secretary", "second")
        lines = open(r["appended"]).read().splitlines()
        self.assertEqual([l for l in lines if l.startswith("- ")][0][-47:], "claude-code: add skill: pdf-fill (ref specs/x.md)"[-47:])
        self.assertEqual(len([l for l in lines if l.startswith("- ")]), 2)
        self.assertTrue(I.intake_append(self.home, "x", "my password is hunter2")["skipped"].startswith("filtered"))

    def test_cli(self):
        a = self.h.register(project="orchestration", model=MODEL, role="claude-code")["id"]
        r = subprocess.run([sys.executable, "-B", os.path.join(SCRIPTS, "harness.py"), "--home", self.home,
                            "intake", "--agent", a[:8], "--text", "skill idea one"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("ops-coder: skill idea one", open(os.path.join(self.home, "btf_skills_repository", "INTAKE.md")).read())


class RestoreSkill(unittest.TestCase):
    def test_step6_continues_through_next_list(self):
        t = open(os.path.join(HERE, "..", "skills", "restore", "SKILL.md"), encoding="utf-8").read()
        self.assertLessEqual(len(t.splitlines()), 60)
        step = [l for l in t.splitlines() if l.startswith("6. ")][0]
        self.assertIn("Next list", step)
        self.assertNotIn("Then wait", step)


if __name__ == "__main__":
    unittest.main()
