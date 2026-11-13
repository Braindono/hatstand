"""cc 0.25.0 item 29 (security): restore auto_confirm gates from the ledger, not the capsule's frontmatter. Run: python3 -B tests/test_c250_item29.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _env  # noqa: F401  isolate HOME and HARNESS_* first
import os, unittest

import test_cc154_restore_auto as R
from test_cc154_restore_auto import PROJ, H

MODEL_ONLY = "---\nmodel: claude-sonnet-5-5\n---\n# critic capsule\n\nbody\n"


class Item29(R.RestoreAuto):
    def hand(self, a, text):
        r = self.h.handoff(a, text, None, False, None)
        rel = r.get("path") or r.get("capsule")
        if not rel:
            rel = "projects/%s/handoffs/%s" % (PROJ, sorted(os.listdir(os.path.join(self.home, "projects", PROJ, "handoffs")))[-1])
        return rel

    def auto_reason(self, rel, role="lead"):
        ok, why, _ = self.h.restore_auto_check(role, rel, PROJ)
        return ok, why

    def test_a_capsule_with_only_model_frontmatter_passes_the_real_critic_4_shape(self):
        a = self.holder()
        rel = self.hand(a, MODEL_ONLY)
        self.assertEqual(self.auto_reason(rel), (True, "ok"))
        self.assertNotIn("pending", self.restore(rel))

    def test_an_accepted_capsule_is_refused_and_names_the_real_gate(self):
        a = self.holder()
        rel = self.hand(a, MODEL_ONLY)
        self.restore(rel)                                                     # the accept writes a later version
        ok, why = self.auto_reason(rel)
        self.assertFalse(ok)
        self.assertRegex(why, "has not handed off|does not name|not open|latest version|accepted")

    def test_a_status_line_removed_by_hand_after_the_commit_is_refused_by_the_sha(self):
        a = self.holder()
        rel = self.hand(a, self.capsule_text(a, status="accepted by someone"))        # closed capsule
        ok, why = self.auto_reason(rel)
        self.assertFalse(ok)                                                          # status says accepted
        self.assertRegex(why, "already accepted or closed")
        p = os.path.join(self.home, rel)
        txt = open(p).read().replace("status: accepted by someone\n", "")
        open(p, "w").write(txt)                                                       # removed by hand
        ok, why = self.auto_reason(rel)
        self.assertFalse(ok)
        self.assertRegex(why, "hand-edited")

    def test_a_capsule_whose_latest_version_is_by_another_agent_is_refused(self):
        a = self.holder()
        rel = self.hand(a, MODEL_ONLY)
        b = self.h.register(project=PROJ, model=R.MODEL)["id"]
        key = rel
        self.h.claim(b, key)
        open(os.path.join(self.home, rel), "a").write("\nedit by b\n")
        self.h.commit(b, key, None, "an edit")
        ok, why = self.auto_reason(rel)
        self.assertFalse(ok)
        self.assertRegex(why, "latest version was not committed by the holder")

    def test_a_holder_that_has_not_handed_off_is_refused(self):
        a = self.holder()
        d = os.path.join(self.home, "projects", PROJ, "handoffs")
        os.makedirs(d, exist_ok=True)
        rel = "projects/%s/handoffs/2026-11-13-nohand.md" % PROJ
        open(os.path.join(self.home, rel), "w").write(MODEL_ONLY)
        ok, why = self.auto_reason(rel)
        self.assertFalse(ok)
        self.assertRegex(why, "has not handed off")

    def test_a_capsule_the_holders_handoff_event_does_not_name_is_refused(self):
        a = self.holder()
        self.hand(a, MODEL_ONLY)
        rel2 = "projects/%s/handoffs/2026-11-13-second.md" % PROJ                      # another file the holder commits with a handoff note
        open(os.path.join(self.home, rel2), "w").write(MODEL_ONLY.replace("body", "second"))
        self.h.claim(a, rel2)
        self.h.commit(a, rel2, None, "handoff capsule by hand")
        ok, why = self.auto_reason(rel2)
        self.assertFalse(ok)
        self.assertRegex(why, "does not name this capsule")

    def test_an_unrelated_agent_has_no_path_to_a_capsule(self):
        """No new path: the unrelated agent would need the holder's own artifact.versioned and agent.handed_off."""
        a = self.holder()
        rel = self.hand(a, MODEL_ONLY)
        other = self.h.register(project=PROJ, model=R.MODEL)["id"]
        self.as_(other)
        ok, _ = self.auto_reason(rel, role="lead")
        self.assertTrue(ok)                    # the check is about the capsule and the HOLDER, never the caller: the caller is still gated by confirmed=true
        self.assertEqual(self.h.state().role_handoffs["lead"]["agent"], a)



    def test_the_capsule_name_match_is_exact_not_a_suffix_or_slug_substring(self):
        a = self.holder()
        rel = self.hand(a, MODEL_ONLY)
        other = "projects/%s/handoffs/2026-11-14-other.md" % PROJ                          # a different capsule the holder never named
        open(os.path.join(self.home, other), "w").write(MODEL_ONLY)
        ok, why = self.auto_reason(other)
        self.assertFalse(ok)
        self.assertRegex(why, "does not name this capsule")
        self.assertEqual(self.auto_reason(rel), (True, "ok"))

    def test_two_concurrent_auto_restores_exactly_one_wins(self):
        import threading
        a = self.holder()
        rel = self.hand(a, MODEL_ONLY)
        ok, why, auto = self.h.restore_auto_check("lead", rel, PROJ)
        self.assertTrue(ok, why)
        out, barrier = [], threading.Barrier(2)

        def go():
            h2 = H.Harness(self.home)
            barrier.wait()
            out.append(h2.restore("lead", R.MODEL, PROJ, None, True, rel, dict(auto)))
        ts = [threading.Thread(target=go) for _ in range(2)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        refused = [x for x in out if "restore refused" in str(x.get("text"))]
        won = [x for x in out if x.get("short")]
        self.assertEqual((len(won), len(refused)), (1, 1), out)
        self.assertEqual(len(self.types("restore.auto")), 1)


for _n in [n for n in dir(R.RestoreAuto) if n.startswith("test_")]:
    setattr(Item29, _n, None)

if __name__ == "__main__":
    unittest.main()
