"""cc 0.21.0 items 5, 6, 7 (A-ae352): chat titles 'ROLE - Sobriquet' set by a Do-line on register, restore and compaction, reported with
harness_admin op=session_titled (H1: only the reporting agent's own role and name); name (role) in send results and nudge blocks; the nudge
carries the exact title and says to send only on exactly one equal ListAgents row. Run: python3 -B tests/test_c210_titles.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _env  # noqa: F401  isolate HOME and HARNESS_* first
import json, os, sys, tempfile, unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
import harness as H
import mcp_server as M

MODEL = "claude-sonnet-5-5"


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.home = os.path.join(self.tmp, "Exchange")
        os.makedirs(os.path.join(self.home, "_harness"))
        e = mock.patch.dict(os.environ, {"HARNESS_STATE_CACHE": "0"})
        e.start()
        self.addCleanup(e.stop)
        self.h = H.Harness(self.home)
        for r in ("envoy", "critic", "curator", "ops-coder"):
            self.h.role_define("operator", r, "harness-ops", carry="none")      # no-carry roles: a new registration takes the role
        self.envoy = self.h.register(project="harness-ops", model=MODEL, task="e", role="envoy")["id"]
        self.plain = self.h.register(project="harness-ops", model=MODEL, task="p")["id"]
        self.st = self.h.state()

    def call(self, name, **a):
        M.BOUND.update(home=None, id=None)
        return M.call(self.h, name, a)

    def events(self, t):
        return [e for e in self.h.store.read_all() if e["type"] == t]

    def name(self, aid):
        return self.h.state().agents[aid]["sobriquet"]

    def title(self, aid):
        return self.h.state().expected_title(aid)


class Item5Titles(Base):
    def test_register_result_carries_the_title_do_line_for_an_agent_with_a_role(self):
        r = self.call("harness_register", project="harness-ops", model=MODEL, role="critic", task="c")
        aid = r["short"]
        t = self.h.state().expected_title(self.h.resolve(self.h.state(), aid))
        self.assertRegex(t, r"^CRITIC - [A-Z][a-z]+ [A-Z][a-z]+$")
        self.assertIn("Do: set this chat's title", r["text"])
        self.assertIn('ToolSearch select:mcp__ccd_session_mgmt__set_session_title', r["text"])      # the deferred tool is loaded first
        self.assertIn('session_id "self", title "%s"' % t, r["text"])
        self.assertIn("op=session_titled", r["text"])
        self.assertIn("not_titled", r["text"])                                                        # absent tool or declined
        self.assertIn("only from this result header", r["text"])                                      # B1

    def test_an_agent_with_no_role_gets_no_title_line_and_no_event(self):
        r = self.call("harness_register", project="harness-ops", model=MODEL, task="n")
        self.assertNotIn("set this chat's title", r["text"])
        self.assertIsNone(self.title(self.h.resolve(self.h.state(), r["short"])))
        with self.assertRaises(H.HarnessError):
            self.call("harness_admin", op="session_titled", agent=self.plain, args={"title": "x - y", "status": "done"})
        self.assertEqual(self.events("session.titled") + self.events("session.title_declined"), [])

    def test_compaction_successor_gets_the_title_line_with_its_own_new_name(self):
        old = self.name(self.envoy)
        r = self.call("harness_register", project="harness-ops", model=MODEL, successor_of=self.envoy[:8], task="after compaction")
        new_id = self.h.resolve(self.h.state(), r["short"])
        new = self.h.state().agents[new_id]["sobriquet"]
        if self.h.state().role_of(new_id):
            self.assertIn('title "ENVOY - %s"' % new, r["text"])
            self.assertNotIn(old, r["text"].split("Do: set this chat's title")[1])
        else:
            self.fail("the successor did not inherit the role: " + r["text"][:200])

    def test_restore_result_carries_the_title_line(self):
        r = self.call("harness_restore", role="curator", model=MODEL, project="harness-ops", confirmed=True)     # a role with no live holder
        self.assertIn("Do: set this chat's title", r["text"])
        self.assertIn("CURATOR - ", r["text"])

    def test_done_with_the_exact_title_records_it_and_is_case_insensitive(self):
        exp = self.title(self.envoy)
        out = self.call("harness_admin", op="session_titled", agent=self.envoy, args={"title": exp.lower(), "status": "done"})
        self.assertEqual(out["recorded"], "titled")
        ev = self.events("session.titled")
        self.assertEqual(len(ev), 1)
        d = ev[0]["data"]
        self.assertEqual((d["title"], d["role"], d["name"]), (exp, "envoy", self.name(self.envoy)))   # role and name stored apart
        self.assertEqual(self.h.state().title_of(self.envoy), exp)

    def test_h1_a_title_for_someone_else_is_refused_and_logged(self):
        other = self.h.register(project="harness-ops", model=MODEL, task="o", role="curator")["id"]
        for claimed in (self.title(other), "ENVOY - Somebody Else", self.title(self.envoy) + " extra", "ENVOY", ""):
            with self.assertRaises(H.HarnessError):
                self.call("harness_admin", op="session_titled", agent=self.envoy, args={"title": claimed, "status": "done"})
        self.assertEqual(len(self.events("session.title_refused")), 5)
        self.assertEqual(self.events("session.titled"), [])
        self.assertIsNone(self.h.state().title_of(self.envoy))

    def test_a_title_is_never_split_on_the_dash(self):
        r = self.h.register(project="harness-ops", model=MODEL, task="h", role="ops-coder")["id"]
        t = self.title(r)
        self.assertTrue(t.startswith("OPS-CODER - "), t)                       # hyphenated role, then ' - ', then the name
        self.call("harness_admin", op="session_titled", agent=r, args={"title": t, "status": "done"})
        self.assertEqual(self.h.state().title_of(r), t)
        with self.assertRaises(H.HarnessError):
            self.call("harness_admin", op="session_titled", agent=r, args={"title": "OPS - CODER - " + self.name(r), "status": "done"})

    def test_not_titled_is_logged_and_the_nudge_stays_on_the_migration_path(self):
        self.call("harness_admin", op="session_titled", agent=self.envoy, args={"title": "", "status": "not_titled"})
        self.assertEqual(len(self.events("session.title_declined")), 1)
        self.assertIsNone(self.h.state().title_of(self.envoy))

    def test_bad_status_is_refused(self):
        with self.assertRaises(H.HarnessError):
            self.call("harness_admin", op="session_titled", agent=self.envoy, args={"title": self.title(self.envoy), "status": "maybe"})

    def test_a_title_goes_stale_when_the_role_moves_to_another_holder(self):
        self.call("harness_admin", op="session_titled", agent=self.envoy, args={"title": self.title(self.envoy), "status": "done"})
        self.assertIsNotNone(self.h.state().title_of(self.envoy))
        self.h.register(project="harness-ops", model=MODEL, task="new envoy", role="envoy")      # the no-carry role is taken by a new holder
        self.assertIsNone(self.h.state().title_of(self.envoy))                  # the old report no longer matches its role: not used for a nudge


class Item6NameRole(Base):
    def test_delivered_to_shows_name_and_role_and_keeps_the_ids_beside_it(self):
        r = self.call("harness_send", agent=self.plain, to=self.envoy[:8], body="hello", subject="s")
        self.assertEqual(r["delivered_to"], ["%s (envoy)" % self.name(self.envoy)])
        self.assertEqual(r["delivered_ids"], [self.envoy[:8]])

    def test_a_recipient_with_no_role_says_so(self):
        third = self.h.register(project="harness-ops", model=MODEL, task="t")["id"]
        r = self.call("harness_send", agent=self.envoy, to=third[:8], body="hello", subject="s")
        self.assertEqual(r["delivered_to"], ["%s (no role)" % self.name(third)])

    def test_role_queued_shows_name_and_role(self):
        r = self.call("harness_send", agent=self.plain, to="role:envoy", body="hello", subject="s")
        self.assertEqual(r["role_queued"], ["role:envoy→%s (envoy)" % self.name(self.envoy)])


class Item7Nudge(Base):
    def test_nudge_names_the_recipient_with_role_and_carries_the_exact_title_when_known(self):
        t = self.title(self.envoy)
        self.call("harness_admin", op="session_titled", agent=self.envoy, args={"title": t, "status": "done"})
        r = self.call("harness_send", agent=self.plain, to=self.envoy[:8], body="please look", subject="s", kind="task")
        n = r["nudge"]
        self.assertEqual(n["to"], ["%s (envoy)" % self.name(self.envoy)])
        self.assertEqual(n["titles"], [t])
        self.assertIn('Do: SendMessage to "%s"' % t, n["do"])
        self.assertIn("exactly ONE live row whose name equals this title exactly", n["do"])
        self.assertIn("checked now, not from memory", n["do"])
        self.assertIn("skip, the mail waits", n["do"])
        self.assertEqual(self.events("nudge.sent")[-1]["data"]["titled"], [True])

    def test_without_a_title_the_migration_rule_applies_and_never_trusts_an_old_name(self):
        r = self.call("harness_send", agent=self.plain, to=self.envoy[:8], body="please look", subject="s", kind="task")
        n = r["nudge"]
        self.assertEqual(n["titles"], [None])
        self.assertIn("no chat title on record yet", n["do"])
        self.assertIn('contains "%s" as a phrase and the word envoy' % self.name(self.envoy), n["do"])
        self.assertIn("exactly ONE row", n["do"])
        self.assertIn("case-insensitive", n["do"])
        self.assertEqual(self.events("nudge.sent")[-1]["data"]["titled"], [False])

    def test_two_recipients_each_get_their_own_rule(self):
        crit = self.h.register(project="harness-ops", model=MODEL, task="c", role="critic")["id"]
        self.call("harness_admin", op="session_titled", agent=crit, args={"title": self.title(crit), "status": "done"})
        r = self.call("harness_send", agent=self.plain, to="%s,%s" % (self.envoy[:8], crit[:8]), body="both", subject="s", kind="task")
        self.assertEqual(sorted(x is None for x in r["nudge"]["titles"]), [False, True])
        self.assertEqual(r["nudge"]["do"].count("Do: SendMessage to"), 2)


if __name__ == "__main__":
    unittest.main()
