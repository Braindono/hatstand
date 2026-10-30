"""cc 0.21.0 item 9 (A-5a989, D-6385f): hatstand_guard structural rule, private terms and fail-closed. Every planted file is written at run time
from a synthetic home and a synthetic terms list; no file in the package carries a refused key, a role-state value or a private term.
Run: python3 -B tests/test_c210_guard.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _env  # noqa: F401  isolate HOME and HARNESS_* first
import json, os, shutil, subprocess, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(HERE, "..", "scripts")
sys.path.insert(0, SCRIPTS)
import hatstand_guard as G

TERMS = ["# synthetic private terms for the tests", "zorgblat", "frobnitz-widgets", "quux interview"]
RS = "role-state" + ":dreamer:some-intro"           # built here so this file itself carries no role-state value
MAP = "map" + "ping"                                  # likewise for the structural key


def make_home(terms=TERMS, ledger=True, terms_file=True):
    home = tempfile.mkdtemp()
    os.makedirs(os.path.join(home, "_harness", "data"))
    if ledger:
        with open(os.path.join(home, "_harness", "events.jsonl"), "w") as f:
            f.write(json.dumps({"type": "corpus.recorded", "data": {"title": "t", "tags": ["release", RS]}}) + "\n")
    if terms_file:
        with open(os.path.join(home, "_harness", "data", G.TERMS_FILE), "w") as f:
            f.write("\n".join(terms) + "\n")
    return home


class Base(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.home = make_home()
        for d in (self.root, self.home):
            self.addCleanup(shutil.rmtree, d, True)

    def put(self, name, text):
        p = os.path.join(self.root, "plugins", "demo", name)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        open(p, "w", encoding="utf-8").write(text)
        return "plugins/demo/" + name

    def check(self, name, home=None):
        return G.check(self.root, [name], self.home if home is None else home)


class Structural(Base):
    def test_a_changelog_carrying_a_role_state_value_is_refused(self):
        n = self.put("CHANGELOG.md", "# Changelog\n\n## 9.9.9\n- tagged %s for the intro pass\n" % RS)
        h = self.check(n)
        self.assertTrue(h and "role-state" in h[0][1], h)

    def test_a_json_file_with_a_role_state_value_or_key_is_refused(self):
        self.assertTrue(self.check(self.put("planted.json", json.dumps({"tags": ["release", RS]}))))
        self.assertTrue(self.check(self.put("planted2.json", json.dumps({"a": {RS: 1}}))))

    def test_the_mapping_and_omitted_legacy_tags_keys_are_refused_at_any_depth(self):
        for body in ({MAP: {"x": 1}}, {"deep": [{"ok": {"omitted_legacy_tags": {"count": 1}}}]}, {"v": 1, "a": {"b": {MAP: {}}}}):
            h = self.check(self.put("d.json", json.dumps(body)))
            self.assertTrue(h and "structural" in h[0][1], (body, h))

    def test_yaml_fixture_and_changelog_text_are_read_for_the_same_things(self):
        self.assertTrue(self.check(self.put("conf.yaml", "%s:\n  a: 1\n" % MAP)))
        self.assertTrue(self.check(self.put("tests/fixtures/x.txt", "tags: [%s]\n" % RS)))
        self.assertTrue(self.check(self.put("CHANGELOG.md", 'the file had "omitted_legacy_tags": 3 in it\n')))

    def test_prose_and_code_are_not_read_for_the_structural_rule(self):
        self.assertEqual(self.check(self.put("notes.md", "The legacy mapping lives in a local file. It maps role-state tags.\n")), [])
        self.assertEqual(self.check(self.put("m.py", "d = {}\nx = d.get('%s')\n# role-state tags are explained in the docs\n" % MAP)), [])

    def test_a_clean_json_data_file_passes(self):
        self.assertEqual(self.check(self.put("o.json", json.dumps({"v": 1, "concepts": [{"id": "act.release", "label": "release"}]}))), [])

    def test_the_shipped_ontology_has_none_of_the_refused_keys(self):
        root = os.path.join(HERE, "..")
        h = G.check(root, ["data/ontology.json"], self.home)
        self.assertEqual(h, [], h)


class PrivateTerms(Base):
    def test_a_readme_with_ordinary_words_passes(self):
        self.assertEqual(self.check(self.put("README.md", "# Readme\n\nThis plugin helps with release and review work, resume and spotlight too.\n")), [])

    def test_a_private_term_in_a_skill_file_is_refused(self):
        h = self.check(self.put("skills/x/SKILL.md", "---\nname: x\n---\n- The zorgblat tokens drive the palette.\n"))
        self.assertTrue(h and "private term" in h[0][1], h)

    def test_a_private_term_in_code_is_refused_too(self):
        self.assertTrue(self.check(self.put("m.py", "NAME = 'Zorgblat'  # employer\n")))

    def test_multi_word_terms_match_spaced_joined_and_underscored_forms(self):
        for text in ("Frobnitz Widgets", "frobnitzwidgets", "FROBNITZ_WIDGETS", "frobnitz-widgets", "Quux Interview notes", "QuuxInterview"):
            self.assertTrue(self.check(self.put("t.md", "see %s here\n" % text)), text)

    def test_whole_words_only(self):
        for text in ("xzorgblatx", "zorgblatation", "a widgets frobnitz", "quux and interview apart"):
            self.assertEqual(self.check(self.put("t.md", text + "\n")), [], text)

    def test_the_refusal_names_the_file_and_the_line_never_the_term(self):
        h = self.check(self.put("t.md", "zorgblat\n"))
        why = h[0][1]
        self.assertIn("line 2", why)
        self.assertNotIn("zorgblat", why.lower())
        r = subprocess.run([sys.executable, "-B", os.path.join(SCRIPTS, "hatstand_guard.py"), self.root],
                           input="plugins/demo/t.md\0".encode(), capture_output=True, env=dict(os.environ, HARNESS_HOME=self.home))
        self.assertEqual(r.returncode, 1)
        self.assertNotIn(b"zorgblat", r.stderr.lower())
        self.assertIn(b"STOP", r.stderr)

    def test_the_exact_terms_file_name_is_used(self):
        self.assertEqual(G.TERMS_FILE, "hatstand-private-terms.txt")
        home = make_home(terms_file=False)
        self.addCleanup(shutil.rmtree, home, True)
        with open(os.path.join(home, "_harness", "data", "private-terms.txt"), "w") as f:      # the wrong file name is not read
            f.write("zorgblat\n")
        self.assertIn("cannot be read", G.check(self.root, [self.put("t.md", "ok\n")], home)[0][1])


class FailClosed(Base):
    def test_no_home_stops(self):
        h = G.check(self.root, [self.put("t.md", "fine\n")], None)
        self.assertEqual(len(h), 1)
        self.assertIn("HARNESS_HOME is not set", h[0][1])

    def test_an_unreadable_ledger_stops(self):
        home = make_home(ledger=False)
        self.addCleanup(shutil.rmtree, home, True)
        self.assertIn("ledger cannot be read", G.check(self.root, [self.put("t.md", "fine\n")], home)[0][1])

    def test_a_missing_empty_or_unreadable_terms_file_stops(self):
        for kw, word in (({"terms_file": False}, "cannot be read"), ({"terms": ["# only comments", ""]}, "empty")):
            home = make_home(**kw)
            self.addCleanup(shutil.rmtree, home, True)
            h = G.check(self.root, [self.put("t.md", "fine\n")], home)
            self.assertTrue(h and word in h[0][1], (kw, h))
        home = make_home()
        self.addCleanup(shutil.rmtree, home, True)
        p = os.path.join(home, "_harness", "data", G.TERMS_FILE)
        os.chmod(p, 0)
        self.addCleanup(os.chmod, p, 0o600)
        if os.access(p, os.R_OK):
            self.skipTest("running as a user that can read a mode-000 file")
        self.assertIn("cannot be read", G.check(self.root, [self.put("t.md", "fine\n")], home)[0][1])

    def test_no_environment_variable_turns_it_off(self):
        env = {k: v for k, v in os.environ.items() if not k.startswith("HARNESS_")}
        env.update(HATSTAND_GUARD_OFF="1", HATSTAND_GUARD_SKIP="1", HARNESS_GUARD_OFF="1", HATSTAND_NO_TERMS="1")
        r = subprocess.run([sys.executable, "-B", os.path.join(SCRIPTS, "hatstand_guard.py"), self.root],
                           input=(self.put("t.md", "fine\n") + "\0").encode(), capture_output=True, env=env)
        self.assertEqual(r.returncode, 1)                                    # HARNESS_HOME unset: STOP, whatever else is set
        self.assertIn(b"HARNESS_HOME is not set", r.stderr)

    def test_with_a_prepared_home_a_clean_push_passes_end_to_end(self):
        r = subprocess.run([sys.executable, "-B", os.path.join(SCRIPTS, "hatstand_guard.py"), self.root],
                           input=(self.put("README.md", "ordinary words\n") + "\0").encode(), capture_output=True,
                           env=dict(os.environ, HARNESS_HOME=self.home))
        self.assertEqual((r.returncode, r.stderr), (0, b""))

    def test_a_stop_for_a_missing_home_does_not_depend_on_the_files(self):
        self.assertEqual(len(G.check(self.root, [], None)), 1)               # even an empty push is refused: nothing can be certified


if __name__ == "__main__":
    unittest.main()
