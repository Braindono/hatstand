"""cc 0.14.6 H-016: sobriquet word lists + banner role. Run: python3 -B tests/test_wordlists.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _env  # noqa: F401  isolate HOME and HARNESS_* first
import json, os, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
import harness as H

MODEL = "claude-sonnet-5-5"
DATA = os.path.join(HERE, "..", "data")
OLD_ADJ = """Amber Ashen Azure Birch Bold Brisk Bronze Calm Cedar Cinder Clever Cobalt Copper Coral Crimson Dappled Dawn Deft
Dusk Ember Fern Flint Frost Gilded Granite Hazel Hollow Indigo Iron Ivory Jade Keen Lucid Lunar Maple Marble Misty Nimble
Oaken Onyx Opal Pale Quartz Quiet Rapid Russet Saffron Sable Scarlet Silver Slate Solar Steady Stone Swift Tawny Umber
Velvet Verdant Vivid Willow Wistful Zephyr""".split()


def wl(text):
    p = os.path.join(tempfile.mkdtemp(), "w.md")
    with open(p, "w", encoding="utf-8") as f:
        f.write(text)
    return p


class Loader(unittest.TestCase):
    def test_blank_duplicate_invalid(self):
        words, rej = H.load_wordlist(wl("Amber\n\n  \nAmber\n Bold \namber\nAMBER\nab\nTwo Words\nWaytoolongword\nX1y\nCalm\nBold\n"))
        self.assertEqual(words, ["Amber", "Bold", "Calm"])      # blanks and repeats dropped, order kept
        self.assertEqual(rej, ["amber", "AMBER", "ab", "Two Words", "Waytoolongword", "X1y"])   # a case variant fails the pattern

    def test_missing_file_falls_back(self):
        self.assertEqual(H.load_wordlist("/nonexistent/x.md", ["Fall", "Back"])[0], ["Fall", "Back"])

    def test_shipped_files_clean_and_prefix_unchanged(self):
        adj = open(os.path.join(DATA, "adjectives.md")).read().splitlines()
        noun = open(os.path.join(DATA, "nouns.md")).read().splitlines()
        self.assertEqual((len(adj), len(noun)), (134, 197))
        self.assertEqual(adj[:63], OLD_ADJ)            # first 63 lines, original order
        self.assertEqual(H.ADJ, adj)
        self.assertEqual(H.NOUN, noun)
        self.assertEqual(H.NOUN[:63], H._NOUN63)
        self.assertEqual((H._ADJ_REJECTED, H._NOUN_REJECTED), ([], []))
        self.assertEqual(len({w.lower() for w in H.ADJ}), len(H.ADJ))
        self.assertEqual(len({w.lower() for w in H.NOUN}), len(H.NOUN))


class CrossList(unittest.TestCase):
    def test_shared_word_dropped_for_new_picks(self):
        dropped, kept = H.cross_list_dupes(set())
        self.assertEqual((dropped, kept), ({"Ember"}, set()))
        for i in range(400):
            n = H.make_sobriquet(f"{i * 7919 + 12345:064x}", set())
            self.assertFalse(n.endswith(" Ember"), n)

    def test_kept_and_flagged_when_existing_agent_uses_it(self):
        dropped, kept = H.cross_list_dupes({"gilded ember"})
        self.assertEqual((dropped, kept), (set(), {"Ember"}))

    def test_adj_equals_noun_never_picked(self):
        for i in range(200):
            a, b = H.make_sobriquet(f"{i:064x}", set()).split(" ")
            self.assertNotEqual(a, b)


class StoredNames(unittest.TestCase):
    def test_existing_names_unchanged_and_taken(self):
        home = os.path.join(tempfile.mkdtemp(), "h")
        os.makedirs(home)
        h = H.Harness(home)
        old = ["Amber Anchor", "Gilded Ember", "Zephyr Kiln", "Quiet Lynx"]
        for i, n in enumerate(old):                      # names from the old 63x63 lists, written as legacy events
            aid = f"{i + 1:064x}"
            h.store.append("agent.registered", aid, {"id": aid, "sobriquet": n, "project": "orchestration", "model": MODEL})
        st = h.state()
        self.assertEqual(sorted(a["sobriquet"] for a in st.agents.values()), sorted(old))
        taken = {H.norm_name(n) for n in old}
        for i in range(300):
            self.assertNotIn(H.make_sobriquet(f"{i * 104729:064x}", taken).lower(), taken)
        new = [h.register(project="orchestration", model=MODEL)["sobriquet"] for _ in range(12)]
        self.assertEqual(len(set(new + old)), 16)
        st = h.state()
        self.assertEqual(sorted(a["sobriquet"] for a in st.agents.values() if a["sobriquet"] in old), sorted(old))

    def test_new_picks_use_larger_lists(self):
        words = {w for i in range(600) for w in H.make_sobriquet(f"{i * 15485863:064x}", set()).split()}
        self.assertTrue(words - set(H._ADJ63) - set(H._NOUN63), "no word from the appended part was ever picked")


class BannerRole(unittest.TestCase):
    def setUp(self):
        home = os.path.join(tempfile.mkdtemp(), "h")
        os.makedirs(home)
        self.h = H.Harness(home)
        self.h.role_define("operator", "skill-curation-lead", "skill-curation")

    def test_role_next_to_name(self):
        aid = self.h.register(project="skill-curation", model=MODEL, role="skill-curation-lead")["id"]
        b = self.h.card(self.h.state(), aid)["banner"]
        a = self.h.state().agents[aid]
        self.assertIn(f"◆ {a['sobriquet']} #{aid[:8]} · curator", b)

    def test_no_role_plain_line_and_restore_banner(self):
        aid = self.h.register(project="skill-curation", model=MODEL)["id"]
        line = [l for l in self.h.card(self.h.state(), aid)["banner"].splitlines() if "◆" in l][0]
        self.assertTrue(line.endswith(f"#{aid[:8]}"), line)
        r = self.h.restore("skill-curation-lead", MODEL, confirmed=True)
        self.assertIn("· curator", r["text"].splitlines()[1])

    def test_banner_re_only_matches_box(self):
        box = "╭─ CREW COORDINATOR ────\n│ ◆ Quiet Lynx #aabbccdd · role\n│ expertise: x"
        self.assertEqual(H.BANNER_RE.findall(box), ["aabbccdd"])
        self.assertEqual(H.BANNER_RE.findall(json.dumps(box)), ["aabbccdd"])
        self.assertEqual(H.BANNER_RE.findall("mail: ◆ Quiet Lynx #11111111 asked"), [])
        self.assertEqual(H.BANNER_RE.findall(box + "\n◆ Other Fox #22222222"), ["aabbccdd"])

    def test_banner_agent_ignores_quoted_names(self):
        p = os.path.join(tempfile.mkdtemp(), "t.jsonl")
        box = "╭─ CREW COORDINATOR ────\n│ ◆ Quiet Lynx #aabbccdd\n"
        with open(p, "w") as f:
            f.write(json.dumps({"message": {"content": box}}) + "\n")
            f.write(json.dumps({"message": {"content": "ledger: ◆ Other Fox #22222222"}}) + "\n")
        self.assertEqual(H.banner_agent(p), "aabbccdd")


if __name__ == "__main__":
    unittest.main()
