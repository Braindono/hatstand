"""cc 0.17.0 H-013 (curator definition m-0c50912c6042): a tags value passed as one string was iterated as characters
("a-b" became the tags a, -, b). It is now split on commas and whitespace. Run: python3 -B tests/test_c170_h013.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _env  # noqa: F401  isolate HOME and HARNESS_* first
import os, sys, tempfile, unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
import harness as H
import mcp_server as M
from corpus import tag_list


class StringTags(unittest.TestCase):
    def setUp(self):
        home = os.path.join(tempfile.mkdtemp(), "Exchange")
        os.makedirs(os.path.join(home, "_harness"))
        e = mock.patch.dict(os.environ, {"HARNESS_STATE_CACHE": "0"})
        e.start()
        self.addCleanup(e.stop)
        self.h = H.Harness(home)
        self.a = self.h.register(project="harness-ops", model="claude-opus-5-5")["id"]

    def tags_of(self, rid):
        ev = [e for e in self.h.store.read_all() if e["type"] == "corpus.recorded" and e["data"]["id"] == rid][0]
        return ev["data"]["tags"]

    def test_string_and_list_give_whole_tags_in_cards(self):
        r1 = self.h.record(self.a, "note", "string tags", "b1", tags="a-b")
        r2 = self.h.record(self.a, "note", "list tags", "b2", tags=["a-b", "c"])
        self.assertEqual(self.tags_of(r1["id"]), ["a-b"])
        self.assertEqual(self.tags_of(r2["id"]), ["a-b", "c"])
        cards = self.h.recall("tags")["text"]
        self.assertIn("string tags [a-b]", cards)
        self.assertIn("list tags [a-b c]", cards)

    def test_mcp_string_tags(self):
        r = M._call(self.h, "harness_record", {"agent": self.a, "kind": "note", "title": "mcp", "body": "b", "tags": "x-y, z"})
        self.assertEqual(self.tags_of(r["id"]), ["x-y", "z"])

    def test_role_owns_and_partners_given_as_one_string(self):
        self.h.role_define("operator", "builder", "harness-ops", owns="projects/x/*.py, docs/My Notes.md", partners="envoy")
        R = self.h.state().roles["builder"]
        self.assertEqual(R["owns"], ["projects/x/*.py", "docs/My Notes.md"])     # paths keep their spaces
        self.assertEqual(R["partners"], ["envoy"])

    def test_tag_list(self):
        self.assertEqual(tag_list(None), [])
        self.assertEqual(tag_list(" a-b ,c  d "), ["a-b", "c", "d"])
        self.assertEqual(tag_list(("p", "q")), ["p", "q"])


if __name__ == "__main__":
    unittest.main()
