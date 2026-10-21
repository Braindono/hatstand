"""cc 0.15.0 corpus system v2: write-time role and tier, expiry, pin by citation, owner ack, archive keeps content,
unarchive, threshold key. Run: python3 -B tests/test_corpus_v2.py"""
import json, os, re, sys, tempfile, time, unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
import harness as H
import corpus as C

MODEL = "claude-sonnet-5-5"
REAL_FOUNDATIONS = os.path.normpath(os.path.join(HERE, "..", "..", "..", "..", "orchestration", "FOUNDATIONS.md"))


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.home = os.path.join(self.tmp, "home")
        os.makedirs(self.home)
        self.cache = os.path.join(self.tmp, "cache")
        self._env = mock.patch.dict(os.environ, {"HARNESS_CACHE": self.cache})
        self._env.start()
        self.addCleanup(self._env.stop)
        self.h = H.Harness(self.home)

    def agent(self, role=None, project="orch"):
        if role:
            if role not in self.h.state().roles:
                self.h.role_define("operator", role, project)
        a = self.h.register(project=project, model=MODEL)["id"]
        if role:
            self.h.role_assign("operator", role, a)
        return a

    def row(self, i):
        self.h.corpus.refresh()
        c = self.h.corpus.db.execute("SELECT id,role,tier,expires,superseded_by,tags FROM entries WHERE id=?", (i,))
        return dict(zip(("id", "role", "tier", "expires", "superseded_by", "tags"), c.fetchone()))

    def types(self, t):
        return [e for e in self.h.store.read_all() if e.get("type") == t]


class WriteTime(Base):
    def test_replay_old_log_loads(self):
        # an event written by 0.14.x: no role, tier or expires
        old = {"id": "N-0ld01", "kind": "note", "title": "old note", "body": "from before", "tags": [], "project": "orch",
               "refs": [], "supersedes": None, "offload": False, "sha": "x1", "model": "m"}
        old2 = dict(old, id="D-0ld02", kind="decision", title="old decision", sha="x2")
        a = self.agent()
        self.h.store.append("corpus.recorded", a, old)
        self.h.store.append("corpus.recorded", a, old2)
        for i in ("N-0ld01", "D-0ld02"):
            r = self.row(i)
            self.assertEqual((r["tier"], r["expires"], r["role"]), ("ephemeral", "", ""))
        self.assertEqual(self.h.corpus.due(C.today(400)), [])
        self.assertIn("old note", self.h.recall("old")["text"])

    def test_defaults_tier_expiry(self):
        a = self.agent()
        n = self.h.record(a, "note", "a note")["id"]
        c = self.h.record(a, "context", "a context")["id"]
        d = self.h.record(a, "decision", "a decision")["id"]
        self.assertEqual(self.row(n)["tier"], "ephemeral")
        self.assertEqual(self.row(n)["expires"], C.today(14))
        self.assertEqual(self.row(c)["expires"], C.today(14))
        self.assertEqual((self.row(d)["tier"], self.row(d)["expires"]), ("ephemeral", ""))

    def test_missing_role_unassigned(self):
        a = self.agent()
        i = self.h.record(a, "note", "no role held")["id"]
        self.assertEqual(self.row(i)["role"], "unassigned")
        b = self.agent("writer-role")
        self.assertEqual(self.row(self.h.record(b, "note", "role held")["id"])["role"], "writer-role")
        self.assertEqual(self.row(self.h.record(b, "note", "explicit", role="unassigned")["id"])["role"], "unassigned")

    def test_reject_undefined_role(self):
        a = self.agent("writer-role")
        with self.assertRaises(H.HarnessError) as cm:
            self.h.record(a, "note", "bad role", role="ghost")
        self.assertIn("ghost", str(cm.exception))
        self.assertIn("writer-role", str(cm.exception))   # the defined list
        # a role defined only in a project's ROLES.md counts as defined
        write(os.path.join(self.home, "projects", "orch", "ROLES.md"),
              "## orch\n\n| role | carry |\n| --- | --- |\n| doc-role | full |\n")
        self.assertTrue(self.h.record(a, "note", "from ROLES.md", role="doc-role")["id"])

    def test_foundation_needs_envoy(self):
        a = self.agent("writer-role")
        with self.assertRaises(H.HarnessError):
            self.h.record(a, "note", "foundation try", tier="foundation")
        e = self.agent("corpus-envoy")
        i = self.h.record(e, "note", "foundation ok", tier="foundation")["id"]
        self.assertEqual((self.row(i)["tier"], self.row(i)["expires"]), ("foundation", ""))

    def test_state_note_supersedes(self):
        a = self.agent("writer-role")
        self.h.state_note(a, "first state")
        self.h.state_note(a, "second state")
        ev = self.types("corpus.recorded")
        self.assertEqual([e["data"]["tier"] for e in ev], ["role-state", "role-state"])
        self.assertEqual(ev[1]["data"]["supersedes"], ev[0]["data"]["id"])
        self.assertEqual(self.row(ev[0]["data"]["id"])["superseded_by"], ev[1]["data"]["id"])
        self.assertEqual(self.row(ev[1]["data"]["id"])["expires"], "")


class Expiry(Base):
    def test_pin_exemption(self):
        a = self.agent()
        p = self.h.record(a, "note", "pinned note", "the keep rule line")["id"]
        q = self.h.record(a, "note", "plain note")["id"]
        self.h.pin("operator", [p], reason='"the keep rule line"')
        with mock.patch("time.time", return_value=time.time() + 30 * 86400):
            self.assertEqual(self.h.corpus.due(), [q])

    def test_foundations_replaces_archivable(self):
        if not os.path.exists(REAL_FOUNDATIONS):
            self.skipTest("real FOUNDATIONS.md not found")
        with open(REAL_FOUNDATIONS, encoding="utf-8") as f:
            txt = f.read()
        rep = set(C.IDRE.findall(re.search(r"^replaces:(.*)$", txt, re.M).group(1)))
        self.assertEqual(len(rep), 16)
        write(os.path.join(self.home, "projects", "orchestration", "FOUNDATIONS.md"), txt)
        a = self.agent()
        for n, i in enumerate(sorted(rep)):
            self.h.store.append("corpus.recorded", a, {"id": i, "kind": "note", "title": f"replaced {n}", "body": "", "tags": [],
                                "project": "orch", "refs": [], "supersedes": None, "offload": False, "sha": f"r{n}",
                                "model": "m", "role": "unassigned", "tier": "ephemeral", "expires": "2000-01-01"})
        self.assertFalse(self.h.corpus.foundation_cited() & rep)
        self.assertEqual(set(self.h.corpus.due()), rep)

    def test_citation_pins_unless_replaced(self):
        a = self.agent()
        keep = self.h.record(a, "note", "cited in body")["id"]
        gone = self.h.record(a, "note", "listed in replaces")["id"]
        write(os.path.join(self.home, "projects", "orch", "FOUNDATIONS.md"),
              f"---\ndoc: foundations\nreplaces: {gone}\n---\n# F\n- rule [{keep}] and provenance [{gone}]\n")
        with mock.patch("time.time", return_value=time.time() + 30 * 86400):
            self.assertEqual(self.h.corpus.due(), [gone])

    def test_due_flag_only(self):
        a = self.agent()
        n = self.h.record(a, "note", "will be due")["id"]
        with mock.patch("time.time", return_value=time.time() + 20 * 86400):
            self.assertEqual(self.h.corpus.due(), [n])
            self.assertIn(" due", self.h.recall("will be due")["text"])
        self.assertEqual(self.h.corpus.due(), [])
        self.assertEqual(self.row(n)["superseded_by"], "")   # still live and searchable
        self.assertEqual(self.types("corpus.archived"), [])

    def test_threshold_key_and_default(self):
        a = self.agent()
        self.assertEqual(self.row(self.h.record(a, "note", "default days")["id"])["expires"], C.today(14))
        write(os.path.join(self.home, "OPERATOR-PREFERENCES.md"), "- corpus-expiry-days: 3\n")
        self.assertEqual(self.row(self.h.record(a, "note", "three days")["id"])["expires"], C.today(3))
        write(os.path.join(self.home, "OPERATOR-PREFERENCES.md"), "- corpus-expiry-days: soon\n")
        self.assertEqual(self.row(self.h.record(a, "note", "bad value")["id"])["expires"], C.today(14))


class Archive(Base):
    def test_decision_archive_needs_owner_ack(self):
        owner = self.agent("writer-role")
        steward = self.agent("corpus-steward")
        other = self.agent("someone-else")
        d = self.h.record(owner, "decision", "owned decision", "the rule line here")["id"]
        reason = '"the rule line here"'
        with self.assertRaises(H.HarnessError):
            self.h.archive(steward, [d], reason)
        with self.assertRaises(H.HarnessError):
            self.h.archive(other, [d], reason)
        ack = self.h.send(owner, steward, f"ack archive {d}")["id"]
        self.assertEqual(self.h.archive(steward, [d], reason, ack=ack)["archived"], [d])
        # no recorded role: the corpus-envoy is owner
        envoy = self.agent("corpus-envoy")
        u = self.h.record(self.agent(), "decision", "orphan decision", "unowned rule line")["id"]
        with self.assertRaises(H.HarnessError):
            self.h.archive(steward, [u], '"unowned rule line"', ack=ack)   # ack is from the wrong role
        self.assertEqual(self.h.archive(envoy, [u], '"unowned rule line"')["archived"], [u])
        # the operator is its own approval
        v = self.h.record(owner, "decision", "another one", "operator rule line")["id"]
        self.assertEqual(self.h.archive("operator", [v], '"operator rule line"')["archived"], [v])

    def test_ack_must_name_the_id_and_postdate_the_entry(self):   # R2
        owner = self.agent("writer-role")
        steward = self.agent("corpus-steward")
        old = self.h.send(owner, steward, "unrelated owner message")["id"]
        da = self.h.record(owner, "decision", "dec a", "rule line a one")["id"]
        db = self.h.record(owner, "decision", "dec b", "rule line b two")["id"]
        with self.assertRaises(H.HarnessError):   # unrelated owner message
            self.h.archive(steward, [da], '"rule line a one"', ack=old)
        named_a = self.h.send(owner, steward, f"ack archive {da}")["id"]
        with self.assertRaises(H.HarnessError):   # names only D-a, does not cover D-b
            self.h.archive(steward, [db], '"rule line b two"', ack=named_a)
        self.assertEqual(self.h.archive(steward, [da], '"rule line a one"', ack=named_a)["archived"], [da])

    def _archived_note(self):
        a = self.agent()
        i = self.h.record(a, "note", "keep me", "body text kept intact")["id"]
        self.h.archive("operator", [i], '"body text kept intact"')
        return i

    def test_archive_keeps_content_and_manifest(self):
        i = self._archived_note()
        wk = os.path.join(self.home, "_archive", "corpus", time.strftime("%G-W%V", time.gmtime()))
        with open(os.path.join(wk, i + ".md"), encoding="utf-8") as f:
            self.assertIn("body text kept intact", f.read())
        with open(os.path.join(wk, "manifest.jsonl"), encoding="utf-8") as f:
            m = [json.loads(l) for l in f]
        self.assertEqual([(x["id"], x["title"], x["tier"]) for x in m], [(i, "keep me", "ephemeral")])
        self.assertTrue(m[0]["reason"] and m[0]["date"])
        self.assertEqual(self.h.recall("keep me")["text"].split("\n")[0].split(" · ")[0], "0 hit(s)")

    def test_recall_archived_by_id(self):
        i = self._archived_note()
        t = self.h.recall(ids=[i])["text"]
        self.assertIn("body text kept intact", t)
        self.assertIn("ARCHIVED", t)

    def test_unarchive_round_trip(self):
        i = self._archived_note()
        r = self.h.unarchive("operator", [i])
        self.assertEqual(r["unarchived"], [i])
        self.assertEqual(len(self.types("corpus.unarchived")), 1)
        row = self.row(i)
        self.assertEqual((row["superseded_by"], row["expires"]), ("", C.today(14)))
        self.assertIn("keep me", self.h.recall("keep me")["text"])
        d = self.h.record(self.agent(), "decision", "dec back", "decision rule line")["id"]
        self.h.archive("operator", [d], '"decision rule line"')
        self.h.unarchive("operator", [d])
        self.assertEqual((self.row(d)["superseded_by"], self.row(d)["expires"]), ("", ""))

    def test_unarchive_noop_live(self):
        a = self.agent()
        i = self.h.record(a, "note", "still live")["id"]
        n = len(self.h.store.read_all())
        r = self.h.unarchive("operator", [i])
        self.assertIn("no-op", r["text"])
        self.assertEqual(r["unarchived"], [])
        self.assertEqual(len(self.h.store.read_all()), n)

    def test_unarchive_noop_unknown(self):
        n = len(self.h.store.read_all())
        r = self.h.unarchive("operator", ["N-nope1"])
        self.assertIn("no-op", r["text"])
        self.assertIn("unknown", r["text"])
        self.assertEqual(len(self.h.store.read_all()), n)


if __name__ == "__main__":
    unittest.main()
